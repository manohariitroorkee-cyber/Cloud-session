"""Road cross-section template – finished-surface GEOMETRY only.

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


def half_section(tpl: dict) -> list[Strip]:
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
        z1 = z + s.get("crossfall_pct", 0.0) / 100 * s["width"]
        strips.append(Strip(s["type"], x, x + s["width"], z, z1))
        x, z = x + s["width"], z1
    return strips


def row_half_width(tpl: dict) -> float:
    return half_section(tpl)[-1].x1


def surface_at(tpl: dict, offset: float) -> tuple[str, float] | None:
    """(strip type, level relative to centreline FRL) at an offset, or None outside the template."""
    a = abs(offset)
    for s in half_section(tpl):
        if s.x0 - 1e-9 <= a <= s.x1 + 1e-9:
            f = (a - s.x0) / (s.x1 - s.x0) if s.x1 > s.x0 else 0.0
            return s.type, s.z0 + f * (s.z1 - s.z0)
    return None


@dataclass
class Section:
    chainage: float
    frl: float
    points: list[tuple[float, float, float | None]] = field(default_factory=list)  # (offset, design, ground)


def section_at(ch: float, frl: float, tpl: dict, ground_at, step: float = 0.5) -> Section:
    """Design surface and ground across the template at chainage ch.
    ground_at(offset) -> level or None (outside surveyed terrain)."""
    W = row_half_width(tpl)
    n = int(round(W / step))
    offs = sorted({-W, W, 0.0} | {round(k * step, 6) for k in range(-n, n + 1)})
    pts = []
    for o in offs:
        hit = surface_at(tpl, o)
        if hit:
            pts.append((o, frl + hit[1], ground_at(o)))
    return Section(ch, frl, pts)
