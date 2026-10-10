#!/usr/bin/env python3
"""Read and write the .xds textures of Forza Horizon cars.

An .xds is a 0x34-byte D3D texture header followed by the texture data. The
header's Xenos fetch constant (six big-endian words at 0x1C) gives the size,
format, tiling, endianness, mip count, packed-mip flag and the page offsets of
level 0 and of the mip chain. Car body textures are DXT5 (format 53,
k_DXT4_5_AS_16_16_16_16), tiled, 8-in-16 endian, with a full packed mip chain;
DXT1 (format 51) appears on interior textures.

Layout rules follow the SDK, which reads these textures at run time
(thirdparty/shiftglue-sdk/src/graphics/pipeline/texture/info.cpp and
extent.cpp): every level is padded to whole 32x32-block tiles; mip level i of a
WxH texture is next_pow2(W)>>i by next_pow2(H)>>i; the levels from the first
one whose smaller side is 16 texels or less share one packed tile.
"""
# No `from __future__ import annotations`: the dataclasses below must also work
# when tools load this file by path (importlib), where string annotations fail.
import struct
import sys
import time
import zlib
from dataclasses import dataclass

HEADER_SIZE = 0x34
TILE_BLOCKS = 32
PAGE = 4096
# format number -> (name, bytes per 4x4 block)
FORMATS = {18: ("DXT1", 8), 51: ("DXT1", 8), 20: ("DXT5", 16), 53: ("DXT5", 16)}


@dataclass(frozen=True)
class Level:
    width: int                                 # texels
    height: int
    blocks: tuple[int, int]                    # visible 4x4 blocks
    padded_blocks: tuple[int, int]             # blocks after tile padding
    offset: int                                # byte offset of the level's tile region in the data
    packed_blocks: tuple[int, int] | None      # block position inside the packed tile, if packed


@dataclass(frozen=True)
class Layout:
    width: int
    height: int
    format: str
    format_number: int
    block_bytes: int
    tiled: bool
    endianness: int
    packed_mips: bool
    levels: list[Level]
    data_size: int


def _next_pow2(value: int) -> int:
    return 1 << max(value - 1, 0).bit_length()


def _log2_ceil(value: int) -> int:
    return max(value - 1, 0).bit_length()


def _blocks(width: int, height: int) -> tuple[tuple[int, int], tuple[int, int]]:
    visible = ((width + 3) // 4, (height + 3) // 4)
    padded = tuple(-(-n // TILE_BLOCKS) * TILE_BLOCKS for n in visible)
    return visible, padded


def _packed_base(width: int, height: int) -> int:
    """The first mip level that lives in the packed tile."""
    return max(min(_log2_ceil(width), _log2_ceil(height)) - 4, 0)


def _packed_offset(width: int, height: int, level: int) -> tuple[int, int] | None:
    """Block position of mip `level` of a width x height texture inside the
    packed tile. Orientation and the smallest levels' offsets follow the base
    texture, as the stock files show: the FR-S's 128x64 wood.xds keeps its 4x2,
    2x1 and 1x1 levels at blocks (4,0), (2,0) and (1,0). The SDK's
    GetPackedTileOffset gives the same positions for square textures only."""
    log2_width, log2_height = _log2_ceil(width), _log2_ceil(height)
    base = _packed_base(width, height)
    if level < base:
        return None
    packed, wide = level - base, log2_width > log2_height
    if packed < 3:
        x, y = (0, 16 >> packed) if wide else (16 >> packed, 0)
    elif wide:
        x, y = (1 << (log2_width - base)) >> (packed - 2), 0
    else:
        x, y = 0, (1 << (log2_height - base)) >> (packed - 2)
    return x // 4, y // 4


def layout(header: bytes) -> Layout:
    """The texture's levels and data size, from its .xds header."""
    if len(header) < HEADER_SIZE or struct.unpack_from(">I", header, 0)[0] != 3:
        raise ValueError("not an .xds texture")
    fetch = struct.unpack_from(">6I", header, 0x1C)
    if fetch[0] & 3 != 2 or (fetch[5] >> 9) & 3 != 1:
        raise ValueError("not a 2D .xds texture")
    format_number = fetch[1] & 0x3F
    if format_number not in FORMATS:
        raise ValueError(f"unsupported .xds format {format_number}: only DXT1 and DXT5 car textures")
    name, block_bytes = FORMATS[format_number]
    width, height = (fetch[2] & 0x1FFF) + 1, ((fetch[2] >> 13) & 0x1FFF) + 1
    pitch = ((fetch[0] >> 22) & 0x1FF) * 32 or width
    mip_count = ((fetch[4] >> 6) & 0xF) + 1
    packed = bool((fetch[5] >> 11) & 1)
    base_offset, mip_offset = (fetch[1] >> 12) * PAGE, (fetch[5] >> 12) * PAGE

    visible, padded = _blocks(width, height)
    padded = (_blocks(pitch, height)[1][0], padded[1])
    width_pow2, height_pow2 = _next_pow2(width), _next_pow2(height)
    levels = [Level(width, height, visible, padded, base_offset,
                    _packed_offset(width_pow2, height_pow2, 0) if packed else None)]
    data_size = base_offset + padded[0] * padded[1] * block_bytes
    if mip_count > 1:
        if mip_offset % PAGE or mip_offset < data_size:
            raise ValueError("mip data overlaps level 0 in the .xds header")
        offset, tail_size = mip_offset, 0
        for index in range(1, mip_count):
            w, h = max(width_pow2 >> index, 1), max(height_pow2 >> index, 1)
            visible, padded = _blocks(w, h)
            size = padded[0] * padded[1] * block_bytes
            position = _packed_offset(width_pow2, height_pow2, index) if packed else None
            if position is not None:
                tail_size = tail_size or size  # the packed tile is the first packed level's
                levels.append(Level(w, h, visible, padded, offset, position))
            else:
                levels.append(Level(w, h, visible, padded, offset, None))
                offset += size
        data_size = offset + tail_size
    return Layout(width, height, name, format_number, block_bytes, bool(fetch[0] >> 31),
                  (fetch[1] >> 6) & 3, packed, levels, data_size)


def tiled_offset_2d(x: int, y: int, pitch: int, bytes_per_block_log2: int) -> int:
    """Byte offset of block (x, y) in a Xenos 2D tiled surface (SDK GetTiledOffset2D)."""
    pitch = (pitch + 31) & ~31
    macro = ((x >> 5) + (y >> 5) * (pitch >> 5)) << (bytes_per_block_log2 + 7)
    micro = ((x & 7) + ((y & 0xE) << 2)) << bytes_per_block_log2
    offset = macro + ((micro & ~0xF) << 1) + (micro & 0xF) + ((y & 1) << 4)
    return (((offset & ~0x1FF) << 3) + ((y & 16) << 7) + ((offset & 0x1C0) << 2)
            + (((((y & 8) >> 2) + (x >> 3)) & 3) << 6) + (offset & 0x3F))


# Byte permutation within each block for none, 8-in-16, 8-in-32 and 16-in-32 endianness.
_ENDIAN_MASKS = (0, 1, 3, 2)


def _swap(block: bytes, endianness: int) -> bytes:
    mask = _ENDIAN_MASKS[endianness]
    return block if not mask else bytes(block[i ^ mask] for i in range(len(block)))


def _block_offsets(layout: Layout, level: Level):
    """Data offset of each visible block of a level, row by row."""
    if not layout.tiled:
        raise ValueError("untiled .xds textures are not supported")
    log2 = layout.block_bytes.bit_length() - 1
    px, py = level.packed_blocks or (0, 0)
    pitch = level.padded_blocks[0]
    for y in range(level.blocks[1]):
        for x in range(level.blocks[0]):
            yield level.offset + tiled_offset_2d(x + px, y + py, pitch, log2)


def read_blocks(data: bytes) -> list[bytes]:
    """Every level's visible blocks, row by row, in standard (little-endian) DXT byte order."""
    texture = layout(data)
    if len(data) < HEADER_SIZE + texture.data_size:
        raise ValueError("the .xds texture is shorter than its header says")
    size, body = texture.block_bytes, memoryview(data)[HEADER_SIZE:]
    return [b"".join(_swap(bytes(body[o:o + size]), texture.endianness) for o in _block_offsets(texture, level))
            for level in texture.levels]


def write_blocks(header: bytes, levels: list[bytes], template: bytes | None = None) -> bytes:
    """Header + data with the given blocks tiled into place; padding comes from `template`
    (a texture with this exact header and size) or is zero."""
    texture = layout(header)
    if len(levels) != len(texture.levels):
        raise ValueError(f"expected {len(texture.levels)} mip levels, got {len(levels)}")
    if template is not None:
        if template[:HEADER_SIZE] != header[:HEADER_SIZE] or len(template) != HEADER_SIZE + texture.data_size:
            raise ValueError("the template texture's header or size differs")
        data = bytearray(template[HEADER_SIZE:])
    else:
        data = bytearray(texture.data_size)
    size = texture.block_bytes
    for level, blocks in zip(texture.levels, levels):
        if len(blocks) != level.blocks[0] * level.blocks[1] * size:
            raise ValueError(f"level {level.width}x{level.height} needs {level.blocks[0] * level.blocks[1]} blocks")
        for index, offset in enumerate(_block_offsets(texture, level)):
            data[offset:offset + size] = _swap(blocks[index * size:(index + 1) * size], texture.endianness)
    return bytes(header[:HEADER_SIZE]) + bytes(data)


def _colors(block: bytes, allow_transparent: bool) -> list[tuple[int, int, int, int]]:
    """The four-entry palette of a DXT colour block (same rules as inspect-fh1-ui.py)."""
    color0, color1 = struct.unpack_from("<HH", block, 0)

    def expand(color: int) -> tuple[int, int, int]:
        red, green, blue = color >> 11, (color >> 5) & 0x3F, color & 0x1F
        return (red << 3 | red >> 2, green << 2 | green >> 4, blue << 3 | blue >> 2)

    first, second = expand(color0), expand(color1)
    if color0 > color1 or not allow_transparent:
        third = tuple((2 * a + b + 1) // 3 for a, b in zip(first, second))
        fourth = tuple((a + 2 * b + 1) // 3 for a, b in zip(first, second))
        return [(*first, 255), (*second, 255), (*third, 255), (*fourth, 255)]
    middle = tuple((a + b + 1) // 2 for a, b in zip(first, second))
    return [(*first, 255), (*second, 255), (*middle, 255), (0, 0, 0, 0)]


def _alphas(block: bytes) -> list[int]:
    alpha0, alpha1 = block[0], block[1]
    if alpha0 > alpha1:
        palette = [alpha0, alpha1] + [((7 - i) * alpha0 + i * alpha1 + 3) // 7 for i in range(1, 7)]
    else:
        palette = [alpha0, alpha1] + [((5 - i) * alpha0 + i * alpha1 + 2) // 5 for i in range(1, 5)] + [0, 255]
    bits = int.from_bytes(block[2:8], "little")
    return [palette[(bits >> (3 * texel)) & 7] for texel in range(16)]


def _decode_block(format: str, block: bytes) -> list[tuple[int, int, int, int]]:
    """A 4x4 block's 16 RGBA texels, row by row."""
    colors_at = 8 if format == "DXT5" else 0
    palette = _colors(block[colors_at:colors_at + 8], colors_at == 0)
    indices = struct.unpack_from("<I", block, colors_at + 4)[0]
    texels = [palette[(indices >> (2 * texel)) & 3] for texel in range(16)]
    if colors_at:
        alpha = _alphas(block)
        texels = [(r, g, b, alpha[texel]) for texel, (r, g, b, _) in enumerate(texels)]
    return texels


def _decode_level(texture: Layout, level: Level, blocks: bytes) -> bytes:
    width, height, columns = level.width, level.height, level.blocks[0]
    rgba = bytearray(width * height * 4)
    for index in range(len(blocks) // texture.block_bytes):
        block = blocks[index * texture.block_bytes:(index + 1) * texture.block_bytes]
        bx, by = (index % columns) * 4, (index // columns) * 4
        for texel, value in enumerate(_decode_block(texture.format, block)):
            x, y = bx + texel % 4, by + texel // 4
            if x < width and y < height:
                at = 4 * (y * width + x)
                rgba[at:at + 4] = bytes(value)
    return bytes(rgba)


def decode_levels(data: bytes) -> list[bytes]:
    """Every mip level as RGBA8 rows (texel channels as stored; car textures use XYZW)."""
    texture = layout(data)
    return [_decode_level(texture, level, blocks) for level, blocks in zip(texture.levels, read_blocks(data))]


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def encode_png(width: int, height: int, rgba: bytes) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    stride = 4 * width
    raw = b"".join(b"\x00" + rgba[row * stride:(row + 1) * stride] for row in range(height))
    return (_PNG_SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def decode_png(data: bytes) -> tuple[int, int, bytes]:
    """Width, height and RGBA8 rows of an 8-bit RGBA, non-interlaced PNG."""
    if not data.startswith(_PNG_SIGNATURE):
        raise ValueError("not a PNG file")
    at, header, compressed = len(_PNG_SIGNATURE), None, b""
    while at + 8 <= len(data):
        size, kind = struct.unpack_from(">I4s", data, at)
        body = data[at + 8:at + 8 + size]
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            compressed += body
        at += 12 + size
    if header is None or header[2:] != (8, 6, 0, 0, 0):
        raise ValueError("only 8-bit RGBA non-interlaced PNG files are supported")
    width, height = header[:2]
    raw, stride = zlib.decompress(compressed), 4 * width
    rows, previous = [], bytearray(stride)
    for row in range(height):
        line = raw[row * (stride + 1):(row + 1) * (stride + 1)]
        kind, current = line[0], bytearray(line[1:])
        for index in range(stride):
            left = current[index - 4] if index >= 4 else 0
            up, corner = previous[index], previous[index - 4] if index >= 4 else 0
            if kind == 1:
                current[index] = (current[index] + left) & 0xFF
            elif kind == 2:
                current[index] = (current[index] + up) & 0xFF
            elif kind == 3:
                current[index] = (current[index] + (left + up) // 2) & 0xFF
            elif kind == 4:
                estimate = left + up - corner
                distances = (abs(estimate - left), abs(estimate - up), abs(estimate - corner))
                current[index] = (current[index] + (left, up, corner)[distances.index(min(distances))]) & 0xFF
        rows.append(bytes(current))
        previous = current
    return width, height, b"".join(rows)


# Car textures are gamma-encoded (header gamma bits); mips average in linear light.
_TO_LINEAR = [(value / 255) ** 2.2 for value in range(256)]


def _to_gamma(linear: float) -> int:
    return min(255, max(0, round(linear ** (1 / 2.2) * 255)))


def _downsample(rgba: bytes, width: int, height: int, out_width: int, out_height: int) -> bytes:
    """Box filter: each output texel averages the source texels that map onto it."""
    out = bytearray(out_width * out_height * 4)
    linear = _TO_LINEAR
    for dy in range(out_height):
        y0 = dy * height // out_height
        y1 = max(y0 + 1, (dy + 1) * height // out_height)
        for dx in range(out_width):
            x0 = dx * width // out_width
            x1 = max(x0 + 1, (dx + 1) * width // out_width)
            red = green = blue = alpha = 0.0
            for y in range(y0, y1):
                row = y * width * 4
                for x in range(x0, x1):
                    at = row + 4 * x
                    red += linear[rgba[at]]
                    green += linear[rgba[at + 1]]
                    blue += linear[rgba[at + 2]]
                    alpha += rgba[at + 3]
            count = (y1 - y0) * (x1 - x0)
            at = 4 * (dy * out_width + dx)
            out[at:at + 4] = bytes((_to_gamma(red / count), _to_gamma(green / count),
                                    _to_gamma(blue / count), round(alpha / count)))
    return bytes(out)


def make_mips(rgba: bytes, width: int, height: int, sizes: list[tuple[int, int]]) -> list[bytes]:
    """Each requested mip size, filtered from the previous level."""
    levels = []
    for out_width, out_height in sizes:
        rgba = _downsample(rgba, width, height, out_width, out_height)
        width, height = out_width, out_height
        levels.append(rgba)
    return levels


def _pack565(color: tuple[float, float, float]) -> int:
    red, green, blue = (min(255.0, max(0.0, c)) for c in color)
    return (round(red * 31 / 255) << 11) | (round(green * 63 / 255) << 5) | round(blue * 31 / 255)


def _expand565(color: int) -> tuple[int, int, int]:
    red, green, blue = color >> 11, (color >> 5) & 0x3F, color & 0x1F
    return (red << 3 | red >> 2, green << 2 | green >> 4, blue << 3 | blue >> 2)


def _principal_ends(colors: list[tuple[int, int, int]]) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """The two extreme colours along the block's principal axis."""
    count = len(colors)
    mean = [sum(c[i] for c in colors) / count for i in range(3)]
    cov = [[sum((c[i] - mean[i]) * (c[j] - mean[j]) for c in colors) for j in range(3)] for i in range(3)]
    # Start from the colour farthest from the mean: never perpendicular to the spread.
    offsets = [[c[i] - mean[i] for i in range(3)] for c in colors]
    axis = max(offsets, key=lambda v: v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if max(abs(v) for v in axis) < 1e-9:
        return tuple(mean), tuple(mean)
    for _ in range(6):
        turned = [sum(cov[i][j] * axis[j] for j in range(3)) for i in range(3)]
        norm = max(abs(v) for v in turned)
        if norm < 1e-9:
            break
        axis = [v / norm for v in turned]
    projections = [sum((c[i] - mean[i]) * axis[i] for i in range(3)) for c in colors]
    return tuple(colors[projections.index(max(projections))]), tuple(colors[projections.index(min(projections))])


def _palette(color0: int, color1: int, four: bool) -> list[tuple[int, int, int]]:
    first, second = _expand565(color0), _expand565(color1)
    if four:
        return [first, second, tuple((2 * a + b + 1) // 3 for a, b in zip(first, second)),
                tuple((a + 2 * b + 1) // 3 for a, b in zip(first, second))]
    return [first, second, tuple((a + b + 1) // 2 for a, b in zip(first, second))]


def _nearest(colors, palette) -> tuple[list[int], int]:
    indices, error = [], 0
    for color in colors:
        distances = [sum((a - b) ** 2 for a, b in zip(color, entry)) for entry in palette]
        best = min(distances)
        indices.append(distances.index(best))
        error += best
    return indices, error


def _fit_colors(colors: list[tuple[int, int, int]], four: bool) -> tuple[int, int, list[int], int]:
    """565 endpoints, per-colour palette indices and squared error: principal-axis
    ends, then one least-squares pass."""
    start, end = _principal_ends(colors)
    best = None
    for _ in range(2):
        color0, color1 = _pack565(start), _pack565(end)
        if four and color0 < color1:
            color0, color1 = color1, color0
        elif not four and color0 > color1:
            color0, color1 = color1, color0
        indices, error = _nearest(colors, _palette(color0, color1, four))
        if best is None or error < best[3]:
            best = (color0, color1, indices, error)
        weights = ((1, 0), (0, 1), (2 / 3, 1 / 3), (1 / 3, 2 / 3)) if four else ((1, 0), (0, 1), (0.5, 0.5))
        aa = sum(weights[i][0] ** 2 for i in indices)
        ab = sum(weights[i][0] * weights[i][1] for i in indices)
        bb = sum(weights[i][1] ** 2 for i in indices)
        det = aa * bb - ab * ab
        if abs(det) < 1e-9:
            break
        ax = [sum(weights[i][0] * c[k] for i, c in zip(indices, colors)) for k in range(3)]
        bx = [sum(weights[i][1] * c[k] for i, c in zip(indices, colors)) for k in range(3)]
        start = tuple((bb * ax[k] - ab * bx[k]) / det for k in range(3))
        end = tuple((aa * bx[k] - ab * ax[k]) / det for k in range(3))
    return best


def _encode_alpha(alphas: list[int]) -> bytes:
    high, low = max(alphas), min(alphas)
    if high == low:
        return bytes([high, low]) + bytes(6)
    palette = [high, low] + [((7 - i) * high + i * low + 3) // 7 for i in range(1, 7)]
    bits = 0
    for texel, value in enumerate(alphas):
        distances = [abs(value - entry) for entry in palette]
        bits |= distances.index(min(distances)) << (3 * texel)
    return bytes([high, low]) + bits.to_bytes(6, "little")


def _encode_block(format: str, texels: list[tuple[int, int, int, int]]) -> bytes:
    """One 4x4 block in standard (little-endian) DXT1 or DXT5 byte order."""
    colors = [t[:3] for t in texels]
    if format == "DXT5":
        color0, color1, indices, _ = _fit_colors(colors, four=True)
        bits = sum(index << (2 * texel) for texel, index in enumerate(indices))
        return _encode_alpha([t[3] for t in texels]) + struct.pack("<HHI", color0, color1, bits)
    opaque = [t[3] >= 128 for t in texels]
    if all(opaque):
        # Opaque DXT1 blocks may use either mode: thirds (four colours) or an exact midpoint (three).
        color0, color1, indices, _ = min(_fit_colors(colors, four=True), _fit_colors(colors, four=False),
                                         key=lambda fit: fit[3])
        if color0 == color1:
            indices = [0] * 16
    elif any(opaque):
        visible = [c for c, keep in zip(colors, opaque) if keep]
        color0, color1, fitted, _ = _fit_colors(visible, four=False)
        fitted = iter(fitted)
        indices = [next(fitted) if keep else 3 for keep in opaque]
    else:
        color0, color1, indices = 0, 0xFFFF, [3] * 16
    bits = sum(index << (2 * texel) for texel, index in enumerate(indices))
    return struct.pack("<HHI", color0, color1, bits)


def _encode_level(format: str, rgba: bytes, width: int, height: int, cache: dict) -> bytes:
    """A level's blocks, row by row; edge blocks repeat the last texel row and column."""
    out = []
    for by in range(0, height, 4):
        for bx in range(0, width, 4):
            if bx + 4 <= width and by + 4 <= height:
                raw = b"".join(rgba[4 * (y * width + bx):4 * (y * width + bx) + 16] for y in range(by, by + 4))
            else:
                spots = [4 * (min(y, height - 1) * width + min(x, width - 1))
                         for y in range(by, by + 4) for x in range(bx, bx + 4)]
                raw = b"".join(rgba[at:at + 4] for at in spots)
            block = cache.get(raw)
            if block is None:
                block = _encode_block(format, [tuple(raw[i:i + 4]) for i in range(0, 64, 4)])
                cache[raw] = block
            out.append(block)
    return b"".join(out)


def write_xds(template_header: bytes, rgba: bytes, width: int, height: int) -> bytes:
    """Encode level 0 and generated mips into the layout the (stock) header describes."""
    texture = layout(template_header)
    if (width, height) != (texture.width, texture.height) or len(rgba) != width * height * 4:
        raise ValueError(f"the texture needs a {texture.width}x{texture.height} RGBA image")
    sizes = [(level.width, level.height) for level in texture.levels[1:]]
    images = [rgba] + make_mips(rgba, width, height, sizes)
    cache: dict = {}
    levels = [_encode_level(texture.format, image, level.width, level.height, cache)
              for image, level in zip(images, texture.levels)]
    return write_blocks(template_header, levels)


def _block_texels(rgba: bytes, width: int, height: int, bx: int, by: int) -> bytes:
    """A 4x4 block's 64 RGBA bytes; edge blocks repeat the last texel row and column, as `_encode_level`."""
    if (bx + 1) * 4 <= width and (by + 1) * 4 <= height:
        return b"".join(rgba[4 * (y * width + 4 * bx):4 * (y * width + 4 * bx) + 16] for y in range(4 * by, 4 * by + 4))
    spots = [4 * (min(y, height - 1) * width + min(x, width - 1))
             for y in range(4 * by, 4 * by + 4) for x in range(4 * bx, 4 * bx + 4)]
    return b"".join(rgba[at:at + 4] for at in spots)


def _source_blocks(start: int, end: int, size: int, previous: int) -> range:
    """The previous level's blocks (along one axis) that mip texels start..end-1 of a
    `size`-texel level average, with `_downsample`'s mapping."""
    first = start * previous // size
    last = max((end - 1) * previous // size + 1, end * previous // size)
    return range(first // 4, (last + 3) // 4)


def repaint_xds(stock: bytes, rgba: bytes) -> bytes:
    """`stock` with its colours replaced by level 0 `rgba`, whose alpha must be the
    stock texture's own. Only the colour half of the DXT5 blocks whose texels
    changed is re-encoded, at level 0 and in every mip block whose footprint holds
    a changed texel (colours from mips of the new image); every other byte,
    including each block's alpha half, padding and header, is the stock file's."""
    texture = layout(stock)
    if texture.format != "DXT5":
        raise ValueError("only DXT5 body textures can be repainted")
    base = texture.levels[0]
    width, height = base.width, base.height
    if len(rgba) != width * height * 4:
        raise ValueError(f"the texture needs a {width}x{height} RGBA image")
    blocks = read_blocks(stock)
    original = _decode_level(texture, base, blocks[0])
    if rgba[3::4] != original[3::4]:
        raise ValueError("a repaint keeps the stock alpha, but the image's alpha differs from the texture's")
    columns, rows = base.blocks
    changed = {(bx, by) for by in range(rows) for bx in range(columns)
               if _block_texels(rgba, width, height, bx, by) != _block_texels(original, width, height, bx, by)}
    if not changed:
        return stock
    images = [rgba] + make_mips(rgba, width, height, [(level.width, level.height) for level in texture.levels[1:]])
    levels, cache = [], {}
    for index, (level, image) in enumerate(zip(texture.levels, images)):
        if index:
            pw, ph = texture.levels[index - 1].width, texture.levels[index - 1].height
            lw, lh = level.width, level.height
            changed = {(bx, by) for bx in range(level.blocks[0]) for by in range(level.blocks[1])
                       if any((x, y) in changed
                              for y in _source_blocks(4 * by, min(4 * by + 4, lh), lh, ph)
                              for x in _source_blocks(4 * bx, min(4 * bx + 4, lw), lw, pw))}
        out = bytearray(blocks[index])
        for bx, by in changed:
            raw = _block_texels(image, level.width, level.height, bx, by)
            colour = cache.get(raw)
            if colour is None:
                colour = cache[raw] = _encode_block("DXT5", [tuple(raw[i:i + 4]) for i in range(0, 64, 4)])[8:]
            at = 16 * (by * level.blocks[0] + bx)
            out[at + 8:at + 16] = colour
        levels.append(bytes(out))
    return write_blocks(stock[:HEADER_SIZE], levels, template=stock)


def roundtrip(data: bytes, encode: bool = False) -> dict:
    """Layout check: untile every level and retile it onto zeroed padding; a
    correct layout reproduces the stock file byte for byte. With `encode`, also
    re-encode level 0 (and its mips) and measure level 0's error and the time."""
    texture = layout(data)
    rebuilt = write_blocks(data[:HEADER_SIZE], read_blocks(data))
    result = {"size": f"{texture.width}x{texture.height}", "format": texture.format,
              "levels": len(texture.levels), "byte_exact": rebuilt == data,
              "differing_bytes": sum(a != b for a, b in zip(rebuilt, data)) + abs(len(rebuilt) - len(data))}
    if encode:
        original = decode_levels(data)[0]
        started = time.perf_counter()
        encoded = write_xds(data[:HEADER_SIZE], original, texture.width, texture.height)
        seconds = time.perf_counter() - started
        errors = [abs(a - b) for a, b in zip(decode_levels(encoded)[0], original)]
        result |= {"reencode_mean": round(sum(errors) / len(errors), 3), "reencode_max": max(errors),
                   "encode_seconds": round(seconds, 1)}
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("roundtrip", help="check that the layout reproduces each texture exactly")
    check.add_argument("files", nargs="+", type=Path)
    check.add_argument("--encode", action="store_true", help="also re-encode level 0 and report error and time")
    encode = commands.add_parser("encode", help="encode a PNG into a texture shaped like TEMPLATE")
    encode.add_argument("template", type=Path)
    encode.add_argument("input", type=Path)
    encode.add_argument("output", type=Path)
    decode = commands.add_parser("decode", help="write one mip level as a PNG")
    decode.add_argument("input", type=Path)
    decode.add_argument("output", type=Path)
    decode.add_argument("--level", type=int, default=0)
    args = parser.parse_args(argv)
    if args.command == "encode":
        width, height, rgba = decode_png(args.input.read_bytes())
        args.output.write_bytes(write_xds(args.template.read_bytes()[:HEADER_SIZE], rgba, width, height))
        print(json.dumps({"template": str(args.template), "png": str(args.input), "xds": str(args.output)}))
        return 0
    if args.command == "decode":
        data = args.input.read_bytes()
        level = layout(data).levels[args.level]
        args.output.write_bytes(encode_png(level.width, level.height, decode_levels(data)[args.level]))
        print(json.dumps({"file": str(args.input), "level": args.level, "size": f"{level.width}x{level.height}",
                          "png": str(args.output)}))
        return 0
    exact = True
    for path in args.files:
        try:
            result = {"file": str(path)} | roundtrip(path.read_bytes(), encode=args.encode)
        except ValueError as error:
            result = {"file": str(path), "skipped": str(error)}
        exact &= result.get("byte_exact", True)
        print(json.dumps(result))
    return 0 if exact else 1


if __name__ == "__main__":
    sys.exit(main())
