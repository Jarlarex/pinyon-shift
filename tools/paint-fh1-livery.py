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
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
PANEL_TABLES = ROOT / "config/livery-cars/panels"
PANEL_NAME = re.compile(r"[a-z][a-z0-9_]*")


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
        outline = _points(f"{where}'s outline", entry.get("outline"), 3, 32)
        corners = _points(f"{where}'s frame", entry.get("frame"), 3, 3)
        try:
            frame = Frame.from_points(corners)
        except ValueError as error:
            raise ValueError(f"{where}: {error}") from None
        panels[name] = Panel(name, outline, frame)
    return panels
