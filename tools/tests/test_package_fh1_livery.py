"""Livery packages from synthetic stock cars: rows, string tables, thumbnail, header and layout."""
import importlib.util
import sqlite3
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


package = load("package_fh1_livery", TOOLS / "package-fh1-livery.py")
clone = load("clone_fh1_car_for_package", TOOLS / "clone-fh1-car.py")
clone_tests = load("test_clone_fh1_car_for_package", Path(__file__).with_name("test_clone_fh1_car.py"))

CAR = {"stock_id": 1557, "new_id": 3001, "stock_media": "DOD_Car_12", "media_name": "DOD_Car_RSE_12",
       "display_name": "Car Rockstar", "price": None}


def game_database(unicorn: int = 0) -> sqlite3.Connection:
    """car-clone's synthetic game database, with the offer tables and stripe colours of the real one."""
    db = clone_tests.game_database()
    db.executescript(f"""
        ALTER TABLE Data_Car ADD COLUMN IsUnicorn INTEGER;
        UPDATE Data_Car SET IsUnicorn = {unicorn};
        CREATE TABLE StripeColors (Ordinal INT, Sequence INT, ColorStripe INT, MetallicAmount REAL);
        INSERT INTO StripeColors VALUES (1557, 1, 4, 0.5), (1600, 1, 4, 0.5);
        CREATE TABLE ContentOffers (ID TEXT, OfferId INTEGER PRIMARY KEY, DisplayName TEXT, Description TEXT,
            PubOfferingID INT, LicenseLevel INT, LicenseMask INT, IsDLC INT, ImagePath TEXT, ThumbPath TEXT,
            IsInstalled INT, IsPurchased INT, IsVIP INT, Hidden INT, IsALaCarte INT, SeasonPassOffer BIGINT);
        INSERT INTO ContentOffers VALUES ('4D5309C9FD0AB400', 5571807927125849088, '_&1', '_&2', 2800, 2, 1, 1,
            'a', 'b', 0, 0, 0, 0, 0, 0);
        CREATE TABLE ContentOffersMapping (Id INTEGER PRIMARY KEY, OfferId BIGINT, ContentId INT, ContentType INT);
        INSERT INTO ContentOffersMapping VALUES (9055, 5571807927125849088, 1686, 1);
    """)
    return db


def cloned_merge(db: sqlite3.Connection) -> bytes:
    names = clone.CarNames(CAR["media_name"], clone.string_reference(6002), clone.string_reference(6003))
    return clone.clone_rows(db, CAR["stock_id"], CAR["new_id"], names).database


def rows_of(merge: bytes, sql: str) -> list:
    con = sqlite3.connect(":memory:")
    con.deserialize(merge)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


class PackageRowTests(unittest.TestCase):
    def setUp(self):
        self.db = game_database()
        self.addCleanup(self.db.close)
        self.merge = cloned_merge(self.db)

    def rows(self, car=CAR, paint=(0x8C, 0x00, 0x01)):
        return package.package_rows(self.merge, self.db, car, paint)

    def test_the_price_defaults_to_the_stock_cars(self):
        merge, report = self.rows()
        self.assertEqual(rows_of(merge, "SELECT BaseCost FROM Data_Car"), [(45000,)])
        self.assertEqual(report["price"], 45000)
        merge, _ = self.rows(CAR | {"price": 60000})
        self.assertEqual(rows_of(merge, "SELECT BaseCost FROM Data_Car"), [(60000,)])

    def test_a_unicorn_stock_car_gives_a_car_the_autoshow_lists(self):
        db = game_database(unicorn=1)
        self.addCleanup(db.close)
        merge, _ = package.package_rows(cloned_merge(db), db, CAR, (1, 2, 3))
        self.assertEqual(rows_of(merge, "SELECT IsUnicorn FROM Data_Car"), [(0,)])

    def test_one_paint_option_in_the_recipes_colour(self):
        merge, report = self.rows()
        self.assertEqual(rows_of(merge, "SELECT ID, Ordinal, Sequence, RGB, BaseTexture FROM Combo_Colors"),
                         [(3001001, 3001, 1, 0x8C0001, "nodamage.tga")])
        tables = {name for (name,) in rows_of(merge, "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse(tables & {"Combo_Colors_Exceptions", "StripeColors"})
        self.assertEqual(report["dropped"], {"Combo_Colors": 1, "Combo_Colors_Exceptions": 2, "StripeColors": 1})

    def test_a_hidden_offer_owns_the_car(self):
        merge, report = self.rows()
        offer = 0x4D5309C9_50530BB9
        self.assertEqual(rows_of(merge, "SELECT ID, OfferId, DisplayName, PubOfferingID, LicenseLevel, LicenseMask,"
                                        " IsDLC, Hidden, IsVIP, SeasonPassOffer FROM ContentOffers"),
                         [("4D5309C950530BB9", offer, clone.string_reference(6002), 3001, 2, 1, 1, 1, 0, 0)])
        self.assertEqual(rows_of(merge, "SELECT ImagePath, ThumbPath FROM ContentOffers"),
                         [("GAME:\\Media\\UI\\Textures\\UI4\\Marketplace\\Day1_LG.tga",
                           "GAME:\\Media\\UI\\Textures\\UI4\\Marketplace\\Day1_SM.tga")])
        self.assertEqual(rows_of(merge, "SELECT * FROM ContentOffersMapping"), [(30010, offer, 3001, 1)])
        self.assertEqual(report["offer"], {"offer_id": "4D5309C950530BB9", "pub_offering_id": 3001,
                                           "license_mask": 1, "mapping_id": 30010})
        # The tables take the game database's own schema, so the title's merge accepts them.
        schema = dict(self.db.execute("SELECT name, sql FROM sqlite_master WHERE name LIKE 'ContentOffers%'"))
        self.assertEqual(dict(rows_of(merge, "SELECT name, sql FROM sqlite_master WHERE name LIKE 'ContentOffers%'")),
                         schema)

    def test_every_other_row_is_the_clones(self):
        merge, _ = self.rows()
        for table in ("CameraOverrides", "CarPartPositions", "List_UpgradeEngine", "Data_Engine"):
            with self.subTest(table=table):
                self.assertEqual(rows_of(merge, f"SELECT * FROM {table}"), rows_of(self.merge, f"SELECT * FROM {table}"))
        before = rows_of(self.merge, "SELECT * FROM Data_Car")[0]
        after = rows_of(merge, "SELECT * FROM Data_Car")[0]
        columns = [c[1] for c in self.db.execute("PRAGMA table_info(Data_Car)")]
        self.assertEqual({c for c, a, b in zip(columns, before, after) if a != b}, set())   # stock price, not a unicorn

    def test_the_result_merges_into_the_game_database(self):
        merge, _ = self.rows()
        clone.Sources._apply_merge(self.db, merge)
        self.assertEqual(self.db.execute("SELECT ContentId FROM ContentOffersMapping WHERE Id=30010").fetchone(), (3001,))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM Combo_Colors WHERE Ordinal=3001").fetchone(), (1,))

    def test_equal_inputs_give_equal_bytes(self):
        self.assertEqual(self.rows()[0], self.rows()[0])

    def test_taken_offer_and_mapping_ids_are_refused(self):
        for sql, message in (("INSERT INTO ContentOffers (OfferId, PubOfferingID) VALUES (1, 3001)", "offering 3001"),
                             (f"INSERT INTO ContentOffers (OfferId, PubOfferingID) VALUES ({0x4D5309C9_50530BB9}, 9)",
                              "offer 4D5309C950530BB9"),
                             ("INSERT INTO ContentOffersMapping VALUES (30010, 1, 1, 1)", "mapping 30010"),
                             ("INSERT INTO ContentOffersMapping VALUES (77, 1, 3001, 1)", "car 3001 already")):
            db = game_database()
            self.addCleanup(db.close)
            merge = cloned_merge(db)
            db.execute(sql)
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                package.package_rows(merge, db, CAR, (0, 0, 0))

    def test_a_merge_without_the_cars_row_is_refused(self):
        with self.assertRaisesRegex(ValueError, "no Data_Car row for car 3002"):
            package.package_rows(self.merge, self.db, CAR | {"new_id": 3002}, (0, 0, 0))


strings = load("fh1_strings_for_package", TOOLS / "fh1-strings.py")
archives = load("patch_fh1_archive_for_package", TOOLS / "patch-fh1-archive.py")


def read_zip(data: bytes) -> list[tuple[str, bytes]]:
    import io
    import zipfile
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return [(info.filename, archive.read(info)) for info in archive.infolist()]


class StringTableTests(unittest.TestCase):
    BASE = {"EN": (2950, "PKG/StringTables_pri_2950.zip", clone_tests.string_table([(7451, "Pizza Hut"), (24056, "Car")])),
            "br": (0, "disc br.zip", clone_tests.string_table([(24056, "Carro")]))}
    # car-clone's entries: a display name, and a short name holding the stock car's in each language.
    LIVERY = [{"key": 6002, "text": "Car Rockstar"}, {"key": 6003, "same_as": 24056},
              {"key": 6004, "text": "Car Meguiar's"}, {"key": 6005, "same_as": 24056}]

    def test_every_language_keeps_its_base_entries_and_gains_the_livery_cars(self):
        tables = package.livery_tables(self.BASE, self.LIVERY)
        self.assertEqual(set(tables), {"EN", "br"})
        self.assertEqual(strings.parse(tables["EN"]), [(6002, "Car Rockstar"), (6003, "Car"), (6004, "Car Meguiar's"),
                                                       (6005, "Car"), (7451, "Pizza Hut"), (24056, "Car")])
        self.assertEqual({key: text for key, text in strings.parse(tables["br"]) if key in (6003, 6004, 24056)},
                         {6003: "Carro", 6004: "Car Meguiar's", 24056: "Carro"})

    def test_a_short_name_missing_from_a_language_takes_the_english_one(self):
        base = self.BASE | {"DE": (0, "disc DE.zip", clone_tests.string_table([(1, "Anderes")]))}
        self.assertEqual(dict(strings.parse(package.livery_tables(base, self.LIVERY)["DE"]))[6003], "Car")
        with self.assertRaisesRegex(ValueError, "string 999"):
            package.livery_tables(base, [{"key": 6003, "same_as": 999}])

    def test_the_string_files_are_shaped_like_turn_10s(self):
        files = package.string_files(package.livery_tables(self.BASE, self.LIVERY), 3001)
        self.assertEqual(sorted(files), ["StringTables_pri_3001.zip", "stringtables.xml", "zipmount.xml"])
        self.assertEqual([name for name, _ in read_zip(files["StringTables_pri_3001.zip"])],
                         ["br/Data_Car.str", "EN/Data_Car.str"])           # Turn 10's order ignores case
        self.assertEqual(files["stringtables.xml"],
                         b'<?xml version="1.0" ?> \r\n<stringtables> \r\n   <table Name="Data_Car" /> \r\n'
                         b'</stringtables> \r\n')
        self.assertEqual(files["zipmount.xml"],
                         b'<?xml version="1.0" ?> \r\n<zipmount> \r\n   <zip Name="StringTables_pri_3001.zip" '
                         b'Mount="game:\\Media\\StringTables\\"  /> \r\n</zipmount> \r\n')

    def test_members_follow_turn_10s_order(self):
        names = ["media/wheels/W/wheel.xds", "media/cars/C/LiveryMasks/TOP.tga", "media/cars/C/damage_LOD0.xds",
                 "media/cars/C/damagelights.xds", "media/cars/C/BuildNumber.txt", "media/UI/Textures/Thumbnails/T.xds",
                 "media/db/patch/1_merge.slt", "media/cars/C/C.carbin", "media/cars/C/C_lod0.carbin"]
        # Files before folders at each level, names compared in upper case, as Turn 10's packager wrote them.
        self.assertEqual(sorted(names, key=package.member_order),
                         ["media/cars/C/BuildNumber.txt", "media/cars/C/C.carbin", "media/cars/C/C_lod0.carbin",
                          "media/cars/C/damagelights.xds", "media/cars/C/damage_LOD0.xds",
                          "media/cars/C/LiveryMasks/TOP.tga", "media/db/patch/1_merge.slt",
                          "media/UI/Textures/Thumbnails/T.xds", "media/wheels/W/wheel.xds"])


ui = load("inspect_fh1_ui_for_package", TOOLS / "inspect-fh1-ui.py")
ui_tests = load("test_inspect_fh1_ui_for_package", Path(__file__).with_name("test_inspect_fh1_ui.py"))
dlc = load("manage_fh1_dlc_for_package", TOOLS / "manage-fh1-dlc.py")


class HeaderTests(unittest.TestCase):
    def test_the_package_id_is_fixed_per_car_and_shaped_like_turn_10s(self):
        self.assertEqual(package.package_id(3001), package.package_id(3001))
        self.assertNotEqual(package.package_id(3001), package.package_id(3002))
        self.assertRegex(package.package_id(3001), r"\A[0-9A-F]{40}4D\Z")
        self.assertTrue(dlc.PACKAGE_ID.fullmatch(package.package_id(3007)))

    def test_the_header_has_the_sdk_layout_and_licenses_the_offer(self):
        name = "2012 Dodge Car Rockstar"
        header = package.content_header("ABCDEF4D", name)
        self.assertEqual(len(header), 332)
        self.assertEqual(header[:8], bytes.fromhex("0000000100000002"))       # device 1, Marketplace content
        self.assertEqual(header[8:8 + 2 * len(name)].decode("utf-16-be"), name)
        self.assertEqual(header[8 + 2 * len(name):0x108], bytes(0x100 - 2 * len(name)))
        self.assertEqual(header[0x108:0x140], b"ABCDEF4D" + bytes(0x30))
        self.assertEqual(header[0x140:0x148], bytes.fromhex("4D5309C900000000"))
        self.assertEqual(int.from_bytes(header[328:], "little"), 1)        # where the DLC manager reads the mask

    def test_a_long_name_or_a_bad_package_id_is_refused(self):
        with self.assertRaisesRegex(ValueError, "127 characters"):
            package.content_header("ABCDEF4D", "x" * 128)
        for bad in ("abc", "", "G" * 4, "A" * 43):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "package ID"):
                package.content_header(bad, "Car")


class ThumbnailTests(unittest.TestCase):
    def stock(self):
        payload = bytes((index * 7) & 0xFF for index in range(32 * 32 * 4))
        return ui_tests.make_xds(32, 8, 6, 2, payload, swizzle="ZYXW")     # k_8_8_8_8, tiled, as the thumbnails

    def test_without_art_the_stock_thumbnail_is_kept(self):
        self.assertEqual(package.thumbnail_xds(self.stock(), None), self.stock())

    def test_art_is_written_into_the_stock_textures_storage(self):
        art = (32, 8, bytes((x * 8, y * 32, 99, 255)[c] for y in range(8) for x in range(32) for c in range(4)))
        out = package.thumbnail_xds(self.stock(), art)
        self.assertEqual(ui.decode_xds(out)[1], art[2])
        self.assertEqual(out[:ui.XDS_HEADER_SIZE], self.stock()[:ui.XDS_HEADER_SIZE])

    def test_art_of_another_size_is_refused(self):
        with self.assertRaisesRegex(ValueError, "32 x 8"):
            package.thumbnail_xds(self.stock(), (16, 8, bytes(16 * 8 * 4)))

    def test_the_stock_thumbnail_comes_from_the_discs_ui_textures(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            game = Path(directory) / "game"
            clone_tests.write_zip(game / "media/ui/Textures.zip", {"Thumbnails/Thumbnail_1557.xds": b"thumb",
                                                                   "Thumbnails/Thumbnail_1600.xds": b"other"})
            sources = clone.Sources(Path(directory) / "state", game, Path("extractor.exe"))
            self.assertEqual(package.stock_thumbnail(sources, 1557), b"thumb")
            with self.assertRaisesRegex(ValueError, "no thumbnail for car 1548"):
                package.stock_thumbnail(sources, 1548)


paint_tool = load("paint_fh1_livery_for_package", TOOLS / "paint-fh1-livery.py")
paint_tests = load("test_paint_fh1_livery_for_package", Path(__file__).with_name("test_paint_fh1_livery.py"))
STOCK_THUMBNAIL = ui_tests.make_xds(32, 8, 6, 2, bytes(range(256)) * 16, swizzle="ZYXW")
MAKE = (0x3323 << 16) | 5


class PackageSetup:
    """car-clone's player files (stock car 1557 on the disc, an installed package with a complete
    English table) with body textures, a thumbnail, a make name and a recipe for car 3001."""

    def __init__(self, root: Path):
        import json
        self.root = root
        self.files = clone_tests.CloneSetup(root)
        db = game_database()
        db.executescript(f"""ALTER TABLE Data_Car ADD COLUMN Year INTEGER; ALTER TABLE Data_Car ADD COLUMN MakeName TEXT;
                             UPDATE Data_Car SET Year = 2012, MakeName = '_&{MAKE}' WHERE Id = 1557;""")
        db.commit()
        clone_tests.write_zip(self.files.state / "title-update-v4/media.zip", {"db/gamedb.slt": db.serialize()})
        db.close()
        english = [(6002, "Taken"), (23100, "Challenger '12"), (24056, "Challenger")]
        clone_tests.write_zip(self.files.state / clone_tests.TITLE / "00000002/PKG/Media/DLCZips/StringTables_pri_2950.zip",
                              {"EN/Data_Car.str": clone_tests.string_table(english)})
        clone_tests.write_zip(self.files.game / "media/cars/DOD_Car_12.zip", {
            "DOD_Car_12.carbin": b"stock model", "damage.xds": b"scratches",
            "nodamage.xds": paint_tests.body_texture(16), "nodamage_LOD0.xds": paint_tests.body_texture(32)})
        clone_tests.write_zip(self.files.game / "media/StringTables/EN.zip", {
            "Data_Car.str": clone_tests.string_table(english[1:]), "List_CarMake.str": clone_tests.string_table([(5, "Dodge")])})
        clone_tests.write_zip(self.files.game / "media/ui/Textures.zip", {"Thumbnails/Thumbnail_1557.xds": STOCK_THUMBNAIL})
        self.panels = root / "panels"
        self.panels.mkdir()
        (self.panels / "DOD_Car_12.json").write_text(json.dumps(paint_tests.table(paint_tests.PANELS)), encoding="utf-8")
        self.recipe_path = root / "test-livery.json"
        self.recipe_path.write_text(json.dumps({
            "schema_version": 1, "car": {**CAR, "display_name": "Car Rockstar"}, "paint": {"rgb": "8C0001"},
            "layers": [{"fill": "8C0001", "panels": "all"}, {"band": "F2D500", "panel": "left", "u": [0, 1], "v": [0.4, 0.6]}]}))
        self.output = root / "out" / "package"

    def recipe(self):
        return paint_tool.load_recipe(self.recipe_path, art_dir=self.root / "art", panel_tables=self.panels,
                                      id_table=self.files.ids)

    def sources(self):
        return clone.Sources(self.files.state, self.files.game, Path("extractor.exe"))

    def build(self, output=None, **options):
        return package.build_package(self.recipe(), self.sources(), output or self.output, id_table=self.files.ids,
                                     **options)


class BuildPackageTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.setup = PackageSetup(Path(self.temporary.name))

    def tree(self, root):
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}

    def members(self, name):
        return dict(read_zip(self.tree(self.setup.output)[name]))

    def test_the_package_has_the_layout_of_turn_10s_livery_cars(self):
        report, header = self.setup.build()
        tree = self.tree(self.setup.output)
        self.assertEqual(sorted(tree), ["Media/3001.puboffer", "Media/DLCZips/3001_pri_65.zip",
                                        "Media/DLCZips/StringTables_pri_3001.zip", "Media/DLCZips/stringtables.xml",
                                        "Media/DLCZips/zipmount.xml"])
        self.assertEqual(tree["Media/3001.puboffer"], b" \r\n")
        self.assertEqual([name for name, _ in read_zip(tree["Media/DLCZips/3001_pri_65.zip"])], [
            "media/audio/cars/CarModelTuning/DOD_Car_RSE_12_CMT.xml",
            "media/audio/cars/Engines/EngineTuning/DOD_Car_RSE_12_ET.xml",
            "media/cars/DOD_Car_RSE_12/damage.xds", "media/cars/DOD_Car_RSE_12/DOD_Car_RSE_12.carbin",
            "media/cars/DOD_Car_RSE_12/nodamage.xds", "media/cars/DOD_Car_RSE_12/nodamage_LOD0.xds",
            "media/db/patch/3001000_merge.slt", "media/UI/Textures/Thumbnails/Thumbnail_3001.xds"])
        self.assertEqual(header, package.content_header(package.package_id(3001), "2012 Dodge Car Rockstar"))
        self.assertEqual(report["package_id"], package.package_id(3001))
        self.assertEqual(report["header_name"], "2012 Dodge Car Rockstar")
        self.assertEqual(report["header_sha256"], __import__("hashlib").sha256(header).hexdigest().upper())
        self.assertEqual({entry["path"] for entry in report["files"]}, set(tree))

    def test_the_car_is_painted_offered_and_named(self):
        report, _ = self.setup.build()
        car = self.members("Media/DLCZips/3001_pri_65.zip")
        self.assertNotEqual(car["media/cars/DOD_Car_RSE_12/nodamage.xds"], paint_tests.body_texture(16))
        self.assertEqual(car["media/UI/Textures/Thumbnails/Thumbnail_3001.xds"], STOCK_THUMBNAIL)
        merge = car["media/db/patch/3001000_merge.slt"]
        self.assertEqual(rows_of(merge, "SELECT RGB FROM Combo_Colors"), [(0x8C0001,)])
        self.assertEqual(rows_of(merge, "SELECT ContentId FROM ContentOffersMapping"), [(3001,)])
        self.assertEqual(report["offer"]["offer_id"], "4D5309C950530BB9")
        names = dict(strings.parse(self.members("Media/DLCZips/StringTables_pri_3001.zip")["EN/Data_Car.str"]))
        self.assertEqual(names, {6002: "Taken", 6003: "Car Rockstar", 6004: "Challenger '12", 23100: "Challenger '12",
                                 24056: "Challenger"})
        self.assertEqual(report["strings"], {"EN": "PKG/StringTables_pri_2950.zip"})
        self.assertEqual(report["string_keys"], [{"field": "DisplayName", "key": 6003, "text": "Car Rockstar"},
                                                 {"field": "ModelShort", "key": 6004, "same_as": 23100}])

    def test_other_livery_cars_names_join_the_tables(self):
        self.setup.build(others=[{"key": 6100, "text": "Other livery car"}])
        names = dict(strings.parse(self.members("Media/DLCZips/StringTables_pri_3001.zip")["EN/Data_Car.str"]))
        self.assertEqual(names[6100], "Other livery car")

    def test_a_recipe_thumbnail_replaces_the_stock_one(self):
        import dataclasses
        art = (32, 8, bytes(range(256)) * 4)
        recipe = dataclasses.replace(self.setup.recipe(), thumbnail=art)
        package.build_package(recipe, self.setup.sources(), self.setup.output, id_table=self.setup.files.ids)
        thumbnail = self.members("Media/DLCZips/3001_pri_65.zip")["media/UI/Textures/Thumbnails/Thumbnail_3001.xds"]
        self.assertEqual(ui.decode_xds(thumbnail)[1], art[2])

    def test_equal_inputs_give_equal_packages(self):
        first, header = self.setup.build()
        second, again = self.setup.build(self.setup.output.with_name("again"))
        self.assertEqual(self.tree(self.setup.output), self.tree(self.setup.output.with_name("again")))
        self.assertEqual(header, again)

    def test_the_build_changes_no_source_file(self):
        before = self.setup.files.hashes()
        self.setup.build()
        self.assertEqual(self.setup.files.hashes(), before)

    def test_an_existing_output_or_a_failed_build_leaves_nothing_behind(self):
        self.setup.output.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.setup.build()
        self.setup.output.rmdir()
        (self.setup.files.game / "media/ui/Textures.zip").unlink()
        with self.assertRaisesRegex(ValueError, "no thumbnail for car 1557"):
            self.setup.build()
        self.assertEqual(list(self.setup.output.parent.iterdir()), [])

    def test_the_build_command_writes_the_tree_and_its_header(self):
        import io
        import json
        from contextlib import redirect_stderr, redirect_stdout
        out, err, folder = io.StringIO(), io.StringIO(), self.setup.root / "built"
        args = ["build", "--recipe", self.setup.recipe_path, "--state-root", self.setup.files.state,
                "--game-root", self.setup.files.game, "--output", folder, "--art", self.setup.root / "art",
                "--panels", self.setup.panels, "--ids", self.setup.files.ids, "--extractor", self.setup.root / "x.exe"]
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(package.main([str(arg) for arg in args]), 0, err.getvalue())
        pid = package.package_id(3001)
        self.assertEqual(json.loads(out.getvalue())["package_id"], pid)
        self.assertTrue((folder / pid / "Media/3001.puboffer").is_file())
        self.assertEqual(len((folder / f"{pid}.header").read_bytes()), 332)
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            self.assertEqual(package.main([str(arg) for arg in args]), 1)
        self.assertIn("already exists", err.getvalue())


class CommittedTestRecipeTests(unittest.TestCase):
    def test_the_in_game_test_recipes_load_without_art(self):
        recipes = sorted((TOOLS.parent / "config/livery-cars/tests").glob("*.json"))
        self.assertEqual([path.name for path in recipes], ["challenger-test.json", "fiesta-orientation.json"])
        for path in recipes:
            with self.subTest(recipe=path.name):
                recipe = paint_tool.load_recipe(path)
                self.assertEqual(recipe.art, {})
                self.assertIsNone(recipe.thumbnail)
                self.assertEqual(set(recipe.panels), {"left", "right", "top", "front", "rear"})


if __name__ == "__main__":
    unittest.main()
