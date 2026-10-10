#!/usr/bin/env python3
"""Clone a stock FH1 car into a new, separate car, from the player's own files.

The result is a staging tree in the layout a DLC package mounts (`media/...`):
the stock car's model files under a new media name, its audio tuning, and a
merge database with its rows copied to a new car ID. Every source is read
only; nothing in the disc, the title update or an installed package changes.
"""
import re
import sqlite3
import struct
import subprocess
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

    def car_files(self, media_name: str) -> dict[str, bytes]:
        """The stock car's model archive: the disc's media/cars/<name>.zip, or the
        media/cars/<name>/ folder of an enabled package."""
        disc = self.game_root / "media" / "cars" / f"{media_name}.zip"
        if disc.is_file():
            return self._members(disc)
        prefix = f"media/cars/{media_name}/"
        for archive in self._package_archives():
            with zipfile.ZipFile(archive) as zipped:
                if any(name.lower().startswith(prefix.lower()) for name in zipped.namelist()):
                    return self._members(archive, prefix)
        raise ValueError(f"car {media_name} is not on the disc or in an enabled package")

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
