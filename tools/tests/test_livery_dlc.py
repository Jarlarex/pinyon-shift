"""Livery packages in the DLC manager: install, rebuild, list, toggle and verify, from a synthetic stock car."""
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dlc = load("manage_fh1_dlc_for_livery", TOOLS / "manage-fh1-dlc.py")
package = load("package_fh1_livery_for_livery", TOOLS / "package-fh1-livery.py")
package_tests = load("test_package_fh1_livery_for_livery", Path(__file__).with_name("test_package_fh1_livery.py"))
strings = load("fh1_strings_for_livery", TOOLS / "fh1-strings.py")
CAR_ID = package_tests.CAR["new_id"]
NO_GAME = b""
GAME_RUNNING = b'"pinyon_shift.exe","1234","Console","1","1,000 K"'


class LiveryInstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.setup = package_tests.PackageSetup(Path(self.temporary.name))
        self.state = self.setup.files.state
        self.id = package.package_id(CAR_ID)
        self.active, self.inactive, self.header = dlc.package_paths(self.state, self.id)
        self.game = patch.object(dlc.subprocess, "check_output", return_value=NO_GAME)
        self.game.start()
        self.addCleanup(self.game.stop)

    def install(self, recipe=None):
        return dlc.install_livery(self.state, self.setup.files.game, Path("extractor.exe"),
                                  recipe or self.setup.recipe_path, self.setup.root / "art",
                                  panels=self.setup.panels, ids=self.setup.files.ids)

    def record(self, package_id=None):
        return json.loads((self.state / "dlc" / f"{package_id or self.id}.json").read_text(encoding="utf-8"))

    def listed(self):
        return next(r for r in dlc.list_content(self.state) if r["package_id"] == self.id)

    def car_rows(self, folder, sql):
        merge = package_tests.read_zip((folder / "Media/DLCZips/3001_pri_65.zip").read_bytes())
        return package_tests.rows_of(dict(merge)["media/db/patch/3001000_merge.slt"], sql)

    def names(self, folder, car_id=CAR_ID):
        tables = dict(package_tests.read_zip((folder / f"Media/DLCZips/StringTables_pri_{car_id}.zip").read_bytes()))
        return dict(strings.parse(tables["EN/Data_Car.str"]))

    def add_livery_package(self, car_id, keys, enabled=True):
        """Another livery car's package and record, as install-livery leaves them."""
        other = package.package_id(car_id)
        active, inactive, header = dlc.package_paths(self.state, other)
        content = active if enabled else inactive
        (content / "Media").mkdir(parents=True)
        (content / f"Media/{car_id}.puboffer").write_bytes(b" \r\n")
        header.parent.mkdir(parents=True, exist_ok=True)
        header.write_bytes(package.content_header(other, f"Car {car_id}"))
        _, digest = dlc.payload_catalog(content)
        (self.state / "dlc").mkdir(exist_ok=True)
        (self.state / "dlc" / f"{other}.json").write_text(json.dumps({
            "package_id": other, "display_name": f"Car {car_id}", "kind": "generated", "car_id": car_id,
            "string_keys": keys, "payload_sha256": digest, "file_count": 1, "license_mask": "00000001",
            "header_sha256": hashlib.sha256(header.read_bytes()).hexdigest().upper()}))
        return other

    def test_install_builds_the_package_and_leaves_the_car_enabled(self):
        result = self.install()
        self.assertTrue((self.active / "Media/3001.puboffer").is_file())
        self.assertFalse(self.inactive.exists())
        header = self.header.read_bytes()
        self.assertEqual(header, package.content_header(self.id, "2012 Dodge Car Rockstar"))
        record = self.record()
        _, digest = dlc.payload_catalog(self.active)
        self.assertEqual((record["kind"], record["car_id"], record["stock_id"], record["license_mask"]),
                         ("generated", 3001, 1557, "00000001"))
        self.assertEqual(record["payload_sha256"], digest)
        self.assertEqual(record["header_sha256"], hashlib.sha256(header).hexdigest().upper())
        self.assertEqual(record["recipe_sha256"], hashlib.sha256(self.setup.recipe_path.read_bytes()).hexdigest().upper())
        self.assertEqual(record["string_keys"], result["livery"]["string_keys"])
        listed = self.listed()
        self.assertEqual((listed["enabled"], listed["status"], listed["display_name"]),
                         (True, "gameplay_unverified", "2012 Dodge Car Rockstar"))
        dlc.verified_content(self.state, self.id, require_enabled=True)
        self.assertEqual(result["livery"]["package_id"], self.id)
        self.assertFalse(list((self.state / "dlc").glob("staging-*")))

    def test_installing_changes_no_other_file(self):
        def hashes():
            files = sorted(self.state.rglob("*")) + sorted(self.setup.files.game.rglob("*"))
            return {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.is_file()}
        before = hashes()
        self.install()
        after = hashes()
        new = {self.header, self.state / "dlc" / f"{self.id}.json", self.state / "dlc" / "import.lock"}
        self.assertEqual({p: h for p, h in after.items() if p not in new and self.active not in p.parents}, before)

    def test_disable_and_enable_move_the_package(self):
        self.install()
        dlc.set_enabled(self.state, self.id, False)
        self.assertTrue(self.inactive.is_dir())
        self.assertFalse(self.listed()["enabled"])
        dlc.set_enabled(self.state, self.id, True)
        self.assertTrue(self.active.is_dir())

    def test_a_changed_payload_header_or_record_is_refused(self):
        self.install()
        dlc.set_enabled(self.state, self.id, False)
        offer = self.inactive / "Media/3001.puboffer"
        offer.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "incomplete or changed"):
            dlc.set_enabled(self.state, self.id, True)
        offer.write_bytes(b" \r\n")
        original = self.header.read_bytes()
        self.header.write_bytes(original[:328] + (3).to_bytes(4, "little"))
        with self.assertRaisesRegex(ValueError, "licence changed"):
            dlc.set_enabled(self.state, self.id, True)
        self.header.write_bytes(original)
        record = self.record()
        # Widening the licence in the record (with a matching header) is refused too.
        self.header.write_bytes(original[:328] + (3).to_bytes(4, "little"))
        (self.state / "dlc" / f"{self.id}.json").write_text(json.dumps(record | {
            "license_mask": "00000003", "header_sha256": hashlib.sha256(self.header.read_bytes()).hexdigest().upper()}))
        with self.assertRaisesRegex(ValueError, "licence changed"):
            dlc.set_enabled(self.state, self.id, True)
        self.assertTrue(self.inactive.is_dir())

    def test_a_rebuild_replaces_the_package_and_keeps_its_state(self):
        self.install()
        dlc.set_enabled(self.state, self.id, False)
        recipe = json.loads(self.setup.recipe_path.read_text())
        recipe["car"]["price"] = 60000
        self.setup.recipe_path.write_text(json.dumps(recipe))
        self.install()
        self.assertTrue(self.inactive.is_dir())
        self.assertFalse(self.active.exists())
        self.assertEqual(self.car_rows(self.inactive, "SELECT BaseCost FROM Data_Car"), [(60000,)])
        self.assertEqual(len(list((self.state / "dlc/replaced" / self.id).iterdir())), 1)
        dlc.set_enabled(self.state, self.id, True)
        # Enabled, the car's own rows are in the game database; the rebuild must not see them as taken.
        recipe["car"]["price"] = 61000
        self.setup.recipe_path.write_text(json.dumps(recipe))
        self.install()
        self.assertEqual(self.car_rows(self.active, "SELECT BaseCost FROM Data_Car"), [(61000,)])
        dlc.verified_content(self.state, self.id, require_enabled=True)

    def test_a_running_game_is_refused_before_anything_is_written(self):
        with patch.object(dlc.subprocess, "check_output", return_value=GAME_RUNNING):
            with self.assertRaisesRegex(ValueError, "close the game"):
                self.install()
        self.assertFalse(self.active.exists() or self.header.exists())

    def test_string_keys_another_livery_package_holds_are_refused(self):
        self.add_livery_package(3002, [{"field": "DisplayName", "key": 6003, "text": "Other"}], enabled=False)
        with self.assertRaisesRegex(ValueError, "string key 6003"):
            self.install()
        self.assertFalse(self.active.exists() or self.header.exists())
        self.assertFalse((self.state / "dlc" / f"{self.id}.json").exists())

    def test_the_names_of_the_other_enabled_livery_cars_are_included(self):
        self.add_livery_package(3002, [{"field": "DisplayName", "key": 6100, "text": "Other livery car"}])
        self.add_livery_package(3003, [{"field": "DisplayName", "key": 6200, "text": "Disabled livery car"}],
                                enabled=False)
        self.install()
        names = self.names(self.active)
        self.assertEqual(names[6100], "Other livery car")
        self.assertNotIn(6200, names)

    def test_content_this_tool_did_not_build_is_left_in_place(self):
        (self.active / "Media").mkdir(parents=True)
        (self.active / "Media/other.puboffer").write_bytes(b"other")
        with self.assertRaisesRegex(ValueError, "did not build"):
            self.install()
        self.assertEqual((self.active / "Media/other.puboffer").read_bytes(), b"other")

    def test_installing_a_folder_of_dlc_leaves_a_disabled_livery_car_disabled(self):
        self.install()
        dlc.set_enabled(self.state, self.id, False)
        empty = self.setup.root / "no-dlc"
        empty.mkdir()
        dlc.install_folder(empty, self.state, Path("extractor.exe"))
        self.assertFalse(self.listed()["enabled"])

    def test_the_install_livery_command_prints_the_packages(self):
        args = ["install-livery", "--state-root", self.state, "--game-root", self.setup.files.game,
                "--recipe", self.setup.recipe_path, "--art", self.setup.root / "art", "--extractor", "extractor.exe",
                "--panels", self.setup.panels, "--ids", self.setup.files.ids]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = dlc.main([str(arg) for arg in args])
        self.assertEqual(code, 0, err.getvalue())
        result = json.loads(out.getvalue())
        self.assertEqual(result["livery"]["package_id"], self.id)
        self.assertIn(self.id, [record["package_id"] for record in result["packages"]])


if __name__ == "__main__":
    unittest.main()
