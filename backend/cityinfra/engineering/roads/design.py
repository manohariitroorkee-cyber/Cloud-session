"""Road alignment and curve design: horizontal and vertical alignment checks,
long-section, cross-section geometry, and identification of utilities
affected by the road levels.

Out of scope by decision: pavement thickness design, structural (RCC)
design, earthwork and quantities.

ROAD_ALIGNMENT object (LineString through start, PIs, end) attributes:
    design_speed_kmh, terrain ("plain"/"rolling"),
    curves:  {"1": [radius_m, transition_m], ...}     keyed by PI index
    profile: [[chainage, level, vertical_curve_length], ...]
    template: cross-section template (see cross_section.py)
    section_interval_m: spacing of cross-sections (default 20)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ...gis.geometry import line_coords, point_coord
from ...model.core import EngineeringObject, ObjectKind, Project, RelationType
from ...rules.framework import CheckResult, CheckStatus, RuleContext
from . import cross_section as xs
from .horizontal import HorizontalAlignment, build
from .vertical import VIP, TIN, VerticalAlignment, crest_length_for, sag_length_for, ssd

METHOD = ("Horizontal: circular curves with clothoid transitions; vertical: symmetric parabolic curves; "
          "ground: linear TIN")

# objects whose top level should follow the finished road surface
LEVEL_KEYS = {ObjectKind.MANHOLE: "ground_level", ObjectKind.DRAIN_NODE: "ground_level",
              ObjectKind.TELECOM_CHAMBER: "cover_level", ObjectKind.VALVE: "cover_level"}


@dataclass
class RoadDesign:
    road: EngineeringObject
    h: HorizontalAlignment
    v: VerticalAlignment
    sections: list[xs.Section]
    checks: list[CheckResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def long_section(self, step: float = 20.0, tin: TIN | None = None) -> list[dict]:
        rows, ch = [], 0.0
        while ch <= self.h.length + 1e-9:
            x, y, _ = self.h.at(ch)
            g = tin.level(x, y) if tin else None
            f = self.v.level(ch)
            rows.append({"chainage": round(ch, 3), "x": round(x, 3), "y": round(y, 3), "frl": round(f, 3),
                         "ground": None if g is None else round(g, 3),
                         "cut_fill": None if g is None else round(f - g, 3)})
            ch = ch + step if ch + step <= self.h.length or ch >= self.h.length else self.h.length
        return rows


def terrain(pr: Project) -> TIN | None:
    pts = []
    for o in pr.of_kind(ObjectKind.TERRAIN_POINT):
        c = point_coord(o.geometry)
        z = c[2] if len(c) > 2 else o.attr("level")
        if z is not None:
            pts.append((c[0], c[1], float(z)))
    return TIN(pts) if len(pts) >= 3 else None


def design_road(pr: Project, road: EngineeringObject, rules: RuleContext) -> RoadDesign:
    pis = [tuple(c[:2]) for c in line_coords(road.geometry)]
    curves = {int(k): (float(v[0]), float(v[1])) for k, v in (road.attr("curves") or {}).items()}
    h = build(pis, curves)
    v = VerticalAlignment([VIP(*map(float, p)) for p in road.attr("profile")])
    errors = list(h.errors) + list(v.errors)
    if abs(v.vips[-1].chainage - h.length) > 0.5:
        errors.append(f"Profile ends at ch {v.vips[-1].chainage:.2f} but alignment length is {h.length:.2f} m.")
    tpl = road.attr("template")
    tin = terrain(pr)
    sections: list[xs.Section] = []
    if tin is None:
        errors.append("No terrain points: ground profile and cross-section ground lines not available.")
    if not errors or (tin is None and not h.errors and not v.errors):
        step = float(road.attr("section_interval_m", 20))
        chs = [min(i * step, h.length) for i in range(int(h.length // step) + 1)]
        if chs[-1] < h.length - 1e-6:
            chs.append(h.length)
        for ch in chs:
            ground = (lambda off, ch=ch: tin.level(*h.offset_point(ch, off))) if tin else (lambda off: None)
            sections.append(xs.section_at(ch, v.level(ch), tpl, ground))
    d = RoadDesign(road, h, v, sections, errors=errors)
    d.checks = _checks(d, rules)
    return d


def _checks(d: RoadDesign, rules: RuleContext) -> list[CheckResult]:
    r = d.road
    V = float(r.attr("design_speed_kmh"))
    out: list[CheckResult] = []
    e_max, f_lat = rules.get("e_max"), rules.get("f_lateral")
    rmin = V * V / (127 * (e_max.value + f_lat.value))
    for c in d.h.curves:
        lbl = f"{r.label} PI{c.pi_index}"
        out.append(CheckResult("min_radius", r.id, lbl, CheckStatus.PASS if c.radius >= rmin else CheckStatus.FAIL,
                               f"R {c.radius:.0f} m vs R_min {rmin:.0f} m = V²/127(e+f) at {V:.0f} km/h",
                               c.radius, rmin, "m", e_max))
        # transition length: centrifugal-acceleration criterion and superelevation run-off criterion
        cpar = rules.get("c_rate")
        C = min(max(cpar.value["numerator"] / (cpar.value["offset"] + V), cpar.value["min"]), cpar.value["max"])
        v = V / 3.6
        ls1 = v ** 3 / (C * c.radius)
        e_des = min(V * V / (rules.value("e_design_divisor") * c.radius), e_max.value)
        npar = rules.get("superelevation_runoff_N")
        w_rot = _rotated_width(r.attr("template"))
        ls2 = e_des * npar.value * w_rot
        need = max(ls1, ls2)
        out.append(CheckResult("transition_length", r.id, lbl,
                               CheckStatus.PASS if c.spiral >= need - 1e-6 else CheckStatus.FAIL,
                               f"Ls {c.spiral:.1f} m vs required {need:.1f} m (v³/CR = {ls1:.1f} m with C = {C:.2f}; "
                               f"run-off e·N·W = {ls2:.1f} m with e = {e_des*100:.1f} %, W = {w_rot:.2f} m)",
                               c.spiral, need, "m", cpar))
    gmax, gmin = rules.get("max_grade_pct"), rules.get("min_grade_pct")
    for i in range(len(d.v.vips) - 1):
        g = d.v.grade(i) * 100
        lbl = f"{r.label} grade {i+1} (ch {d.v.vips[i].chainage:.0f}–{d.v.vips[i+1].chainage:.0f})"
        out.append(CheckResult("max_grade", r.id, lbl, CheckStatus.PASS if abs(g) <= gmax.value else CheckStatus.FAIL,
                               f"Grade {g:.2f} % vs maximum {gmax.value} %", abs(g), gmax.value, "%", gmax))
        if r.attr("kerbed", True):
            out.append(CheckResult("min_grade", r.id, lbl,
                                   CheckStatus.PASS if abs(g) >= gmin.value else CheckStatus.WARNING,
                                   f"Grade {g:.2f} % vs minimum {gmin.value} % for kerb-channel drainage",
                                   abs(g), gmin.value, "%", gmin))
    fpar = rules.get("f_longitudinal")
    S = ssd(V, rules.value("reaction_time_s"), fpar.lookup(V))
    for i, g1, g2, L, kind in d.v.curves():
        A = abs(g2 - g1)
        lbl = f"{r.label} VC at ch {d.v.vips[i].chainage:.0f} ({kind})"
        if kind == "crest":
            need = crest_length_for(S, A, rules.value("eye_height_m"), rules.value("object_height_m"))
        else:
            need = sag_length_for(S, A, rules.value("headlight_height_m"), rules.value("headlight_beam_deg"))
        need = max(need, rules.value("min_vertical_curve_m") if A > 0 else 0)
        out.append(CheckResult("vertical_curve_length", r.id, lbl,
                               CheckStatus.PASS if L >= need - 1e-6 else CheckStatus.FAIL,
                               f"L {L:.0f} m vs required {need:.0f} m for SSD {S:.0f} m, A = {A*100:.2f} %",
                               L, need, "m", fpar))
    return out


def _rotated_width(tpl: dict) -> float:
    """Carriageway width rotated on one side (divided road rotated about the median edge;
    for an undivided road this is half the carriageway, i.e. rotation about the centreline)."""
    return sum(s.x1 - s.x0 for s in xs.half_section(tpl) if s.type == "carriageway")


def level_impacts(pr: Project, d: RoadDesign, tolerance_m: float = 0.05) -> list[dict]:
    """Utilities within the road corridor whose top level no longer matches
    the finished road surface.  Registers LOCATED_IN and DEPENDS_ON_LEVEL
    relationships so the change-impact graph records the dependency."""
    tpl = d.road.attr("template")
    W = xs.row_half_width(tpl)
    out = []
    existing = {(r.source_id, r.target_id, r.type) for r in pr.relationships}
    for kind, key in LEVEL_KEYS.items():
        for o in pr.of_kind(kind):
            if o.attr(key) is None:
                continue
            pt = point_coord(o.geometry)
            ch, off = d.h.station(pt)
            if abs(off) > W or ch <= 0 or ch >= d.h.length:
                continue
            strip, dz = xs.surface_at(tpl, off)
            z = d.v.level(ch) + dz
            for t in (RelationType.LOCATED_IN, RelationType.DEPENDS_ON_LEVEL):
                if (o.id, d.road.id, t) not in existing:
                    pr.relate(o, d.road, t)
            diff = z - float(o.attr(key))
            if abs(diff) > tolerance_m:
                out.append({"object_id": o.id, "object": o.label, "kind": kind.value, "chainage": round(ch, 2),
                            "offset": round(off, 2), "strip": strip, "current_level": o.attr(key),
                            "road_surface_level": round(z, 3), "difference_m": round(diff, 3)})
    return out
