#!/usr/bin/env python3
"""Write the extracted-file catalog for a supported dump.

`verify-extracted-game.ps1` accepts an extracted game folder only when every
file matches this catalog by size and SHA-256. Run it once on a folder that
setup extracted from a verified ISO; the catalog holds paths, sizes and hashes
only, never game data. The disc's `$SystemUpdate` is not game input and is
skipped, as setup and the verifier skip it."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SYSTEM_UPDATE = "$SystemUpdate"


def build_catalog(root: Path, dump_id: str, iso_sha256: str) -> dict:
    if not re.fullmatch(r"[0-9A-F]{64}", iso_sha256):
        raise ValueError("the ISO SHA-256 must be 64 uppercase hexadecimal digits")
    root = root.resolve()
    files = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if relative.parts[0] == SYSTEM_UPDATE:
            continue
        if path.is_symlink() or path.is_junction():
            raise ValueError(f"linked game input is unsupported: {relative.as_posix()}")
        if not path.is_file():
            continue
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest().upper()
        files.append(dict(guest_path=relative.as_posix(), size_bytes=path.stat().st_size, sha256=digest))
    if not files:
        raise ValueError("the extracted game folder is empty")
    files.sort(key=lambda entry: entry["guest_path"].casefold())
    return dict(schema_version=1, dump_id=dump_id, iso_sha256=iso_sha256, files=files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, required=True, help="verified extracted game folder")
    parser.add_argument("--dump-id", required=True, help="id of the dump in config/supported-dumps.json")
    parser.add_argument("--iso-sha256", required=True, help="the dump's whole-ISO SHA-256")
    parser.add_argument("--out", type=Path, required=True, help="catalog file to write")
    parser.add_argument("--force", action="store_true", help="replace an existing catalog")
    args = parser.parse_args(argv)
    if args.out.exists() and not args.force:
        print(f"{args.out} exists; pass --force to replace it", file=sys.stderr)
        return 1
    try:
        catalog = build_catalog(args.root, args.dump_id, args.iso_sha256.upper())
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    args.out.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(catalog['files'])} files to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
