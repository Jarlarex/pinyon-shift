"""The livery-car route generator against the routes livery-package ran in game."""
import importlib.util
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
ROOT = TOOLS.parent


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generator = load("make_livery_car_routes", TOOLS / "make-livery-car-routes.py")
paint = load("paint_fh1_livery_for_routes", TOOLS / "paint-fh1-livery.py")
runner = load("run_fh1_render_test_for_routes", TOOLS / "run-fh1-render-test.py")
TEST_RECIPE = ROOT / "config/livery-cars/tests/challenger-test.json"


def steps(text: str) -> list[str]:
    return [line for line in text.splitlines() if line and not line.startswith("#")]


class RouteGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.recipe = paint.load_recipe(TEST_RECIPE, require_art=False)
        self.routes = generator.routes(self.recipe, 14, 4, kinds=generator.KINDS)

    def route(self, kind):
        return self.routes[f"fh1-promo-challenger-test-{kind}.fh1test"]

    def committed(self, name):
        return (ROOT / "config/render-tests" / f"{name}.fh1test").read_text(encoding="utf-8")

    def test_the_showroom_and_reload_routes_are_the_ones_livery_package_ran(self):
        self.assertEqual(steps(self.route("showroom")), steps(self.committed("fh1-livery-car-showroom")))
        self.assertEqual(steps(self.route("reload")), steps(self.committed("fh1-livery-car-reload")))

    def test_the_buy_route_drops_only_the_showroom_save_wait(self):
        # That wait held for car 3001 but timed out for the F100 (fh1-livery-car-disable): it depends on the car.
        committed = [line for line in steps(self.committed("fh1-livery-car-buy")) if not line.endswith("file playerdatabase")]
        self.assertEqual(len(committed), len(steps(self.committed("fh1-livery-car-buy"))) - 1)
        self.assertEqual(steps(self.route("buy")), committed)

    def test_every_route_is_one_the_runner_accepts(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, text in self.routes.items():
                with self.subTest(route=name):
                    path = Path(directory) / name
                    path.write_text(text, encoding="utf-8")
                    captures = runner.parse_scenario(path)[0]
                    self.assertTrue(captures)

    def test_each_route_names_its_car_and_traces_it(self):
        for name, text in self.routes.items():
            with self.subTest(route=name):
                self.assertIn("# dlc-car-trace\n# dlc-car-ids 3001,1557\n", text)
                self.assertIn("recipe challenger-test", text)
                self.assertFalse({c for c in text if ord(c) < 32 and c != "\n"})

    def test_the_garage_and_paint_routes_travel_to_their_hub_icons(self):
        self.assertIn("input 3020 0000 0 0 -20000 -10000 0 0", steps(self.route("garage")))
        self.assertIn("input 3020 0000 0 0 -20000 -15000 0 0", steps(self.route("paint")))
        for kind in ("paint", "paint-clear"):
            self.assertIn("renderer-log check", self.route(kind))

    def test_the_list_captures_the_cards_asked_for(self):
        listed = generator.routes(self.recipe, 17, 0, kinds=("list",), cards=5)["fh1-promo-challenger-test-list.fh1test"]
        self.assertEqual([line.split()[2] for line in steps(listed) if line.startswith("capture ")][-5:],
                         ["card-00", "card-01", "card-02", "card-03", "card-04"])
        self.assertEqual(sum(1 for line in steps(listed) if line.endswith(" 0008 0 0 0 0 0 0")), 17 + 4)

    def test_an_unknown_kind_is_refused(self):
        with self.assertRaisesRegex(ValueError, "no route kind 'race'"):
            generator.routes(self.recipe, 14, 4, kinds=("race",))

    def test_the_command_writes_the_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            out, err = io.StringIO(), io.StringIO()
            args = ["--recipe", str(TEST_RECIPE), "--make-presses", "14", "--car-presses", "4", "--output", directory]
            with redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(generator.main(args), 0, err.getvalue())
                self.assertEqual(generator.main(args[:2] + ["--make-presses=-1"] + args[4:]), 1)
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()),
                             [f"fh1-promo-challenger-test-{kind}.fh1test" for kind in ("buy", "list", "reload", "showroom")])
            self.assertIn("presses must be 0 or more", err.getvalue())


if __name__ == "__main__":
    unittest.main()
