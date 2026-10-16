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


if __name__ == "__main__":
    unittest.main()
