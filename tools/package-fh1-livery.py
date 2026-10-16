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
import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID_TABLE = ROOT / "config/livery-cars/ids.json"
PANEL_TABLES = ROOT / "config/livery-cars/panels"
TITLE_ID = 0x4D5309C9
# Offers of the livery cars: the title's ID in the high half, "PS" and the car ID in the low half.
OFFER_BASE = TITLE_ID << 32 | 0x50530000
LICENSE_MASK = 1
MARKETPLACE_IMAGE = "GAME:\\Media\\UI\\Textures\\UI4\\Marketplace\\Day1_{}.tga"   # on every disc
PUBOFFER = b" \r\n"   # Media/<PubOfferingID>.puboffer: the title takes the offer from its name


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


# -- string tables ----------------------------------------------------------

def member_order(name: str) -> list[tuple[int, str]]:
    """Sort key giving Turn 10's archive order: at each folder level its files come before its
    subfolders, and names compare in upper case (damagelights.xds before damage_LOD0.xds)."""
    parts = name.split("/")
    return [(1, part.upper()) for part in parts[:-1]] + [(0, parts[-1].upper())]


def livery_tables(tables: dict[str, tuple[int, str, bytes]], entries: list[dict]) -> dict[str, bytes]:
    """Each language's Data_Car table (from Sources.string_tables, the livery packages left out)
    with every enabled livery car's names added. The title uses only the highest-priority copy of
    each table, so every livery package carries the whole table. `entries` are car-clone's string
    entries: {"key", "text"}, or {"key", "same_as"} for a key holding another key's text in each
    language (the stock car's short name), the English text where a language lacks it."""
    strings = _load_tool("fh1-strings")
    english = next((data for lang, (_, _, data) in tables.items() if lang.upper() == "EN"), None)
    fallback = dict(strings.parse(english)) if english else {}
    out = {}
    for lang, (_, _, data) in tables.items():
        base, texts = dict(strings.parse(data)), {}
        for entry in entries:
            if "text" in entry:
                texts[entry["key"]] = entry["text"]
                continue
            text = base.get(entry["same_as"], fallback.get(entry["same_as"]))
            if text is None:
                raise ValueError(f"no Data_Car table holds string {entry['same_as']}, the text of key {entry['key']}")
            texts[entry["key"]] = text
        out[lang] = strings.replace_strings(data, texts)
    return out


def string_files(tables: dict[str, bytes], car_id: int) -> dict[str, bytes]:
    """The files that ship the tables in Media/DLCZips, in the text format of Turn 10's packages:
    StringTables_pri_<car ID>.zip (above every Turn 10 priority), stringtables.xml and zipmount.xml."""
    archive = f"StringTables_pri_{car_id}.zip"
    members = sorted(((f"{lang}/Data_Car.str", data) for lang, data in tables.items()),
                     key=lambda member: member_order(member[0]))
    return {archive: _load_tool("patch-fh1-archive").write_archive(members),
            "stringtables.xml": b'<?xml version="1.0" ?> \r\n<stringtables> \r\n   <table Name="Data_Car" /> \r\n'
                                b'</stringtables> \r\n',
            "zipmount.xml": f'<?xml version="1.0" ?> \r\n<zipmount> \r\n   <zip Name="{archive}" '
                            f'Mount="game:\\Media\\StringTables\\"  /> \r\n</zipmount> \r\n'.encode("ascii")}


# -- thumbnail and header ---------------------------------------------------

def _find(folder: Path, *parts: str) -> Path | None:
    """A path below `folder`, matching each part in any case (the disc has media/ui/Textures.zip)."""
    for part in parts:
        if not folder.is_dir():
            return None
        folder = next((child for child in sorted(folder.iterdir()) if child.name.lower() == part.lower()), None)
        if folder is None:
            return None
    return folder


def stock_thumbnail(sources, stock_id: int) -> bytes:
    """The stock car's Autoshow thumbnail from the disc's media/ui/Textures.zip."""
    import zipfile

    name = f"thumbnails/thumbnail_{stock_id}.xds"
    archive = _find(sources.game_root, "media", "ui", "textures.zip")
    if archive is not None:
        with zipfile.ZipFile(archive) as zipped:
            info = next((info for info in zipped.infolist() if info.filename.replace("\\", "/").lower() == name), None)
        if info is not None:
            return sources.member(archive, info)
    raise ValueError(f"the disc has no thumbnail for car {stock_id} (Thumbnails/Thumbnail_{stock_id}.xds "
                     "in media/ui/Textures.zip)")


def thumbnail_xds(stock: bytes, art: tuple[int, int, bytes] | None) -> bytes:
    """The livery car's thumbnail: the stock car's, or the recipe's art written into its storage
    (an uncompressed 8888 texture, so only the texels change)."""
    if art is None:
        return stock
    ui = _load_tool("inspect-fh1-ui")
    header = ui.parse_xds(stock)
    if art[:2] != (header["width"], header["height"]):
        raise ValueError(f"the thumbnail art must be {header['width']} x {header['height']}, the stock thumbnail's size")
    return ui.reencode_xds(stock, art[2])


def garage_thumbnail(xdc: bytes) -> bytes:
    """The garage thumbnail the title renders when a car is bought (the profile's
    Thumbnails/Thumbnail_<n>.xdc), as the 768 x 288 RGBA PNG a recipe names as its
    "thumbnail". The file is a cxds container: magic, version 2, the unpacked size, then
    chunks of (packed size, unpacked size, raw deflate); unpacked, it is exactly an
    Autoshow thumbnail, header included, showing the car with its livery."""
    import struct
    import zlib

    if len(xdc) < 12 or xdc[:4] != b"cxds":
        raise ValueError("not a garage thumbnail: no cxds header")
    version, total = struct.unpack_from(">II", xdc, 4)
    if version != 2:
        raise ValueError(f"garage thumbnail cxds version {version} is not 2")
    at, texture = 12, bytearray()
    while len(texture) < total:
        if at + 8 > len(xdc):
            raise ValueError("the garage thumbnail is truncated")
        packed, unpacked = struct.unpack_from(">II", xdc, at)
        at += 8
        if at + packed > len(xdc):
            raise ValueError("the garage thumbnail is truncated")
        try:
            chunk = zlib.decompress(xdc[at:at + packed], -15)
        except zlib.error:
            raise ValueError("the garage thumbnail's data is damaged") from None
        if len(chunk) != unpacked:
            raise ValueError("the garage thumbnail's chunk sizes do not match")
        texture += chunk
        at += packed
    if len(texture) != total or at != len(xdc):
        raise ValueError("the garage thumbnail's sizes do not match")
    ui = _load_tool("inspect-fh1-ui")
    try:
        header = ui.parse_xds(bytes(texture))
    except ValueError:
        raise ValueError("the garage thumbnail is not an Autoshow thumbnail") from None
    if (header["format"], header["width"], header["height"], header["tiled"]) != ("k_8_8_8_8", 768, 288, True):
        raise ValueError("the garage thumbnail is not an Autoshow thumbnail (768 x 288 k_8_8_8_8)")
    _, rgba = ui.decode_xds(bytes(texture))
    return _load_tool("fh1_xds").encode_png(768, 288, rgba)


def package_id(car_id: int) -> str:
    """The livery car's package ID, the same on every build: 40 hex digits and 4D, the shape of Turn 10's."""
    import hashlib

    return hashlib.sha1(f"pinyon-shift/livery-car/{car_id}".encode()).hexdigest().upper() + "4D"


def content_header(package: str, display_name: str, mask: int = LICENSE_MASK) -> bytes:
    """The 332-byte content header the SDK keeps beside an installed package: device 1 and content
    type 2 (Marketplace), the display name (UTF-16BE, 128 characters with the terminator), the
    package ID, the title, and at byte 328 the licence mask (little-endian) the title ORs into the
    package's offer."""
    import re

    if not re.fullmatch(r"[0-9A-F]{1,42}", package):
        raise ValueError(f"package ID {package!r} must be 1 to 42 upper-case hex digits")
    if len(display_name) > 127:
        raise ValueError("a package's display name holds at most 127 characters")
    header = bytearray(332)
    header[0:8] = (1).to_bytes(4, "big") + (2).to_bytes(4, "big")
    name = display_name.encode("utf-16-be")
    header[8:8 + len(name)] = name
    header[0x108:0x108 + len(package)] = package.encode("ascii")
    header[0x140:0x144] = TITLE_ID.to_bytes(4, "big")
    header[328:332] = mask.to_bytes(4, "little")
    return bytes(header)


# -- package ----------------------------------------------------------------

def livery_package_ids(id_table: Path = ID_TABLE) -> set[str]:
    """The package IDs of every reserved livery car, whose string tables are rebuilt, never read."""
    return {package_id(entry["id"]) for entry in json.loads(Path(id_table).read_text(encoding="utf-8"))["cars"]}


def header_name(sources, db: sqlite3.Connection, stock_id: int, display: str) -> str:
    """The package's display name, as Turn 10's read ("2013 Ford Shelby GT500 - Rockstar Energy"):
    the stock car's year and English make before the livery car's name."""
    row = db.execute("SELECT * FROM Data_Car WHERE Id=?", (stock_id,)).fetchone()
    values = dict(zip(_columns(db, "Data_Car"), row or ()))
    make, reference = None, values.get("MakeName")
    if isinstance(reference, str) and reference.startswith("_&") and reference[2:].isdigit():
        tables = sources.string_tables("list_carmake.str")
        english = next((data for lang, (_, _, data) in tables.items() if lang.upper() == "EN"), None)
        if english:
            make = dict(_load_tool("fh1-strings").parse(english)).get(int(reference[2:]) & 0xFFFF)
    return " ".join(str(part) for part in (values.get("Year"), make, display) if part)[:127]


def build_package(recipe, sources, output: Path, *, id_table: Path = ID_TABLE, others=()) -> tuple[dict, bytes]:
    """Build a livery car's package into `output` (the folder installed as 00000002/<package ID>)
    and return its report and content header. The stock car is cloned (car-clone), painted
    (livery-paint), given its package rows and thumbnail, and named in complete Data_Car tables
    that also hold `others`, the string entries of the other enabled livery cars. `sources` is
    only read; an existing output is refused, and a failed build leaves no output."""
    started = time.perf_counter()
    output = Path(output)
    if output.exists():
        raise ValueError(f"{output} already exists; choose a new output folder")
    car, car_id = recipe.car, recipe.car["new_id"]
    archive_tool = _load_tool("patch-fh1-archive")
    output.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        staged = work / "clone"
        cloned = _load_tool("clone-fh1-car").clone_car(sources, car["stock_id"], car_id, car["media_name"],
                                                       car["display_name"], staged, table=id_table)
        painted = _load_tool("paint-fh1-livery").paint_livery(recipe, staged)
        merge = staged / cloned["merge_database"]
        db = sources.database()
        try:
            database, rows = package_rows(merge.read_bytes(), db, car, recipe.paint)
            name = header_name(sources, db, car["stock_id"], car["display_name"])
        finally:
            db.close()
        merge.write_bytes(database)
        thumbnail = staged / f"media/UI/Textures/Thumbnails/Thumbnail_{car_id}.xds"
        thumbnail.parent.mkdir(parents=True, exist_ok=True)
        thumbnail.write_bytes(thumbnail_xds(stock_thumbnail(sources, car["stock_id"]), recipe.thumbnail))

        members = sorted(((path.relative_to(staged).as_posix(), path.read_bytes())
                          for path in staged.rglob("*") if path.is_file()), key=lambda member: member_order(member[0]))
        tables = sources.string_tables("data_car.str", skip=livery_package_ids(id_table))
        names = livery_tables(tables, cloned["strings"] + list(others))
        files = {f"Media/{car_id}.puboffer": PUBOFFER,
                 f"Media/DLCZips/{car_id}_pri_65.zip": archive_tool.write_archive(members)}
        files |= {f"Media/DLCZips/{file}": data for file, data in string_files(names, car_id).items()}
        package = work / "package"
        for path, data in files.items():
            (package / path).parent.mkdir(parents=True, exist_ok=True)
            (package / path).write_bytes(data)
        package.rename(output)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    header = content_header(package_id(car_id), name)
    return {
        "package_id": package_id(car_id), "header_name": name,
        "header_sha256": hashlib.sha256(header).hexdigest().upper(), "license_mask": f"{LICENSE_MASK:08X}",
        "car": car, "offer": rows["offer"], "price": rows["price"], "paint": rows["paint"], "dropped": rows["dropped"],
        "string_keys": cloned["strings"], "strings": {lang: label for lang, (_, label, _) in sorted(tables.items())},
        "thumbnail": "recipe" if recipe.thumbnail else "stock",
        "files": [{"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest().upper()}
                  for path, data in sorted(files.items())],
        "clone": cloned, "painted": painted, "seconds": round(time.perf_counter() - started, 1),
    }, header


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="build a livery car's package and header into a folder, for inspection")
    build.add_argument("--recipe", type=Path, required=True)
    build.add_argument("--state-root", type=Path, required=True, help="the installed preview state (.local/preview)")
    build.add_argument("--game-root", type=Path, required=True, help="the extracted disc (.local/game/eur-base)")
    build.add_argument("--output", type=Path, required=True,
                       help="a folder receiving <package ID>/ and <package ID>.header")
    build.add_argument("--art", type=Path, help="the recipe's art folder (default: .local/livery-art/<recipe name>)")
    build.add_argument("--extractor", type=Path, help="archive extractor (default: the one the build made)")
    build.add_argument("--panels", type=Path, default=PANEL_TABLES, help=argparse.SUPPRESS)
    build.add_argument("--ids", type=Path, default=ID_TABLE, help=argparse.SUPPRESS)
    thumbnail = commands.add_parser("thumbnail", help="the garage thumbnail of a bought car as a recipe's thumbnail art")
    thumbnail.add_argument("--xdc", type=Path, required=True,
                           help="the profile's ForzaProfile/Thumbnails/Thumbnail_<n>.xdc, from a private run's state")
    thumbnail.add_argument("--output", type=Path, required=True, help="the PNG to write, e.g. .local/livery-art/<recipe>/thumbnail.png")
    args = parser.parse_args(argv)
    if args.command == "thumbnail":
        try:
            if args.output.exists():
                raise ValueError(f"{args.output} already exists; choose a new file")
            png = garage_thumbnail(args.xdc.read_bytes())
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(png)
        except (OSError, ValueError) as error:
            print(str(error), file=sys.stderr)
            return 1
        print(json.dumps({"output": str(args.output), "size": "768x288",
                          "sha256": hashlib.sha256(png).hexdigest().upper()}))
        return 0
    try:
        recipe = _load_tool("paint-fh1-livery").load_recipe(args.recipe, art_dir=args.art, panel_tables=args.panels,
                                                            id_table=args.ids)
        extractor = args.extractor or _load_tool("manage-fh1-dlc").default_extractor()
        identifier = package_id(recipe.car["new_id"])
        # A build never sees its own installed package, so an installed car can be built again.
        sources = _load_tool("clone-fh1-car").Sources(args.state_root.absolute(), args.game_root.absolute(),
                                                      extractor.resolve(), exclude={identifier})
        header_path = args.output / f"{identifier}.header"
        if header_path.exists():
            raise ValueError(f"{header_path} already exists; choose a new output folder")
        report, header = build_package(recipe, sources, args.output / identifier, id_table=args.ids)
        header_path.write_bytes(header)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
