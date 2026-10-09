"""FH1 .xds car texture codec, with synthetic headers only (no game data)."""
import importlib.util
import struct
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("fh1_xds", Path(__file__).parents[1] / "fh1_xds.py")
xds = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(xds)

DXT1, DXT5 = 51, 53  # k_DXT1_AS_16_16_16_16, k_DXT4_5_AS_16_16_16_16 (the car textures' formats)


def header(width, height, format_number, mips, mip_page, packed=True, tiled=True):
    """A car-texture header laid out like the stock ones (fetch constant at 0x1C)."""
    fetch = (
        2 | (3 << 2) | (3 << 4) | (3 << 6) | ((max(width, 128) // 32) << 22) | (int(tiled) << 31),
        format_number | (1 << 6),
        (width - 1) | ((height - 1) << 13),
        0xD10,
        (mips - 1) << 6,
        (1 << 9) | (int(packed) << 11) | (mip_page << 12),
    )
    return struct.pack(">7I", 3, 1, 0, 0, 0, 0xFFFF0000, 0xFFFF0000) + struct.pack(">6I", *fetch)


class LayoutTests(unittest.TestCase):
    def test_header_fields_of_a_body_texture(self):
        layout = xds.layout(header(2048, 2048, DXT5, 12, 0x400))
        self.assertEqual((layout.width, layout.height, layout.format), (2048, 2048, "DXT5"))
        self.assertEqual((layout.tiled, layout.endianness, layout.packed_mips), (True, 1, True))
        self.assertEqual(len(layout.levels), 12)

    def test_2048_dxt5_data_size_matches_the_stock_file(self):
        layout = xds.layout(header(2048, 2048, DXT5, 12, 0x400))
        self.assertEqual(layout.data_size, 5_636_096)
        self.assertEqual(layout.levels[0].offset, 0)
        self.assertEqual(layout.levels[0].padded_blocks, (512, 512))
        self.assertEqual(layout.levels[1].offset, 0x400000)

    def test_1024_dxt5_mips_pad_to_whole_tiles_then_share_one_packed_tile(self):
        layout = xds.layout(header(1024, 1024, DXT5, 11, 0x100))
        self.assertEqual(layout.data_size, 1_441_792)
        sizes = [(level.width, level.offset) for level in layout.levels[1:6]]
        self.assertEqual(sizes, [(512, 0x100000), (256, 0x140000), (128, 0x150000),
                                 (64, 0x154000), (32, 0x158000)])
        self.assertEqual(layout.levels[5].padded_blocks, (32, 32))
        tail = layout.levels[6:]
        self.assertEqual({level.offset for level in tail}, {0x15C000})
        self.assertEqual([level.packed_blocks for level in tail],
                         [(4, 0), (2, 0), (1, 0), (0, 2), (0, 1)])
        self.assertIsNone(layout.levels[5].packed_blocks)

    def test_512_dxt5_data_size_matches_the_stock_file(self):
        self.assertEqual(xds.layout(header(512, 512, DXT5, 10, 0x40)).data_size, 393_216)

    def test_512_dxt1_uses_eight_byte_blocks(self):
        layout = xds.layout(header(512, 512, DXT1, 10, 0x20))
        self.assertEqual(layout.format, "DXT1")
        self.assertEqual(layout.data_size, 196_608)

    def test_single_level_non_square_texture_fills_one_tile(self):
        layout = xds.layout(header(128, 16, DXT5, 1, 0))
        self.assertEqual(len(layout.levels), 1)
        self.assertEqual(layout.levels[0].blocks, (32, 4))
        self.assertEqual(layout.data_size, 16_384)

    def test_unpacked_mips_follow_each_other(self):
        layout = xds.layout(header(64, 64, DXT5, 3, 0x4, packed=False))
        self.assertEqual([level.offset for level in layout.levels], [0, 0x4000, 0x8000])
        self.assertEqual(layout.data_size, 0xC000)

    def test_mip_data_overlapping_level_zero_is_refused(self):
        with self.assertRaisesRegex(ValueError, "mip data"):
            xds.layout(header(1024, 1024, DXT5, 11, 0x80))

    def test_formats_other_than_dxt1_and_dxt5_are_refused(self):
        with self.assertRaisesRegex(ValueError, "format"):
            xds.layout(header(256, 256, 6, 1, 0))

    def test_short_or_foreign_data_is_refused(self):
        with self.assertRaisesRegex(ValueError, "xds"):
            xds.layout(b"\0" * 10)


def distinct_blocks(layout):
    """Every visible block of every level filled with its own recognisable bytes."""
    levels = []
    for index, level in enumerate(layout.levels):
        count = level.blocks[0] * level.blocks[1]
        levels.append(b"".join(struct.pack(">HH", index, n) * (layout.block_bytes // 4) for n in range(count)))
    return levels


class BlockTests(unittest.TestCase):
    def test_tiled_offsets_visit_every_block_of_a_tile_once(self):
        for log2 in (3, 4):
            offsets = {xds.tiled_offset_2d(x, y, 32, log2) for y in range(32) for x in range(32)}
            self.assertEqual(offsets, set(range(0, 1024 << log2, 1 << log2)))

    def test_blocks_round_trip_on_an_odd_size(self):
        head = header(200, 72, DXT5, 1, 0, packed=False)
        layout = xds.layout(head)
        levels = distinct_blocks(layout)
        data = xds.write_blocks(head, levels)
        self.assertEqual(len(data), xds.HEADER_SIZE + layout.data_size)
        self.assertEqual(xds.read_blocks(data), levels)

    def test_eight_in_sixteen_endian_swaps_byte_pairs(self):
        head = header(4, 4, DXT1, 1, 0, packed=False)
        data = xds.write_blocks(head, [bytes(range(8))])
        self.assertEqual(data[xds.HEADER_SIZE:xds.HEADER_SIZE + 8], bytes([1, 0, 3, 2, 5, 4, 7, 6]))

    def test_square_packed_mip_chain_round_trips_and_levels_do_not_overlap(self):
        head = header(64, 64, DXT5, 7, 0x4)
        layout = xds.layout(head)
        levels = distinct_blocks(layout)
        data = xds.write_blocks(head, levels)
        self.assertEqual(xds.read_blocks(data), levels)
        tail = [level for level in layout.levels if level.packed_blocks is not None]
        positions = [(level.offset, level.packed_blocks) for level in tail]
        self.assertEqual(len(set(positions)), len(tail))

    def test_non_square_packed_mip_chain_round_trips(self):
        head = header(256, 64, DXT5, 9, 0x10)
        levels = distinct_blocks(xds.layout(head))
        self.assertEqual(xds.read_blocks(xds.write_blocks(head, levels)), levels)

    def test_wide_texture_places_its_smallest_levels_like_the_stock_files(self):
        # The FR-S's 128x64 wood.xds keeps its 4x2, 2x1 and 1x1 levels here.
        layout = xds.layout(header(128, 64, DXT1, 8, 0x2))
        self.assertEqual([level.packed_blocks for level in layout.levels[2:]],
                         [(0, 4), (0, 2), (0, 1), (4, 0), (2, 0), (1, 0)])

    def test_writing_onto_a_template_keeps_its_padding(self):
        head = header(128, 16, DXT5, 1, 0, packed=False)
        template = head + bytes(range(256)) * 64
        data = xds.write_blocks(head, distinct_blocks(xds.layout(head)), template=template)
        visible = {xds.tiled_offset_2d(x, y, 32, 4) + i for y in range(4) for x in range(32) for i in range(16)}
        padding = [i for i in range(16384) if i not in visible]
        self.assertTrue(padding)
        self.assertTrue(all(data[xds.HEADER_SIZE + i] == template[xds.HEADER_SIZE + i] for i in padding))

    def test_roundtrip_reports_an_exact_texture(self):
        head = header(64, 64, DXT5, 7, 0x4)
        data = xds.write_blocks(head, distinct_blocks(xds.layout(head)))
        result = xds.roundtrip(data)
        self.assertEqual((result["byte_exact"], result["differing_bytes"]), (True, 0))

    def test_roundtrip_reports_bytes_outside_every_level(self):
        head = header(128, 16, DXT5, 1, 0, packed=False)
        data = bytearray(xds.write_blocks(head, distinct_blocks(xds.layout(head))))
        data[-1] = 0xAA  # last byte of the tile lies in padding below the 4 visible block rows
        result = xds.roundtrip(bytes(data))
        self.assertEqual((result["byte_exact"], result["differing_bytes"]), (False, 1))

    def test_untiled_textures_are_refused(self):
        head = header(64, 64, DXT5, 1, 0, packed=False, tiled=False)
        with self.assertRaisesRegex(ValueError, "untiled"):
            xds.read_blocks(head + bytes(0x4000))


def texels(rgba, width, x, y):
    return tuple(rgba[4 * (y * width + x):4 * (y * width + x) + 4])


class DecodeTests(unittest.TestCase):
    def test_dxt1_opaque_block_interpolates_two_thirds(self):
        head = header(4, 4, DXT1, 1, 0, packed=False)
        block = struct.pack("<HHI", 0xF800, 0x001F, 0b11_10_01_00)  # red, blue; texels 0-3 use indices 0-3
        rgba = xds.decode_levels(xds.write_blocks(head, [block]))[0]
        self.assertEqual([texels(rgba, 4, x, 0) for x in range(4)],
                         [(255, 0, 0, 255), (0, 0, 255, 255), (170, 0, 85, 255), (85, 0, 170, 255)])

    def test_dxt1_block_with_smaller_first_colour_has_a_transparent_texel(self):
        head = header(4, 4, DXT1, 1, 0, packed=False)
        block = struct.pack("<HHI", 0x001F, 0xF800, 0b11_10)  # texel 0: index 2 (middle), texel 1: index 3
        rgba = xds.decode_levels(xds.write_blocks(head, [block]))[0]
        self.assertEqual(texels(rgba, 4, 0, 0), (128, 0, 128, 255))
        self.assertEqual(texels(rgba, 4, 1, 0), (0, 0, 0, 0))

    def test_dxt5_alpha_uses_eight_steps_when_the_first_endpoint_is_larger(self):
        head = header(4, 4, DXT5, 1, 0, packed=False)
        indices = sum(i << (3 * i) for i in range(8))  # texels 0-7 take alpha indices 0-7
        alpha = bytes([255, 0]) + indices.to_bytes(6, "little")
        rgba = xds.decode_levels(xds.write_blocks(head, [alpha + struct.pack("<HHI", 0xFFFF, 0xFFFF, 0)]))[0]
        self.assertEqual([texels(rgba, 4, x % 4, x // 4)[3] for x in range(8)],
                         [255, 0, 219, 182, 146, 109, 73, 36])

    def test_dxt5_alpha_six_step_mode_ends_in_zero_and_full(self):
        head = header(4, 4, DXT5, 1, 0, packed=False)
        indices = (6 << 0) | (7 << 3)
        alpha = bytes([0, 255]) + indices.to_bytes(6, "little")
        rgba = xds.decode_levels(xds.write_blocks(head, [alpha + struct.pack("<HHI", 0, 0, 0)]))[0]
        self.assertEqual((texels(rgba, 4, 0, 0)[3], texels(rgba, 4, 1, 0)[3]), (0, 255))

    def test_every_mip_level_decodes_at_its_own_size(self):
        head = header(8, 8, DXT5, 4, 0x4)
        layout = xds.layout(head)
        rgba = xds.decode_levels(xds.write_blocks(head, distinct_blocks(layout)))
        self.assertEqual([len(level) for level in rgba], [8 * 8 * 4, 4 * 4 * 4, 2 * 2 * 4, 4])

    def test_png_holds_the_decoded_level(self):
        png = xds.encode_png(2, 1, bytes([1, 2, 3, 4, 5, 6, 7, 8]))
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", png[16:24]), (2, 1))
        self.assertEqual(xds.decode_png(png), (2, 1, bytes([1, 2, 3, 4, 5, 6, 7, 8])))


if __name__ == "__main__":
    unittest.main()
