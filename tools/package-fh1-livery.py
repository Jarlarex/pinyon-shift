#!/usr/bin/env python3
"""Package a livery car as an FH1 DLC package, from a recipe and the player's own files.

The package has the shape of Turn 10's own livery cars (the Shelby GT500
Rockstar Energy, the Pizza Hut Mustang): an offer file, one archive holding the
car's model tree, audio tuning, merge database and thumbnail, the complete
Data_Car string tables, and a content header whose licence owns the car's offer.
car-clone copies the stock car, livery-paint paints it, and this tool adds what
a DLC car needs. tools/manage-fh1-dlc.py installs the result beside the
player's owned DLC.
"""
import sqlite3
from pathlib import Path

TITLE_ID = 0x4D5309C9
# Offers of the livery cars: the title's ID in the high half, "PS" and the car ID in the low half.
OFFER_BASE = TITLE_ID << 32 | 0x50530000
LICENSE_MASK = 1
MARKETPLACE_IMAGE = "GAME:\\Media\\UI\\Textures\\UI4\\Marketplace\\Day1_{}.tga"   # on every disc


def _load_tool(name: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# -- rows -------------------------------------------------------------------

def offer_id(car_id: int) -> int:
    return OFFER_BASE + car_id


def mapping_id(car_id: int) -> int:
    return 10 * car_id


def _columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in con.execute(f"PRAGMA table_info([{table}])")]


def _count(con: sqlite3.Connection, table: str) -> int:
    return con.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]


def package_rows(merge: bytes, game_db: sqlite3.Connection, car: dict, paint: tuple[int, int, int]) -> tuple[bytes, dict]:
    """The package's merge database from a clone's: the recipe's price (null keeps the stock
    car's), never a Unicorn car, one paint option in the recipe's colour under the livery (the
    clone's stripe and colour variants would replace it), and the hidden offer whose licence owns
    the car, as Turn 10's livery cars have. `game_db` (the merged game database) is only read,
    for its schemas and to check every new ID is unused."""
    car_id = car["new_id"]
    offer = offer_id(car_id)
    for sql, values, message in (
            ("SELECT 1 FROM ContentOffers WHERE PubOfferingID=?", (car_id,), f"offering {car_id} is already used"),
            ("SELECT 1 FROM ContentOffers WHERE OfferId=?", (offer,), f"offer {offer:016X} is already used"),
            ("SELECT 1 FROM ContentOffersMapping WHERE Id=?", (mapping_id(car_id),),
             f"offer mapping {mapping_id(car_id)} is already used"),
            ("SELECT 1 FROM ContentOffersMapping WHERE ContentId=? AND ContentType=1", (car_id,),
             f"car {car_id} already has an offer")):
        if game_db.execute(sql, values).fetchone():
            raise ValueError(message)
    schema = dict(game_db.execute("SELECT name, sql FROM sqlite_master WHERE type='table'"))

    con = sqlite3.connect(":memory:")
    try:
        con.deserialize(merge)
        row = con.execute("SELECT DisplayName, BaseCost FROM Data_Car WHERE Id=?", (car_id,)).fetchone()
        if row is None:
            raise ValueError(f"the clone has no Data_Car row for car {car_id}")
        display, price = row
        if car.get("price") is not None:
            price = car["price"]
            con.execute("UPDATE Data_Car SET BaseCost=? WHERE Id=?", (price, car_id))
        if "IsUnicorn" in _columns(con, "Data_Car"):
            con.execute("UPDATE Data_Car SET IsUnicorn=0 WHERE Id=?", (car_id,))

        tables = {name for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        dropped = {}
        if "Combo_Colors" in tables:
            first = con.execute("SELECT ID FROM Combo_Colors WHERE Ordinal=? ORDER BY Sequence, ID LIMIT 1",
                                (car_id,)).fetchone()
            if first is None:
                raise ValueError(f"the clone has no paint option for car {car_id}")
            dropped["Combo_Colors"] = con.execute("DELETE FROM Combo_Colors WHERE ID<>?", first).rowcount
            red, green, blue = paint
            settings = {"Sequence": 1, "RGB": red << 16 | green << 8 | blue, "BaseTexture": "nodamage.tga",
                        "DamageTexture": "damage.tga"}
            settings = {column: value for column, value in settings.items() if column in _columns(con, "Combo_Colors")}
            con.execute(f"UPDATE Combo_Colors SET {', '.join(f'[{c}]=?' for c in settings)} WHERE ID=?",
                        (*settings.values(), first[0]))
        for table in ("Combo_Colors_Exceptions", "StripeColors"):
            if table in tables:
                dropped[table] = _count(con, table)
                con.execute(f"DROP TABLE [{table}]")

        con.execute(schema["ContentOffers"])
        con.execute(schema["ContentOffersMapping"])
        offer_row = {"ID": f"{offer:016X}", "OfferId": offer, "DisplayName": display, "Description": display,
                     "PubOfferingID": car_id, "LicenseLevel": 2, "LicenseMask": LICENSE_MASK, "IsDLC": 1,
                     "ImagePath": MARKETPLACE_IMAGE.format("LG"), "ThumbPath": MARKETPLACE_IMAGE.format("SM"),
                     "IsInstalled": 0, "IsPurchased": 0, "IsVIP": 0, "Hidden": 1, "IsALaCarte": 0,
                     "SeasonPassOffer": 0}
        con.execute(f"INSERT INTO ContentOffers ({','.join(f'[{c}]' for c in offer_row)}) "
                    f"VALUES ({','.join('?' * len(offer_row))})", tuple(offer_row.values()))
        con.execute("INSERT INTO ContentOffersMapping (Id, OfferId, ContentId, ContentType) VALUES (?, ?, ?, 1)",
                    (mapping_id(car_id), offer, car_id))
        con.commit()
        con.execute("VACUUM")   # drop the deleted rows' pages, so equal inputs give equal bytes
        database = con.serialize()
    finally:
        con.close()
    return database, {"price": price, "paint": "%02X%02X%02X" % paint, "dropped": dropped,
                      "offer": {"offer_id": f"{offer:016X}", "pub_offering_id": car_id,
                                "license_mask": LICENSE_MASK, "mapping_id": mapping_id(car_id)}}
