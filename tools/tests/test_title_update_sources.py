import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


def load(name: str) -> dict:
    return json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))


class VerifiedBaseTests(unittest.TestCase):
    def test_each_verified_base_is_a_supported_dump(self):
        dumps = {dump["media_id"]: dump for dump in load("supported-dumps.json")["dumps"]}
        for update in load("supported-title-updates.json")["updates"]:
            for base in update["verified_bases"]:
                with self.subTest(media_id=base["media_id"]):
                    dump = dumps[base["media_id"]]
                    executables = {entry["guest_path"]: entry["sha256"] for entry in dump["executables"]}
                    self.assertEqual({module["guest_path"]: module["base_sha256"] for module in base["modules"]},
                                     executables)

    def test_eu_base_is_the_update_target_and_rebuilds_the_same_images(self):
        update = load("supported-title-updates.json")["updates"][0]
        bases = {base["media_id"]: base for base in update["verified_bases"]}
        self.assertEqual(update["media_id"], "4000D145")
        eur, usa = bases["4000D145"], bases["2DC7007B"]
        self.assertEqual(eur["version"], update["source_version"])
        images = lambda base: {module["guest_path"]: module["image_sha256"] for module in base["modules"]}
        self.assertEqual(images(eur), images(usa))
        for module in eur["modules"]:
            self.assertRegex(module["headers_sha256"], r"^[0-9A-F]{64}$")


import hashlib
import importlib.util
import tempfile

SPEC = importlib.util.spec_from_file_location("title_update", ROOT / "tools/verify-fh1-title-update.py")
TITLE_UPDATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TITLE_UPDATE)


class DefaultInputTests(unittest.TestCase):
    def fixture(self, root: Path, installed: dict[str, bytes]) -> None:
        """Two dumps (USA in base, EU in eur-base); the update lists both executables as verified bases."""
        config = root / "config"
        config.mkdir()
        digests = {name: hashlib.sha256(name.encode()).hexdigest().upper() for name in ("usa", "eur")}
        dumps = [dict(id=name, game_root=game_root, executables=[dict(guest_path="default.xex", sha256=digests[name])])
                 for name, game_root in (("usa", ".local/game/base"), ("eur", ".local/game/eur-base"))]
        (config / "supported-dumps.json").write_text(json.dumps(dict(dumps=dumps)))
        bases = [dict(modules=[dict(guest_path="default.xex", base_sha256=digest)]) for digest in digests.values()]
        (config / "supported-title-updates.json").write_text(json.dumps(dict(updates=[dict(verified_bases=bases)])))
        for game_root, data in installed.items():
            (root / game_root).mkdir(parents=True)
            (root / game_root / "default.xex").write_bytes(data)

    def test_base_root_follows_the_installed_verified_disc(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root, {".local/game/eur-base": b"eur"})
            self.assertEqual(TITLE_UPDATE.default_base_root(root), root / ".local/game/eur-base")

    def test_usa_wins_when_both_are_installed_and_unknown_files_are_skipped(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root, {".local/game/base": b"usa", ".local/game/eur-base": b"eur"})
            self.assertEqual(TITLE_UPDATE.default_base_root(root), root / ".local/game/base")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root, {".local/game/base": b"modified", ".local/game/eur-base": b"eur"})
            self.assertEqual(TITLE_UPDATE.default_base_root(root), root / ".local/game/eur-base")

    def test_without_an_installed_base_the_legacy_root_is_used(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root, {})
            self.assertEqual(TITLE_UPDATE.default_base_root(root), root / ".local/game/base")

    def test_extractor_is_found_in_the_game_or_tools_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release, tools = (root / path / TITLE_UPDATE.EXTRACTOR_NAME for path in TITLE_UPDATE.EXTRACTOR_BUILDS)
            self.assertEqual(TITLE_UPDATE.default_extractor(root), release)
            tools.parent.mkdir(parents=True)
            tools.write_bytes(b"exe")
            self.assertEqual(TITLE_UPDATE.default_extractor(root), tools)
            release.parent.mkdir(parents=True)
            release.write_bytes(b"exe")
            self.assertEqual(TITLE_UPDATE.default_extractor(root), release)


if __name__ == "__main__":
    unittest.main()
