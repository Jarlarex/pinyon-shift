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


def _packed_offset(width: int, height: int, packed_tile: int) -> tuple[int, int] | None:
    """Block position of a level inside the packed tile (SDK GetPackedTileOffset)."""
    log2_width, log2_height = _log2_ceil(width), _log2_ceil(height)
    if min(log2_width, log2_height) > 4:
        return None
    wide = log2_width > log2_height
    if packed_tile < 3:
        x, y = (0, 16 >> packed_tile) if wide else (16 >> packed_tile, 0)
    else:
        x, y = (16 >> (packed_tile - 2), 0) if wide else (0, 16 >> (packed_tile - 2))
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
    levels = [Level(width, height, visible, padded, base_offset,
                    _packed_offset(_next_pow2(width), _next_pow2(height), 0) if packed else None)]
    data_size = base_offset + padded[0] * padded[1] * block_bytes
    if mip_count > 1:
        if mip_offset % PAGE or mip_offset < data_size:
            raise ValueError("mip data overlaps level 0 in the .xds header")
        offset, packed_base, tail_size = mip_offset, None, 0
        for index in range(1, mip_count):
            w, h = max(_next_pow2(width) >> index, 1), max(_next_pow2(height) >> index, 1)
            visible, padded = _blocks(w, h)
            size = padded[0] * padded[1] * block_bytes
            if packed and (packed_base is not None or min(w, h) <= 16):
                if packed_base is None:
                    packed_base, tail_size = index, size
                levels.append(Level(w, h, visible, padded, offset,
                                    _packed_offset(w, h, index - packed_base)))
            else:
                levels.append(Level(w, h, visible, padded, offset, None))
                offset += size
        data_size = offset + tail_size
    return Layout(width, height, name, format_number, block_bytes, bool(fetch[0] >> 31),
                  (fetch[1] >> 6) & 3, packed, levels, data_size)
