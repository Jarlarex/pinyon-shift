"""Painting a livery into a cloned car's body textures, with synthetic textures and art only."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("paint_fh1_livery", Path(__file__).parents[1] / "paint-fh1-livery.py")
paint = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(paint)


def close(test, a, b, places=9):
    for x, y in zip(a, b):
        test.assertAlmostEqual(x, y, places=places)


def table(panels, stock_media="DOD_Car_12"):
    return {"schema_version": 1, "stock_media": stock_media, "panels": panels}


SQUARE = {"outline": [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]],
          "frame": [[0.25, 0.25], [0.75, 0.25], [0.25, 0.75]]}


class FrameTests(unittest.TestCase):
    def test_a_frame_maps_panel_corners_to_its_three_points(self):
        frame = paint.Frame.from_points([[0.1, 0.2], [0.9, 0.2], [0.1, 0.5]])
        close(self, frame.to_texture(0, 0), (0.1, 0.2))
        close(self, frame.to_texture(1, 0), (0.9, 0.2))
        close(self, frame.to_texture(0, 1), (0.1, 0.5))
        close(self, frame.to_texture(1, 1), (0.9, 0.5))
        close(self, frame.to_texture(0.5, 0.5), (0.5, 0.35))

    def test_every_rotation_and_mirror_round_trips(self):
        # Front-top, rear-top, front-bottom corners of the same 0.6 x 0.2 rectangle, turned and flipped.
        frames = {"upright": [[0.2, 0.4], [0.8, 0.4], [0.2, 0.6]],
                  "upside down": [[0.8, 0.6], [0.2, 0.6], [0.8, 0.4]],     # the Pizza Hut's upper side panel
                  "quarter turn": [[0.6, 0.2], [0.6, 0.8], [0.4, 0.2]],
                  "three quarters": [[0.4, 0.8], [0.4, 0.2], [0.6, 0.8]],
                  "mirrored": [[0.8, 0.4], [0.2, 0.4], [0.8, 0.6]],
                  "mirrored upside down": [[0.2, 0.6], [0.8, 0.6], [0.2, 0.4]]}
        for name, points in frames.items():
            with self.subTest(name):
                frame = paint.Frame.from_points(points)
                for u, v in ((0, 0), (1, 0), (0, 1), (0.3, 0.7), (1, 1)):
                    close(self, frame.to_panel(*frame.to_texture(u, v)), (u, v))
        for name in ("upright", "upside down", "quarter turn", "three quarters"):
            self.assertFalse(paint.Frame.from_points(frames[name]).mirrored, name)
        self.assertTrue(paint.Frame.from_points(frames["mirrored"]).mirrored)
        self.assertTrue(paint.Frame.from_points(frames["mirrored upside down"]).mirrored)

    def test_a_frame_whose_points_lie_on_a_line_is_refused(self):
        with self.assertRaisesRegex(ValueError, "frame"):
            paint.Frame.from_points([[0.1, 0.1], [0.5, 0.5], [0.9, 0.9]])

    def test_the_frame_gives_the_panel_length_and_height_in_texels(self):
        frame = paint.Frame.from_points([[0.1, 0.2], [0.9, 0.2], [0.1, 0.5]])
        close(self, frame.size(1000, 500), (800.0, 150.0))


class MaskTests(unittest.TestCase):
    @staticmethod
    def texels(mask, width):
        return {(i % width, i // width) for i, inside in enumerate(mask) if inside}

    def test_a_square_covers_the_texels_whose_centres_it_holds(self):
        mask = paint.polygon_mask(SQUARE["outline"], 8, 8)
        self.assertEqual(self.texels(mask, 8), {(x, y) for x in range(2, 6) for y in range(2, 6)})

    def test_a_concave_outline_leaves_its_notch_out(self):
        notch = [[0, 0], [1, 0], [1, 1], [0.5, 1], [0.5, 0.5], [0, 0.5]]
        texels = self.texels(paint.polygon_mask(notch, 4, 4), 4)
        self.assertEqual(texels, {(x, y) for x in range(4) for y in range(2)} | {(x, y) for x in (2, 3) for y in (2, 3)})

    def test_the_mask_follows_the_texture_size(self):
        self.assertEqual(sum(paint.polygon_mask(SQUARE["outline"], 64, 32)), 32 * 16)

    def test_a_triangle_includes_a_texel_only_when_its_centre_is_inside(self):
        texels = self.texels(paint.polygon_mask([[0, 0], [1, 0], [0, 1]], 4, 4), 4)
        self.assertEqual(texels, {(x, y) for y in range(4) for x in range(4) if (x + 0.5) + (y + 0.5) < 4})


class PanelTableTests(unittest.TestCase):
    def load(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "DOD_Car_12.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return paint.load_panels(path)

    def test_a_table_loads_its_panels(self):
        panels = self.load(table({"left": SQUARE, "top": SQUARE}))
        self.assertEqual(sorted(panels), ["left", "top"])
        self.assertEqual(panels["left"].outline, [(0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75)])
        close(self, panels["left"].frame.to_texture(1, 1), (0.75, 0.75))

    def test_bad_tables_are_refused_with_the_reason(self):
        cases = {
            "schema_version": {"schema_version": 2, "stock_media": "DOD_Car_12", "panels": {"left": SQUARE}},
            "no panels": table({}),
            "panel name": table({"Left Side": SQUARE}),
            "3 to 32 points": table({"left": {**SQUARE, "outline": [[0, 0], [1, 1]]}}),
            "between 0 and 1": table({"left": {**SQUARE, "outline": [[0, 0], [1.5, 0], [1, 1]]}}),
            "frame": table({"left": {**SQUARE, "frame": [[0, 0], [1, 1]]}}),
            "line": table({"left": {**SQUARE, "frame": [[0.1, 0.1], [0.5, 0.5], [0.9, 0.9]]}}),
            "stock_media": table({"left": SQUARE}, stock_media="OTHER_Car_12"),
        }
        for message, data in cases.items():
            with self.subTest(message), self.assertRaisesRegex(ValueError, message):
                self.load(data)


if __name__ == "__main__":
    unittest.main()
