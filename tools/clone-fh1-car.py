#!/usr/bin/env python3
"""Clone a stock FH1 car into a new, separate car, from the player's own files.

The result is a staging tree in the layout a DLC package mounts (`media/...`):
the stock car's model files under a new media name, its audio tuning, and a
merge database with its rows copied to a new car ID. Every source is read
only; nothing in the disc, the title update or an installed package changes.
"""
import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

TITLE_CONTENT = Path("user/0000000000000000/4D5309C9")
XMEM = 21  # FH1's LZX ("XMem") zip compression method


def _load_tool(name: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Sources:
    """Read-only view of the player's disc, installed title update and enabled packages."""

    def __init__(self, state_root: Path, game_root: Path, extractor: Path):
        self.state_root, self.game_root, self.extractor = Path(state_root), Path(game_root), Path(extractor)

    # -- archives ---------------------------------------------------------

    def member(self, archive: Path, info: zipfile.ZipInfo) -> bytes:
        """One archive member's bytes; XMem members go through the native extractor."""
        if info.compress_type != XMEM:
            with zipfile.ZipFile(archive) as zipped:
                return zipped.read(info)
        with open(archive, "rb") as stream:
            stream.seek(info.header_offset)
            header = stream.read(30)
        name_length, extra_length = struct.unpack_from("<HH", header, 26)
        offset = info.header_offset + 30 + name_length + extra_length
        with tempfile.TemporaryDirectory(prefix="pinyon-clone-") as directory:
            output = Path(directory) / "member"
            result = subprocess.run([str(self.extractor), str(archive), str(offset), str(info.compress_size),
                                     str(info.file_size), str(output)], capture_output=True)
            if result.returncode or not output.is_file():
                raise ValueError(f"the archive extractor could not read {info.filename} from {archive.name}")
            return output.read_bytes()

    def _members(self, archive: Path, prefix: str = "", file_name: str | None = None) -> dict[str, bytes]:
        """Members under `prefix` (optionally only those named `file_name`), keyed without the prefix."""
        with zipfile.ZipFile(archive) as zipped:
            infos = [info for info in zipped.infolist()
                     if not info.is_dir() and info.filename.lower().startswith(prefix.lower())
                     and (file_name is None or info.filename.replace("\\", "/").split("/")[-1].lower() == file_name)]
        return {info.filename[len(prefix):]: self.member(archive, info) for info in infos}

    def _package_archives(self) -> list[Path]:
        """Every DLCZips archive of the enabled packages (Disabled/ is skipped)."""
        return sorted((self.state_root / TITLE_CONTENT / "00000002").glob("*/Media/DLCZips/*.zip"))

    # -- database ---------------------------------------------------------

    def database(self) -> sqlite3.Connection:
        """The title update's game database with its merges and every enabled
        package's merge applied, merges in merge-number order, in memory."""
        update = self.state_root / "title-update-v4" / "media.zip"
        merges: list[tuple[int, bytes]] = []
        if update.is_file():
            with zipfile.ZipFile(update) as zipped:
                infos = {info.filename.lower(): info for info in zipped.infolist()}
            base = self.member(update, infos["db/gamedb.slt"])
            merges += [(self._merge_number(name), self.member(update, info)) for name, info in infos.items()
                       if name.startswith("db/patch/") and name.endswith("_merge.slt")]
        else:
            base = (self.game_root / "media/db/gamedb.slt").read_bytes()
        for archive in self._package_archives():
            with zipfile.ZipFile(archive) as zipped:
                infos = [info for info in zipped.infolist()
                         if info.filename.lower().startswith("media/db/patch/")
                         and info.filename.lower().endswith("_merge.slt")]
            merges += [(self._merge_number(info.filename), self.member(archive, info)) for info in infos]
        con = sqlite3.connect(":memory:")
        con.deserialize(base)
        for _, data in sorted(merges, key=lambda merge: merge[0]):
            self._apply_merge(con, data)
        # Uncommitted merges are invisible to serialize() and make backup() wait forever.
        con.commit()
        return con

    @staticmethod
    def _merge_number(name: str) -> int:
        match = re.search(r"(\d+)_merge\.slt$", name, re.IGNORECASE)
        return int(match.group(1)) if match else 0

    @staticmethod
    def _apply_merge(con: sqlite3.Connection, data: bytes) -> None:
        merge = sqlite3.connect(":memory:")
        merge.deserialize(data)
        for table, sql in merge.execute("SELECT name, sql FROM sqlite_master WHERE type='table'"):
            if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                con.execute(sql)
            columns = [column[1] for column in merge.execute(f"PRAGMA table_info([{table}])")]
            names = ",".join(f"[{column}]" for column in columns)
            # A later merge replaces a row with the same key (the update re-ships CameraOverrides).
            con.executemany(f"INSERT OR REPLACE INTO [{table}] ({names}) VALUES ({','.join('?' * len(columns))})",
                            merge.execute(f"SELECT {names} FROM [{table}]"))
        merge.close()

    # -- strings ----------------------------------------------------------

    def data_car_keys(self) -> set[int]:
        """Every key used in any installed Data_Car string table, any language."""
        strings = _load_tool("fh1-strings")
        tables = []
        for archive in sorted((self.game_root / "media/StringTables").glob("*.zip")):
            tables += self._members(archive, file_name="data_car.str").values()
        for archive in self._package_archives():
            if archive.name.lower().startswith("stringtables_"):
                tables += self._members(archive, file_name="data_car.str").values()
        return {key for data in tables for key, _ in strings.parse(data)}

    # -- car files --------------------------------------------------------

    def car_source(self, media_name: str) -> tuple[Path, str] | None:
        """Where a car's model files are: the disc's media/cars/<name>.zip (any
        case, as the Lancer's is mit_lancerevoxgsr_08.zip), or the
        media/cars/<name>/ folder of an enabled package; None if neither."""
        discs = {path.stem.lower(): path for path in (self.game_root / "media" / "cars").glob("*.zip")}
        if media_name.lower() in discs:
            return discs[media_name.lower()], ""
        prefix = f"media/cars/{media_name}/"
        for archive in self._package_archives():
            with zipfile.ZipFile(archive) as zipped:
                if any(name.lower().startswith(prefix.lower()) for name in zipped.namelist()):
                    return archive, prefix
        return None

    def car_files(self, media_name: str) -> dict[str, bytes]:
        """The stock car's model archive members, keyed by their path in the car's folder."""
        source = self.car_source(media_name)
        if source is None:
            raise ValueError(f"car {media_name} is not on the disc or in an enabled package")
        return self._members(*source)

    def inputs(self, media_name: str | None = None) -> list[Path]:
        """Every file a clone of `media_name` reads: the title update (or the
        disc's database), each enabled package archive, the disc's string tables
        and audio tuning, and the car's own disc archive."""
        update = self.state_root / "title-update-v4" / "media.zip"
        files = [update] if update.is_file() else [self.game_root / "media/db/gamedb.slt"]
        files += self._package_archives()
        files += sorted((self.game_root / "media/StringTables").glob("*.zip"))
        files += [self.game_root / name for name in ("media/audio/cars/CarModelTuning.zip",
                                                     "media/audio/cars/Engines/EngineTuning.zip")
                  if (self.game_root / name).is_file()]
        source = self.car_source(media_name) if media_name else None
        if source and source[0] not in files:
            files.append(source[0])
        return files

    def audio_files(self, media_name: str) -> dict[str, bytes]:
        """The car's CarModelTuning and EngineTuning XML, from the disc or a package."""
        wanted = {"CarModelTuning": (f"{media_name}_CMT.xml", "media/audio/cars/CarModelTuning.zip",
                                     "media/audio/cars/CarModelTuning/"),
                  "EngineTuning": (f"{media_name}_ET.xml", "media/audio/cars/Engines/EngineTuning.zip",
                                   "media/audio/cars/Engines/EngineTuning/")}
        found = {}
        for kind, (file_name, disc_archive, package_folder) in wanted.items():
            disc = self.game_root / disc_archive
            if disc.is_file():
                with zipfile.ZipFile(disc) as zipped:
                    info = next((i for i in zipped.infolist() if i.filename.lower() == file_name.lower()), None)
                if info:
                    found[kind] = self.member(disc, info)
                    continue
            for archive in self._package_archives():
                with zipfile.ZipFile(archive) as zipped:
                    info = next((i for i in zipped.infolist()
                                 if i.filename.lower() == (package_folder + file_name).lower()), None)
                if info:
                    found[kind] = self.member(archive, info)
                    break
            else:
                raise ValueError(f"no {kind} file for car {media_name}")
        return found


# -- model tree -------------------------------------------------------------

CAR_FOLDER = "media/cars/{}/"
AUDIO_FILES = {"CarModelTuning": "media/audio/cars/CarModelTuning/{}_CMT.xml",
               "EngineTuning": "media/audio/cars/Engines/EngineTuning/{}_ET.xml"}


def _same_case(written: str, media: str) -> str:
    """`media` in the case a file name wrote the stock media name in (the stripped_ copies are lowercase)."""
    return media.lower() if written.islower() else media.upper() if written.isupper() else media


def clone_member_name(name: str, stock: str, new: str) -> str:
    """A model-archive member's name in the clone, as Turn 10 named the Pizza
    Hut's: the stock media name, in whatever case the file wrote it, becomes the
    new one (model files, stripped_ copies, build report, exporter settings).
    In DigitalGauge only Dash_<media>.* is renamed, since the game opens
    <car>\\digitalgauge\\Dash_<media>.bgf; its gauge textures keep their names,
    which the dash's .fbf uses."""
    folder, _, base = name.replace("\\", "/").rpartition("/")
    if folder.lower() == "digitalgauge" and not base.lower().startswith(f"dash_{stock.lower()}"):
        return name
    base = re.sub(re.escape(stock), lambda match: _same_case(match.group(), new), base, flags=re.IGNORECASE)
    return f"{folder}/{base}" if folder else base


def rewrite_dash_paths(data: bytes, stock: str, new: str) -> bytes:
    """A dash .fbf names its textures by absolute path, each a big-endian u32
    length then GAME:\\MEDIA\\CARS\\<MEDIA>\\DIGITALGAUGE\\<texture>; the paths
    into the stock car's folder are pointed at the clone's. Turn 10's Pizza
    Hut .fbf is the Boss 302's with exactly this change (plus its own font and
    placeholder text). Paths into other folders (SHARED) stay."""
    folder = re.compile(rb"(?i)(GAME:\\MEDIA\\CARS\\)(" + re.escape(stock.encode()) + rb")\\")
    out, at = bytearray(), 0
    for match in folder.finditer(data):
        start = match.start() - 4
        length = struct.unpack_from(">I", data, start)[0] if start >= at else 0
        if length < len(match.group()) or match.start() + length > len(data):
            raise ValueError(f"unexpected dash file layout at byte {match.start()}: car-clone cannot point its "
                             "texture paths at the new car")
        replacement = match.group(1) + _same_case(match.group(2).decode(), new).encode() + b"\\"
        out += data[at:start] + struct.pack(">I", length + len(replacement) - len(match.group())) + replacement
        at = match.end()
    return bytes(out + data[at:])


def clone_files(car_files: dict[str, bytes], audio: dict[str, bytes], stock: str,
                new: str) -> tuple[dict[str, bytes], list[dict]]:
    """The clone's model tree and audio tuning in package layout (path -> bytes),
    and one record per file: its source, size, SHA-256 and whether it was
    renamed or its dash texture paths rewritten. Every other byte is the stock car's."""
    staged: dict[str, bytes] = {}
    records = []

    def add(source: str, path: str, data: bytes, renamed: bool) -> None:
        if any(path.lower() == other.lower() for other in staged):
            raise ValueError(f"two stock files would both be written as {path}")
        out = rewrite_dash_paths(data, stock, new) if path.lower().endswith(".fbf") else data
        staged[path] = out
        records.append({"source": source, "path": path, "size": len(out), "sha256": hashlib.sha256(out).hexdigest(),
                        "renamed": renamed, "rewritten": out != data})

    for name, data in sorted(car_files.items()):
        renamed = clone_member_name(name, stock, new)
        add(name, CAR_FOLDER.format(new) + renamed, data, renamed != name)
    for kind, data in sorted(audio.items()):
        source = AUDIO_FILES[kind].format(stock).replace("media/audio/cars/", "").replace("Engines/", "")
        add(source, AUDIO_FILES[kind].format(new), data, True)
    return staged, records


# -- names ------------------------------------------------------------------

DATA_CAR_STRINGS = 0xCD49   # the Data_Car string table's ID; cars name it as `_&<(table << 16) | key>`
STRING_SENTINEL = 0xFFFF


def string_reference(key: int) -> str:
    return f"_&{(DATA_CAR_STRINGS << 16) | key}"


def string_key(reference: str) -> int | None:
    """The Data_Car string key a `_&<id>` reference names, or None for text or another table."""
    match = re.fullmatch(r"_&(\d+)", reference or "")
    if not match or int(match.group(1)) >> 16 != DATA_CAR_STRINGS:
        return None
    return int(match.group(1)) & 0xFFFF


def referenced_string_keys(db: sqlite3.Connection) -> set[int]:
    """Data_Car string keys any car's DisplayName or ModelShort names."""
    keys = {string_key(value) for row in db.execute("SELECT DisplayName, ModelShort FROM Data_Car") for value in row}
    return keys - {None}


def allocate_string_keys(used: set[int], new_id: int, count: int = 2) -> list[int]:
    """`count` keys no installed table or car uses, searched from 2 x the car
    ID up: the livery cars 3001-3007 get 6002-6015 (free in every installed
    table), so cars built before each other's packages are installed never
    share a key. Key 0 and the table's 0xFFFF sentinel are never used."""
    keys, key = [], (2 * new_id) & 0xFFFF
    for _ in range(0x10000):
        if key not in used and key not in (0, STRING_SENTINEL):
            keys.append(key)
            if len(keys) == count:
                return keys
        key = (key + 1) & 0xFFFF
    raise ValueError("there are no unused Data_Car string keys left")


def clone_names(db: sqlite3.Connection, table_keys: set[int], stock_id: int, new_id: int, media: str,
                display: str) -> tuple["CarNames", list[dict]]:
    """The new car's names: a new DisplayName string, and a new ModelShort key
    holding the stock car's short name (the Pizza Hut's ModelShort key 6879
    holds the Boss 302's "Ford Mustang '13"). `table_keys` are the keys of every
    installed Data_Car table; returns the names and the strings to write."""
    stock_short = db.execute("SELECT ModelShort FROM Data_Car WHERE Id=?", (stock_id,)).fetchone()
    if stock_short is None:
        raise ValueError(f"car {stock_id} is not in the game database")
    display_key, short_key = allocate_string_keys(table_keys | referenced_string_keys(db), new_id)
    stock_key = string_key(stock_short[0])
    short = {"same_as": stock_key} if stock_key is not None else {"text": stock_short[0]}
    return (CarNames(media, string_reference(display_key), string_reference(short_key)),
            [{"field": "DisplayName", "key": display_key, "text": display},
             {"field": "ModelShort", "key": short_key, **short}])


# -- rows -------------------------------------------------------------------

# Car-defining tables keyed by the car ID, beside every List_Upgrade* table with
# an Ordinal column. Gameplay tables that only mention a car (CarChallenges,
# CarChallengeTitles, EventParticipants, EventRecommendedCars, Rewards_*) are
# never copied: they stay with the stock car, as on Turn 10's own clones.
CAR_TABLES = {"Data_Car": "Id", "CameraOverrides": "CarId", "CarExceptions": "CarID", "CarPIOverrides": "CarID",
              "CarUpgradeExceptions": "CarID", "CarTrackOffsets": "Id", "CarPartPositions": "Ordinal",
              "Combo_Colors": "Ordinal", "Combo_Colors_Exceptions": "Ordinal", "Combo_Engines": "Ordinal",
              "StripeColors": "Ordinal", "List_AntiSwayPhysics": "Ordinal", "List_SpringDamperPhysics": "Ordinal"}
COMPONENT_TABLES = {"Data_Engine": ("engine", "EngineID"), "Data_CarBody": ("body", "Id"),
                    "Data_Drivetrain": ("drivetrain", "DrivetrainID")}
# Row IDs Turn 10 numbers 1, 2, 3, ... instead of owner x 1000 + n.
SEQUENTIAL_IDS = {"Combo_Colors_Exceptions": "ID", "Combo_Engines": "EngineComboID"}
# Columns naming the car's own physics rows (car x 1000 + n) and its engine's torque curves (engine x 1000 + n).
CAR_ROW_REFERENCES = {"antiswayphysicsid", "springdamperphysicsid", "frontspringdamperphysicsid",
                      "rearspringdamperphysicsid"}
TORQUE_CURVE_COLUMNS = {"torquecurveid", "torquecurvefullthrottleid"}
THUMBNAIL = "game:\\Media\\UI\\Textures\\Thumbnails\\Thumbnail_{}.xds"


class CarNames(NamedTuple):
    """The new car's media name and its Data_Car string references (`_&<id>`)."""
    media: str
    display: str
    model_short: str


class Components(NamedTuple):
    """A car and the engine, car body and drivetrain it is built from."""
    car: int
    engine: int
    body: int
    drivetrain: int

    def row_base(self, kind: str) -> int:
        """Turn 10 numbers a component's rows owner x 1000 + n; a car body ID already is car x 1000."""
        return self.body if kind == "body" else getattr(self, kind) * 1000


@dataclass
class RowClone:
    database: bytes   # the merge database (an SQLite file), holding only the new rows
    tables: dict      # rows written per table
    stock: Components
    ids: dict         # the new car, engine, body, drivetrain and torque-curve IDs
    shared: dict      # stock references the clone keeps: wheels, family, powertrain, aero, swap engines


def _table_key(table: str, columns: list[str]) -> tuple[str, str] | None:
    """The component a table's rows belong to and the column naming it; None for every other table."""
    if table in CAR_TABLES:
        return "car", CAR_TABLES[table]
    if table in COMPONENT_TABLES:
        return COMPONENT_TABLES[table]
    if table.startswith("List_Upgrade"):
        lower = {column.lower(): column for column in columns}
        for kind, column in (("car", "ordinal"), ("engine", "engineid"), ("body", "carbodyid"),
                             ("drivetrain", "drivetrainid")):
            if column in lower:
                return kind, lower[column]
    return None


def _rebase(table: str, column: str, value, old_base: int, new_base: int) -> int:
    if not isinstance(value, int) or not old_base <= value < old_base + 1000:
        raise ValueError(f"{table}.{column} {value} does not follow Turn 10's numbering ({old_base} + n), "
                         "so car-clone cannot give it a new ID")
    return new_base + value - old_base


def _new_id(table: str, kind: str, key: str | None, column: str, value, index: int,
            old: Components, new: Components):
    """The clone's value for an ID column of one of the stock car's rows, or None
    when the column is not an ID the clone owns (a shared reference or plain data)."""
    lower = column.lower()
    if column == key:
        return getattr(new, kind)
    if column == SEQUENTIAL_IDS.get(table):
        return new.car * 1000 + index
    if lower == "id":
        return _rebase(table, column, value, old.row_base(kind), new.row_base(kind))
    if lower in CAR_ROW_REFERENCES:
        return _rebase(table, column, value, old.row_base("car"), new.row_base("car"))
    if lower in TORQUE_CURVE_COLUMNS:
        return _rebase(table, column, value, old.row_base("engine"), new.row_base("engine"))
    for component, name in (("car", "modelid"), ("engine", "engineid"), ("body", "carbodyid"),
                            ("drivetrain", "drivetrainid")):
        if lower == name and value == getattr(old, component):
            return getattr(new, component)
    return None   # swap engines, wheels, aero, powertrain and every value column stay as they are


def _stock_components(db: sqlite3.Connection, stock_id: int) -> Components:
    def single(sql: str, what: str) -> int:
        rows = db.execute(sql, (stock_id,)).fetchall()
        if len(rows) != 1:
            raise ValueError(f"car {stock_id} has {len(rows)} {what}; car-clone expects exactly one")
        return rows[0][0]

    return Components(stock_id,
                      single("SELECT EngineID FROM List_UpgradeEngine WHERE Ordinal=? AND IsStock=1", "stock engines"),
                      single("SELECT CarBodyID FROM List_UpgradeCarBody WHERE Ordinal=?", "car bodies"),
                      single("SELECT DrivetrainID FROM List_UpgradeDrivetrain WHERE Ordinal=?", "drivetrains"))


def _columns(db: sqlite3.Connection, table: str) -> list[str]:
    return [column[1] for column in db.execute(f"PRAGMA table_info([{table}])")]


def clone_rows(db: sqlite3.Connection, stock_id: int, new_id: int, names: CarNames) -> RowClone:
    """Copy a stock car's car-defining rows to a new car ID, as Turn 10 did for
    the Pizza Hut Mustang: the car's own rows keyed by the new ID, its stock
    engine and drivetrain under the new ID, its car body as new ID x 1000, row
    IDs and torque curves renumbered under their new owner, and wheels, aero,
    family, powertrain and swap engines shared with the stock car. Data_Car
    changes only its IDs, media name, names, thumbnail and HasRaceLivery; the
    stock engine takes the new media name, as its engine sound follows it.

    `db` (the merged game database) is only read; the result is a separate
    merge database with only new rows, each new ID checked unused in `db`."""
    stock = db.execute("SELECT * FROM Data_Car WHERE Id=?", (stock_id,)).fetchone()
    if stock is None:
        raise ValueError(f"car {stock_id} is not in the game database")
    if db.execute("SELECT 1 FROM Data_Car WHERE Id=? OR ModelId=?", (new_id, new_id)).fetchone():
        raise ValueError(f"car ID {new_id} is already used")
    if db.execute("SELECT 1 FROM Data_Car WHERE MediaName=? COLLATE NOCASE", (names.media,)).fetchone():
        raise ValueError(f"media name {names.media} is already used")
    stock = dict(zip(_columns(db, "Data_Car"), stock))
    old = _stock_components(db, stock_id)
    new = Components(new_id, new_id, new_id * 1000, new_id)
    data_car = {"MediaName": names.media, "DisplayName": names.display, "ModelShort": names.model_short,
                "Thumbnail": THUMBNAIL.format(new_id), "HasRaceLivery": 1}

    schema = dict(db.execute("SELECT name, sql FROM sqlite_master WHERE type='table'"))
    written: dict[str, tuple[list[str], list[list]]] = {}
    new_ids: dict[tuple[str, str], set] = {}
    torque_curves: set[int] = set()

    def copy(table: str, kind: str, key: str | None, rows: list) -> None:
        # Two packages shipping the same car (the 1100 and 1200 car packs) leave keyless tables holding its rows twice.
        columns, out, rows = _columns(db, table), [], list(dict.fromkeys(rows))
        for index, row in enumerate(rows, start=1):
            values = list(row)
            for at, (column, value) in enumerate(zip(columns, row)):
                rekeyed = _new_id(table, kind, key, column, value, index, old, new)
                if rekeyed is not None:
                    values[at] = rekeyed
                    new_ids.setdefault((table, column), set()).add(rekeyed)
                    if column.lower() == "torquecurvefullthrottleid":
                        torque_curves.add(value)
                elif table == "Data_Car" and column in data_car:
                    values[at] = data_car[column]
                elif table == "Data_Engine" and column == "MediaName" and value == stock["MediaName"]:
                    values[at] = names.media
            out.append(values)
        if out:
            written[table] = (columns, out)

    for table in schema:
        found = _table_key(table, _columns(db, table))
        if found:
            kind, key = found
            copy(table, kind, key, db.execute(f"SELECT * FROM [{table}] WHERE [{key}]=?",
                                              (getattr(old, kind),)).fetchall())
    if torque_curves and "List_TorqueCurve" in schema:
        marks = ",".join("?" * len(torque_curves))
        copy("List_TorqueCurve", "engine", None, db.execute(
            f"SELECT * FROM List_TorqueCurve WHERE TorqueCurveID IN ({marks})", sorted(torque_curves)).fetchall())

    for (table, column), values in new_ids.items():
        marks = ",".join("?" * len(values))
        used = db.execute(f"SELECT [{column}] FROM [{table}] WHERE [{column}] IN ({marks})", sorted(values)).fetchone()
        if used:
            raise ValueError(f"{table} already has {column} {used[0]}; every ID of the clone must be unused")

    merge = sqlite3.connect(":memory:")
    for table, (columns, rows) in written.items():
        merge.execute(schema[table])
        quoted = ",".join(f"[{column}]" for column in columns)
        merge.executemany(f"INSERT INTO [{table}] ({quoted}) VALUES ({','.join('?' * len(columns))})", rows)
    merge.commit()
    database = merge.serialize()
    merge.close()

    def written_values(column: str, table: str | None = None) -> set:
        return {row[columns.index(column)] for name, (columns, rows) in written.items()
                if column in columns and table in (None, name) for row in rows}

    return RowClone(
        database=database,
        tables={table: len(rows) for table, (_, rows) in written.items()},
        stock=old,
        ids={"car": new.car, "engine": new.engine, "body": new.body, "drivetrain": new.drivetrain,
             "torque_curves": sorted(written_values("TorqueCurveID", "List_TorqueCurve"))},
        shared={**{field: stock[field] for field in ("StockWheelID", "FamilyModelID", "PowertrainID")
                   if field in stock},
                "AeroPhysicsID": sorted(written_values("AeroPhysicsID")),
                "swap_engines": sorted(written_values("EngineID", "List_UpgradeEngine") - {new.engine})})


# -- clone ------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
ID_TABLE = ROOT / "config/livery-cars/ids.json"
MEDIA_NAME = re.compile(r"[A-Za-z0-9_]+")


def reserved_ids(table: Path = ID_TABLE) -> dict[int, dict]:
    """The committed car ID table: new car ID -> its entry (stock car and name)."""
    return {entry["id"]: entry for entry in json.loads(Path(table).read_text(encoding="utf-8"))["cars"]}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def clone_car(sources: Sources, stock_id: int, new_id: int, media_name: str, display_name: str, output: Path,
              table: Path = ID_TABLE) -> dict:
    """Stage a clone of a stock car in `output` in package layout (model tree,
    audio tuning, media/db/patch/<new ID>000_merge.slt) and return its report.
    Refuses an existing output, an ID the committed table does not reserve for
    this stock car, a used car ID or media name, and an unknown stock car.
    Every source file has the same SHA-256 afterwards; nothing is written
    outside `output`, and a failed clone leaves no output."""
    output = Path(output)
    if not MEDIA_NAME.fullmatch(media_name or ""):
        raise ValueError(f"media name must be letters, digits and underscores, not {media_name!r}")
    if output.exists():
        raise ValueError(f"{output} already exists; choose a new output folder")
    reserved = reserved_ids(table).get(new_id)
    if reserved is None:
        raise ValueError(f"car ID {new_id} is not reserved in {table}")
    if reserved["stock_id"] != stock_id:
        raise ValueError(f"car ID {new_id} is reserved for a clone of car {reserved['stock_id']}, not {stock_id}")

    before = {path: _sha256(path) for path in sources.inputs()}
    db = sources.database()
    try:
        stock = db.execute("SELECT MediaName FROM Data_Car WHERE Id=?", (stock_id,)).fetchone()
        if stock is None:
            raise ValueError(f"car {stock_id} is not in the game database")
        stock_media = stock[0]
        used = sources.car_source(media_name)
        if used:
            raise ValueError(f"media name {media_name} is already used by {used[0]}")
        archive = sources.car_source(stock_media)
        before.update({path: _sha256(path) for path in sources.inputs(stock_media) if path not in before})
        names, strings = clone_names(db, sources.data_car_keys(), stock_id, new_id, media_name, display_name)
        rows = clone_rows(db, stock_id, new_id, names)
    finally:
        db.close()
    staged, files = clone_files(sources.car_files(stock_media), sources.audio_files(stock_media), stock_media,
                                media_name)
    merge = f"media/db/patch/{new_id}000_merge.slt"
    staged[merge] = rows.database

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        for path, data in staged.items():
            (staging / path).parent.mkdir(parents=True, exist_ok=True)
            (staging / path).write_bytes(data)
        after = {path: _sha256(path) for path in before}
        changed = [str(path) for path in before if after[path] != before[path]]
        if changed:
            raise ValueError(f"source files changed while cloning: {', '.join(changed)}")
        staging.rename(output)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "car": {"id": new_id, "media_name": media_name, "display_name": display_name},
        "stock": {"id": stock_id, "media_name": stock_media, "archive": str(archive[0]) if archive else None},
        "output": str(output),
        "merge_database": merge,
        "ids": rows.ids,
        "shared": rows.shared,
        "strings": strings,
        "rows": sum(rows.tables.values()),
        "tables": rows.tables,
        "files": files,
        "sources": [{"path": str(path), "sha256": digest} for path, digest in before.items()],
        "sources_unchanged": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--state-root", type=Path, required=True, help="the installed preview state (.local/preview)")
    parser.add_argument("--game-root", type=Path, required=True, help="the extracted disc (.local/game/eur-base)")
    parser.add_argument("--stock-id", type=int, required=True)
    parser.add_argument("--new-id", type=int, required=True, help="a car ID reserved in config/livery-cars/ids.json")
    parser.add_argument("--media-name", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--output", type=Path, required=True, help="a new folder for the staged car")
    parser.add_argument("--extractor", type=Path, help="archive extractor (default: the one the build made)")
    parser.add_argument("--ids", type=Path, default=ID_TABLE, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    extractor = args.extractor or _load_tool("manage-fh1-dlc").default_extractor()
    try:
        # CreateProcess needs the extractor as an absolute Windows path.
        sources = Sources(args.state_root.absolute(), args.game_root.absolute(), extractor.resolve())
        report = clone_car(sources, args.stock_id, args.new_id, args.media_name, args.display_name,
                           args.output.absolute(), args.ids)
    except (OSError, ValueError, zipfile.BadZipFile, sqlite3.Error) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
