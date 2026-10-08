import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("extracted_catalog", ROOT / "tools/generate-extracted-catalog.py")
CATALOG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CATALOG)


def write_tree(root: Path, contents: dict[str, bytes]) -> None:
    for name, data in contents.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


class ExtractedCatalogTests(unittest.TestCase):
    def test_catalog_lists_game_files_sorted_and_skips_the_system_update(self):
        with tempfile.TemporaryDirectory(prefix="pinyon-catalog-") as temporary:
            game = Path(temporary) / "game"
            write_tree(game, {
                "default.xex": b"executable",
                "SpeechFacade_default.xex": b"speech",
                "media/b.zip": b"bb",
                "media/A.zip": b"a",
                "$SystemUpdate/su.bin": b"not game input",
            })
            catalog = CATALOG.build_catalog(game, "fixture-dump", "AB" * 32)
            self.assertEqual(catalog["schema_version"], 1)
            self.assertEqual(catalog["dump_id"], "fixture-dump")
            self.assertEqual(catalog["iso_sha256"], "AB" * 32)
            paths = [entry["guest_path"] for entry in catalog["files"]]
            self.assertEqual(paths, ["default.xex", "media/A.zip", "media/b.zip", "SpeechFacade_default.xex"])
            entry = catalog["files"][0]
            self.assertEqual(entry["size_bytes"], len(b"executable"))
            self.assertEqual(entry["sha256"], hashlib.sha256(b"executable").hexdigest().upper())

    def test_cli_refuses_to_overwrite_without_force(self):
        with tempfile.TemporaryDirectory(prefix="pinyon-catalog-") as temporary:
            game = Path(temporary) / "game"
            write_tree(game, {"default.xex": b"x"})
            out = Path(temporary) / "catalog.json"
            out.write_text("{}", encoding="utf-8")
            args = ["--root", str(game), "--dump-id", "d", "--iso-sha256", "CD" * 32, "--out", str(out)]
            self.assertNotEqual(CATALOG.main(args), 0)
            self.assertEqual(out.read_text(encoding="utf-8"), "{}")
            self.assertEqual(CATALOG.main(args + ["--force"]), 0)
            written = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(written["files"][0]["guest_path"], "default.xex")
            self.assertTrue(out.read_text(encoding="utf-8").endswith("\n"))

    def test_rejects_an_invalid_iso_hash(self):
        with tempfile.TemporaryDirectory(prefix="pinyon-catalog-") as temporary:
            game = Path(temporary) / "game"
            write_tree(game, {"default.xex": b"x"})
            with self.assertRaises(ValueError):
                CATALOG.build_catalog(game, "d", "not-a-hash")


class DumpTableTests(unittest.TestCase):
    def setUp(self):
        self.table = json.loads((ROOT / "config/supported-dumps.json").read_text(encoding="utf-8"))

    def test_every_dump_describes_its_region_and_build_support(self):
        self.assertEqual(self.table["schema_version"], 2)
        dumps = self.table["dumps"]
        self.assertEqual(len({dump["id"] for dump in dumps}), len(dumps))
        self.assertEqual(len({dump["game_root"] for dump in dumps}), len(dumps))
        self.assertEqual(len({dump["media_id"] for dump in dumps}), len(dumps))
        for dump in dumps:
            with self.subTest(dump=dump["id"]):
                self.assertIn(dump["region"], {"USA", "EUR"})
                self.assertRegex(dump["media_id"], r"^[0-9A-F]{8}$")
                self.assertRegex(dump["version"], r"^\d+\.\d+\.\d+\.\d+$")
                self.assertIn(dump["build_support"], {"supported", "pending"})
                self.assertTrue(dump["game_root"].startswith(".local/game/"))
                self.assertTrue(dump["voice_languages"])
                self.assertTrue(dump["serial"] is None or isinstance(dump["serial"], str))

    def test_usa_disc_keeps_its_identity_and_build(self):
        usa = next(dump for dump in self.table["dumps"] if dump["region"] == "USA")
        self.assertEqual(usa["id"], "forza-horizon-usa-ms-2505-retail-base")
        self.assertEqual(usa["game_root"], ".local/game/base")
        self.assertEqual(usa["build_support"], "supported")
        self.assertEqual(self.table["dumps"][0], usa)

    def test_eur_disc_is_recognized_but_not_buildable_yet(self):
        eur = next(dump for dump in self.table["dumps"] if dump["region"] == "EUR")
        self.assertEqual(eur["media_id"], "4000D145")
        self.assertEqual(eur["version"], "0.0.0.12")
        self.assertEqual(eur["build_support"], "pending")
        self.assertIsNone(eur["serial"])
        self.assertNotIn("rally_adapter_inputs", eur)
        self.assertEqual(eur["title_id"], "4D5309C9")

    def test_extracted_catalogs_match_their_dumps(self):
        for dump in self.table["dumps"]:
            with self.subTest(dump=dump["id"]):
                catalog = json.loads((ROOT / "config" / dump["extraction"]["file_catalog"]).read_text(encoding="utf-8"))
                self.assertEqual(catalog["dump_id"], dump["id"])
                self.assertEqual(catalog["iso_sha256"], dump["iso"]["sha256"])
                self.assertEqual(len(catalog["files"]), dump["extraction"]["file_count"])
                self.assertEqual(sum(entry["size_bytes"] for entry in catalog["files"]),
                                 dump["extraction"]["size_bytes"])
                by_path = {entry["guest_path"]: entry for entry in catalog["files"]}
                for executable in dump["executables"]:
                    self.assertEqual(by_path[executable["guest_path"]]["sha256"], executable["sha256"])


if __name__ == "__main__":
    unittest.main()
