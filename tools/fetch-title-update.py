#!/usr/bin/env python3
"""Download the pinned FH1 title update and import it into a state root.

Sources come from config/title-update-sources.json, tried in order; the size
and SHA-256 come only from config/supported-title-updates.json, so a source can
never change what is accepted. The package is written to
<state>/downloads/title-update/<id>.partial and renamed to <id>.pkg once it
matches. An interrupted transfer resumes when the source honours Range. Any
failure, or --offline / PINYON_OFFLINE=1, ends in a "fallback" result: setup
then continues with the base disc. Only this one title update is ever fetched."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UPDATE = "forza-horizon-world-v4-4000d145"
MAX_REDIRECTS = 5
CHUNK = 1 << 16
TIMEOUT_SECONDS = 30


class SourceFailed(Exception):
    pass


class LimitedRedirects(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS

    def redirect_request(self, request, fp, code, message, headers, new_url):
        if urllib.parse.urlsplit(new_url).scheme not in ("http", "https"):
            raise urllib.error.HTTPError(new_url, code, "redirect to a non-HTTP address", headers, fp)
        return super().redirect_request(request, fp, code, message, headers, new_url)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest().upper()


def matches(path: Path, size: int, digest: str) -> bool:
    return path.is_file() and path.stat().st_size == size and sha256(path) == digest


def download(url: str, partial: Path, size: int, digest: str, progress: Callable[[int], None]) -> None:
    offset = partial.stat().st_size if partial.is_file() else 0
    if offset >= size:
        partial.unlink()
        offset = 0
    request = urllib.request.Request(url, headers={"User-Agent": "PinyonShift title-update fetch"})
    if offset:
        request.add_header("Range", f"bytes={offset}-")
    opener = urllib.request.build_opener(LimitedRedirects)
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            resumed = bool(offset) and response.status == 206 and \
                (response.headers.get("Content-Range") or "").startswith(f"bytes {offset}-")
            written = offset if resumed else 0
            with partial.open("ab" if resumed else "wb") as output:
                while chunk := response.read(CHUNK):
                    written += len(chunk)
                    if written > size:
                        output.close()
                        partial.unlink()
                        raise SourceFailed(f"the download is larger than the pinned {size} bytes")
                    output.write(chunk)
                    progress(written)
    except (OSError, urllib.error.URLError) as error:
        # Network trouble keeps what arrived so the next attempt can resume.
        raise SourceFailed(f"download failed: {error}") from error
    if written != size:
        raise SourceFailed(f"the download stopped at {written} of {size} bytes")
    if sha256(partial) != digest:
        partial.unlink()
        raise SourceFailed("the download does not match the pinned SHA-256")


def fetch(state_root: Path, *, update_id: str = DEFAULT_UPDATE, root: Path = ROOT, offline: bool = False,
          emit: Callable[[dict], None] = lambda event: None) -> dict:
    updates = json.loads((root / "config/supported-title-updates.json").read_text(encoding="utf-8"))["updates"]
    update = next(entry for entry in updates if entry["id"] == update_id)
    size, digest = update["package"]["size_bytes"], update["package"]["sha256"].upper()
    folder = state_root / "downloads/title-update"
    package, partial = folder / f"{update_id}.pkg", folder / f"{update_id}.partial"
    if package.is_file():
        if matches(package, size, digest):
            return dict(status="cached", package=str(package), update_id=update_id)
        package.unlink()

    def fallback(reason: str, failures: list[dict]) -> dict:
        emit(dict(event="tu_download_fallback", stage="tools", percent=36,
                  message=f"Continuing with the base disc: the title update is unavailable ({reason}).",
                  failures=failures))
        return dict(status="fallback", reason=reason, failures=failures, update_id=update_id)

    if offline:
        return fallback("offline", [])
    sources_path = root / "config/title-update-sources.json"
    sources = json.loads(sources_path.read_text(encoding="utf-8"))["sources"].get(update_id, []) \
        if sources_path.is_file() else []
    if not sources:
        return fallback("no download source is configured", [])
    hosts = ", ".join(dict.fromkeys(urllib.parse.urlsplit(source["url"]).hostname for source in sources))
    emit(dict(event="tu_download_plan", stage="tools", percent=33, size_bytes=size, sha256=digest,
              folder=str(folder), sources=[source["url"] for source in sources],
              message=f"Downloading the title update ({size / 1048576:.1f} MB) from {hosts}. "
                      f"It is checked against SHA-256 {digest[:8]}…{digest[-4:]} and saved in {folder}."))
    folder.mkdir(parents=True, exist_ok=True)
    failures = []
    for source in sources:
        reported = -10

        def progress(written: int) -> None:
            nonlocal reported
            percent = written * 100 // size
            if percent >= reported + 10:
                reported = percent
                emit(dict(event="tu_download_progress", stage="tools", percent=33 + percent * 3 // 100,
                          message=f"Downloading the title update: {percent}%", source=source["id"]))

        try:
            download(source["url"], partial, size, digest, progress)
        except SourceFailed as error:
            failures.append(dict(source=source["id"], reason=str(error)))
            emit(dict(event="tu_download_source_failed", stage="tools", percent=33,
                      message=f"Title update source {source['id']} failed: {error}", source=source["id"]))
            continue
        partial.replace(package)
        emit(dict(event="tu_download_done", stage="tools", percent=36, source=source["id"],
                  message="The title update was downloaded and matches its pinned SHA-256."))
        return dict(status="downloaded", source=source["id"], package=str(package), update_id=update_id)
    return fallback("every source failed", failures)


def import_package(state_root: Path, package: str) -> str | None:
    """Install through the existing verifier path; returns an error message on failure."""
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                             str(ROOT / "tools/manage-title-update.ps1"), "-Action", "import",
                             "-StateRoot", str(state_root), "-InputPath", package],
                            capture_output=True, text=True)
    if result.returncode == 0:
        return None
    lines = (result.stderr or result.stdout).strip().splitlines()
    return lines[-1] if lines else f"the import failed with exit code {result.returncode}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--update-id", default=DEFAULT_UPDATE)
    parser.add_argument("--offline", action="store_true", help="never use the network (also PINYON_OFFLINE=1)")
    parser.add_argument("--no-import", action="store_true", help="download only")
    parser.add_argument("--json-events", action="store_true", help="print ::pinyon:: progress events")
    args = parser.parse_args(argv)

    def emit(event: dict) -> None:
        if args.json_events:
            print("::pinyon::" + json.dumps(event, separators=(",", ":"), ensure_ascii=False), flush=True)

    offline = args.offline or os.environ.get("PINYON_OFFLINE") == "1"
    state_root = args.state_root.resolve()
    result = fetch(state_root, update_id=args.update_id, offline=offline, emit=emit)
    if result["status"] != "fallback" and not args.no_import:
        error = import_package(state_root, result["package"])
        if error:
            # The verified package stays for a later import; this run uses the base disc.
            emit(dict(event="tu_download_fallback", stage="tools", percent=36,
                      message=f"Continuing with the base disc: {error}"))
            result = dict(result, status="fallback", reason=error)
        else:
            result = dict(result, imported=True)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
