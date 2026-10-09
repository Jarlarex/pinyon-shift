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


def decode_levels(data: bytes) -> list[bytes]:
    """Every mip level as RGBA8 rows (texel channels as stored; car textures use XYZW)."""
    texture = layout(data)
    result = []
    for level, blocks in zip(texture.levels, read_blocks(data)):
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
        result.append(bytes(rgba))
    return result


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


def roundtrip(data: bytes) -> dict:
    """Layout check: untile every level and retile it onto zeroed padding; a
    correct layout reproduces the stock file byte for byte."""
    texture = layout(data)
    rebuilt = write_blocks(data[:HEADER_SIZE], read_blocks(data))
    return {"size": f"{texture.width}x{texture.height}", "format": texture.format,
            "levels": len(texture.levels), "byte_exact": rebuilt == data,
            "differing_bytes": sum(a != b for a, b in zip(rebuilt, data)) + abs(len(rebuilt) - len(data))}


def main() -> int:
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("roundtrip", help="check that the layout reproduces each texture exactly")
    check.add_argument("files", nargs="+", type=Path)
    decode = commands.add_parser("decode", help="write one mip level as a PNG")
    decode.add_argument("input", type=Path)
    decode.add_argument("output", type=Path)
    decode.add_argument("--level", type=int, default=0)
    args = parser.parse_args()
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
            result = {"file": str(path)} | roundtrip(path.read_bytes())
        except ValueError as error:
            result = {"file": str(path), "skipped": str(error)}
        exact &= result.get("byte_exact", True)
        print(json.dumps(result))
    return 0 if exact else 1


if __name__ == "__main__":
    sys.exit(main())
