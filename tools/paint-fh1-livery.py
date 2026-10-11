#!/usr/bin/env python3
"""Paint a recreated livery into a cloned FH1 car's body textures.

Turn 10's livery cars (the Pizza Hut Mustang, the Shelby GT500 Rockstar
Energy) carry their livery in the colour of the paint area, the texels whose
alpha is 0, of nodamage.xds and nodamage_LOD0.xds; alpha and the damage
textures stay stock. A recipe (config/livery-cars/<name>.json) places layers
on named body panels, whose outlines and frames per stock car live in
config/livery-cars/panels/<StockMedia>.json as numbers only. Art comes from
.local/livery-art/<name>/ and is never committed.

Coordinates are normalised texture coordinates (x right, y down, 0..1), so
one panel table serves the 1024 and 2048 textures. A panel's frame holds its
front-top, rear-top and front-bottom corners; panel coordinates run u = 0 at
the car's front to 1 at its rear, and v = 0 at the panel's top to 1 at its
bottom (for the top panel, "top" is the car's left; for the front and rear,
u runs from the car's left to its right).
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
PANEL_TABLES = ROOT / "config/livery-cars/panels"
ID_TABLE = ROOT / "config/livery-cars/ids.json"
ART_ROOT = ROOT / ".local/livery-art"
PANEL_NAME = re.compile(r"[a-z][a-z0-9_]*")
MEDIA_NAME = re.compile(r"[A-Za-z0-9_]+")
ART_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.png", re.IGNORECASE)


def _load_tool(name: str):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


xds = _load_tool("fh1_xds")


# -- geometry ---------------------------------------------------------------

class Frame(NamedTuple):
    """The affine map from panel (u, v) to normalised texture (x, y)."""
    origin: tuple[float, float]   # front-top corner
    u: tuple[float, float]        # front-top -> rear-top
    v: tuple[float, float]        # front-top -> front-bottom

    @classmethod
    def from_points(cls, points) -> "Frame":
        (x0, y0), (x1, y1), (x2, y2) = points
        frame = cls((x0, y0), (x1 - x0, y1 - y0), (x2 - x0, y2 - y0))
        if abs(frame.determinant) < 1e-9:
            raise ValueError("the frame's three points lie on a line")
        return frame

    @property
    def determinant(self) -> float:
        return self.u[0] * self.v[1] - self.u[1] * self.v[0]

    @property
    def mirrored(self) -> bool:
        """True when the panel is laid out reflected rather than only turned."""
        return self.determinant < 0

    def to_texture(self, u: float, v: float) -> tuple[float, float]:
        return (self.origin[0] + u * self.u[0] + v * self.v[0], self.origin[1] + u * self.u[1] + v * self.v[1])

    def to_panel(self, x: float, y: float) -> tuple[float, float]:
        dx, dy, det = x - self.origin[0], y - self.origin[1], self.determinant
        return ((dx * self.v[1] - dy * self.v[0]) / det, (self.u[0] * dy - self.u[1] * dx) / det)

    def size(self, width: int, height: int) -> tuple[float, float]:
        """The panel's length (front to rear) and height in texels of a width x height texture."""
        return (((self.u[0] * width) ** 2 + (self.u[1] * height) ** 2) ** 0.5,
                ((self.v[0] * width) ** 2 + (self.v[1] * height) ** 2) ** 0.5)


@dataclass(frozen=True)
class Panel:
    name: str
    outline: list[tuple[float, float]]
    frame: Frame


def polygon_mask(points, width: int, height: int) -> bytearray:
    """1 for each texel whose centre lies inside the polygon (even-odd rule), row by row."""
    mask = bytearray(width * height)
    edges = [(points[i], points[(i + 1) % len(points)]) for i in range(len(points))]
    for row in range(height):
        cy = (row + 0.5) / height
        crossings = sorted(x0 + (cy - y0) * (x1 - x0) / (y1 - y0)
                           for (x0, y0), (x1, y1) in edges if (y0 <= cy < y1) or (y1 <= cy < y0))
        for left, right in zip(crossings[::2], crossings[1::2]):
            # Texels whose centre (x + 0.5) / width lies in [left, right).
            first, end = max(0, math.ceil(left * width - 0.5)), min(width, math.ceil(right * width - 0.5))
            if end > first:
                mask[row * width + first:row * width + end] = b"\x01" * (end - first)
    return mask


# -- panel tables -----------------------------------------------------------

def _points(where: str, value, low: int, high: int) -> list[tuple[float, float]]:
    if not isinstance(value, list) or not low <= len(value) <= high:
        count = f"{low} to {high}" if low != high else str(low)
        raise ValueError(f"{where} needs {count} points")
    points = []
    for point in value:
        if (not isinstance(point, list) or len(point) != 2
                or not all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in point)):
            raise ValueError(f"{where}: each point is [x, y]")
        if not all(0 <= c <= 1 for c in point):
            raise ValueError(f"{where}: points must lie between 0 and 1, not {point}")
        points.append((float(point[0]), float(point[1])))
    return points


def load_panels(path: Path) -> dict[str, Panel]:
    """A stock car's panel table, validated: the file is named after the car's media name."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError(f"{path.name}: schema_version must be 1")
    if data.get("stock_media") != path.stem:
        raise ValueError(f"{path.name}: stock_media {data.get('stock_media')!r} does not match the file name")
    if not data.get("panels"):
        raise ValueError(f"{path.name}: the table has no panels")
    panels = {}
    for name, entry in data["panels"].items():
        if not PANEL_NAME.fullmatch(name):
            raise ValueError(f"{path.name}: panel name {name!r} must be lowercase letters, digits and underscores")
        where = f"{path.name}: panel {name}"
        outline = _points(f"{where}'s outline", entry.get("outline"), 3, 64)
        corners = _points(f"{where}'s frame", entry.get("frame"), 3, 3)
        try:
            frame = Frame.from_points(corners)
        except ValueError as error:
            raise ValueError(f"{where}: {error}") from None
        panels[name] = Panel(name, outline, frame)
    return panels


# -- recipes ----------------------------------------------------------------

LAYER_KEYS = {
    "fill": {"fill", "panels", "opacity", "opaque"},
    "band": {"band", "panel", "u", "v", "opacity", "opaque"},
    "image": {"image", "panel", "at", "width", "height", "rotate", "mirror", "opacity", "opaque"},
}


@dataclass(frozen=True)
class Recipe:
    name: str                 # the recipe file's stem, which also names its art folder
    car: dict                 # stock_id, new_id, stock_media, media_name, display_name, price
    paint: tuple[int, int, int]
    layers: list[dict]        # validated, with defaults filled in
    panels: dict[str, Panel]
    art: dict[str, tuple[int, int, bytes]]   # file name -> width, height, RGBA


def _colour(value, where: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9A-Fa-f]{6}", value):
        raise ValueError(f"{where}: {value!r} is not a colour (RRGGBB)")
    return tuple(bytes.fromhex(value))


def _number(value, where: str, low: float, high: float, low_inclusive: bool = True) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not (
            (low <= value if low_inclusive else low < value) and value <= high):
        bound = f"{'from' if low_inclusive else 'above'} {low} to {high}"
        raise ValueError(f"{where} must be a number {bound}, not {value!r}")
    return float(value)


def _pair(value, where: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{where} must be a pair [a, b]")
    return _number(value[0], where, -1, 2), _number(value[1], where, -1, 2)


def _layer(index: int, entry: dict, panels: dict[str, Panel], art_dir: Path, art: dict) -> dict:
    where = f"layer {index + 1}"
    kinds = [kind for kind in LAYER_KEYS if kind in entry] if isinstance(entry, dict) else []
    if len(kinds) != 1:
        raise ValueError(f"{where}: each layer is one of fill, band or image")
    kind = kinds[0]
    unknown = sorted(set(entry) - LAYER_KEYS[kind])
    if unknown:
        raise ValueError(f"{where}: unknown setting {unknown[0]!r} for a {kind} layer")

    def panel(name) -> str:
        if name not in panels:
            raise ValueError(f"{where}: unknown panel {name!r} (the table has {', '.join(sorted(panels))})")
        return name

    layer = {"kind": kind, "opacity": _number(entry.get("opacity", 1), f"{where}: opacity", 0, 1),
             "opaque": bool(entry.get("opaque", False))}
    if kind == "fill":
        layer["colour"] = _colour(entry["fill"], f"{where}: fill")
        targets = entry.get("panels", "all")
        if targets == "all":
            if layer["opaque"]:
                raise ValueError(f"{where}: opaque cannot cover the whole paint area; name its panels")
            layer["panels"] = "all"
        elif isinstance(targets, list) and targets:
            layer["panels"] = [panel(name) for name in targets]
        else:
            raise ValueError(f"{where}: panels must be \"all\" or a list of panel names")
    elif kind == "band":
        layer |= {"colour": _colour(entry["band"], f"{where}: band"), "panel": panel(entry.get("panel")),
                  "u": _pair(entry.get("u"), f"{where}: u"), "v": _pair(entry.get("v"), f"{where}: v")}
    else:
        name = entry["image"]
        if not isinstance(name, str) or not ART_NAME.fullmatch(name):
            raise ValueError(f"{where}: art {name!r} must be a plain file name (letters, digits, '_', '-', '.') "
                             "ending in .png, inside the recipe's art folder")
        if name not in art:
            path = art_dir / name
            if not path.is_file():
                raise ValueError(f"{where}: art file {name} not found in {art_dir}")
            try:
                art[name] = xds.decode_png(path.read_bytes())
            except ValueError:
                raise ValueError(f"{where}: {name} must be an 8-bit RGBA, non-interlaced PNG") from None
        layer |= {"file": name, "panel": panel(entry.get("panel")), "at": _pair(entry.get("at"), f"{where}: at"),
                  "width": _number(entry.get("width"), f"{where}: width", 0, 4, low_inclusive=False),
                  "height": (_number(entry["height"], f"{where}: height", 0, 4, low_inclusive=False)
                             if "height" in entry else None),
                  "rotate": _number(entry.get("rotate", 0), f"{where}: rotate", -360, 360),
                  "mirror": bool(entry.get("mirror", False))}
    return layer


def load_recipe(path: Path, art_dir: Path | None = None, panel_tables: Path = PANEL_TABLES,
                id_table: Path = ID_TABLE) -> Recipe:
    """A livery recipe, validated against the committed car ID table and the stock car's panel table;
    its art (named, never embedded) comes from `art_dir`, by default .local/livery-art/<recipe name>/."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError(f"{path.name}: schema_version must be 1")
    car = data.get("car") or {}
    for key, kind in (("stock_id", int), ("new_id", int), ("stock_media", str), ("media_name", str),
                      ("display_name", str)):
        if not isinstance(car.get(key), kind) or isinstance(car.get(key), bool) or car.get(key) == "":
            raise ValueError(f"{path.name}: car.{key} is missing or not a {kind.__name__}")
    for key in ("stock_media", "media_name"):
        if not MEDIA_NAME.fullmatch(car[key]):
            raise ValueError(f"{path.name}: car.{key} must be letters, digits and underscores")
    if car.get("price") is not None and (not isinstance(car["price"], int) or car["price"] < 0):
        raise ValueError(f"{path.name}: car.price must be credits or null (the stock car's price)")
    reserved = {entry["id"]: entry for entry in json.loads(Path(id_table).read_text(encoding="utf-8"))["cars"]}
    entry = reserved.get(car["new_id"])
    if entry is None:
        raise ValueError(f"{path.name}: car ID {car['new_id']} is not reserved in {id_table}")
    if entry["stock_id"] != car["stock_id"]:
        raise ValueError(f"{path.name}: car ID {car['new_id']} is reserved for a clone of car "
                         f"{entry['stock_id']}, not {car['stock_id']}")
    table = Path(panel_tables) / f"{car['stock_media']}.json"
    if not table.is_file():
        raise ValueError(f"{path.name}: no panel table for {car['stock_media']} in {panel_tables}")
    panels = load_panels(table)
    paint = _colour((data.get("paint") or {}).get("rgb"), f"{path.name}: paint.rgb")
    art_dir = Path(art_dir) if art_dir is not None else ART_ROOT / path.stem
    art: dict = {}
    layers = data.get("layers")
    if not isinstance(layers, list):
        raise ValueError(f"{path.name}: layers must be a list")
    try:
        layers = [_layer(index, entry, panels, art_dir, art) for index, entry in enumerate(layers)]
    except ValueError as error:
        raise ValueError(f"{path.name}: {error}") from None
    return Recipe(path.stem, dict(car), paint, layers, panels, art)


# -- compositing ------------------------------------------------------------

_PAINT_AREA = bytes(1 if alpha < 128 else 0 for alpha in range(256))   # alpha -> 1 in the paint area


def _and(a: bytes, b: bytes) -> bytes:
    return (int.from_bytes(a, "little") & int.from_bytes(b, "little")).to_bytes(len(a), "little")


def _or(a: bytes, b: bytes) -> bytes:
    return (int.from_bytes(a, "little") | int.from_bytes(b, "little")).to_bytes(len(a), "little")


def _blend(colour: int, opacity: float) -> bytes:
    """A channel's table: what each value below becomes under `colour` at `opacity`."""
    return bytes(int(colour * opacity + below * (1 - opacity) + 0.5) for below in range(256))


def _fill(out: bytearray, mask: bytes, colour: tuple[int, int, int], opacity: float) -> None:
    tables = [_blend(c, opacity) for c in colour]
    for run in re.finditer(rb"\x01+", mask):
        start, end = run.span()
        for channel in range(3):
            segment = slice(4 * start + channel, 4 * end + channel, 4)
            out[segment] = out[segment].translate(tables[channel])


def _sample(width: int, height: int, rgba: bytes, x: float, y: float) -> tuple[float, float, float, float]:
    """Bilinear, edges clamped, on premultiplied colour; returns straight colour and alpha (0..255)."""
    fx, fy = x * width - 0.5, y * height - 0.5
    x0, y0 = math.floor(fx), math.floor(fy)
    wx, wy = fx - x0, fy - y0
    red = green = blue = alpha = 0.0
    for dy, weight_y in ((0, 1 - wy), (1, wy)):
        row = min(max(y0 + dy, 0), height - 1) * width
        for dx, weight_x in ((0, 1 - wx), (1, wx)):
            weight = weight_x * weight_y
            if weight:
                at = 4 * (row + min(max(x0 + dx, 0), width - 1))
                a = rgba[at + 3] * weight
                red, green, blue, alpha = (red + rgba[at] * a, green + rgba[at + 1] * a,
                                           blue + rgba[at + 2] * a, alpha + a)
    if not alpha:
        return 0.0, 0.0, 0.0, 0.0
    return red / alpha, green / alpha, blue / alpha, alpha


def _image(out: bytearray, mask: bytes, width: int, height: int, layer: dict, panel: Panel,
           art: tuple[int, int, bytes]) -> None:
    """An art layer placed in panel space (texels along the panel's length and height) so that it
    reads as drawn when seen from outside the car: on a panel whose frame is mirrored as seen from
    outside (the right side, the top and the front, where u runs right to left) the art is flipped
    and `rotate` (degrees clockwise as seen from outside) turns the other way in panel space.
    `mirror` flips the art as seen from outside."""
    art_width, art_height, pixels = art
    length, tall = panel.frame.size(width, height)
    image_width = layer["width"] * length
    image_height = layer["height"] * tall if layer["height"] is not None else image_width * art_height / art_width
    centre = (layer["at"][0] * length, layer["at"][1] * tall)
    flip = layer["mirror"] != panel.frame.mirrored
    angle = math.radians(-layer["rotate"] if panel.frame.mirrored else layer["rotate"])
    cos, sin = math.cos(angle), math.sin(angle)
    corners = []
    for sx, sy in ((-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)):
        px, py = sx * image_width, sy * image_height
        corners.append(panel.frame.to_texture((centre[0] + cos * px - sin * py) / length,
                                              (centre[1] + sin * px + cos * py) / tall))
    x_first = max(0, math.floor(min(x for x, _ in corners) * width))
    x_end = min(width, math.ceil(max(x for x, _ in corners) * width) + 1)
    y_first = max(0, math.floor(min(y for _, y in corners) * height))
    y_end = min(height, math.ceil(max(y for _, y in corners) * height) + 1)
    opacity = layer["opacity"]
    for ty in range(y_first, y_end):
        row = ty * width
        for tx in range(x_first, x_end):
            if not mask[row + tx]:
                continue
            u, v = panel.frame.to_panel((tx + 0.5) / width, (ty + 0.5) / height)
            dx, dy = u * length - centre[0], v * tall - centre[1]
            s = (cos * dx + sin * dy) / image_width + 0.5
            t = (cos * dy - sin * dx) / image_height + 0.5
            if not (0 <= s < 1 and 0 <= t < 1):
                continue
            red, green, blue, alpha = _sample(art_width, art_height, pixels, 1 - s if flip else s, t)
            a = alpha / 255 * opacity
            if a <= 0:
                continue
            at = 4 * (row + tx)
            out[at] = int(red * a + out[at] * (1 - a) + 0.5)
            out[at + 1] = int(green * a + out[at + 1] * (1 - a) + 0.5)
            out[at + 2] = int(blue * a + out[at + 2] * (1 - a) + 0.5)


def compose(stock: bytes, width: int, height: int, recipe: Recipe) -> bytes:
    """The recipe's layers painted, in order, over a stock texture's level 0 (RGBA). Each layer is
    clipped to its panels' outlines and to the paint area (stock alpha < 128) unless it is opaque;
    only colour changes, so the result keeps the stock alpha exactly."""
    if len(stock) != width * height * 4:
        raise ValueError(f"the stock image is not {width}x{height} RGBA")
    out = bytearray(stock)
    paint_area = stock[3::4].translate(_PAINT_AREA)
    outlines: dict[str, bytes] = {}

    def outline(name: str) -> bytes:
        if name not in outlines:
            outlines[name] = bytes(polygon_mask(recipe.panels[name].outline, width, height))
        return outlines[name]

    for layer in recipe.layers:
        if layer["kind"] == "fill" and layer["panels"] == "all":
            mask = paint_area
        else:
            names = layer["panels"] if layer["kind"] == "fill" else [layer["panel"]]
            mask = outline(names[0])
            for name in names[1:]:
                mask = _or(mask, outline(name))
            if not layer["opaque"]:
                mask = _and(mask, paint_area)
        if layer["kind"] == "fill":
            _fill(out, mask, layer["colour"], layer["opacity"])
        elif layer["kind"] == "band":
            frame = recipe.panels[layer["panel"]].frame
            (u0, u1), (v0, v1) = layer["u"], layer["v"]
            band = polygon_mask([frame.to_texture(u0, v0), frame.to_texture(u1, v0), frame.to_texture(u1, v1),
                                 frame.to_texture(u0, v1)], width, height)
            _fill(out, _and(mask, bytes(band)), layer["colour"], layer["opacity"])
        else:
            _image(out, mask, width, height, layer, recipe.panels[layer["panel"]], recipe.art[layer["file"]])
    return bytes(out)


# -- painting a clone -------------------------------------------------------

BODY_TEXTURES = ("nodamage.xds", "nodamage_LOD0.xds")


def _find(folder: Path, name: str) -> Path | None:
    """`folder/name` in any case (car archives spell their members variously)."""
    if not folder.is_dir():
        return None
    return next((path for path in folder.iterdir() if path.name.lower() == name.lower()), None)


def _opaque_png(width: int, height: int, rgba: bytes) -> bytes:
    shown = bytearray(rgba)
    shown[3::4] = b"\xff" * (width * height)
    return xds.encode_png(width, height, bytes(shown))


def paint_livery(recipe: Recipe, clone_dir: Path, preview: Path | None = None) -> dict:
    """Paint `recipe` into a car-clone staging folder: its media/cars/<media>/nodamage.xds and
    nodamage_LOD0.xds are repainted through `fh1_xds.repaint_xds` (colour only, untouched blocks
    kept) and replaced together once both are ready, so a failure leaves the clone unchanged.
    `preview` receives flat PNGs of the painted textures. Returns the report."""
    started = time.perf_counter()
    media = recipe.car["media_name"]
    cars = _find(Path(clone_dir) / "media", "cars")
    folder = _find(cars, media) if cars else None
    if folder is None:
        raise ValueError(f"{clone_dir} holds no media/cars/{media} folder; clone the car first")
    painted, textures = [], []
    for name in BODY_TEXTURES:
        path = _find(folder, name)
        if path is None:
            raise ValueError(f"the clone has no {name} in {folder}")
        texture_started = time.perf_counter()
        stock = path.read_bytes()
        texture = xds.layout(stock)
        width, height = texture.width, texture.height
        level0 = xds.decode_level(stock, 0)
        image = compose(level0, width, height, recipe)
        data = xds.repaint_xds(stock, image)
        # Alpha is unchanged, so a texel changed when its four bytes did.
        changed = bytes(a != b for a, b in zip(memoryview(image).cast("I"), memoryview(level0).cast("I")))
        panels = {panel_name: _and(changed, bytes(polygon_mask(panel.outline, width, height))).count(1)
                  for panel_name, panel in recipe.panels.items()}
        blocks = [sum(a[i:i + 16] != b[i:i + 16] for i in range(0, len(a), 16))
                  for a, b in zip(xds.read_blocks(stock), xds.read_blocks(data))]
        painted.append((path, data, width, height, image))
        textures.append({"file": path.relative_to(clone_dir).as_posix(), "size": f"{width}x{height}",
                         "texels_changed": changed.count(1), "panels": panels, "blocks_reencoded": blocks,
                         "sha256": hashlib.sha256(data).hexdigest(),
                         "seconds": round(time.perf_counter() - texture_started, 1)})
    temporary = []
    try:
        for path, data, *_ in painted:
            temporary.append(path.with_name(path.name + ".painting"))
            temporary[-1].write_bytes(data)
        for (path, *_), staged in zip(painted, temporary):
            os.replace(staged, path)
    finally:
        for staged in temporary:
            staged.unlink(missing_ok=True)
    if preview is not None:
        Path(preview).mkdir(parents=True, exist_ok=True)
        for path, _, width, height, image in painted:
            (Path(preview) / f"{media}_{path.stem}.png").write_bytes(_opaque_png(width, height, image))
    return {"recipe": recipe.name, "car": recipe.car, "clone": str(clone_dir), "layers": len(recipe.layers),
            "textures": textures, "seconds": round(time.perf_counter() - started, 1)}


# -- panel previews ---------------------------------------------------------

VARIANT = re.compile(r"nodamage.+\.xds", re.IGNORECASE)    # Turn 10's stripe and colour variants
LANE_PANELS = ("top", "front", "rear")                     # where Turn 10's stripe lanes run
PANEL_COLOURS = [(230, 25, 75), (60, 180, 75), (255, 225, 25), (0, 130, 200), (245, 130, 48), (145, 30, 180),
                 (70, 240, 240), (240, 50, 230), (210, 245, 60), (250, 190, 212)]


def _line(rgba: bytearray, width: int, height: int, start, end, colour, thick: int = 1) -> None:
    """A straight line between texel positions, `thick` texels wide."""
    (x0, y0), (x1, y1) = start, end
    steps = max(1, int(max(abs(x1 - x0), abs(y1 - y0))))
    for step in range(steps + 1):
        x, y = x0 + (x1 - x0) * step / steps, y0 + (y1 - y0) * step / steps
        for dy in range(thick):
            for dx in range(thick):
                tx, ty = int(x) + dx - thick // 2, int(y) + dy - thick // 2
                if 0 <= tx < width and 0 <= ty < height:
                    rgba[4 * (ty * width + tx):4 * (ty * width + tx) + 4] = bytes((*colour, 255))


def _mask_png(mask: bytes, width: int, height: int, on=(255, 255, 255), off=(0, 0, 0)) -> bytes:
    lit, dark = bytes((*on, 255)), bytes((*off, 255))
    return xds.encode_png(width, height, b"".join(lit if value else dark for value in mask))


def panel_previews(files: dict[str, bytes], panels: dict[str, Panel] | None, output: Path) -> dict:
    """Local previews for authoring a stock car's panel table, from the car's own textures: the paint
    area of both body textures, the damage texture (whose scratches outline the body panels) with a
    0.05 grid, Turn 10's stripe lanes (each stock variant diffed against nodamage), and, given a
    table, its outlines and frames with the coverage numbers of spec criterion 1."""
    textures = {name.lower(): data for name, data in files.items() if "/" not in name}
    for name in ("nodamage.xds", "nodamage_lod0.xds", "damage.xds"):
        if name not in textures:
            raise ValueError(f"the stock car has no {name}")
    base, lod0, damage = (xds.decode_level(textures[name], 0) for name in ("nodamage.xds", "nodamage_lod0.xds",
                                                                          "damage.xds"))
    width, wide = xds.layout(textures["nodamage.xds"]).width, xds.layout(textures["nodamage_lod0.xds"]).width
    if xds.layout(textures["damage.xds"]).width != width:
        raise ValueError("damage.xds and nodamage.xds differ in size")
    paint_area, paint_lod0 = base[3::4].translate(_PAINT_AREA), lod0[3::4].translate(_PAINT_AREA)
    scratches = _and(damage[3::4].translate(bytes(1 if a > 16 else 0 for a in range(256))), paint_area)
    lanes = None
    for name, data in sorted(textures.items()):
        if VARIANT.fullmatch(name) and not name.endswith("_lod0.xds") and xds.layout(data).width == width:
            variant = xds.decode_level(data, 0)
            found = bytes(1 if max(abs(variant[4 * i + c] - base[4 * i + c]) for c in range(4)) > 24 else 0
                          for i in range(width * width))
            lanes = found if lanes is None else _or(lanes, found)
    if lanes is not None:
        lanes = _and(lanes, paint_area)    # decals and interior parts the variants re-encode are not lanes

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    written = {"paint-area.png": _mask_png(paint_area, width, width),
               "paint-area-LOD0.png": _mask_png(paint_lod0, wide, wide)}
    grid = bytearray(damage)
    for i in range(width * width):
        if not paint_area[i]:
            grid[4 * i:4 * i + 3] = bytes(c * 35 // 100 for c in damage[4 * i:4 * i + 3])
        grid[4 * i + 3] = 255
    for step in range(1, 20):
        at = step * width / 20
        colour, thick = ((255, 0, 255), 2) if step % 5 == 0 else ((0, 200, 255), 1)
        _line(grid, width, width, (at, 0), (at, width - 1), colour, thick)
        _line(grid, width, width, (0, at), (width - 1, at), colour, thick)
    written["damage-grid.png"] = xds.encode_png(width, width, bytes(grid))
    if lanes is not None:
        written["stripe-lanes.png"] = _mask_png(lanes, width, width, on=(255, 60, 60))

    coverage = None
    if panels:
        drawn = bytearray(grid)
        union, lane_union, report = bytes(width * width), bytes(width * width), {}
        for index, (name, panel) in enumerate(sorted(panels.items())):
            mask, mask_lod0 = bytes(polygon_mask(panel.outline, width, width)), bytes(polygon_mask(panel.outline, wide, wide))
            texels = mask.count(1)
            report[name] = {"texels": texels, "in_paint_area": {
                "nodamage.xds": round(_and(mask, paint_area).count(1) / texels, 4) if texels else 0.0,
                "nodamage_LOD0.xds": round(_and(mask_lod0, paint_lod0).count(1) / max(1, mask_lod0.count(1)), 4)}}
            union = _or(union, mask)
            if name in LANE_PANELS:
                lane_union = _or(lane_union, mask)
            colour = PANEL_COLOURS[index % len(PANEL_COLOURS)]
            points = [(x * width, y * width) for x, y in panel.outline]
            for a, b in zip(points, points[1:] + points[:1]):
                _line(drawn, width, width, a, b, colour, 2)
            corner, rear, bottom = (tuple(c * width for c in panel.frame.to_texture(u, v))
                                    for u, v in ((0, 0), (1, 0), (0, 1)))
            _line(drawn, width, width, corner, rear, colour, 3)          # front -> rear
            _line(drawn, width, width, corner, bottom, colour, 1)        # top -> bottom
            for u, v in ((0.95, -0.05), (0.95, 0.05)):                   # arrowhead at the rear
                _line(drawn, width, width, rear, tuple(c * width for c in panel.frame.to_texture(u, v)), colour, 2)
        written["panels.png"] = xds.encode_png(width, width, bytes(drawn))
        scratch_total = scratches.count(1)
        scratch_share = round(_and(union, scratches).count(1) / scratch_total, 4) if scratch_total else None
        # Turn 10 paints its stripes past the panels' ends and into colour swatches, so the check is
        # that the lane texels lying on panels lie on top, front or rear.
        lane_share = lanes_on_panels = None
        if lanes is not None and lanes.count(1):
            on_panels = _and(lanes, union).count(1)
            lanes_on_panels = round(on_panels / lanes.count(1), 4)
            lane_share = round(_and(lanes, lane_union).count(1) / on_panels, 4) if on_panels else 0.0
        coverage = {"panels": report, "scratches_covered": scratch_share, "stripe_lanes_covered": lane_share,
                    "stripe_lanes_on_panels": lanes_on_panels,
                    "checks": {"outlines_in_paint_area": all(v >= 0.99 for entry in report.values()
                                                             for v in entry["in_paint_area"].values()),
                               "scratches_covered": scratch_share is not None and scratch_share >= 0.9,
                               "stripe_lanes_covered": None if lane_share is None else lane_share >= 0.99}}
    for name, data in written.items():
        (output / name).write_bytes(data)
    return {"output": str(output), "files": sorted(written), "sizes": {"nodamage.xds": width, "nodamage_LOD0.xds": wide},
            "coverage": coverage}


# -- probe ------------------------------------------------------------------

PROBE_MOD = "livery-probe"
# Each quadrant of a panel holds a large patch whose colour names its corner of the frame: white at
# the front-top (u < 0.5, v < 0.5), black at the rear-top, magenta at the front-bottom and cyan at
# the rear-bottom. The colours stay apart under any showroom light and none is a panel colour, so a
# capture shows where u and v run on the car and whether a frame is mirrored, even when wheel arches
# or windows hide part of a panel. On the top panel "top" is the car's left; on the front and rear
# panels u runs from the car's left to its right.
QUADRANT_COLOURS = {(0, 0): (255, 255, 255), (1, 0): (0, 0, 0), (0, 1): (240, 50, 230), (1, 1): (70, 240, 240)}
PATCH = (0.08, 0.42)                       # each patch's extent inside its half, along u and along v


def probe_texel(colour: tuple[int, int, int], u: float, v: float, length: float, tall: float) -> tuple[int, int, int]:
    """The probe's colour at panel coordinates (u, v) of a panel `length` x `tall` texels."""
    qu, qv = int(u >= 0.5), int(v >= 0.5)
    if PATCH[0] <= u - 0.5 * qu <= PATCH[1] and PATCH[0] <= v - 0.5 * qv <= PATCH[1]:
        return QUADRANT_COLOURS[(qu, qv)]
    if abs(u * 10 - round(u * 10)) * length / 10 < 0.5 or abs(v * 10 - round(v * 10)) * tall / 10 < 0.5:
        return tuple(c // 2 for c in colour)
    return colour


def probe_image(stock: bytes, width: int, height: int, panels: dict[str, Panel],
                alpha0_panel: str | None = None) -> bytes:
    """A test pattern over a stock texture's level 0 for checking a panel table in game: each panel
    opaque in its own colour with a 0.1 grid and the quadrant patches of `probe_texel`.
    `alpha0_panel` keeps its stock alpha instead, to see how the title shows colour in the paint area."""
    if alpha0_panel is not None and alpha0_panel not in panels:
        raise ValueError(f"no panel {alpha0_panel} in the table")
    out = bytearray(stock)
    for index, (name, panel) in enumerate(sorted(panels.items())):
        colour = PANEL_COLOURS[index % len(PANEL_COLOURS)]
        length, tall = panel.frame.size(width, height)
        mask = polygon_mask(panel.outline, width, height)
        for run in re.finditer(rb"\x01+", bytes(mask)):
            for i in range(*run.span()):
                u, v = panel.frame.to_panel((i % width + 0.5) / width, (i // width + 0.5) / height)
                out[4 * i:4 * i + 3] = bytes(probe_texel(colour, u, v, length, tall))
                if name != alpha0_panel:
                    out[4 * i + 3] = 255
    return bytes(out)


def write_probe(files: dict[str, bytes], archive: str, panels: dict[str, Panel], output: Path,
                alpha0_panel: str | None = None) -> dict:
    """The probe painted into every body texture of a stock car (nodamage, nodamage_LOD0 and Turn
    10's colour and stripe variants of them, which share their layout: the Autoshow shows the
    Challenger in its striped variant), written as the private asset mod
    <output>/mods/livery-probe/members/<archive>/<member> (re-encoded whole, since its alpha changes)."""
    members = {name.lower(): name for name in files if "/" not in name}
    mod = Path(output) / "mods" / PROBE_MOD
    written = []
    for name in BODY_TEXTURES:
        if name.lower() not in members:
            raise ValueError(f"the stock car has no {name}")
    for member in sorted(name for lower, name in members.items() if re.fullmatch(r"nodamage.*\.xds", lower)):
        stock = files[member]
        texture = xds.layout(stock)
        image = probe_image(xds.decode_level(stock, 0), texture.width, texture.height, panels, alpha0_panel)
        path = mod / "members" / archive / member
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(xds.write_xds(stock[:xds.HEADER_SIZE], image, texture.width, texture.height))
        written.append(path.relative_to(output).as_posix())
    (mod / "mod.toml").write_text(f'name = "{PROBE_MOD}"\nversion = "1.0.0"\nabi = 1\n', encoding="utf-8")
    legend = {name: "%02x%02x%02x" % PANEL_COLOURS[index % len(PANEL_COLOURS)]
              for index, name in enumerate(sorted(panels))}
    return {"mod": str(mod), "files": written, "legend": legend, "alpha0_panel": alpha0_panel}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    paint = commands.add_parser("paint", help="paint a recipe into a car-clone staging folder")
    paint.add_argument("recipe", type=Path, help="config/livery-cars/<name>.json")
    paint.add_argument("--clone", type=Path, required=True, help="the clone-fh1-car.py output folder")
    paint.add_argument("--art", type=Path, help="the art folder (default: .local/livery-art/<recipe name>)")
    paint.add_argument("--preview", type=Path, help="write flat PNGs of the painted textures here")
    panels = commands.add_parser("panels", help="previews and coverage for a stock car's panel table")
    panels.add_argument("--state-root", type=Path, required=True, help="the installed preview state (.local/preview)")
    panels.add_argument("--game-root", type=Path, required=True, help="the extracted disc (.local/game/eur-base)")
    panels.add_argument("--stock-media", required=True)
    panels.add_argument("--output", type=Path, required=True, help="a local folder for the previews")
    panels.add_argument("--extractor", type=Path, help="archive extractor (default: the one the build made)")
    probe = commands.add_parser("probe", help="the probe livery on a stock car, as a private asset mod")
    probe.add_argument("--state-root", type=Path, required=True, help="the installed preview state (.local/preview)")
    probe.add_argument("--game-root", type=Path, required=True, help="the extracted disc (.local/game/eur-base)")
    probe.add_argument("--stock-media", required=True)
    probe.add_argument("--output", type=Path, required=True, help="a state folder whose mods/ receives the probe")
    probe.add_argument("--alpha0-panel", help="paint this panel's colour under the stock alpha instead")
    probe.add_argument("--extractor", type=Path, help="archive extractor (default: the one the build made)")
    for command in (paint, panels, probe):
        command.add_argument("--panels", type=Path, default=PANEL_TABLES, help=argparse.SUPPRESS)
        command.add_argument("--ids", type=Path, default=ID_TABLE, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.command == "paint":
            recipe = load_recipe(args.recipe, art_dir=args.art, panel_tables=args.panels, id_table=args.ids)
            report = paint_livery(recipe, args.clone, preview=args.preview)
        elif args.command == "panels":
            report = {"stock_media": args.stock_media} | panel_previews(
                _stock_files(args, args.stock_media), _table_or_none(args.panels, args.stock_media), args.output)
        else:
            table = _table_or_none(args.panels, args.stock_media)
            if table is None:
                raise ValueError(f"no panel table for {args.stock_media} in {args.panels}")
            sources = _sources(args)
            source = sources.car_source(args.stock_media)
            if source is None or source[1]:
                raise ValueError(f"{args.stock_media} is not a disc car; the probe replaces members of its disc archive")
            archive = source[0].relative_to(args.game_root.absolute()).as_posix()
            report = {"stock_media": args.stock_media} | write_probe(
                sources.car_files(args.stock_media), archive, table, args.output, args.alpha0_panel)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


def _sources(args):
    """car-clone's read-only view of the player's files."""
    extractor = args.extractor or _load_tool("manage-fh1-dlc").default_extractor()
    return _load_tool("clone-fh1-car").Sources(args.state_root.absolute(), args.game_root.absolute(),
                                               extractor.resolve())      # CreateProcess needs an absolute path


def _stock_files(args, media: str) -> dict[str, bytes]:
    """A stock car's archive members, read only."""
    return _sources(args).car_files(media)


def _table_or_none(folder: Path, media: str) -> dict[str, Panel] | None:
    path = Path(folder) / f"{media}.json"
    return load_panels(path) if path.is_file() else None


if __name__ == "__main__":
    sys.exit(main())
