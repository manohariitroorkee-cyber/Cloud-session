"""Road cross-section template – finished-surface GEOMETRY only.

Superelevation: on curves where the design superelevation E exceeds the camber, the
outer side of each carriageway rotates from −camber to +E and the inner side from
−camber to −E, linearly with curvature through the transition (about the median edge on
a divided road, the centreline on an undivided one).  Where E ≤ camber the normal
cambered section is kept.

Scope decision: pavement thickness design, pavement layers, structural (RCC)
design and earthwork/quantities are NOT part of this module.  The template
defines widths, crossfalls and kerb steps so that the finished road surface
level is known at any offset.  It is used for cross-section drawings
(design surface against ground) and for checking utility cover levels
against the road.

Template (road attribute ``template``), symmetric about the centreline:

    {"median": {"width": 1.2, "raised_m": 0.15},          # optional
     "strips": [                                          # from centre outwards
        {"type": "carriageway", "width": 7.0, "crossfall_pct": -2.5},
        {"type": "cycle_track", "width": 2.0, "crossfall_pct": -2.0, "step_m": 0.15},
        {"type": "footpath",    "width": 2.0, "crossfall_pct": 2.0},
        {"type": "drain",       "width": 1.0},
        {"type": "utility_corridor", "width": 2.0, "crossfall_pct": 2.0},
        {"type": "verge",       "width": 1.0, "crossfall_pct": 4.0}]}

``step_m`` is a kerb step at the inner edge of the strip.
"""

from __future__ import annotations

from dataclasses import dataclass, field

STRIP_TYPES = {"carriageway", "median", "cycle_track", "footpath", "verge", "drain", "utility_corridor", "shoulder"}


@dataclass
class Strip:
    type: str
    x0: float          # offset of inner edge (m, ≥ 0)
    x1: float
    z0: float          # finished level relative to centreline FRL at inner edge
    z1: float


def half_section(tpl: dict, carriageway_slope_pct: float | None = None) -> list[Strip]:
    """Strips of one side, from the centreline outwards.  carriageway_slope_pct, when
    given, replaces the carriageway crossfall on this side (superelevation; + = rising
    outwards)."""
    strips: list[Strip] = []
    x, z = 0.0, 0.0
    med = tpl.get("median")
    if med:
        w = med["width"] / 2
        zr = med.get("raised_m", 0.0)
        strips.append(Strip("median", 0.0, w, zr, zr))
        x = w
    for s in tpl["strips"]:
        if s["type"] not in STRIP_TYPES:
            raise ValueError(f"unknown strip type {s['type']!r}")
        z += s.get("step_m", 0.0)
        cf = s.get("crossfall_pct", 0.0)
        if carriageway_slope_pct is not None and s["type"] == "carriageway":
            cf = carriageway_slope_pct
        z1 = z + cf / 100 * s["width"]
        strips.append(Strip(s["type"], x, x + s["width"], z, z1))
        x, z = x + s["width"], z1
    return strips


def row_half_width(tpl: dict) -> float:
    return half_section(tpl)[-1].x1


def carriageway_slopes(camber_pct: float, e_full: float, progress: float, turn: int) -> dict[int, float]:
    """Carriageway crossfall (%, + rising outwards) on each side (+1 right, −1 left).

    Superelevation is developed linearly with `progress` (0 on the straight, 1 on the
    arc): the outer side rotates from −camber to +E and the inner side from −camber
    to −E, so there is no step in level anywhere.  E ≤ camber keeps the normal
    cambered section (no superelevation provided)."""
    c, E = abs(camber_pct), abs(e_full) * 100
    if E <= c + 1e-12 or progress <= 0:
        return {1: -c, -1: -c}
    p = min(progress, 1.0)
    outer = -c + p * (c + E)
    inner = -c - p * (E - c)
    inside = 1 if turn > 0 else -1            # a right-hand curve falls to the right
    return {inside: inner, -inside: outer}


def camber_of(tpl: dict) -> float:
    return max((abs(s.get("crossfall_pct", 0.0)) for s in tpl["strips"] if s["type"] == "carriageway"), default=0.0)


def surface_at(tpl: dict, offset: float, slopes: dict[int, float] | None = None) -> tuple[str, float] | None:
    """(strip type, level relative to centreline FRL) at an offset, or None outside the template.
    slopes = carriageway crossfall per side from carriageway_slopes() (None = normal camber)."""
    a = abs(offset)
    side = 1 if offset >= 0 else -1
    for s in half_section(tpl, slopes[side] if slopes else None):
        if s.x0 - 1e-9 <= a <= s.x1 + 1e-9:
            f = (a - s.x0) / (s.x1 - s.x0) if s.x1 > s.x0 else 0.0
            return s.type, s.z0 + f * (s.z1 - s.z0)
    return None


@dataclass
class Section:
    chainage: float
    frl: float
    points: list[tuple[float, float, float | None]] = field(default_factory=list)  # (offset, design, ground)


def section_at(ch: float, frl: float, tpl: dict, ground_at, step: float = 0.5,
               slopes: dict[int, float] | None = None) -> Section:
    """Design surface and ground across the template at chainage ch (with carriageway slopes).
    ground_at(offset) -> level or None (outside surveyed terrain)."""
    W = row_half_width(tpl)
    n = int(round(W / step))
    offs = sorted({-W, W, 0.0} | {round(k * step, 6) for k in range(-n, n + 1)})
    pts = []
    for o in offs:
        hit = surface_at(tpl, o, slopes)
        if hit:
            pts.append((o, frl + hit[1], ground_at(o)))
    return Section(ch, frl, pts)
