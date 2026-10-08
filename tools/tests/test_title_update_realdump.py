"""Downloads and installs the real title update into a temporary state root.

Skipped unless PINYON_DUMPS_DIR is set (the EU disc must already be extracted by
setup into .local/game/eur-base) and PINYON_NETWORK_TESTS=1 allows the download.
Nothing is written outside the temporary state root."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
ENABLED = bool(os.environ.get("PINYON_DUMPS_DIR")) and os.environ.get("PINYON_NETWORK_TESTS") == "1"


def fetch(state: Path, *extra: str) -> dict:
    result = subprocess.run([sys.executable, str(ROOT / "tools/fetch-title-update.py"), "--state-root", str(state),
                             *extra], capture_output=True, text=True)
    return json.loads(result.stdout.strip().splitlines()[-1])


@unittest.skipUnless(ENABLED and shutil.which("powershell"), "set PINYON_DUMPS_DIR and PINYON_NETWORK_TESTS=1")
class RealTitleUpdateTests(unittest.TestCase):
    def test_download_verify_install_reuse_and_offline_fallback(self):
        if not (ROOT / ".local/game/eur-base/default.xex").is_file():
            self.skipTest("the EU disc has not been extracted by setup")
        with tempfile.TemporaryDirectory(prefix="pinyon-tu-real-") as temporary:
            state = Path(temporary)
            first = fetch(state)
            self.assertEqual(first["status"], "downloaded", first)
            self.assertTrue(first["imported"], first)
            installed = sorted(path.name for path in (state / "title-update-v4").iterdir())
            self.assertEqual(installed, ["SpeechFacade_default.xexp", "XMediaFacade_default.xexp",
                                         "default.xexp", "media.zip"])
            second = fetch(state)
            self.assertEqual(second["status"], "cached", second)
            offline = fetch(Path(temporary) / "other-state", "--offline")
            self.assertEqual(offline["status"], "fallback")
            self.assertEqual(offline["reason"], "offline")


if __name__ == "__main__":
    unittest.main()
