#!/usr/bin/env python3
"""Import verified owned FH1 content into the runtime's existing content tree."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
CONTENT = Path("0000000000000000/4D5309C9")
PACKAGE_ID = re.compile(r"[0-9A-F]{1,42}\Z")
MAGIC = (b"LIVE", b"PIRS", b"CON ")
MAX_PACKAGE = 2 * 1024**3
RALLY = "6F6992766050D818245ADD408031E280FB5F4E634D"
GENERATED = "generated"   # import records of livery packages built by install-livery
LIVERY_MASK = "00000001"


def long_path(path: Path) -> Path:
    path = path.resolve()
    if os.name == "nt" and not str(path).startswith("\\\\?\\"):
        value = str(path)
        return Path("\\\\?\\UNC\\" + value[2:] if value.startswith("\\\\") else "\\\\?\\" + value)
    return path


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def catalog() -> dict:
    return json.loads((ROOT / "config/supported-dlc.json").read_text(encoding="utf-8"))


def import_record(path: Path) -> dict | None:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if (isinstance(record, dict) and record.get("package_id") == path.stem and
                isinstance(record.get("display_name", path.stem), str) and
                all(isinstance(record[key], str) and re.fullmatch(r"[0-9A-F]{64}", record[key])
                    for key in ("sha256", "payload_sha256", "header_sha256") if key in record)):
            return record
    except (OSError, ValueError):
        pass
    return None


def package_paths(state: Path, package_id: str) -> tuple[Path, Path, Path]:
    if not PACKAGE_ID.fullmatch(package_id):
        raise ValueError("invalid package ID")
    title = state / "user" / CONTENT
    return (title / "00000002" / package_id,
            title / "Disabled" / "00000002" / package_id,
            title / "Headers" / "00000002" / (package_id + ".header"))


def payload_catalog(root: Path) -> tuple[list[dict], str]:
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("content contains a symbolic link")
        if path.is_file():
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest().upper()
            files.append(dict(path=path.relative_to(root).as_posix(),
                              size=path.stat().st_size, sha256=digest))
    digest = hashlib.sha256(json.dumps(files, sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest().upper()
    return files, digest


def inspect(stream, size: int, manifest: dict) -> tuple[dict, dict]:
    header = stream.read(0x971A)
    if len(header) != 0x971A or header[:4] not in MAGIC:
        raise ValueError("not an Xbox 360 content package")
    if header[0x360:0x364].hex().upper() != manifest["title_id"]:
        raise ValueError("package belongs to another game")
    if header[0x344:0x348].hex().upper() != manifest["content_type"]:
        raise ValueError("expected Marketplace DLC, not a title update or save")
    if not len(header) <= size <= MAX_PACKAGE:
        raise ValueError("invalid DLC package size")
    content_id = header[0x32C:0x340].hex().upper()
    package = next((p for p in manifest["packages"] if p["content_id"] == content_id), None)
    if package is None:
        raise ValueError("this DLC package is not in the verified catalog")
    digest = hashlib.sha256(header)
    total = len(header)
    while block := stream.read(4 * 1024**2):
        total += len(block)
        if total > size:
            raise ValueError("package size changed while reading")
        digest.update(block)
    if total != size:
        raise ValueError("incomplete DLC package")
    sha = digest.hexdigest().upper()
    for rejected in package["rejected"]:
        if rejected["sha256"] == sha:
            if rejected.get("license_only") and rejected["size"] == size:
                return package, rejected
            raise ValueError(f'{package["display_name"]}: {rejected["reason"]}')
    variant = next((v for v in package["accepted"] if v["size"] == size and v["sha256"] == sha), None)
    if variant is None:
        raise ValueError(f'{package["display_name"]}: SHA-256 differs from the verified inputs')
    return package, variant


class LicenceOnlyInput(ValueError):
    """A copy whose payload is rejected but whose licence may join a verified copy."""

    @classmethod
    def for_package(cls, package: dict) -> "LicenceOnlyInput":
        return cls(f'{package["display_name"]}: this copy supplies only its licence; '
                   'import the verified package too')


def licence_variants(package: dict) -> list[dict]:
    """Variants whose licence counts: accepted copies, then rejected copies
    marked license_only, whose payload is never installed."""
    return package["accepted"] + [v for v in package.get("rejected", []) if v.get("license_only")]


def record_variants(package: dict, shas: list[str]) -> list[dict]:
    """Catalog variants for these hashes, in catalog order, or ValueError."""
    variants = [v for v in licence_variants(package) if v["sha256"] in shas]
    if not shas or len(variants) != len(set(shas)):
        raise ValueError("import record is damaged; import the original package again")
    return variants


def combined_mask(package: dict, variants: list[dict]) -> str:
    """Several verified variants of one package share a payload and differ
    only in the purchase recorded in their licence; owning each grants the
    union, as the original console would after both purchases. A catalog
    licence grant adds bits that no supplied variant of the package carries."""
    mask = int(package.get("license_grant", {}).get("mask", "0"), 16)
    for variant in variants:
        mask |= int(variant["license_mask"], 16)
    return f"{mask:08X}"


def safe_archive_path(name: str) -> None:
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or ":" in name or "\0" in name:
        raise ValueError("unsafe ZIP member path")


def stage_inputs(source: Path, temporary: Path, manifest: dict) -> list[tuple[Path, dict, dict]]:
    """Read only the inputs; never extract wrapper member paths to the host."""
    found = {}

    def accept(stream, size: int) -> None:
        if size > MAX_PACKAGE:
            raise ValueError("DLC package exceeds the supported size")
        path = temporary / f"input-{len(found)}.stfs"
        with path.open("wb") as output:
            # Bound ZIP inflation even if its size fields are inconsistent.
            copied = 0
            while block := stream.read(4 * 1024**2):
                copied += len(block)
                if copied > size:
                    raise ValueError("package exceeds its declared size")
                output.write(block)
        with path.open("rb") as file:
            package, variant = inspect(file, size, manifest)
        id = package["package_id"]
        # A licence-only copy contributes its licence, never its payload.
        payload = None if variant.get("license_only") else path
        if payload is None:
            path.unlink()
        if id in found:
            # Same payload, another licence: keep one copy and both purchases.
            previous, _, _, variants = found[id]
            if all(v["sha256"] != variant["sha256"] for v in variants):
                variants.append(variant)
            if previous is None and payload is not None:
                found[id] = (payload, package, variant, variants)
            elif payload is not None:
                path.unlink()
            return
        found[id] = (payload, package, variant, [variant])

    inputs = sorted(source.rglob("*")) if source.is_dir() else [source]
    for path in inputs:
        if path.is_symlink():
            raise ValueError("input folder contains a symbolic link")
        if not path.is_file():
            continue
        with path.open("rb") as stream:
            magic = stream.read(4)
        if magic in MAGIC:
            with path.open("rb") as stream:
                accept(stream, path.stat().st_size)
        elif zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                for member in archive.infolist():
                    safe_archive_path(member.filename)
                    if member.is_dir():
                        continue
                    with archive.open(member) as stream:
                        prefix = stream.read(4)
                    if prefix in MAGIC:
                        with archive.open(member) as stream:
                            accept(stream, member.file_size)
        elif not source.is_dir():
            raise ValueError("choose a raw DLC package, DLC folder or ZIP")
    if not found:
        raise ValueError("no FH1 DLC packages found")
    return list(found.values())


@contextlib.contextmanager
def mutation_lock(state: Path):
    metadata = state / "dlc"
    metadata.mkdir(parents=True, exist_ok=True)
    with (metadata / "import.lock").open("a+b") as lock:
        lock.seek(0)
        lock.write(b"\0")
        lock.flush()
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            if os.name == "nt":
                running = subprocess.check_output(
                    ["tasklist.exe", "/FI", "IMAGENAME eq pinyon_shift.exe", "/FO", "CSV", "/NH"],
                    creationflags=subprocess.CREATE_NO_WINDOW)
                if b'"pinyon_shift.exe"' in running.lower():
                    raise ValueError("close the game before changing DLC")
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def verified_livery(content: Path, header: Path, record: dict) -> dict:
    """A generated livery package is checked against the record its build wrote, since its payload
    comes from the player's own disc and DLC and no catalog can hold its hash. Its licence owns only
    its own offer (mask 00000001), never more."""
    data = header.read_bytes()
    if (len(data) != 332 or record.get("header_sha256") != hashlib.sha256(data).hexdigest().upper() or
            record.get("license_mask") != LIVERY_MASK or int.from_bytes(data[328:332], "little") != int(LIVERY_MASK, 16)):
        raise ValueError("content header or licence changed; build the livery car again")
    _, digest = payload_catalog(content)
    if record.get("payload_sha256") != digest:
        raise ValueError("installed content is incomplete or changed; build the livery car again")
    return dict(package_id=record["package_id"], display_name=record.get("display_name", record["package_id"]),
                kind=GENERATED)


def verified_content(state: Path, id: str, *, require_enabled: bool = False) -> tuple[Path, dict, dict]:
    """Validate the installed payload and original licence before using it."""
    state = long_path(state)
    active, inactive, header = package_paths(state, id)
    if active.exists() and inactive.exists():
        raise ValueError("both enabled and disabled copies exist")
    content = active if active.is_dir() else inactive
    if not content.is_dir() or not header.is_file():
        raise ValueError("import the verified package first")
    if require_enabled and content != active:
        raise ValueError("enable the imported package first")
    record = import_record(state / "dlc" / (id + ".json"))
    if record and record.get("kind") == GENERATED:
        return content, verified_livery(content, header, record), record
    package = next((p for p in catalog()["packages"] if p["package_id"] == id), None)
    if not package or not record:
        raise ValueError("import record is damaged; import the original package again")
    shas = record.get("variants", [record.get("sha256")])
    if not isinstance(shas, list) or record.get("sha256") not in shas:
        raise ValueError("import record is damaged; import the original package again")
    mask = combined_mask(package, record_variants(package, shas))
    data = header.read_bytes()
    if (len(data) not in (328, 332) or
            record.get("header_sha256") != hashlib.sha256(data).hexdigest().upper() or
            record.get("license_mask") != mask or
            int.from_bytes(data[328:332], "little") != int(mask, 16)):
        raise ValueError("content header or licence changed; import the original package again")
    _, digest = payload_catalog(content)
    if digest != package["payload_sha256"] or record.get("payload_sha256") != digest:
        raise ValueError("installed content is incomplete or changed; import the original package again")
    return content, package, record


def list_content(state: Path) -> list[dict]:
    state = long_path(state)
    records = []
    metadata = state / "dlc"
    for path in sorted(metadata.glob("*.json")):
        id = path.stem
        if not PACKAGE_ID.fullmatch(id):
            continue
        enabled, disabled, header = package_paths(state, id)
        record = import_record(path)
        if record is None:
            records.append(dict(package_id=id, display_name=id, enabled=enabled.is_dir(),
                                status="metadata_invalid"))
            continue
        record["enabled"] = enabled.is_dir()
        record["status"] = ("conflict" if enabled.exists() and disabled.exists() else
                            "missing" if not (enabled.is_dir() or disabled.is_dir()) or not header.is_file()
                            else "gameplay_unverified")
        if header.is_file() and record.get("header_sha256") != hashlib.sha256(header.read_bytes()).hexdigest().upper():
            record["status"] = "missing"
        if id == RALLY:
            # Report generated assets separately from gameplay qualification.
            try:
                prepared = json.loads((state / "cache/rally_adapter/preparation.json").read_text())
                recipe = prepared["recipe"]
                record["rally_assets_cached"] = (prepared["schema"] == "pinyon-shift.rally-preparation.v1" and
                    recipe["package_sha256"] == record["sha256"] and
                    recipe["header_sha256"] == record["header_sha256"] and
                    (state / "cache/rally_adapter/game/media/db/gamedb.slt").is_file() and
                    (state / "cache/rally_adapter/rally-stage.toml").is_file() and
                    (state / "cache/rally_adapter/rally-pace.toml").is_file())
            except (OSError, ValueError, KeyError, TypeError):
                record["rally_assets_cached"] = False
        records.append(record)
    known = {r["package_id"] for r in records}
    for folder in (state / "user" / CONTENT / "00000002",
                   state / "user" / CONTENT / "Disabled" / "00000002"):
        if not folder.exists():
            continue
        for path in folder.iterdir():
            if path.is_dir() and path.name not in known:
                records.append(dict(package_id=path.name, display_name=path.name,
                                    enabled=folder.name == "00000002" and folder.parent.name == "4D5309C9",
                                    status="unmanaged"))
    return records


def import_content(source: Path, state: Path, extractor: Path, *, refresh: bool = True) -> list[dict]:
    state = long_path(state)
    with mutation_lock(state), tempfile.TemporaryDirectory(prefix="staging-", dir=state / "dlc") as directory:
        staging = Path(directory)
        inputs = stage_inputs(source, staging, catalog())
        repair = set()
        # Licences already imported for each package; a new variant adds to them.
        previous = {}
        # Reject batch conflicts before publishing any package.
        for input_path, package, _, _ in inputs:
            id = package["package_id"]
            enabled, disabled, _ = package_paths(state, id)
            record_path = state / "dlc" / (id + ".json")
            if enabled.exists() or disabled.exists():
                if enabled.exists() and disabled.exists():
                    raise ValueError(f'{package["display_name"]}: both enabled and disabled copies exist')
                if not record_path.is_file():
                    raise ValueError(f'{package["display_name"]}: existing unmanaged content; leave it in place')
                record = import_record(record_path)
                if record and record.get("sha256"):
                    try:
                        previous[id] = (record["sha256"], record_variants(
                            package, record.get("variants", [record["sha256"]])))
                    except ValueError:
                        pass
                _, digest = payload_catalog(enabled if enabled.exists() else disabled)
                if digest != package["payload_sha256"]:
                    repair.add(id)
            if input_path is None and (id not in previous or id in repair):
                raise LicenceOnlyInput.for_package(package)
        for index, (input_path, package, variant, variants) in enumerate(inputs):
            id = package["package_id"]
            enabled, disabled, header = package_paths(state, id)
            record_path = state / "dlc" / (id + ".json")
            primary, owned = previous.get(id, (variant["sha256"], []))
            shas = {v["sha256"] for v in owned + variants}
            variants = [v for v in licence_variants(package) if v["sha256"] in shas]
            mask = combined_mask(package, variants)
            installed = enabled if enabled.exists() else disabled
            if id not in repair and installed.exists() and header.is_file():
                record = import_record(record_path)
                data = header.read_bytes()
                if record and record.get("header_sha256") == hashlib.sha256(data).hexdigest().upper():
                    if record.get("license_mask") == mask and len(variants) == len(owned):
                        continue
                    if len(data) in (328, 332):
                        # Verified payload; only the licence grows.
                        data = data[:328] + int(mask, 16).to_bytes(4, "little")
                        staged = staging / f"header-{index}"
                        staged.write_bytes(data)
                        staged.replace(header)
                        write_json(record_path, record | dict(
                            sha256=primary, variants=[v["sha256"] for v in variants], license_mask=mask,
                            header_sha256=hashlib.sha256(data).hexdigest().upper()))
                        continue
            if input_path is None:
                raise LicenceOnlyInput.for_package(package)
            extracted = staging / str(index)
            result = subprocess.run([str(extractor), "--dlc-files", str(input_path), str(extracted), id],
                                    capture_output=True, text=True)
            if result.returncode:
                raise ValueError(result.stderr.strip() or "DLC extraction failed")
            content = extracted / CONTENT / "00000002" / id
            _, digest = payload_catalog(content)
            if digest != package["payload_sha256"]:
                raise ValueError(f'{package["display_name"]}: extracted content failed verification')
            staged_header = extracted / CONTENT / "Headers" / "00000002" / (id + ".header")
            header_data = staged_header.read_bytes()
            if len(header_data) not in (328, 332) or int.from_bytes(header_data[328:332], "little") != int(variant["license_mask"], 16):
                raise ValueError("content header failed verification")
            header_data = header_data[:328] + int(mask, 16).to_bytes(4, "little")
            staged_header.write_bytes(header_data)
            record = dict(package_id=id, display_name=package["display_name"],
                          sha256=primary, variants=[v["sha256"] for v in variants], payload_sha256=digest,
                          license_mask=mask, file_count=package["file_count"],
                          header_sha256=hashlib.sha256(header_data).hexdigest().upper())
            header.parent.mkdir(parents=True, exist_ok=True)
            disabled.parent.mkdir(parents=True, exist_ok=True)
            # An orphan header/record is recoverable; content becomes visible last.
            staged_header.replace(header)
            write_json(record_path, record)
            if id in repair:
                installed = enabled if enabled.exists() else disabled
                retained = state / "dlc" / "replaced" / id / uuid.uuid4().hex
                retained.parent.mkdir(parents=True, exist_ok=True)
                installed.rename(retained)
                try:
                    content.rename(installed)
                except OSError:
                    retained.rename(installed)
                    raise
            elif not (enabled.exists() or disabled.exists()):
                content.rename(disabled)
        if refresh:
            _refresh_livery_strings(state, extractor)
    return list_content(state)


def set_enabled(state: Path, id: str, enabled: bool, *, refresh: bool = True) -> list[dict]:
    state = long_path(state)
    with mutation_lock(state):
        record_path = state / "dlc" / (id + ".json")
        active, inactive, header = package_paths(state, id)
        if not record_path.is_file() or (enabled and not header.is_file()):
            raise ValueError("import the verified package first")
        source, destination = (inactive, active) if enabled else (active, inactive)
        if enabled:
            # Repeated enable must also reject an already active damaged package.
            verified_content(state, id)
        if destination.exists():
            if source.exists():
                raise ValueError("both enabled and disabled copies exist")
            return list_content(state)
        if not source.is_dir():
            raise ValueError("the imported content is missing")
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
        if refresh:
            # The enabled livery packages' names follow the installed set.
            _refresh_livery_strings(state)
    return list_content(state)


EXTRACTOR_NAME = "pinyon_shift_fh1_archive_extract.exe"
# The base game build, the v4 build, then the small tools build an EU-only setup makes first.
EXTRACTOR_BUILDS = ("out/build/win-amd64-release", "out/build/win-amd64-v4", "out/build/title-update-tools")


def default_extractor(root: Path = ROOT) -> Path:
    candidates = [root / build / EXTRACTOR_NAME for build in EXTRACTOR_BUILDS]
    return next((path for path in candidates if path.is_file()), candidates[0])


def install_folder(source: Path, state: Path, extractor: Path) -> dict:
    """Import every owned package found in a folder, one file at a time, and enable them all.

    A file that is not a verified FH1 Marketplace package (a disc image, a title
    update, a rejected or unknown package) is reported with its reason and does
    not stop the others. The source files are only read."""
    def records() -> dict[str, str]:
        metadata = long_path(state) / "dlc"
        return {path.stem: path.read_text(encoding="utf-8") for path in metadata.glob("*.json")} \
            if metadata.is_dir() else {}

    rows = []
    paths = sorted(path for path in source.rglob("*") if path.is_file() and not path.is_symlink())
    # A licence-only copy waits for its verified copy, wherever that sorts.
    waiting = []
    for retry, batch in enumerate((paths, waiting)):
        for path in batch:
            with path.open("rb") as stream:
                magic = stream.read(4)
            if magic not in MAGIC and not zipfile.is_zipfile(path):
                rows.append(dict(file=str(path), status="skipped", reason="not a DLC package"))
                continue
            before = records()
            try:
                import_content(path, state, extractor, refresh=False)
            except LicenceOnlyInput as error:
                if not retry:
                    waiting.append(path)
                    continue
                rows.append(dict(file=str(path), status="skipped", reason=str(error)))
                continue
            except (ValueError, zipfile.BadZipFile) as error:
                if str(error).startswith("close the game"):
                    raise  # Nothing can be installed while the game runs; stop instead of failing every file.
                rows.append(dict(file=str(path), status="skipped", reason=str(error)))
                continue
            rows.append(dict(file=str(path), status="imported" if records() != before else "already installed"))
    for record in list_content(state):
        # A livery car the player turned off stays off; only owned DLC is enabled here.
        if not record.get("enabled") and record.get("kind") != GENERATED:
            try:
                set_enabled(state, record["package_id"], True, refresh=False)
            except ValueError as error:
                rows.append(dict(file=record["package_id"], status="not enabled", reason=str(error)))
    refresh_livery_strings(state, extractor)
    return dict(files=rows, packages=list_content(state))


# -- livery cars ----------------------------------------------------------------

def _tool(name: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def livery_records(state: Path) -> list[dict]:
    """The import records of every installed livery package, enabled or disabled."""
    records = [import_record(path) for path in sorted((long_path(state) / "dlc").glob("*.json"))]
    return [record for record in records if record and record.get("kind") == GENERATED]


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest().upper()


def install_livery(state: Path, game_root: Path, extractor: Path, recipe_path: Path, art_dir: Path | None = None,
                   *, panels: Path | None = None, ids: Path | None = None) -> dict:
    """Build a livery car's package from its recipe and the player's own files
    (tools/package-fh1-livery.py) and install it beside the owned DLC, enabled.
    A car that is already installed is built again and replaced in place,
    keeping its enabled state; the old copy is kept under dlc/replaced/. The
    build reads the installed set without the car's own package, and gets the
    names of the other enabled livery cars for its string tables. Refused while
    the game runs, when another livery package holds one of the car's string
    keys, and when the car's package ID holds content this tool did not build."""
    paint, package, clone = _tool("paint-fh1-livery"), _tool("package-fh1-livery"), _tool("clone-fh1-car")
    panels, ids = panels or paint.PANEL_TABLES, ids or paint.ID_TABLE
    recipe = paint.load_recipe(recipe_path, art_dir=art_dir, panel_tables=panels, id_table=ids)
    art_dir = Path(art_dir) if art_dir is not None else paint.ART_ROOT / Path(recipe_path).stem
    thumbnail = json.loads(Path(recipe_path).read_text(encoding="utf-8")).get("thumbnail")
    id = package.package_id(recipe.car["new_id"])
    state = long_path(state)
    with mutation_lock(state):
        active, inactive, header = package_paths(state, id)
        record_path = state / "dlc" / (id + ".json")
        if active.exists() and inactive.exists():
            raise ValueError(f'{recipe.car["display_name"]}: both enabled and disabled copies exist')
        installed = active if active.exists() else inactive if inactive.exists() else None
        previous = import_record(record_path) if record_path.is_file() else None
        if (installed is not None or record_path.exists()) and (previous is None or previous.get("kind") != GENERATED):
            raise ValueError(f"package {id} holds content this tool did not build; leave it in place")
        others = [record for record in livery_records(state) if record["package_id"] != id]
        entries = [entry for record in others if package_paths(state, record["package_id"])[0].is_dir()
                   for entry in record.get("string_keys", [])]
        with tempfile.TemporaryDirectory(prefix="staging-", dir=state / "dlc") as directory:
            staging = Path(directory)
            sources = clone.Sources(state, Path(game_root).absolute(), extractor, exclude={id})
            report, header_data = package.build_package(recipe, sources, staging / "content", id_table=ids,
                                                        others=entries)
            keys = {entry["key"] for entry in report["string_keys"]}
            for other in others:
                taken = sorted(keys & {entry["key"] for entry in other.get("string_keys", [])})
                if taken:
                    raise ValueError(f'string key {taken[0]} of {recipe.car["display_name"]} is also used by '
                                     f'{other.get("display_name", other["package_id"])}; give one of the cars another ID')
            files, digest = payload_catalog(staging / "content")
            art = sorted(set(recipe.art) | ({thumbnail} if thumbnail else set()))
            record = dict(package_id=id, display_name=report["header_name"], kind=GENERATED, generator="livery-package",
                          car_id=recipe.car["new_id"], stock_id=recipe.car["stock_id"], recipe=str(recipe_path),
                          recipe_sha256=_sha256(Path(recipe_path)), art_sha256={name: _sha256(art_dir / name) for name in art},
                          game_root=str(Path(game_root).absolute()), string_keys=report["string_keys"],
                          payload_sha256=digest, file_count=len(files), license_mask=LIVERY_MASK,
                          header_sha256=hashlib.sha256(header_data).hexdigest().upper())
            staged_header = staging / "header"
            staged_header.write_bytes(header_data)
            header.parent.mkdir(parents=True, exist_ok=True)
            active.parent.mkdir(parents=True, exist_ok=True)
            # As import_content: header and record first, the content becomes visible last.
            staged_header.replace(header)
            write_json(record_path, record)
            if installed is not None:
                retained = state / "dlc" / "replaced" / id / uuid.uuid4().hex
                retained.parent.mkdir(parents=True, exist_ok=True)
                installed.rename(retained)
                try:
                    (staging / "content").rename(installed)
                except OSError:
                    retained.rename(installed)
                    raise
            else:
                (staging / "content").rename(active)
        verified_content(state, id)
        # The other enabled livery cars' tables now gain this car's names.
        _refresh_livery_strings(state, extractor)
    return dict(livery=report, packages=list_content(state))


def _refresh_livery_strings(state: Path, extractor: Path | None = None) -> dict:
    """Rewrite the Data_Car tables of every enabled livery package from the installed set: each
    language's winning Turn 10 table plus the names of every enabled livery car. The title uses
    only the highest-priority copy, so each livery package carries the same complete tables and
    any of them can win. Runs after every change to the installed set, under its lock. A livery
    package that fails verification is skipped, never re-signed."""
    state = long_path(state)
    records = livery_records(state)
    enabled = [record for record in records if package_paths(state, record["package_id"])[0].is_dir()]
    result = dict(rewritten=[], skipped=[])
    if not enabled:
        return result
    verified = []
    for record in enabled:
        active, _, header = package_paths(state, record["package_id"])
        try:
            verified_livery(active, header, record)
            if not record.get("game_root"):
                raise ValueError("its record names no disc; build the livery car again")
            verified.append(record)
        except (OSError, ValueError) as error:
            result["skipped"].append(dict(package_id=record["package_id"], reason=str(error)))
    if not verified:
        return result
    package, clone = _tool("package-fh1-livery"), _tool("clone-fh1-car")
    sources = clone.Sources(state, Path(verified[0]["game_root"]), Path(extractor or default_extractor()).resolve())
    tables = sources.string_tables("data_car.str", skip={record["package_id"] for record in records})
    names = package.livery_tables(tables, [entry for record in enabled for entry in record.get("string_keys", [])])
    for record in verified:
        active = package_paths(state, record["package_id"])[0]
        for name, data in package.string_files(names, record["car_id"]).items():
            path = active / "Media" / "DLCZips" / name
            if not path.is_file() or path.read_bytes() != data:
                staged = path.with_name(path.name + ".refresh")
                staged.write_bytes(data)
                staged.replace(path)
        files, digest = payload_catalog(active)
        if digest != record["payload_sha256"]:
            write_json(state / "dlc" / (record["package_id"] + ".json"),
                       record | dict(payload_sha256=digest, file_count=len(files)))
            result["rewritten"].append(record["package_id"])
    return result


def refresh_livery_strings(state: Path, extractor: Path | None = None) -> dict:
    """_refresh_livery_strings on its own, under the installed set's lock (the game must be closed)."""
    with mutation_lock(long_path(state)):
        return _refresh_livery_strings(state, extractor)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("list", "import", "install-folder", "enable", "disable", "install-livery",
                                           "refresh-livery-strings"))
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--package-id")
    parser.add_argument("--game-root", type=Path, default=ROOT / ".local/game/base")
    parser.add_argument("--extractor", type=Path,
                        help=f"archive extractor (default: the first of {', '.join(EXTRACTOR_BUILDS)})")
    parser.add_argument("--recipe", type=Path, help="install-livery: the livery car's recipe (config/livery-cars/)")
    parser.add_argument("--art", type=Path, help="install-livery: its art folder (default: .local/livery-art/<recipe>)")
    parser.add_argument("--panels", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--ids", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    args.extractor = args.extractor or default_extractor()
    try:
        state = args.state_root.resolve()
        if args.action == "install-folder":
            if args.source is None or not args.source.is_dir():
                raise ValueError("choose the folder that holds your DLC")
            print(json.dumps(install_folder(args.source.resolve(), state, args.extractor.resolve())))
            return 0
        if args.action == "install-livery":
            if args.recipe is None:
                raise ValueError("choose a livery recipe")
            # CreateProcess needs the extractor as an absolute Windows path.
            print(json.dumps(install_livery(state, args.game_root.resolve(), args.extractor.resolve(), args.recipe,
                                            args.art, panels=args.panels, ids=args.ids)))
            return 0
        if args.action == "refresh-livery-strings":
            refreshed = refresh_livery_strings(state, args.extractor.resolve())
            print(json.dumps(dict(refreshed=refreshed, packages=list_content(state))))
            return 0
        if args.action == "list":
            records = list_content(state)
        elif args.action == "import":
            if args.source is None:
                raise ValueError("choose a DLC input")
            records = import_content(args.source.resolve(), state, args.extractor.resolve())
        else:
            if args.package_id is None:
                raise ValueError("choose an imported package")
            records = set_enabled(state, args.package_id, args.action == "enable")
            if args.action == "enable" and args.package_id == RALLY:
                prepared = subprocess.run([sys.executable, str(ROOT / "tools/prepare-fh1-rally.py"),
                    "--state-root", str(state), "--game-root", str(args.game_root.resolve()),
                    "--extractor", str(args.extractor.resolve())], capture_output=True, text=True)
                if prepared.returncode:
                    raise ValueError("Rally is enabled, but asset preparation failed: " +
                                     (prepared.stderr.strip() or "preparation stopped"))
                records = list_content(state)
        print(json.dumps(dict(packages=records)))
        return 0
    except (OSError, ValueError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
