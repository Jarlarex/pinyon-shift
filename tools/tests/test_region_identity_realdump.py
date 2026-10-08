"""Checks the region table against personally dumped discs; skipped unless PINYON_DUMPS_DIR is set.

Point PINYON_DUMPS_DIR at a folder holding the USA and EU ISOs (any file names). Nothing is
copied, extracted or written; the verifier only reads and hashes the images."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
DUMPS = os.environ.get("PINYON_DUMPS_DIR")


def verify(*args: str) -> dict:
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                             str(ROOT / "tools" / args[0]), *args[1:], "-Json"], capture_output=True)
    return json.loads(result.stdout)


@unittest.skipUnless(DUMPS and shutil.which("powershell"), "set PINYON_DUMPS_DIR to run against real dumps")
class RealDumpRegionTests(unittest.TestCase):
    def test_each_iso_is_recognized_with_its_region(self):
        expected = {"USA": ("2DC7007B", "supported"), "EUR": ("4000D145", "v4")}
        seen = set()
        for iso in sorted(Path(DUMPS).glob("*.iso")):
            with self.subTest(iso=iso.name):
                report = verify("verify-game.ps1", "-IsoPath", str(iso))
                self.assertTrue(report["recognized"], report)
                media_id, build_support = expected[report["region"]]
                self.assertEqual(report["media_id"], media_id)
                self.assertEqual(report["build_support"], build_support)
                seen.add(report["region"])
        self.assertEqual(seen, set(expected))

    def test_extracted_eu_folder_is_recognized(self):
        game = ROOT / ".local/game/eur-base"
        if not (game / "default.xex").is_file():
            self.skipTest("the EU disc has not been extracted by setup")
        report = verify("verify-extracted-game.ps1", "-ExtractedRoot", str(game))
        self.assertTrue(report["recognized"], report.get("mismatches"))
        self.assertEqual(report["region"], "EUR")


if __name__ == "__main__":
    unittest.main()
