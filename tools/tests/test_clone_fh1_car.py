"""Cloning a stock FH1 car into a new car, with synthetic player files only."""
import hashlib
import importlib.util
import sqlite3
import struct
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("clone_fh1_car", Path(__file__).parents[1] / "clone-fh1-car.py")
clone = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(clone)

TITLE = Path("user/0000000000000000/4D5309C9")


def database(statements):
    """SQLite file bytes built from SQL statements."""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "db.slt"
        with sqlite3.connect(path) as con:
            for statement in statements:
                con.execute(statement)
        con.close()
        return path.read_bytes()


def string_table(strings):
    """An LSB2 string table, as tools/tests/test_fh1_strings.py builds one."""
    pool = entries = b""
    for key, text in strings:
        entries += struct.pack(">HI", key, len(pool) // 2)
        pool += text.encode("utf-16-be") + b"\x00\x00"
    entries += struct.pack(">HI", 0xFFFF, len(pool) // 2 - 1)
    chunk = struct.pack(">II", 8 + len(entries) + len(pool), len(strings)) + entries + pool
    return b"LSB2" + struct.pack("<I", 1) + struct.pack(">IIII", 2 << 24, 24, 1, 24) + chunk


def write_zip(path, members):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)


def mark_lzx(path, member):
    """Relabel a stored member as compression method 21, as FH1's XMem members are."""
    data = bytearray(path.read_bytes())
    info = zipfile.ZipFile(path).getinfo(member)
    struct.pack_into("<H", data, info.header_offset + 8, 21)
    at = data.find(b"PK\x01\x02")
    while at >= 0:
        name_length = struct.unpack_from("<H", data, at + 28)[0]
        if data[at + 46:at + 46 + name_length].decode() == member:
            struct.pack_into("<H", data, at + 10, 21)
        at = data.find(b"PK\x01\x02", at + 4)
    path.write_bytes(data)


class PlayerFiles:
    """A disc, an installed title update and two packages (one enabled, one disabled)."""

    def __init__(self, root: Path):
        self.state, self.game = root / "state", root / "game"
        base = database(["CREATE TABLE Data_Car (Id INTEGER, MediaName TEXT)",
                         "INSERT INTO Data_Car VALUES (1557, 'STOCK_Car_12')"])
        update = database(["CREATE TABLE Data_Car (Id INTEGER, MediaName TEXT)",
                           "INSERT INTO Data_Car VALUES (1600, 'UPDATE_Car_12')"])
        write_zip(self.state / "title-update-v4/media.zip",
                  {"db/gamedb.slt": base, "db/patch/1401000_merge.slt": update})
        package = self.state / TITLE / "00000002/PKG/Media/DLCZips"
        write_zip(package / "2800_pri_65.zip", {
            "media/db/patch/2800000_merge.slt": database([
                "CREATE TABLE Data_Car (Id INTEGER, MediaName TEXT)",
                "INSERT INTO Data_Car VALUES (1686, 'DLC_Car_13')",
                "CREATE TABLE ContentOffers (OfferId INTEGER)", "INSERT INTO ContentOffers VALUES (7)"]),
            "media/cars/DLC_Car_13/DLC_Car_13.carbin": b"dlc model",
            "media/cars/DLC_Car_13/LiveryMasks/Masks.xml": b"<masks/>",
            "media/audio/cars/CarModelTuning/DLC_Car_13_CMT.xml": b"<cmt dlc/>",
            "media/audio/cars/Engines/EngineTuning/DLC_Car_13_ET.xml": b"<et dlc/>"})
        write_zip(package / "StringTables_pri_2950.zip", {"EN/Data_Car.str": string_table([(7451, "DLC car")])})
        disabled = self.state / TITLE / "Disabled/00000002/OFF/Media/DLCZips"
        write_zip(disabled / "9000_pri_65.zip", {"media/db/patch/9000000_merge.slt": database([
            "CREATE TABLE Data_Car (Id INTEGER, MediaName TEXT)", "INSERT INTO Data_Car VALUES (9999, 'OFF_Car')"])})
        write_zip(self.game / "media/cars/STOCK_Car_12.zip",
                  {"STOCK_Car_12.carbin": b"stock model", "DigitalGauge/Dash_STOCK_Car_12.bgf": b"dash"})
        write_zip(self.game / "media/audio/cars/CarModelTuning.zip", {"STOCK_Car_12_CMT.xml": b"<cmt stock/>"})
        write_zip(self.game / "media/audio/cars/Engines/EngineTuning.zip", {"STOCK_Car_12_ET.xml": b"<et stock/>"})
        write_zip(self.game / "media/StringTables/EN.zip", {"Data_Car.str": string_table([(24056, "Stock car")])})
        write_zip(self.game / "media/StringTables/DE.zip", {"Data_Car.str": string_table([(24057, "Stockwagen")])})

    def sources(self):
        return clone.Sources(self.state, self.game, Path("extractor.exe"))

    def hashes(self):
        return {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(self.state.rglob("*"))
                + sorted(self.game.rglob("*")) if p.is_file()}


class SourcesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.files = PlayerFiles(Path(self.temporary.name))

    def test_database_holds_the_update_and_enabled_packages_but_not_disabled_ones(self):
        con = self.files.sources().database()
        self.addCleanup(con.close)
        cars = [row[0] for row in con.execute("SELECT Id FROM Data_Car ORDER BY Id")]
        self.assertEqual(cars, [1557, 1600, 1686])
        self.assertEqual(con.execute("SELECT OfferId FROM ContentOffers").fetchall(), [(7,)])

    def test_a_merge_replaces_a_keyed_row_instead_of_failing(self):
        # The update's merge re-ships CameraOverrides rows keyed by CarId.
        base = database(["CREATE TABLE CameraOverrides (CarId INTEGER PRIMARY KEY, Height REAL)",
                         "INSERT INTO CameraOverrides VALUES (1557, 1.0)"])
        update = database(["CREATE TABLE CameraOverrides (CarId INTEGER PRIMARY KEY, Height REAL)",
                           "INSERT INTO CameraOverrides VALUES (1557, 2.5)"])
        write_zip(self.files.state / "title-update-v4/media.zip",
                  {"db/gamedb.slt": base, "db/patch/1401000_merge.slt": update})
        con = self.files.sources().database()
        self.addCleanup(con.close)
        self.assertEqual(con.execute("SELECT CarId, Height FROM CameraOverrides").fetchall(), [(1557, 2.5)])

    def test_data_car_string_keys_come_from_the_disc_and_every_installed_table(self):
        self.assertEqual(self.files.sources().data_car_keys(), {24056, 24057, 7451})

    def test_a_disc_car_reads_its_archive_and_its_audio_tuning(self):
        sources = self.files.sources()
        self.assertEqual(sources.car_files("STOCK_Car_12"),
                         {"STOCK_Car_12.carbin": b"stock model", "DigitalGauge/Dash_STOCK_Car_12.bgf": b"dash"})
        self.assertEqual(sources.audio_files("STOCK_Car_12"), {"CarModelTuning": b"<cmt stock/>",
                                                               "EngineTuning": b"<et stock/>"})

    def test_a_package_car_reads_its_folder_and_its_audio_tuning(self):
        sources = self.files.sources()
        self.assertEqual(sources.car_files("DLC_Car_13"),
                         {"DLC_Car_13.carbin": b"dlc model", "LiveryMasks/Masks.xml": b"<masks/>"})
        self.assertEqual(sources.audio_files("DLC_Car_13"), {"CarModelTuning": b"<cmt dlc/>",
                                                             "EngineTuning": b"<et dlc/>"})

    def test_an_unknown_car_is_refused(self):
        with self.assertRaisesRegex(ValueError, "NO_Car"):
            self.files.sources().car_files("NO_Car")

    def test_xmem_members_are_read_through_the_native_extractor(self):
        archive = self.files.game / "media/cars/STOCK_Car_12.zip"
        mark_lzx(archive, "STOCK_Car_12.carbin")
        calls = []

        def extract(args, **kwargs):
            calls.append(args[1:])
            Path(args[5]).write_bytes(b"decompressed model")
            return subprocess.CompletedProcess(args, 0, b"", b"")

        with patch.object(clone.subprocess, "run", side_effect=extract):
            files = self.files.sources().car_files("STOCK_Car_12")
        self.assertEqual(files["STOCK_Car_12.carbin"], b"decompressed model")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], str(archive))

    def test_reading_everything_changes_no_file(self):
        before = self.files.hashes()
        sources = self.files.sources()
        sources.database().close()
        sources.data_car_keys()
        sources.car_files("STOCK_Car_12")
        sources.audio_files("DLC_Car_13")
        self.assertEqual(self.files.hashes(), before)


if __name__ == "__main__":
    unittest.main()
