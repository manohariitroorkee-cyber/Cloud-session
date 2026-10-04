"""Geometry helpers for engineering measurement.

All engineering geometry is held in a *projected* CRS whose unit is the
metre (for Delhi: UTM zone 43N, EPSG:32643).  Lengths, chainages and angles
are therefore planar.  Reprojection to/from WGS84 for the web map is done by
PostGIS (``ST_Transform``) in the database layer, never by hand here.

Basemap imagery (satellite etc.) is only a backdrop; geometry is never read
from it.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

Coord = Sequence[float]

# Geographic CRSs (degrees) must not be used for engineering measurement.
# Common ones are listed; with pyproj installed (API layer) every code is checked.
GEOGRAPHIC_EPSG = {4326, 4269, 4258, 4283, 7844, 4674, 4019, 4240, 4146, 4755, 4979}


def require_projected(epsg: int) -> None:
    try:                                   # authoritative check when pyproj is available
        from pyproj import CRS              # type: ignore
        if CRS.from_epsg(epsg).is_geographic:
            raise ValueError(f"EPSG:{epsg} is geographic (degrees). Engineering geometry must be in a "
                             "projected metric CRS, e.g. EPSG:32643 (UTM 43N) for Delhi.")
        return
    except ImportError:
        pass
    if epsg in GEOGRAPHIC_EPSG:
        raise ValueError(
            f"EPSG:{epsg} is geographic (degrees). Engineering geometry must be in a "
            "projected metric CRS, e.g. EPSG:32643 (UTM 43N) for Delhi.")


def distance(a: Coord, b: Coord) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def line_coords(geom: dict[str, Any]) -> list[Coord]:
    if geom.get("type") != "LineString":
        raise ValueError(f"expected LineString, got {geom.get('type')}")
    coords = geom["coordinates"]
    if len(coords) < 2:
        raise ValueError("LineString needs at least two vertices")
    return coords


def point_coord(geom: dict[str, Any]) -> Coord:
    if geom.get("type") != "Point":
        raise ValueError(f"expected Point, got {geom.get('type')}")
    return geom["coordinates"]


def line_length(geom: dict[str, Any]) -> float:
    c = line_coords(geom)
    return sum(distance(c[i], c[i + 1]) for i in range(len(c) - 1))


def bearing_deg(a: Coord, b: Coord) -> float:
    """Whole-circle bearing from grid north, clockwise, 0–360°."""
    return math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) % 360.0


def deflection_deg(a: Coord, b: Coord, c: Coord) -> float:
    """Deflection angle at b between a→b and b→c (0 = straight on)."""
    d = bearing_deg(b, c) - bearing_deg(a, b)
    return (d + 180.0) % 360.0 - 180.0


def polygon_area(geom: dict[str, Any]) -> float:
    """Planar area (m²) of a Polygon/MultiPolygon, holes subtracted."""
    def ring(r: list[Coord]) -> float:
        if tuple(r[0][:2]) != tuple(r[-1][:2]):        # tolerate unclosed rings
            r = list(r) + [r[0]]
        return 0.5 * sum(r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1] for i in range(len(r) - 1))

    def poly(rings: list[list[Coord]]) -> float:
        return abs(ring(rings[0])) - sum(abs(ring(h)) for h in rings[1:])

    t = geom.get("type")
    if t == "Polygon":
        return poly(geom["coordinates"])
    if t == "MultiPolygon":
        return sum(poly(p) for p in geom["coordinates"])
    raise ValueError(f"expected Polygon/MultiPolygon, got {t}")


def endpoints(geom: dict[str, Any]) -> tuple[Coord, Coord]:
    c = line_coords(geom)
    return c[0], c[-1]
