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


if __name__ == "__main__":
    unittest.main()
