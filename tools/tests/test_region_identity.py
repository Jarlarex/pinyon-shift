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
                self.assertIn(dump["build_support"], {"supported", "v4", "pending"})
                self.assertTrue(dump["game_root"].startswith(".local/game/"))
                self.assertTrue(dump["voice_languages"])
                self.assertTrue(dump["serial"] is None or isinstance(dump["serial"], str))

    def test_usa_disc_keeps_its_identity_and_build(self):
        usa = next(dump for dump in self.table["dumps"] if dump["region"] == "USA")
        self.assertEqual(usa["id"], "forza-horizon-usa-ms-2505-retail-base")
        self.assertEqual(usa["game_root"], ".local/game/base")
        self.assertEqual(usa["build_support"], "supported")
        self.assertEqual(self.table["dumps"][0], usa)

    def test_eur_disc_builds_on_its_title_update(self):
        eur = next(dump for dump in self.table["dumps"] if dump["region"] == "EUR")
        self.assertEqual(eur["media_id"], "4000D145")
        self.assertEqual(eur["version"], "0.0.0.12")
        self.assertEqual(eur["build_support"], "v4")
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


REGION_FIELDS = dict(region="EUR", media_id="4000D145", version="0.0.0.12",
                     build_support="pending", game_root=".local/game/eur-base")


def fixture_repo(root: Path, scripts: list[str], game_contents: dict[str, bytes], iso: bytes) -> Path:
    """A temporary repository with one EU-like dump whose ISO and game folder are synthetic."""
    for script in scripts:
        target = root / "tools" / script
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "tools" / script, target)
    config = root / "config"
    config.mkdir()
    iso_path = root / "fixture.iso"
    iso_path.write_bytes(iso)
    iso_sha256 = hashlib.sha256(iso).hexdigest().upper()
    game = root / "game"
    write_tree(game, game_contents)
    catalog = CATALOG.build_catalog(game, "fixture-eur", iso_sha256)
    (config / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    executables = [dict(guest_path=entry["guest_path"], role="entrypoint", size_bytes=entry["size_bytes"],
                        sha256=entry["sha256"]) for entry in catalog["files"] if entry["guest_path"] == "default.xex"]
    dump = dict(id="fixture-eur", status="fixture", title_id="4D5309C9", serial=None, **REGION_FIELDS,
                iso=dict(size_bytes=len(iso), sha256=iso_sha256),
                extraction=dict(file_catalog="catalog.json", file_count=len(catalog["files"])),
                executables=executables)
    (config / "supported-dumps.json").write_text(json.dumps(dict(schema_version=2, dumps=[dump])), encoding="utf-8")
    return game


def run_script(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args],
                          capture_output=True)


@unittest.skipUnless(shutil.which("powershell"), "Windows PowerShell required")
class VerifierRegionTests(unittest.TestCase):
    CONTENTS = {"default.xex": b"eu executable", "media/vo/VO_DE.fev": b"german"}

    def test_iso_verifier_reports_region_fields(self):
        with tempfile.TemporaryDirectory(prefix="pinyon-region-") as temporary:
            root = Path(temporary)
            game = fixture_repo(root, ["verify-game.ps1"], self.CONTENTS, b"fixture iso bytes")
            result = run_script(root / "tools/verify-game.ps1", "-IsoPath", str(root / "fixture.iso"),
                                "-ExtractedRoot", str(game), "-Json")
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            report = json.loads(result.stdout)
            self.assertTrue(report["recognized"])
            for key, value in REGION_FIELDS.items():
                self.assertEqual(report[key], value, key)
            self.assertTrue(report["extracted_executables_match"])

            (root / "fixture.iso").write_bytes(b"fixture iso byteZ")
            result = run_script(root / "tools/verify-game.ps1", "-IsoPath", str(root / "fixture.iso"), "-Json")
            self.assertEqual(result.returncode, 1)
            self.assertFalse(json.loads(result.stdout)["recognized"])

    def test_extracted_verifier_reports_region_fields(self):
        with tempfile.TemporaryDirectory(prefix="pinyon-region-") as temporary:
            root = Path(temporary)
            game = fixture_repo(root, ["verify-extracted-game.ps1"], self.CONTENTS, b"iso")
            result = run_script(root / "tools/verify-extracted-game.ps1", "-ExtractedRoot", str(game), "-Json")
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            report = json.loads(result.stdout)
            for key, value in REGION_FIELDS.items():
                self.assertEqual(report[key], value, key)


PENDING_BUILD_EXIT = 3


@unittest.skipUnless(shutil.which("powershell"), "Windows PowerShell required")
class SetupRegionTests(unittest.TestCase):
    CONTENTS = {"default.xex": b"eu executable", "media/vo/VO_DE.fev": b"german"}

    def test_pending_region_extracts_beside_usa_and_stops_before_building(self):
        with tempfile.TemporaryDirectory(prefix="pinyon-region-") as temporary:
            root = Path(temporary)
            game = fixture_repo(root, ["verify-extracted-game.ps1", "setup-preview.ps1", "release-common.ps1"],
                                self.CONTENTS, b"iso")
            shutil.copyfile(ROOT / "config/release-toolchain.json", root / "config/release-toolchain.json")
            for name in ("provision-toolchain", "prepare-rexglue", "build-preview", "prepare-fh1-shaders"):
                (root / f"tools/{name}.ps1").write_text(
                    "param([switch]$JsonEvents, [string]$GameRoot)\n"
                    "Add-Content -LiteralPath (Join-Path $PSScriptRoot '../stages.txt') '" + name + "'\n")
            (root / "tools/setup-title-update.ps1").write_text(
                "param([string]$StateRoot, [string]$MediaId, [string]$Region, [switch]$JsonEvents)\n"
                "Add-Content -LiteralPath (Join-Path $PSScriptRoot '../stages.txt') "
                "\"title-update $MediaId $Region $(Split-Path $StateRoot -Leaf)\"\n")
            usa = root / ".local/game/base"
            usa.mkdir(parents=True)
            (usa / "default.xex").write_bytes(b"usa executable")
            # The completed USA build's state must keep describing that build.
            usa_state = '{"dump_id": "forza-horizon-usa-ms-2505-retail-base", "result": "ready"}\n'
            (root / ".local/setup-state.json").write_text(usa_state)

            command = [str(root / "tools/setup-preview.ps1"), "-ExtractedPath", str(game), "-JsonEvents"]
            result = run_script(*command)
            self.assertEqual(result.returncode, PENDING_BUILD_EXIT, result.stderr.decode(errors="replace"))
            eur = root / ".local/game/eur-base"
            for name, data in self.CONTENTS.items():
                self.assertEqual((eur / name).read_bytes(), data)
            self.assertEqual((usa / "default.xex").read_bytes(), b"usa executable")
            self.assertEqual((root / "stages.txt").read_text().splitlines(),
                             ["provision-toolchain", "prepare-rexglue", "title-update 4000D145 EUR preview"])
            self.assertEqual((root / ".local/setup-state.json").read_text(), usa_state)
            state = json.loads((root / ".local/setup-pending-build.json").read_text())
            self.assertEqual(state["result"], "extracted_pending_build")
            self.assertEqual(state["dump_id"], "fixture-eur")
            self.assertEqual(state["region"], "EUR")
            self.assertIn(b"not supported yet", result.stdout)
            self.assertFalse((root / ".local/logs/setup-error.json").exists())

            # A second run reuses the verified extraction and stops at the same point.
            result = run_script(*command)
            self.assertEqual(result.returncode, PENDING_BUILD_EXIT, result.stderr.decode(errors="replace"))
            self.assertEqual((usa / "default.xex").read_bytes(), b"usa executable")

    def v4_fixture(self, root: Path, *, update_installed: bool) -> list[str]:
        game = fixture_repo(root, ["verify-extracted-game.ps1", "setup-preview.ps1", "release-common.ps1"],
                            self.CONTENTS, b"iso")
        shutil.copyfile(ROOT / "config/release-toolchain.json", root / "config/release-toolchain.json")
        table_path = root / "config/supported-dumps.json"
        table = json.loads(table_path.read_text())
        table["dumps"][0]["build_support"] = "v4"
        table_path.write_text(json.dumps(table))
        stages = "Add-Content -LiteralPath (Join-Path $PSScriptRoot '../stages.txt')"
        for name in ("provision-toolchain", "prepare-rexglue", "build-preview"):
            (root / f"tools/{name}.ps1").write_text(f"param([switch]$JsonEvents)\n{stages} '{name}'\n")
        (root / "tools/setup-title-update.ps1").write_text(
            "param([string]$StateRoot, [string]$MediaId, [string]$Region, [switch]$JsonEvents)\n"
            f"{stages} 'title-update'\n")
        (root / "tools/build-v4.ps1").write_text(
            "param([string]$StateRoot, [string]$GameRoot, [switch]$JsonEvents)\n"
            f"{stages} \"build-v4 $(Split-Path $GameRoot -Leaf) $(Split-Path $StateRoot -Leaf)\"\n")
        (root / "tools/prepare-fh1-shaders.ps1").write_text(
            "param([string]$StateRoot, [string]$GameRoot, [string]$BuildDirectory, [switch]$JsonEvents)\n"
            f"{stages} \"shaders $(Split-Path $GameRoot -Leaf) $(Split-Path $BuildDirectory -Leaf)\"\n")
        if update_installed:
            update = root / ".local/preview/title-update-v4"
            update.mkdir(parents=True)
            for name in ("default.xexp", "SpeechFacade_default.xexp", "XMediaFacade_default.xexp", "media.zip"):
                (update / name).write_bytes(b"verified")
        return [str(root / "tools/setup-preview.ps1"), "-ExtractedPath", str(game), "-JsonEvents"]

    def test_v4_region_builds_the_title_update_from_its_own_game_root(self):
        with tempfile.TemporaryDirectory(prefix="pinyon-region-") as temporary:
            root = Path(temporary)
            result = run_script(*self.v4_fixture(root, update_installed=True))
            self.assertEqual(result.returncode, 0, result.stdout.decode(errors="replace"))
            self.assertEqual((root / "stages.txt").read_text().splitlines(),
                             ["provision-toolchain", "prepare-rexglue", "title-update",
                              "build-v4 eur-base preview", "shaders eur-base win-amd64-v4"])
            state = json.loads((root / ".local/setup-state.json").read_text())
            self.assertEqual(state["build"], "v4")
            self.assertEqual(state["game_root"], ".local/game/eur-base")
            self.assertEqual(state["result"], "ready")

    def test_v4_region_without_its_title_update_stops_and_says_why(self):
        with tempfile.TemporaryDirectory(prefix="pinyon-region-") as temporary:
            root = Path(temporary)
            result = run_script(*self.v4_fixture(root, update_installed=False))
            self.assertEqual(result.returncode, PENDING_BUILD_EXIT, result.stderr.decode(errors="replace"))
            self.assertIn(b"needs the title update", result.stdout)
            self.assertNotIn("build-v4", (root / "stages.txt").read_text())
            self.assertFalse((root / ".local/setup-state.json").exists())

    def test_game_root_outside_the_local_game_folder_is_refused(self):
        with tempfile.TemporaryDirectory(prefix="pinyon-region-") as temporary:
            root = Path(temporary)
            game = fixture_repo(root, ["verify-extracted-game.ps1", "setup-preview.ps1", "release-common.ps1"],
                                self.CONTENTS, b"iso")
            shutil.copyfile(ROOT / "config/release-toolchain.json", root / "config/release-toolchain.json")
            for name in ("provision-toolchain", "prepare-rexglue"):
                (root / f"tools/{name}.ps1").write_text("param([switch]$JsonEvents)\n")
            table_path = root / "config/supported-dumps.json"
            table = json.loads(table_path.read_text())
            table["dumps"][0]["game_root"] = ".local/game/../../outside"
            table_path.write_text(json.dumps(table))
            result = run_script(str(root / "tools/setup-preview.ps1"), "-ExtractedPath", str(game), "-JsonEvents")
            self.assertEqual(result.returncode, 1)
            self.assertIn(b"Unexpected local game destination", result.stdout + result.stderr)
            self.assertFalse((root / "outside").exists())


if __name__ == "__main__":
    unittest.main()
