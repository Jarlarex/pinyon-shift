"""Painting a livery into a cloned car's body textures, with synthetic textures and art only."""
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("paint_fh1_livery", Path(__file__).parents[1] / "paint-fh1-livery.py")
paint = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(paint)
XDS_SPEC = importlib.util.spec_from_file_location("fh1_xds", Path(__file__).parents[1] / "fh1_xds.py")
xds = importlib.util.module_from_spec(XDS_SPEC)
XDS_SPEC.loader.exec_module(xds)


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


# A 16 x 16 stock texture: paint area (alpha 0, white) everywhere except an opaque grey badge at
# texels 0..3 x 0..3; "left" is the top-left quadrant laid upright, "right" the bottom-right one
# laid upside down (front-top corner at its bottom-right).
WHITE = (255, 255, 255)
STOCK = b"".join(bytes((90, 90, 90, 255)) if x < 4 and y < 4 else bytes((*WHITE, 0))
                 for y in range(16) for x in range(16))
PANELS = {
    "left": {"outline": [[0, 0], [0.5, 0], [0.5, 0.5], [0, 0.5]], "frame": [[0, 0], [0.5, 0], [0, 0.5]]},
    "right": {"outline": [[0.5, 0.5], [1, 0.5], [1, 1], [0.5, 1]], "frame": [[1, 1], [0.5, 1], [1, 0.5]]},
}


class RecipeSetup:
    def __init__(self, root: Path):
        self.root = root
        self.panels = root / "panels"
        self.panels.mkdir()
        (self.panels / "DOD_Car_12.json").write_text(json.dumps(table(PANELS)), encoding="utf-8")
        self.ids = root / "ids.json"
        self.ids.write_text(json.dumps({"schema_version": 1, "cars": [{"id": 3001, "stock_id": 1557, "car": "x"}]}))
        self.art = root / "art"
        self.art.mkdir()
        # 2 x 1 art: red on the left, blue on the right.
        (self.art / "flag.png").write_bytes(xds.encode_png(2, 1, bytes((255, 0, 0, 255, 0, 0, 255, 255))))

    def recipe(self, layers, **car):
        data = {"schema_version": 1,
                "car": {"stock_id": 1557, "new_id": 3001, "stock_media": "DOD_Car_12",
                        "media_name": "DOD_Car_RSE_12", "display_name": "Rockstar", "price": None, **car},
                "paint": {"rgb": "111111"}, "layers": layers}
        path = self.root / "test-livery.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return paint.load_recipe(path, art_dir=self.art, panel_tables=self.panels, id_table=self.ids)


def pixel(rgba, x, y, width=16):
    return tuple(rgba[4 * (y * width + x):4 * (y * width + x) + 4])


def changed(before, after, width=16):
    return {(i % width, i // width) for i in range(len(before) // 4) if before[4 * i:4 * i + 3] != after[4 * i:4 * i + 3]}


class CompositeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.setup = RecipeSetup(Path(self.temporary.name))

    def compose(self, layers, size=16, stock=STOCK):
        return paint.compose(stock, size, size, self.setup.recipe(layers))

    def test_a_fill_over_all_colours_the_paint_area_and_keeps_alpha(self):
        out = self.compose([{"fill": "112233", "panels": "all"}])
        self.assertEqual(pixel(out, 10, 10), (0x11, 0x22, 0x33, 0))
        self.assertEqual(pixel(out, 1, 1), (90, 90, 90, 255))           # the badge is not paint
        self.assertEqual(out[3::4], STOCK[3::4])

    def test_a_fill_on_a_panel_stays_inside_its_outline_and_paint_area(self):
        out = self.compose([{"fill": "FF0000", "panels": ["left"]}])
        self.assertEqual(changed(STOCK, out), {(x, y) for x in range(8) for y in range(8)} -
                         {(x, y) for x in range(4) for y in range(4)})

    def test_opaque_also_recolours_stock_opaque_texels_inside_the_outline(self):
        out = self.compose([{"fill": "FF0000", "panels": ["left"], "opaque": True}])
        self.assertEqual(changed(STOCK, out), {(x, y) for x in range(8) for y in range(8)})
        self.assertEqual(pixel(out, 1, 1), (255, 0, 0, 255))

    def test_a_band_follows_the_panel_frame(self):
        # On the upside-down "right" panel, u 0..0.5 and v 0..0.5 is the quadrant at its bottom right.
        out = self.compose([{"band": "00FF00", "panel": "right", "u": [0, 0.5], "v": [0, 0.5]}])
        self.assertEqual(changed(STOCK, out), {(x, y) for x in range(12, 16) for y in range(12, 16)})

    def test_opacity_blends_over_what_is_below(self):
        out = self.compose([{"fill": "000000", "panels": ["right"], "opacity": 0.5}])
        self.assertEqual(pixel(out, 12, 12), (128, 128, 128, 0))

    def test_layers_apply_in_order(self):
        out = self.compose([{"fill": "FF0000", "panels": "all"}, {"fill": "0000FF", "panels": ["right"]}])
        self.assertEqual(pixel(out, 5, 5)[:3], (255, 0, 0))
        self.assertEqual(pixel(out, 12, 12)[:3], (0, 0, 255))

    def image(self, **placement):
        layer = {"image": "flag.png", "panel": "left", "at": [0.5, 0.5], "width": 1.0, **placement}
        return self.compose([layer], size=32, stock=bytes((*WHITE, 0)) * (32 * 32))

    def test_an_image_keeps_its_aspect_and_reads_along_the_panel(self):
        out = self.image()
        # The 16 x 16 panel holds a 16 x 8 image centred on it: red on its front half, blue on its rear.
        self.assertEqual(pixel(out, 2, 8, 32)[:3], (255, 0, 0))
        self.assertEqual(pixel(out, 13, 8, 32)[:3], (0, 0, 255))
        self.assertEqual(pixel(out, 8, 2, 32)[:3], WHITE)                 # above the image
        self.assertEqual(changed(bytes((*WHITE, 0)) * 1024, out, 32), {(x, y) for x in range(16) for y in range(4, 12)})

    def test_mirror_and_rotation_turn_the_image(self):
        mirrored = self.image(mirror=True)
        self.assertEqual((pixel(mirrored, 2, 8, 32)[:3], pixel(mirrored, 13, 8, 32)[:3]), ((0, 0, 255), (255, 0, 0)))
        turned = self.image(rotate=180)
        self.assertEqual((pixel(turned, 2, 8, 32)[:3], pixel(turned, 13, 8, 32)[:3]), ((0, 0, 255), (255, 0, 0)))
        quarter = self.image(rotate=90, width=0.5)
        # Turned a quarter clockwise in panel coordinates (u right, v down): red on top, blue below.
        self.assertEqual((pixel(quarter, 8, 5, 32)[:3], pixel(quarter, 8, 10, 32)[:3]), ((255, 0, 0), (0, 0, 255)))

    def test_an_image_on_an_upside_down_panel_turns_with_it(self):
        layer = {"image": "flag.png", "panel": "right", "at": [0.5, 0.5], "width": 1.0}
        out = paint.compose(bytes((*WHITE, 0)) * 1024, 32, 32, self.setup.recipe([layer]))
        # u runs right to left on this panel, so the front (red) half is on the texture's right.
        self.assertEqual((pixel(out, 29, 24, 32)[:3], pixel(out, 18, 24, 32)[:3]), ((255, 0, 0), (0, 0, 255)))

    def test_transparent_art_changes_nothing(self):
        (self.setup.art / "clear.png").write_bytes(xds.encode_png(2, 2, bytes(16)))
        out = self.compose([{"image": "clear.png", "panel": "left", "at": [0.5, 0.5], "width": 1.0}])
        self.assertEqual(out, STOCK)

    def test_the_same_recipe_paints_the_same_bytes(self):
        layers = [{"fill": "203040", "panels": "all"}, {"image": "flag.png", "panel": "left", "at": [0.4, 0.6],
                                                         "width": 0.7, "rotate": 33, "opacity": 0.8}]
        self.assertEqual(self.compose(layers), self.compose(layers))


class RecipeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.setup = RecipeSetup(Path(self.temporary.name))

    def test_a_recipe_loads_with_its_car_panels_and_art(self):
        recipe = self.setup.recipe([{"image": "flag.png", "panel": "left", "at": [0.5, 0.5], "width": 0.5}])
        self.assertEqual(recipe.name, "test-livery")
        self.assertEqual(recipe.car["media_name"], "DOD_Car_RSE_12")
        self.assertEqual(sorted(recipe.panels), ["left", "right"])
        self.assertEqual(recipe.art["flag.png"][:2], (2, 1))

    def test_bad_recipes_are_refused_with_the_reason(self):
        rgb = self.setup.art / "rgb.png"
        data = bytearray(xds.encode_png(1, 1, bytes(4)))
        data[25] = 2                                       # IHDR colour type 2: RGB without alpha
        rgb.write_bytes(bytes(data))
        cases = {
            "not reserved": ([], {"new_id": 3002}),
            "reserved for a clone of car 1557": ([], {"stock_id": 1600}),
            "no panel table": ([], {"stock_media": "NO_Car_12"}),
            "unknown panel": ([{"fill": "FF0000", "panels": ["roof"]}], {}),
            "colour": ([{"fill": "red", "panels": "all"}], {}),
            "one of fill, band or image": ([{"fill": "FF0000", "band": "FF0000", "panel": "left"}], {}),
            "not found": ([{"image": "missing.png", "panel": "left", "at": [0.5, 0.5], "width": 0.5}], {}),
            "plain file name": ([{"image": "../flag.png", "panel": "left", "at": [0.5, 0.5], "width": 0.5}], {}),
            "8-bit RGBA": ([{"image": "rgb.png", "panel": "left", "at": [0.5, 0.5], "width": 0.5}], {}),
            "opacity": ([{"fill": "FF0000", "panels": "all", "opacity": 2}], {}),
            "whole paint area": ([{"fill": "FF0000", "panels": "all", "opaque": True}], {}),
            "width": ([{"image": "flag.png", "panel": "left", "at": [0.5, 0.5], "width": 0}], {}),
        }
        for message, (layers, car) in cases.items():
            with self.subTest(message), self.assertRaisesRegex(ValueError, message):
                self.setup.recipe(layers, **car)

    def test_an_absolute_art_path_is_refused(self):
        layer = {"image": str(self.setup.art / "flag.png"), "panel": "left", "at": [0.5, 0.5], "width": 0.5}
        with self.assertRaisesRegex(ValueError, "plain file name"):
            self.setup.recipe([layer])


XDS_TESTS = importlib.util.spec_from_file_location("test_fh1_xds_helpers", Path(__file__).with_name("test_fh1_xds.py"))
xds_tests = importlib.util.module_from_spec(XDS_TESTS)
XDS_TESTS.loader.exec_module(xds_tests)


def body_texture(size):
    """A DXT5 body texture like the stock ones: white paint area (alpha 0), an opaque badge top-left."""
    rgba = b"".join(bytes((90, 90, 90, 255)) if x < size // 4 and y < size // 4 else bytes((*WHITE, 0))
                    for y in range(size) for x in range(size))
    return xds.write_xds(xds_tests.header(size, size, xds_tests.DXT5, size.bit_length(), 0x4), rgba, size, size)


class PaintTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.setup = RecipeSetup(Path(self.temporary.name))
        self.clone = Path(self.temporary.name) / "clone"
        self.car = self.clone / "media/cars/DOD_Car_RSE_12"
        self.car.mkdir(parents=True)
        self.stock = {"nodamage.xds": body_texture(64), "nodamage_LOD0.xds": body_texture(128)}
        for name, data in self.stock.items():
            (self.car / name).write_bytes(data)
        (self.car / "damage.xds").write_bytes(b"damage stays stock")
        self.layers = [{"fill": "FF0000", "panels": ["right"]}]

    def test_both_textures_are_repainted_and_only_inside_the_panel(self):
        report = paint.paint_livery(self.setup.recipe(self.layers), self.clone)
        for name, size in (("nodamage.xds", 64), ("nodamage_LOD0.xds", 128)):
            data = (self.car / name).read_bytes()
            level0 = xds.decode_levels(data)[0]
            self.assertEqual(pixel(level0, size * 3 // 4, size * 3 // 4, size)[:3], (255, 0, 0))
            self.assertEqual(pixel(level0, size // 8, size // 2 + 2, size)[:3], WHITE)
            self.assertEqual([level[3::4] for level in xds.decode_levels(data)],
                             [level[3::4] for level in xds.decode_levels(self.stock[name])])
            stock_level0 = xds.read_blocks(self.stock[name])[0]
            blocks = xds.read_blocks(data)[0]
            columns = size // 4
            for index in range(len(blocks) // 16):
                bx, by = index % columns, index // columns
                if bx < columns // 2 or by < columns // 2:      # outside the right panel
                    self.assertEqual(blocks[16 * index:16 * index + 16], stock_level0[16 * index:16 * index + 16])
        self.assertEqual((self.car / "damage.xds").read_bytes(), b"damage stays stock")
        textures = {texture["file"]: texture for texture in report["textures"]}
        lod0 = textures["media/cars/DOD_Car_RSE_12/nodamage_LOD0.xds"]
        self.assertEqual(lod0["size"], "128x128")
        self.assertEqual(lod0["panels"], {"right": 64 * 64, "left": 0})
        self.assertEqual(lod0["sha256"], hashlib.sha256((self.car / "nodamage_LOD0.xds").read_bytes()).hexdigest())
        self.assertGreater(lod0["blocks_reencoded"][0], 0)
        self.assertEqual(report["car"]["new_id"], 3001)

    def test_painting_twice_gives_the_same_bytes(self):
        paint.paint_livery(self.setup.recipe(self.layers), self.clone)
        first = {name: (self.car / name).read_bytes() for name in self.stock}
        for name, data in self.stock.items():
            (self.car / name).write_bytes(data)
        paint.paint_livery(self.setup.recipe(self.layers), self.clone)
        self.assertEqual({name: (self.car / name).read_bytes() for name in self.stock}, first)

    def test_previews_show_the_painted_textures(self):
        preview = Path(self.temporary.name) / "preview"
        paint.paint_livery(self.setup.recipe(self.layers), self.clone, preview=preview)
        width, height, rgba = xds.decode_png((preview / "DOD_Car_RSE_12_nodamage.png").read_bytes())
        self.assertEqual((width, height), (64, 64))
        self.assertEqual(pixel(rgba, 48, 48, 64), (255, 0, 0, 255))

    def test_a_clone_without_the_car_or_its_textures_is_refused(self):
        with self.assertRaisesRegex(ValueError, "no media/cars/DOD_Car_RSE_12"):
            paint.paint_livery(self.setup.recipe(self.layers), Path(self.temporary.name) / "elsewhere")
        (self.car / "nodamage_LOD0.xds").unlink()
        with self.assertRaisesRegex(ValueError, "nodamage_LOD0.xds"):
            paint.paint_livery(self.setup.recipe(self.layers), self.clone)
        self.assertEqual((self.car / "nodamage.xds").read_bytes(), self.stock["nodamage.xds"])

    def test_a_failure_leaves_the_clone_unchanged(self):
        def fail(stock, rgba):
            calls.append(stock)
            if len(calls) == 2:            # the second texture, after the first was already painted
                raise ValueError("encoder stopped")
            return original(stock, rgba)

        calls, original = [], paint.xds.repaint_xds
        with patch.object(paint.xds, "repaint_xds", side_effect=fail):
            with self.assertRaisesRegex(ValueError, "encoder stopped"):
                paint.paint_livery(self.setup.recipe(self.layers), self.clone)
        self.assertEqual({name: (self.car / name).read_bytes() for name in self.stock}, self.stock)
        self.assertEqual(sorted(p.name for p in self.car.iterdir()), ["damage.xds", "nodamage.xds", "nodamage_LOD0.xds"])

    def test_the_paint_command_prints_its_report(self):
        recipe = self.setup.root / "test-livery.json"
        self.setup.recipe(self.layers)
        args = ["paint", str(recipe), "--clone", str(self.clone), "--art", str(self.setup.art),
                "--panels", str(self.setup.panels), "--ids", str(self.setup.ids)]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(paint.main(args), 0)
        self.assertEqual(json.loads(out.getvalue())["recipe"], "test-livery")
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            self.assertEqual(paint.main(args[:3] + [str(self.clone / "missing")] + args[4:]), 1)
        self.assertIn("no media/cars/DOD_Car_RSE_12", err.getvalue())


if __name__ == "__main__":
    unittest.main()
