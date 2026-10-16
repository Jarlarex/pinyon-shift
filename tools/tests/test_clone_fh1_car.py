"""Cloning a stock FH1 car into a new car, with synthetic player files only."""
import hashlib
import importlib.util
import io
import json
import sqlite3
import struct
import subprocess
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
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

    def test_each_language_takes_its_highest_priority_table(self):
        newer = self.files.state / TITLE / "00000002/NEWER/Media/DLCZips"
        write_zip(newer / "StringTables_pri_3001.zip", {"EN/Data_Car.str": string_table([(6002, "Livery car")]),
                                                        "FR/Data_Car.str": string_table([(6002, "Voiture")])})
        write_zip(newer / "StringTables_pri_900.zip", {"DE/Data_Car.str": string_table([(1, "Older")])})
        tables = self.files.sources().string_tables("data_car.str")
        self.assertEqual({lang: (priority, label) for lang, (priority, label, _) in tables.items()},
                         {"EN": (3001, "NEWER/StringTables_pri_3001.zip"), "FR": (3001, "NEWER/StringTables_pri_3001.zip"),
                          "DE": (900, "NEWER/StringTables_pri_900.zip")})
        # A skipped package (the livery packages, whose tables are rebuilt) leaves the rest.
        tables = self.files.sources().string_tables("data_car.str", skip={"NEWER"})
        self.assertEqual({lang: (priority, label) for lang, (priority, label, _) in tables.items()},
                         {"EN": (2950, "PKG/StringTables_pri_2950.zip"), "DE": (0, "disc DE.zip")})
        self.assertEqual(clone._load_tool("fh1-strings").parse(tables["DE"][2]), [(24057, "Stockwagen")])

    def test_an_excluded_package_is_absent_from_every_lookup(self):
        sources = clone.Sources(self.files.state, self.files.game, Path("extractor.exe"), exclude={"PKG"})
        con = sources.database()
        self.addCleanup(con.close)
        self.assertEqual([row[0] for row in con.execute("SELECT Id FROM Data_Car ORDER BY Id")], [1557, 1600])
        self.assertIsNone(sources.car_source("DLC_Car_13"))
        self.assertEqual(sources.data_car_keys(), {24056, 24057})
        self.assertEqual(set(sources.string_tables("data_car.str")), {"EN", "DE"})
        self.assertNotIn("PKG", {path.parents[2].name for path in sources.inputs()})

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

    def test_the_merged_database_is_committed_so_it_can_be_serialised(self):
        con = self.files.sources().database()
        self.addCleanup(con.close)
        self.assertFalse(con.in_transaction)
        copy = sqlite3.connect(":memory:")
        self.addCleanup(copy.close)
        copy.deserialize(con.serialize())
        self.assertEqual(len(copy.execute("SELECT Id FROM Data_Car").fetchall()), 3)


def game_database():
    """A stock car 1557 (engine 1024, body 1557000, drivetrain 963) with an engine
    swap to car 1600's engine 1050, plus gameplay rows that mention it."""
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE Data_Car (Id INTEGER, DisplayName TEXT, ModelShort TEXT, MediaName TEXT, FamilyModelID INTEGER,
            PowertrainID INTEGER, Thumbnail TEXT, StockWheelID INTEGER, ModelId INTEGER, HasRaceLivery INTEGER,
            BaseCost INTEGER, [Time:0-60-sec] REAL);
        INSERT INTO Data_Car VALUES
            (1557, '_&3444137464', '_&3444136508', 'DOD_Car_12', 30, 1,
             'game:\\Media\\UI\\Textures\\Thumbnails\\Thumbnail_1557.xds', 11145, 1557, 0, 45000, 4.5),
            (1600, '_&3444137000', '_&3444137001', 'OTH_Car_10', 12, 2,
             'game:\\Media\\UI\\Textures\\Thumbnails\\Thumbnail_1600.xds', 11000, 1600, 0, 9000, 8.0);
        CREATE TABLE CameraOverrides (CarId INTEGER PRIMARY KEY, CamHeight REAL);
        INSERT INTO CameraOverrides VALUES (1557, 0.1), (1600, 0.2);
        CREATE TABLE CarExceptions (CarID INTEGER, NoMirrors INTEGER);
        INSERT INTO CarExceptions VALUES (1557, 0);
        CREATE TABLE CarPartPositions (ID INTEGER, Ordinal INTEGER, PartId INTEGER, PartPosX REAL);
        INSERT INTO CarPartPositions VALUES (1557000, 1557, 0, 1.5), (1557001, 1557, 1, 2.5), (1600000, 1600, 0, 9.0);
        CREATE TABLE Combo_Colors (ID INTEGER, Ordinal INTEGER, Sequence INTEGER, RGB INTEGER, BaseTexture TEXT);
        INSERT INTO Combo_Colors VALUES (1557001, 1557, 1, 111, 'nodamageBlack.tga'),
            (1557002, 1557, 2, 222, 'nodamageRed.tga');
        CREATE TABLE Combo_Colors_Exceptions (ID INTEGER, Ordinal INTEGER, Sequence INTEGER, ColorStripe INTEGER);
        INSERT INTO Combo_Colors_Exceptions VALUES (827, 1557, 1, 5), (828, 1557, 2, 6), (829, 1600, 1, 7);
        CREATE TABLE List_AntiSwayPhysics (AntiSwayPhysicsID INTEGER, Ordinal INTEGER, Stiffness REAL);
        INSERT INTO List_AntiSwayPhysics VALUES (1557001, 1557, 1.0), (1557101, 1557, 2.0);
        CREATE TABLE List_SpringDamperPhysics (SpringDamperPhysicsID INTEGER, Ordinal INTEGER, RideHeight REAL);
        INSERT INTO List_SpringDamperPhysics VALUES (1557001, 1557, 0.1), (1557101, 1557, 0.2);
        CREATE TABLE List_UpgradeAntiSwayFront (Id INTEGER, Ordinal INTEGER, Level INTEGER, AntiSwayPhysicsID INTEGER);
        INSERT INTO List_UpgradeAntiSwayFront VALUES (1557000, 1557, 1, 1557001);
        CREATE TABLE List_UpgradeSpringDamper (Id INTEGER, Ordinal INTEGER, Level INTEGER,
            FrontSpringDamperPhysicsID INTEGER, RearSpringDamperPhysicsID INTEGER);
        INSERT INTO List_UpgradeSpringDamper VALUES (1557000, 1557, 1, 1557001, 1557101);
        CREATE TABLE List_UpgradeRearWing (Id INTEGER, Ordinal INTEGER, Level INTEGER, AeroPhysicsID INTEGER);
        INSERT INTO List_UpgradeRearWing VALUES (1557000, 1557, 0, 77);
        CREATE TABLE List_UpgradeEngine (Id INTEGER, Ordinal INTEGER, Level INTEGER, EngineID INTEGER, IsStock INTEGER);
        INSERT INTO List_UpgradeEngine VALUES (1557000, 1557, 0, 1024, 1), (1557001, 1557, 1, 1050, 0),
            (1600000, 1600, 0, 1050, 1);
        CREATE TABLE Data_Engine (EngineID INTEGER, MediaName TEXT, [EngineMass-kg] REAL);
        INSERT INTO Data_Engine VALUES (1024, 'DOD_Car_12', 200.0), (1050, 'OTH_Car_10', 150.0);
        CREATE TABLE List_UpgradeEngineCamshaft (Id INTEGER, EngineID INTEGER, Level INTEGER,
            TorqueCurveFullThrottleID INTEGER);
        INSERT INTO List_UpgradeEngineCamshaft VALUES (1024000, 1024, 1, 1024000), (1024002, 1024, 2, 1024002),
            (1050000, 1050, 1, 1050000);
        CREATE TABLE List_UpgradeEngineValves (Id INTEGER, EngineID INTEGER, Level INTEGER, TorqueScale REAL);
        INSERT INTO List_UpgradeEngineValves VALUES (1024000, 1024, 1, 1.1);
        CREATE TABLE List_TorqueCurve (TorqueCurveID INTEGER, TorqueScale REAL, v0 REAL);
        INSERT INTO List_TorqueCurve VALUES (1024000, 1.0, 0.5), (1024002, 1.2, 0.6), (1050000, 0.9, 0.4);
        CREATE TABLE List_UpgradeCarBody (Id INTEGER, Ordinal INTEGER, Level INTEGER, CarBodyID INTEGER);
        INSERT INTO List_UpgradeCarBody VALUES (1557000, 1557, 0, 1557000), (1600000, 1600, 0, 1600000);
        CREATE TABLE Data_CarBody (Id INTEGER, ModelWheelbase REAL);
        INSERT INTO Data_CarBody VALUES (1557000, 2.9), (1600000, 2.5);
        CREATE TABLE List_UpgradeCarBodyHood (Id INTEGER, CarBodyID INTEGER, Level INTEGER, AeroPhysicsID INTEGER);
        INSERT INTO List_UpgradeCarBodyHood VALUES (1557000, 1557000, 0, 78), (1557002, 1557000, 1, 79);
        CREATE TABLE List_UpgradeCarBodyWeight (Id INTEGER, CarbodyId INTEGER, Level INTEGER, Mass REAL);
        INSERT INTO List_UpgradeCarBodyWeight VALUES (1557000, 1557000, 0, 1800.0);
        CREATE TABLE List_UpgradeDrivetrain (Id INTEGER, Ordinal INTEGER, DrivetrainID INTEGER, PowertrainId INTEGER,
            Level INTEGER);
        INSERT INTO List_UpgradeDrivetrain VALUES (1557000, 1557, 963, 1, 0), (1600000, 1600, 970, 2, 0);
        CREATE TABLE Data_Drivetrain (DrivetrainID INTEGER, DrivetypeID INTEGER);
        INSERT INTO Data_Drivetrain VALUES (963, 2), (970, 1);
        CREATE TABLE List_UpgradeDrivetrainClutch (Id INTEGER, DrivetrainID INTEGER, Level INTEGER);
        INSERT INTO List_UpgradeDrivetrainClutch VALUES (963000, 963, 1), (963002, 963, 2);
        CREATE TABLE List_UpgradeDrivetrainDriveline (Id INTEGER, DrivetrainId INTEGER, Level INTEGER);
        INSERT INTO List_UpgradeDrivetrainDriveline VALUES (963000, 963, 1);
        CREATE TABLE List_Wheels (ID INTEGER, MediaName TEXT);
        INSERT INTO List_Wheels VALUES (11145, 'DOD_Car_12');
        CREATE TABLE List_FamilyModel (Id INTEGER, DisplayName TEXT);
        INSERT INTO List_FamilyModel VALUES (30, 'Challenger');
        CREATE TABLE CarChallenges (CarId INTEGER, Title TEXT);
        INSERT INTO CarChallenges VALUES (1557, 'drift');
        CREATE TABLE CarChallengeTitles (CarId INTEGER, Title TEXT);
        INSERT INTO CarChallengeTitles VALUES (1557, 'title');
        CREATE TABLE EventParticipants (ID INTEGER, EventID INTEGER, Ordinal INTEGER);
        INSERT INTO EventParticipants VALUES (1557, 5, 1);
        CREATE TABLE EventRecommendedCars (EventID INTEGER, CarID INTEGER);
        INSERT INTO EventRecommendedCars VALUES (5, 1557);
        CREATE TABLE Rewards_EventPrizes (Id INTEGER, EventId INTEGER, RewardCarId INTEGER);
        INSERT INTO Rewards_EventPrizes VALUES (1, 5, 1557);
    """)
    return con


NAMES = clone.CarNames("DOD_Car_RSE_12", "_&3444120000", "_&3444120001")


class RowCloneTests(unittest.TestCase):
    def setUp(self):
        self.db = game_database()
        self.addCleanup(self.db.close)

    def clone(self, stock_id=1557, new_id=3001, names=NAMES):
        result = clone.clone_rows(self.db, stock_id, new_id, names)
        merge = sqlite3.connect(":memory:")
        merge.deserialize(result.database)
        self.addCleanup(merge.close)
        return result, merge

    @staticmethod
    def rows(con, sql):
        return con.execute(sql).fetchall()

    def test_data_car_changes_only_the_identity_names_thumbnail_and_race_livery(self):
        _, merge = self.clone()
        self.assertEqual(self.rows(merge, "SELECT * FROM Data_Car"), [
            (3001, "_&3444120000", "_&3444120001", "DOD_Car_RSE_12", 30, 1,
             "game:\\Media\\UI\\Textures\\Thumbnails\\Thumbnail_3001.xds", 11145, 3001, 1, 45000, 4.5)])

    def test_per_car_rows_are_copied_under_the_new_car_id(self):
        _, merge = self.clone()
        self.assertEqual(self.rows(merge, "SELECT * FROM CameraOverrides"), [(3001, 0.1)])
        self.assertEqual(self.rows(merge, "SELECT * FROM CarExceptions"), [(3001, 0)])
        self.assertEqual(self.rows(merge, "SELECT * FROM CarPartPositions"),
                         [(3001000, 3001, 0, 1.5), (3001001, 3001, 1, 2.5)])
        self.assertEqual(self.rows(merge, "SELECT * FROM Combo_Colors"),
                         [(3001001, 3001, 1, 111, "nodamageBlack.tga"), (3001002, 3001, 2, 222, "nodamageRed.tga")])
        self.assertEqual(self.rows(merge, "SELECT * FROM List_AntiSwayPhysics"),
                         [(3001001, 3001, 1.0), (3001101, 3001, 2.0)])
        self.assertEqual(self.rows(merge, "SELECT * FROM List_SpringDamperPhysics"),
                         [(3001001, 3001, 0.1), (3001101, 3001, 0.2)])
        self.assertEqual(self.rows(merge, "SELECT * FROM List_UpgradeAntiSwayFront"), [(3001000, 3001, 1, 3001001)])
        self.assertEqual(self.rows(merge, "SELECT * FROM List_UpgradeSpringDamper"),
                         [(3001000, 3001, 1, 3001001, 3001101)])

    def test_rows_repeated_by_two_packages_carrying_the_same_car_are_copied_once(self):
        # The 1100 and 1200 car packs both ship the Boss 302; keyless tables then hold every row twice.
        self.db.execute("INSERT INTO CarPartPositions VALUES (1557000, 1557, 0, 1.5)")
        _, merge = self.clone()
        self.assertEqual(self.rows(merge, "SELECT * FROM CarPartPositions"),
                         [(3001000, 3001, 0, 1.5), (3001001, 3001, 1, 2.5)])

    def test_colour_exceptions_numbered_one_after_another_get_ids_under_the_new_car(self):
        # Turn 10 numbers these rows 1, 2, 3, ...; car x 1000 + n cannot collide with them or another clone.
        _, merge = self.clone()
        self.assertEqual(self.rows(merge, "SELECT * FROM Combo_Colors_Exceptions"),
                         [(3001001, 3001, 1, 5), (3001002, 3001, 2, 6)])

    def test_the_stock_engine_is_rekeyed_with_its_parts_torque_curves_and_media_name(self):
        result, merge = self.clone()
        self.assertEqual(self.rows(merge, "SELECT * FROM Data_Engine"), [(3001, "DOD_Car_RSE_12", 200.0)])
        self.assertEqual(self.rows(merge, "SELECT * FROM List_UpgradeEngineCamshaft"),
                         [(3001000, 3001, 1, 3001000), (3001002, 3001, 2, 3001002)])
        self.assertEqual(self.rows(merge, "SELECT * FROM List_UpgradeEngineValves"), [(3001000, 3001, 1, 1.1)])
        self.assertEqual(self.rows(merge, "SELECT * FROM List_TorqueCurve"), [(3001000, 1.0, 0.5), (3001002, 1.2, 0.6)])
        self.assertEqual(result.ids["engine"], 3001)
        self.assertEqual(result.ids["torque_curves"], [3001000, 3001002])

    def test_a_swap_engine_stays_shared_with_the_car_that_owns_it(self):
        result, merge = self.clone()
        self.assertEqual(self.rows(merge, "SELECT * FROM List_UpgradeEngine"),
                         [(3001000, 3001, 0, 3001, 1), (3001001, 3001, 1, 1050, 0)])
        self.assertEqual(result.shared["swap_engines"], [1050])

    def test_the_car_body_is_car_id_times_1000_whatever_the_key_is_spelt(self):
        result, merge = self.clone()
        self.assertEqual(self.rows(merge, "SELECT * FROM List_UpgradeCarBody"), [(3001000, 3001, 0, 3001000)])
        self.assertEqual(self.rows(merge, "SELECT * FROM Data_CarBody"), [(3001000, 2.9)])
        self.assertEqual(self.rows(merge, "SELECT * FROM List_UpgradeCarBodyHood"),
                         [(3001000, 3001000, 0, 78), (3001002, 3001000, 1, 79)])
        self.assertEqual(self.rows(merge, "SELECT * FROM List_UpgradeCarBodyWeight"), [(3001000, 3001000, 0, 1800.0)])
        self.assertEqual(result.ids["body"], 3001000)

    def test_the_drivetrain_takes_the_new_car_id_and_keeps_its_powertrain(self):
        result, merge = self.clone()
        self.assertEqual(self.rows(merge, "SELECT * FROM List_UpgradeDrivetrain"), [(3001000, 3001, 3001, 1, 0)])
        self.assertEqual(self.rows(merge, "SELECT * FROM Data_Drivetrain"), [(3001, 2)])
        self.assertEqual(self.rows(merge, "SELECT * FROM List_UpgradeDrivetrainClutch"),
                         [(3001000, 3001, 1), (3001002, 3001, 2)])
        self.assertEqual(self.rows(merge, "SELECT * FROM List_UpgradeDrivetrainDriveline"), [(3001000, 3001, 1)])
        self.assertEqual(result.ids["drivetrain"], 3001)

    def test_wheels_aero_family_and_powertrain_are_shared_not_copied(self):
        result, merge = self.clone()
        tables = {name for (name,) in merge.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("List_Wheels", tables)
        self.assertNotIn("List_FamilyModel", tables)
        self.assertEqual(self.rows(merge, "SELECT AeroPhysicsID FROM List_UpgradeRearWing"), [(77,)])
        self.assertEqual(result.shared["StockWheelID"], 11145)
        self.assertEqual(result.shared["FamilyModelID"], 30)
        self.assertEqual(result.shared["PowertrainID"], 1)
        self.assertEqual(result.shared["AeroPhysicsID"], [77, 78, 79])

    def test_gameplay_rows_that_mention_the_car_stay_with_the_stock_car(self):
        _, merge = self.clone()
        tables = {name for (name,) in merge.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for gameplay in ("CarChallenges", "CarChallengeTitles", "EventParticipants", "EventRecommendedCars",
                         "Rewards_EventPrizes"):
            self.assertNotIn(gameplay, tables)

    def test_the_merge_uses_the_source_schema_and_holds_only_new_rows(self):
        result, merge = self.clone()
        source = dict(self.db.execute("SELECT name, sql FROM sqlite_master WHERE type='table'"))
        written = dict(merge.execute("SELECT name, sql FROM sqlite_master WHERE type='table'"))
        self.assertEqual(written, {name: source[name] for name in written})
        self.assertEqual(result.tables, {name: merge.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()[0]
                                         for name in written})
        self.assertEqual(sum(result.tables.values()), 34)

    def test_the_source_database_is_not_changed(self):
        before = self.db.serialize()
        self.clone()
        self.assertEqual(self.db.serialize(), before)

    def test_an_unknown_stock_car_is_refused(self):
        with self.assertRaisesRegex(ValueError, "car 1234 is not in the game database"):
            clone.clone_rows(self.db, 1234, 3001, NAMES)

    def test_a_car_id_already_in_use_is_refused(self):
        for used in (1557, 1600):
            with self.assertRaisesRegex(ValueError, f"car ID {used} is already used"):
                clone.clone_rows(self.db, 1557, used, NAMES)

    def test_a_media_name_already_in_use_is_refused(self):
        with self.assertRaisesRegex(ValueError, "media name oth_car_10 is already used"):
            clone.clone_rows(self.db, 1557, 3001, NAMES._replace(media="oth_car_10"))

    def test_a_component_id_already_in_use_is_refused(self):
        for statement, what in (("INSERT INTO Data_Engine VALUES (3001, 'X', 1.0)", "Data_Engine"),
                                ("INSERT INTO List_TorqueCurve VALUES (3001002, 1.0, 1.0)", "List_TorqueCurve"),
                                ("INSERT INTO Data_CarBody VALUES (3001000, 1.0)", "Data_CarBody"),
                                ("INSERT INTO List_UpgradeDrivetrainClutch VALUES (3001000, 3001, 1)",
                                 "List_UpgradeDrivetrainClutch"),
                                ("INSERT INTO CameraOverrides VALUES (3001, 1.0)", "CameraOverrides")):
            with self.subTest(what):
                db = game_database()
                self.addCleanup(db.close)
                db.execute(statement)
                with self.assertRaisesRegex(ValueError, f"{what} already has"):
                    clone.clone_rows(db, 1557, 3001, NAMES)

    def test_rows_that_break_turn_10s_numbering_are_refused(self):
        self.db.execute("INSERT INTO CarPartPositions VALUES (42, 1557, 2, 0.0)")
        with self.assertRaisesRegex(ValueError, "CarPartPositions.ID 42 does not follow"):
            clone.clone_rows(self.db, 1557, 3001, NAMES)


def fbf_path(text):
    """A dash .fbf string: big-endian u32 length, then the text."""
    return struct.pack(">I", len(text)) + text.encode()


class ModelTreeTests(unittest.TestCase):
    def name(self, member):
        return clone.clone_member_name(member, "DOD_Car_12", "DOD_Car_RSE_12")

    def test_model_files_stripped_copies_build_report_and_exporter_settings_take_the_new_name(self):
        for stock, new in (("DOD_Car_12.carbin", "DOD_Car_RSE_12.carbin"),
                           ("DOD_Car_12_lod0.carbin", "DOD_Car_RSE_12_lod0.carbin"),
                           ("DOD_Car_12_cockpit.carbin", "DOD_Car_RSE_12_cockpit.carbin"),
                           ("DOD_Car_12_caliperLF_LOD0.carbin", "DOD_Car_RSE_12_caliperLF_LOD0.carbin"),
                           ("stripped_dod_car_12_rotorrr_lod0.carbin", "stripped_dod_car_rse_12_rotorrr_lod0.carbin"),
                           ("cars_DOD_Car_12_build_report.html", "cars_DOD_Car_RSE_12_build_report.html"),
                           ("Last_dod_car_12.xml", "Last_dod_car_rse_12.xml"),
                           ("DOD_CAR_12_caliperRR_LOD0.carbin", "DOD_CAR_RSE_12_caliperRR_LOD0.carbin")):
            self.assertEqual(self.name(stock), new)

    def test_the_dash_is_renamed_because_the_game_finds_it_by_media_name(self):
        # v4 builds <car folder>\digitalgauge\Dash_<media>.bgf; Turn 10 renamed it on the Pizza Hut.
        for extension in ("bgf", "bsg", "fbf"):
            self.assertEqual(self.name(f"DigitalGauge/Dash_DOD_Car_12.{extension}"),
                             f"DigitalGauge/Dash_DOD_Car_RSE_12.{extension}")

    def test_gauge_textures_and_other_files_keep_their_names(self):
        for kept in ("DigitalGauge/DOD_CAR_12_GEAR_R.XDS", "DigitalGauge/ALF_8C_08_TEXT_MI.XDS", "nodamage.xds",
                     "nodamagestripe_LOD0.xds", "LiveryMasks/Masks.xml", "Physics/MAXData.xml", "CarAttribs.xml"):
            self.assertEqual(self.name(kept), kept)

    def test_dash_texture_paths_follow_the_car_to_its_new_folder(self):
        own = r"GAME:\MEDIA\CARS\DOD_CAR_12\DIGITALGAUGE\DOD_CAR_12_GEAR_R.TGA"
        shared = r"GAME:\MEDIA\CARS\SHARED\DASHBOARDS\AUD_TEXT_FM.TGA"
        data = b"\x00\x00\x03\xf0" + fbf_path("DOD_CAR_12_GEAR_R.TGA") + fbf_path(own) + b"\x3f\x80" + fbf_path(shared)
        self.assertEqual(clone.rewrite_dash_paths(data, "DOD_Car_12", "DOD_Car_RSE_12"),
                         b"\x00\x00\x03\xf0" + fbf_path("DOD_CAR_12_GEAR_R.TGA")
                         + fbf_path(r"GAME:\MEDIA\CARS\DOD_CAR_RSE_12\DIGITALGAUGE\DOD_CAR_12_GEAR_R.TGA")
                         + b"\x3f\x80" + fbf_path(shared))

    def test_a_dash_path_without_its_length_is_refused(self):
        data = b"\x00\x00\x00\x02" + rb"GAME:\MEDIA\CARS\DOD_CAR_12\X.TGA"
        with self.assertRaisesRegex(ValueError, "dash file"):
            clone.rewrite_dash_paths(data, "DOD_Car_12", "DOD_Car_RSE_12")

    def test_the_tree_holds_every_member_and_the_renamed_audio(self):
        dash = fbf_path(r"GAME:\MEDIA\CARS\DOD_CAR_12\DIGITALGAUGE\G.TGA")
        car_files = {"DOD_Car_12.carbin": b"model", "nodamage.xds": b"paint", "DigitalGauge/Dash_DOD_Car_12.fbf": dash,
                     "DigitalGauge/G.XDS": b"gauge"}
        audio = {"CarModelTuning": b"<cmt/>", "EngineTuning": b"<et/>"}
        staged, records = clone.clone_files(car_files, audio, "DOD_Car_12", "DOD_Car_RSE_12")
        self.assertEqual(staged, {
            "media/cars/DOD_Car_RSE_12/DOD_Car_RSE_12.carbin": b"model",
            "media/cars/DOD_Car_RSE_12/nodamage.xds": b"paint",
            "media/cars/DOD_Car_RSE_12/DigitalGauge/Dash_DOD_Car_RSE_12.fbf":
                fbf_path(r"GAME:\MEDIA\CARS\DOD_CAR_RSE_12\DIGITALGAUGE\G.TGA"),
            "media/cars/DOD_Car_RSE_12/DigitalGauge/G.XDS": b"gauge",
            "media/audio/cars/CarModelTuning/DOD_Car_RSE_12_CMT.xml": b"<cmt/>",
            "media/audio/cars/Engines/EngineTuning/DOD_Car_RSE_12_ET.xml": b"<et/>"})
        by_path = {record["path"]: record for record in records}
        self.assertEqual(by_path["media/cars/DOD_Car_RSE_12/nodamage.xds"],
                         {"source": "nodamage.xds", "path": "media/cars/DOD_Car_RSE_12/nodamage.xds", "size": 5,
                          "sha256": hashlib.sha256(b"paint").hexdigest(), "renamed": False, "rewritten": False})
        self.assertTrue(by_path["media/cars/DOD_Car_RSE_12/DigitalGauge/Dash_DOD_Car_RSE_12.fbf"]["rewritten"])
        self.assertEqual(by_path["media/audio/cars/CarModelTuning/DOD_Car_RSE_12_CMT.xml"]["source"],
                         "CarModelTuning/DOD_Car_12_CMT.xml")

    def test_two_members_landing_on_one_name_are_refused(self):
        with self.assertRaisesRegex(ValueError, "(?i)written as media/cars/DOD_Car_RSE_12/DOD_Car_RSE_12.carbin"):
            clone.clone_files({"DOD_Car_12.carbin": b"a", "dod_car_12.carbin": b"b"}, {}, "DOD_Car_12",
                              "DOD_Car_RSE_12")


class StringKeyTests(unittest.TestCase):
    def test_a_reference_names_the_data_car_table_and_the_key(self):
        # The Pizza Hut Mustang's name: table 0xCD49, key 7451.
        self.assertEqual(clone.string_reference(7451), "_&3444120859")
        self.assertEqual(clone.string_key("_&3444120859"), 7451)

    def test_a_reference_into_another_table_is_not_a_data_car_key(self):
        self.assertIsNone(clone.string_key("_&857938260"))   # MakeName, a different table
        self.assertIsNone(clone.string_key("Plain text"))

    def test_keys_start_at_twice_the_car_id_so_cars_built_together_never_share_one(self):
        self.assertEqual(clone.allocate_string_keys(set(), 3001), [6002, 6003])
        pairs = [clone.allocate_string_keys(set(), car) for car in range(3001, 3008)]
        self.assertEqual(len({key for pair in pairs for key in pair}), 14)

    def test_used_keys_are_skipped(self):
        self.assertEqual(clone.allocate_string_keys({6002, 6004}, 3001), [6003, 6005])

    def test_the_search_wraps_past_the_sentinel_and_key_zero(self):
        self.assertEqual(clone.allocate_string_keys({65534}, 32767), [1, 2])

    def test_a_full_table_is_refused(self):
        with self.assertRaisesRegex(ValueError, "no unused Data_Car string keys"):
            clone.allocate_string_keys(set(range(0x10000)) - {7}, 3001)

    def test_keys_referenced_by_any_car_are_used_even_if_no_table_has_them(self):
        db = game_database()
        self.addCleanup(db.close)
        self.assertEqual(clone.referenced_string_keys(db), {24056, 23100, 23592, 23593})

    def test_names_take_a_new_display_name_and_a_copy_of_the_stock_short_name(self):
        db = game_database()
        self.addCleanup(db.close)
        db.execute("UPDATE Data_Car SET DisplayName='_&3444119410' WHERE Id=1600")   # key 6002 taken by a car
        names, strings = clone.clone_names(db, {6003}, 1557, 3001, "DOD_Car_RSE_12", "Challenger Rockstar")
        self.assertEqual(names, clone.CarNames("DOD_Car_RSE_12", "_&3444119412", "_&3444119413"))
        # Turn 10's Pizza Hut has its own ModelShort key holding the Boss 302's short name.
        self.assertEqual(strings, [{"field": "DisplayName", "key": 6004, "text": "Challenger Rockstar"},
                                   {"field": "ModelShort", "key": 6005, "same_as": 23100}])


class CloneSetup:
    """Player files holding game_database()'s stock car 1557 (DOD_Car_12) on the
    disc, a package car PKG_Car_13, and an ID table reserving 3001 for car 1557."""

    def __init__(self, root: Path):
        self.root, self.state, self.game = root, root / "state", root / "game"
        db = game_database()
        db.commit()
        write_zip(self.state / "title-update-v4/media.zip", {"db/gamedb.slt": db.serialize()})
        db.close()
        package = self.state / TITLE / "00000002/PKG/Media/DLCZips"
        write_zip(package / "2800_pri_65.zip", {"media/cars/PKG_Car_13/PKG_Car_13.carbin": b"package model"})
        write_zip(package / "StringTables_pri_2950.zip", {"EN/Data_Car.str": string_table([(6002, "Taken")])})
        dash = fbf_path(r"GAME:\MEDIA\CARS\DOD_CAR_12\DIGITALGAUGE\G.TGA")
        write_zip(self.game / "media/cars/DOD_Car_12.zip", {
            "DOD_Car_12.carbin": b"stock model", "stripped_dod_car_12.carbin": b"stripped", "nodamage.xds": b"paint",
            "DigitalGauge/Dash_DOD_Car_12.fbf": dash, "DigitalGauge/G.XDS": b"gauge"})
        write_zip(self.game / "media/audio/cars/CarModelTuning.zip", {"DOD_Car_12_CMT.xml": b"<cmt/>"})
        write_zip(self.game / "media/audio/cars/Engines/EngineTuning.zip", {"DOD_Car_12_ET.xml": b"<et/>"})
        write_zip(self.game / "media/StringTables/EN.zip",
                  {"Data_Car.str": string_table([(23100, "Challenger '12"), (24056, "Challenger")])})
        self.ids = root / "ids.json"
        self.ids.write_text('{"schema_version": 1, "cars": [{"id": 3001, "stock_id": 1557, "car": "Rockstar"}]}')
        self.output = root / "out" / "clone"

    def args(self, **changes):
        values = {"--state-root": self.state, "--game-root": self.game, "--stock-id": 1557, "--new-id": 3001,
                  "--media-name": "DOD_Car_RSE_12", "--display-name": "Challenger Rockstar",
                  "--output": self.output, "--ids": self.ids, "--extractor": self.root / "extractor.exe"}
        values.update({f"--{key.replace('_', '-')}": value for key, value in changes.items()})
        return [str(item) for pair in values.items() for item in pair]

    def hashes(self):
        return {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(self.state.rglob("*"))
                + sorted(self.game.rglob("*")) if p.is_file()}


class CloneCarTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.setup = CloneSetup(Path(self.temporary.name))

    def run_cli(self, **changes):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = clone.main(self.setup.args(**changes))
        return code, out.getvalue(), err.getvalue()

    def test_the_cli_stages_the_car_and_prints_its_report(self):
        code, out, err = self.run_cli()
        self.assertEqual((code, err), (0, ""))
        report = json.loads(out)
        staged = sorted(str(p.relative_to(self.setup.output)).replace("\\", "/")
                        for p in self.setup.output.rglob("*") if p.is_file())
        self.assertEqual(staged, [
            "media/audio/cars/CarModelTuning/DOD_Car_RSE_12_CMT.xml",
            "media/audio/cars/Engines/EngineTuning/DOD_Car_RSE_12_ET.xml",
            "media/cars/DOD_Car_RSE_12/DOD_Car_RSE_12.carbin",
            "media/cars/DOD_Car_RSE_12/DigitalGauge/Dash_DOD_Car_RSE_12.fbf",
            "media/cars/DOD_Car_RSE_12/DigitalGauge/G.XDS",
            "media/cars/DOD_Car_RSE_12/nodamage.xds",
            "media/cars/DOD_Car_RSE_12/stripped_dod_car_rse_12.carbin",
            "media/db/patch/3001000_merge.slt"])
        self.assertEqual(report["car"], {"id": 3001, "media_name": "DOD_Car_RSE_12",
                                         "display_name": "Challenger Rockstar"})
        self.assertEqual(report["stock"], {"id": 1557, "media_name": "DOD_Car_12",
                                           "archive": str(self.setup.game / "media/cars/DOD_Car_12.zip")})
        self.assertEqual(report["strings"], [{"field": "DisplayName", "key": 6003, "text": "Challenger Rockstar"},
                                             {"field": "ModelShort", "key": 6004, "same_as": 23100}])
        self.assertEqual(report["ids"]["body"], 3001000)
        self.assertEqual(report["rows"], sum(report["tables"].values()))
        self.assertEqual(len(report["files"]), 7)
        self.assertTrue(report["sources_unchanged"])
        self.assertEqual({source["path"] for source in report["sources"]}, {str(p) for p in self.setup.hashes()})
        merge = sqlite3.connect(self.setup.output / "media/db/patch/3001000_merge.slt")
        self.addCleanup(merge.close)
        self.assertEqual(merge.execute("SELECT Id, DisplayName, ModelShort, MediaName FROM Data_Car").fetchall(),
                         [(3001, "_&3444119411", "_&3444119412", "DOD_Car_RSE_12")])

    def test_cloning_changes_no_source_file(self):
        before = self.setup.hashes()
        self.assertEqual(self.run_cli()[0], 0)
        self.assertEqual(self.setup.hashes(), before)

    def test_an_existing_output_is_refused(self):
        self.setup.output.mkdir(parents=True)
        code, _, err = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)

    def refused(self, message, **changes):
        code, out, err = self.run_cli(**changes)
        self.assertEqual((code, out), (1, ""))
        self.assertRegex(err, message)
        self.assertFalse(self.setup.output.exists())
        self.assertEqual(list(self.setup.output.parent.glob("*")) if self.setup.output.parent.exists() else [], [])

    def test_an_id_not_in_the_committed_table_is_refused(self):
        self.refused("car ID 3002 is not reserved in .*ids.json", new_id=3002)

    def test_a_reserved_id_for_another_stock_car_is_refused(self):
        self.refused("car ID 3001 is reserved for a clone of car 1557, not 1600", stock_id=1600,
                     media_name="OTH_Car_X_10")

    def test_an_unknown_stock_car_is_refused(self):
        self.setup.ids.write_text('{"schema_version": 1, "cars": [{"id": 3001, "stock_id": 1234, "car": "x"}]}')
        self.refused("car 1234 is not in the game database", stock_id=1234)

    def test_a_car_id_already_in_the_game_is_refused(self):
        self.setup.ids.write_text('{"schema_version": 1, "cars": [{"id": 1600, "stock_id": 1557, "car": "x"}]}')
        self.refused("car ID 1600 is already used", new_id=1600)

    def test_a_media_name_used_by_a_car_or_its_files_is_refused(self):
        self.refused("media name OTH_Car_10 is already used", media_name="OTH_Car_10")
        self.refused("media name PKG_Car_13 is already used by .*2800_pri_65.zip", media_name="PKG_Car_13")

    def test_a_media_name_that_is_not_a_plain_file_name_is_refused(self):
        for name in ("../escape", "With Space", ""):
            self.refused("media name must be", media_name=name)

    def test_a_failure_part_way_leaves_no_output(self):
        with patch.object(clone, "clone_files", side_effect=ValueError("unexpected dash file layout")):
            self.refused("unexpected dash file layout")

    def test_the_committed_table_reserves_3001_to_3007_for_the_seven_livery_cars(self):
        table = clone.reserved_ids()
        self.assertEqual({car: entry["stock_id"] for car, entry in table.items()},
                         {3001: 1557, 3002: 1548, 3003: 1548, 3004: 1516, 3005: 1173, 3006: 1082, 3007: 1009})


if __name__ == "__main__":
    unittest.main()
