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


if __name__ == "__main__":
    unittest.main()
