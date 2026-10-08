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


import http.server
import os
import threading

FETCH_SPEC = importlib.util.spec_from_file_location("fetch_title_update", ROOT / "tools/fetch-title-update.py")
FETCH = importlib.util.module_from_spec(FETCH_SPEC)
FETCH_SPEC.loader.exec_module(FETCH)

PACKAGE = os.urandom(200_000)


class ScriptedServer:
    """A local HTTP server; each path has a behavior, and every request is counted."""

    def __init__(self, routes: dict):
        self.routes, self.hits = routes, []
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                server.hits.append((self.path, self.headers.get("Range")))
                kind, body = server.routes.get(self.path, ("404", b""))
                if kind == "404":
                    self.send_error(404)
                elif kind == "redirect":
                    self.send_response(302)
                    self.send_header("Location", body)
                    self.end_headers()
                elif kind == "drop":
                    # Announce the full size, then close after part of the body.
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body[: len(body) // 2])
                    server.routes[self.path] = ("range", body)
                elif kind == "range" and self.headers.get("Range"):
                    start = int(self.headers["Range"].removeprefix("bytes=").split("-")[0])
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
                    self.send_header("Content-Length", str(len(body) - start))
                    self.end_headers()
                    self.wfile.write(body[start:])
                else:
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class FetchTests(unittest.TestCase):
    UPDATE = "fixture-update"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pinyon-tu-fetch-")
        self.root = Path(self.temporary.name) / "repo"
        self.state = Path(self.temporary.name) / "state"
        (self.root / "config").mkdir(parents=True)
        package = dict(size_bytes=len(PACKAGE), sha256=hashlib.sha256(PACKAGE).hexdigest().upper())
        (self.root / "config/supported-title-updates.json").write_text(
            json.dumps(dict(updates=[dict(id=self.UPDATE, package=package)])))
        self.events = []

    def tearDown(self):
        self.temporary.cleanup()

    def serve(self, routes: dict) -> ScriptedServer:
        server = ScriptedServer(routes)
        self.addCleanup(server.close)
        sources = [dict(id=path.strip("/"), url=server.base + path) for path in routes if path.startswith("/s")]
        (self.root / "config/title-update-sources.json").write_text(
            json.dumps(dict(schema_version=1, sources={self.UPDATE: sources})))
        return server

    def fetch(self, **options):
        return FETCH.fetch(self.state, update_id=self.UPDATE, root=self.root, emit=self.events.append, **options)

    @property
    def package(self) -> Path:
        return self.state / "downloads/title-update" / f"{self.UPDATE}.pkg"

    def test_falls_through_to_the_next_source_and_publishes_the_package(self):
        self.serve({"/s1": ("404", b""), "/s2": ("plain", PACKAGE)})
        result = self.fetch()
        self.assertEqual(result["status"], "downloaded")
        self.assertEqual(result["source"], "s2")
        self.assertEqual(self.package.read_bytes(), PACKAGE)
        self.assertFalse(self.package.with_suffix(".partial").exists())
        names = [event["event"] for event in self.events]
        self.assertEqual(names[0], "tu_download_plan")
        self.assertIn("tu_download_source_failed", names)
        self.assertEqual(names[-1], "tu_download_done")

    def test_wrong_bytes_everywhere_fall_back_without_leaving_files(self):
        wrong = bytearray(PACKAGE)
        wrong[0] ^= 1
        self.serve({"/s1": ("plain", bytes(wrong)), "/s2": ("plain", bytes(wrong))})
        result = self.fetch()
        self.assertEqual(result["status"], "fallback")
        self.assertEqual([failure["source"] for failure in result["failures"]], ["s1", "s2"])
        self.assertFalse(self.package.exists())
        self.assertFalse(self.package.with_suffix(".partial").exists())
        self.assertEqual(self.events[-1]["event"], "tu_download_fallback")

    def test_oversized_body_is_aborted_at_the_pinned_size(self):
        self.serve({"/s1": ("plain", PACKAGE + b"x" * 100_000)})
        result = self.fetch()
        self.assertEqual(result["status"], "fallback")
        self.assertIn("larger", result["failures"][0]["reason"])
        self.assertFalse(self.package.exists())

    def test_interrupted_transfer_resumes_with_range(self):
        server = self.serve({"/s1": ("drop", PACKAGE)})
        self.assertEqual(self.fetch()["status"], "fallback")
        self.assertTrue(self.package.with_suffix(".partial").is_file())
        result = self.fetch()
        self.assertEqual(result["status"], "downloaded")
        self.assertEqual(self.package.read_bytes(), PACKAGE)
        self.assertEqual(server.hits[-1][1], f"bytes={len(PACKAGE) // 2}-")

    def test_source_that_ignores_range_restarts_cleanly(self):
        partial = self.package.with_suffix(".partial")
        partial.parent.mkdir(parents=True)
        partial.write_bytes(PACKAGE[:1000])
        self.serve({"/s1": ("plain", PACKAGE)})
        self.assertEqual(self.fetch()["status"], "downloaded")
        self.assertEqual(self.package.read_bytes(), PACKAGE)

    def test_cached_package_needs_no_network_and_a_damaged_one_is_replaced(self):
        server = self.serve({"/s1": ("plain", PACKAGE)})
        self.assertEqual(self.fetch()["status"], "downloaded")
        hits = len(server.hits)
        self.assertEqual(self.fetch()["status"], "cached")
        self.assertEqual(len(server.hits), hits)
        self.package.write_bytes(b"damaged")
        self.assertEqual(self.fetch()["status"], "downloaded")
        self.assertEqual(self.package.read_bytes(), PACKAGE)

    def test_offline_makes_no_requests(self):
        server = self.serve({"/s1": ("plain", PACKAGE)})
        self.assertEqual(self.fetch(offline=True)["status"], "fallback")
        self.assertEqual(server.hits, [])
        self.assertEqual(self.events[-1]["event"], "tu_download_fallback")

    def test_redirect_loops_fail_and_the_next_source_is_tried(self):
        server = self.serve({"/s1": ("redirect", "/loop"), "/s2": ("plain", PACKAGE)})
        server.routes["/loop"] = ("redirect", "/loop")
        result = self.fetch()
        self.assertEqual(result["status"], "downloaded")
        self.assertEqual(result["source"], "s2")
        self.assertLessEqual(sum(path == "/loop" for path, _ in server.hits), FETCH.MAX_REDIRECTS)

    def test_nothing_is_written_outside_the_download_folder(self):
        self.serve({"/s1": ("plain", PACKAGE)})
        self.fetch()
        written = {path.relative_to(self.state).as_posix() for path in self.state.rglob("*") if path.is_file()}
        self.assertEqual(written, {f"downloads/title-update/{self.UPDATE}.pkg"})


import shutil
import subprocess
import sys


@unittest.skipUnless(shutil.which("powershell"), "Windows PowerShell required")
class SetupTitleUpdateTests(unittest.TestCase):
    """tools/setup-title-update.ps1 with stubbed fetch, manage and build steps."""

    def run_step(self, media_id: str, region: str, *, fetch_status: str = "downloaded", profiles: str = "{}",
                 extractor: bool = True):
        temporary = tempfile.TemporaryDirectory(prefix="pinyon-tu-setup-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "tools").mkdir()
        (root / "config").mkdir()
        for name in ("setup-title-update.ps1", "release-common.ps1"):
            shutil.copyfile(ROOT / "tools" / name, root / "tools" / name)
        shutil.copyfile(ROOT / "config/release-toolchain.json", root / "config/release-toolchain.json")
        bases = [dict(media_id="4000D145"), dict(media_id="2DC7007B")]
        (root / "config/supported-title-updates.json").write_text(json.dumps(dict(updates=[dict(verified_bases=bases)])))
        log = root / "calls.txt"
        imported = "true" if fetch_status != "fallback" else "false"
        (root / "tools/fetch-title-update.py").write_text(
            "import json, sys\n"
            f"open(r'{log}', 'a').write('fetch ' + ' '.join(sys.argv[1:]) + '\\n')\n"
            "print('::pinyon::' + json.dumps(dict(stage='tools', percent=33, message='plan')))\n"
            f"print(json.dumps(dict(status='{fetch_status}', imported={imported.title()})))\n")
        (root / "tools/manage-title-update.ps1").write_text(
            "param([string]$Action, [string]$StateRoot)\n"
            f"Add-Content -LiteralPath '{log}' \"manage $Action\"\n"
            f"'{{\"profiles\": {profiles}}}'\n")
        (root / "tools/build-title-update-tools.ps1").write_text(
            f"param([switch]$JsonEvents)\nAdd-Content -LiteralPath '{log}' 'build'\n")
        if extractor:
            tools = root / "out/build/title-update-tools"
            tools.mkdir(parents=True)
            (tools / "pinyon_shift_fh1_archive_extract.exe").write_bytes(b"exe")
        result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                 str(root / "tools/setup-title-update.ps1"), "-StateRoot", str(root / "state"),
                                 "-MediaId", media_id, "-Region", region, "-Python", sys.executable,
                                 "-JsonEvents"], capture_output=True, text=True)
        calls = log.read_text().splitlines() if log.exists() else []
        return result, calls

    def test_eu_fresh_profile_downloads_imports_and_enables_v4(self):
        result, calls = self.run_step("4000D145", "EUR")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(calls[0].startswith("fetch --state-root"))
        self.assertIn("--json-events", calls[0])
        self.assertEqual(calls[1:], ["manage status", "manage enable"])
        self.assertIn("::pinyon::", result.stdout)

    def test_eu_with_base_saves_leaves_the_choice_to_the_player(self):
        result, calls = self.run_step("4000D145", "EUR", profiles='{"E0000ABCD": "base"}')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("manage enable", calls)
        self.assertIn("existing", result.stdout)

    def test_usa_downloads_but_keeps_the_base_build(self):
        result, calls = self.run_step("2DC7007B", "USA")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 1)

    def test_fallback_and_unknown_discs_never_fail_setup(self):
        result, calls = self.run_step("4000D145", "EUR", fetch_status="fallback")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("manage enable", calls)
        result, calls = self.run_step("12345678", "EUR")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [])

    def test_missing_extractor_is_built_first(self):
        result, calls = self.run_step("4000D145", "EUR", extractor=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[0], "build")


class SourceListTests(unittest.TestCase):
    def test_sources_name_known_updates_with_http_urls_and_no_hashes(self):
        sources = load("title-update-sources.json")
        known = {update["id"] for update in load("supported-title-updates.json")["updates"]}
        self.assertEqual(sources["schema_version"], 1)
        for update_id, entries in sources["sources"].items():
            self.assertIn(update_id, known)
            self.assertEqual(len({entry["id"] for entry in entries}), len(entries))
            for entry in entries:
                self.assertEqual(set(entry), {"id", "url"})
                self.assertRegex(entry["url"], r"^https?://")


if __name__ == "__main__":
    unittest.main()
