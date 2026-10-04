"""Road alignment and curve design: horizontal and vertical alignment checks,
long-section, cross-section geometry, and identification of utilities
affected by the road levels.

Out of scope by decision: pavement thickness design, structural (RCC)
design, earthwork and quantities.

ROAD_ALIGNMENT object attributes:
    design_speed_kmh
    horizontal_mode: how the drawn geometry is read (default "pi")
        "pi"       geometry = start, PIs, end; curves = {"1": spec, ...} (see alignment.normalise_spec:
                   simple, equal/unequal transitions, spiral–spiral, compound with transitions)
        "elements" geometry = start point (and optionally a second point for the start bearing);
                   elements = [{"line": 100}, {"spiral": 40, "to_R": 30, "turn": "left"}, {"arc_deg": 200, ...}]
        "bulges"   geometry = CAD polyline vertices; bulges = [b0, b1, ...] (DXF LWPOLYLINE)
        "fit"      geometry = freehand / traced centreline; tangents and radii are fitted
    profile: [[chainage, level, curve_length], ...] or [chainage, level, L_before, L_after] for an
             unsymmetrical curve; the last chainage may be "end" (= alignment length)
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
from . import alignment as hz
from .horizontal import HorizontalAlignment
from .vertical import VIP, TIN, VerticalAlignment, crest_length_for, sag_comfort_length, sag_length_for, ssd

METHOD = ("Horizontal: chain of straights, circular arcs and clothoids (any combination) evaluated exactly "
          "(Gauss–Legendre for clothoids); vertical: symmetric or unsymmetrical parabolic curves; ground: linear TIN")

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
    e_at: object = None             # chainage -> superelevation (fraction, + right-hand)

    def superelevation(self, ch: float) -> float:
        return self.e_at(ch) if self.e_at else 0.0

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


def horizontal_of(road: EngineeringObject) -> HorizontalAlignment:
    coords = [tuple(c[:2]) for c in line_coords(road.geometry)] if road.geometry["type"] == "LineString" \
        else [tuple(point_coord(road.geometry)[:2])]
    mode = road.attr("horizontal_mode", "pi")
    if mode == "pi":
        specs = {int(k): v for k, v in (road.attr("curves") or {}).items()}
        return hz.from_pis(coords, specs)
    if mode == "elements":
        if road.attr("start_bearing_deg") is not None:
            b0 = math.radians(float(road.attr("start_bearing_deg")))
        elif len(coords) > 1:
            b0 = hz.bearing(coords[0], coords[1])
        else:
            raise ValueError("element mode needs start_bearing_deg or a second geometry point")
        return hz.from_elements(coords[0], b0, road.attr("elements") or [])
    if mode == "bulges":
        return hz.from_bulges(coords, road.attr("bulges") or [])
    if mode == "fit":
        pis, specs, rep = hz.fit_drawn(coords, **(road.attr("fit_options") or {}))
        al = hz.from_pis(pis, specs)
        al.source, al.fit_report = "fit", rep
        al.errors = list(rep["errors"]) if rep["errors"] else al.errors
        return al
    raise ValueError(f"unknown horizontal_mode {mode!r}")


def design_road(pr: Project, road: EngineeringObject, rules: RuleContext) -> RoadDesign:
    if road.attr("design_speed_kmh") is None:
        raise ValueError(f"Road {road.label}: design_speed_kmh is required.")
    if not road.attr("template"):
        raise ValueError(f"Road {road.label}: a cross-section template is required.")
    try:
        h = horizontal_of(road)
    except (ValueError, KeyError) as e:
        raise ValueError(f"Road {road.label}: {e}") from e
    if not h.elements:
        raise ValueError(f"Road {road.label}: the horizontal alignment has no elements.")
    prof = [list(p) for p in road.attr("profile")]
    if prof and prof[-1][0] in ("end", None):
        prof[-1][0] = h.length
    v = VerticalAlignment([VIP(*map(float, p)) for p in prof])
    errors = list(h.errors) + list(v.errors)
    if abs(v.vips[-1].chainage - h.length) > 0.5:
        errors.append(f"Profile ends at ch {v.vips[-1].chainage:.2f} but alignment length is {h.length:.2f} m "
                      f"(use \"end\" as the last chainage to follow the alignment).")
    tpl = road.attr("template")
    tin = terrain(pr)
    V = float(road.attr("design_speed_kmh"))
    emax, div = rules.value("e_max"), rules.value("e_design_divisor")
    def e_at(ch: float) -> float:
        k = h.curvature(ch)
        return 0.0 if abs(k) < 1e-12 else math.copysign(min(V * V * abs(k) / div, emax), k)
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
            sections.append(xs.section_at(ch, v.level(ch), tpl, ground, e=e_at(ch)))
    d = RoadDesign(road, h, v, sections, errors=errors, e_at=e_at)
    d.checks = _checks(d, rules)
    return d


def _checks(d: RoadDesign, rules: RuleContext) -> list[CheckResult]:
    r = d.road
    V = float(r.attr("design_speed_kmh"))
    v = V / 3.6
    out: list[CheckResult] = []
    e_max, f_lat = rules.get("e_max"), rules.get("f_lateral")
    rmin = V * V / (127 * (e_max.value + f_lat.value))
    cpar = rules.get("c_rate")
    C = min(max(cpar.value["numerator"] / (cpar.value["offset"] + V), cpar.value["min"]), cpar.value["max"])
    npar = rules.get("superelevation_runoff_N")
    w_rot = _rotated_width(r.attr("template"))
    e_of = lambda k: 0.0 if abs(k) < 1e-12 else math.copysign(
        min(V * V * abs(k) / rules.value("e_design_divisor"), e_max.value), k)

    emp = rules.get("transition_empirical_coeff")
    emp_c = emp.value[r.attr("terrain", "plain")]

    def ls_required(k0: float, k1: float) -> tuple[float, float, float]:
        """(required length, centrifugal criterion, run-off criterion) for a change of curvature k0 → k1.
        The run-off criterion here also covers the empirical IRC form Ls = c·V²/R (c by terrain)."""
        l1 = v ** 3 * abs(k1 - k0) / C
        l2 = max(abs(e_of(k1) - e_of(k0)) * npar.value * w_rot, emp_c * V * V * abs(k1 - k0))
        return max(l1, l2), l1, l2

    shift_par = rules.get("transition_required_shift_m")
    for k, (ch, ang) in enumerate(d.h.kinks, 1):
        out.append(CheckResult("kink", r.id, f"{r.label} ch {ch:.1f}", CheckStatus.FAIL,
                               f"Angle point of {math.degrees(ang):+.2f}° with no curve: the drawn straights/arcs are "
                               f"not tangent here. Insert a curve or make the arc tangent.", math.degrees(abs(ang)), 0, "°"))
    els = d.h.elements
    for g in d.h.groups:
        lbl = f"{r.label} {g.tag}"
        for e in g.elements:
            if e.kind == "arc":
                R = e.radius
                out.append(CheckResult("min_radius", r.id, lbl, CheckStatus.PASS if R >= rmin - 1e-9 else CheckStatus.FAIL,
                                       f"R {R:.1f} m vs R_min {rmin:.1f} m = V²/127(e+f) at {V:.0f} km/h",
                                       R, rmin, "m", e_max))
        if not any(e.kind == "arc" and e.length > 1e-9 for e in g.elements):
            kmax = max(max(abs(e.k0), abs(e.k1)) for e in g.elements)
            R = 1 / kmax
            out.append(CheckResult("min_radius", r.id, lbl, CheckStatus.PASS if R >= rmin - 1e-9 else CheckStatus.FAIL,
                                   f"Sharpest radius reached in the transitions {R:.1f} m vs R_min {rmin:.1f} m "
                                   f"= V²/127(e+f) at {V:.0f} km/h", R, rmin, "m", e_max))
        # every change of curvature inside the group and at its two ends
        idx0 = els.index(g.elements[0])
        seq = ([els[idx0 - 1]] if idx0 > 0 else []) + g.elements + \
              ([els[idx0 + len(g.elements)]] if idx0 + len(g.elements) < len(els) else [])
        prev_k = 0.0 if idx0 == 0 else None
        for j, e in enumerate(seq):
            if e.kind == "spiral":
                need, l1, l2 = ls_required(e.k0, e.k1)
                out.append(CheckResult(
                    "transition_length", r.id, f"{lbl} spiral R {hz._r(e.k0)} → {hz._r(e.k1)}",
                    CheckStatus.PASS if e.length >= need - 1e-6 else CheckStatus.FAIL,
                    f"Ls {e.length:.1f} m vs required {need:.1f} m (v³·Δk/C = {l1:.1f} m with C = {C:.2f}; "
                    f"larger of run-off Δe·N·W and {emp_c}·V²·Δk = {l2:.1f} m, W = {w_rot:.2f} m)", e.length, need, "m", cpar))
            if j > 0:
                a_, b_ = seq[j - 1], e
                ka, kb = a_.k1, b_.k0
                if abs(ka - kb) > 1e-9:                    # curvature jumps: no transition here
                    need, l1, l2 = ls_required(ka, kb)
                    Rj = 1 / max(abs(ka), abs(kb))
                    if abs(ka) > 1e-12 and abs(kb) > 1e-12 and ka * kb > 0:
                        ratio = max(abs(ka), abs(kb)) / min(abs(ka), abs(kb))
                        rp = rules.get("compound_radius_ratio_max")
                        out.append(CheckResult("compound_ratio", r.id, lbl,
                                               CheckStatus.PASS if ratio <= rp.value + 1e-9 else CheckStatus.WARNING,
                                               f"Compound curve without transition: radius ratio {ratio:.2f} vs {rp.value}",
                                               ratio, rp.value, "-", rp))
                    else:
                        p_need = need * need / (24 * Rj)
                        ok = p_need <= shift_par.value + 1e-9
                        what = "reverse curve" if ka * kb < 0 else "curve"
                        out.append(CheckResult(
                            "transition_missing", r.id, lbl, CheckStatus.PASS if ok else CheckStatus.FAIL,
                            f"{what.capitalize()} meets {'a straight' if ka * kb == 0 else 'the opposite curve'} with no "
                            f"transition (R {Rj:.0f} m). Required transition {need:.1f} m would shift the curve by "
                            f"{p_need:.3f} m vs {shift_par.value} m: " +
                            ("transition may be omitted." if ok else "provide a transition."),
                            p_need, shift_par.value, "m", shift_par))
    # tangents between curve groups: broken-back and reverse curves
    bb = rules.get("broken_back_min_tangent_m")
    for g1, g2 in zip(d.h.groups, d.h.groups[1:]):
        t = g2.ch_start - g1.ch_end
        s1 = math.copysign(1, g1.elements[-1].k0 + g1.elements[-1].k1 or g1.delta)
        s2 = math.copysign(1, g2.elements[0].k0 + g2.elements[0].k1 or g2.delta)
        lbl = f"{r.label} {g1.tag}–{g2.tag}"
        if s1 == s2:
            out.append(CheckResult("broken_back", r.id, lbl, CheckStatus.PASS if t >= bb.value - 1e-9 else CheckStatus.WARNING,
                                   f"Same-direction curves separated by {t:.1f} m of straight vs {bb.value} m: "
                                   + ("acceptable." if t >= bb.value else "broken-back curve – consider one curve."),
                                   t, bb.value, "m", bb))
        else:
            k_end, k_start = g1.elements[-1], g2.elements[0]
            has_tr = k_end.kind == "spiral" and k_start.kind == "spiral"
            need = 0.0 if has_tr else (ls_required(0, k_end.k1)[2] + ls_required(0, k_start.k0)[2])
            out.append(CheckResult("reverse_curve", r.id, lbl, CheckStatus.PASS if t >= need - 1e-6 else CheckStatus.FAIL,
                                   f"Reverse curves separated by {t:.1f} m of straight; "
                                   + ("both have transitions, so they may meet directly." if has_tr else
                                      f"{need:.1f} m needed to change superelevation from one side to the other."),
                                   t, need, "m", npar))
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
        basis = f"SSD {S:.0f} m"
        if kind == "crest":
            need = crest_length_for(S, A, rules.value("eye_height_m"), rules.value("object_height_m"))
        else:
            need = sag_length_for(S, A, rules.value("headlight_height_m"), rules.value("headlight_beam_deg"))
            comfort = sag_comfort_length(V, A, rules.value("sag_comfort_c_rate"))
            if comfort > need:
                need, basis = comfort, "comfort 2√(A·v³/C), which exceeds the headlight-SSD length"
        vmin = rules.value("min_vertical_curve_m") if A > 0 else 0
        if vmin > need:
            need, basis = vmin, f"project minimum length (sight distance needs only {need:.0f} m)"
        vip = d.v.vips[i]
        if vip.l2 is not None and A > 0:
            La, Lb = d.v.equivalent_lengths(i)
            Leff = min(La, Lb)
            what = (f"unsymmetrical {vip.la:.0f} m + {vip.lb:.0f} m; sharper leg equivalent to a symmetric "
                    f"curve of {Leff:.1f} m")
        else:
            Leff, what = L, f"L {L:.0f} m"
        out.append(CheckResult("vertical_curve_length", r.id, lbl,
                               CheckStatus.PASS if Leff >= need - 1e-6 else CheckStatus.FAIL,
                               f"{what} vs required {need:.0f} m ({basis}, A = {A*100:.2f} %)",
                               Leff, need, "m", fpar))
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
            strip, dz = xs.surface_at(tpl, off, d.superelevation(ch))
            z = d.v.level(ch) + dz
            for t in (RelationType.LOCATED_IN, RelationType.DEPENDS_ON_LEVEL):
                if (o.id, d.road.id, t) not in existing:
                    pr.relate(o, d.road, t)
            diff = z - float(o.attr(key))
            if abs(diff) > tolerance_m:
                out.append({"object_id": o.id, "object": o.label, "kind": kind.value, "chainage": round(ch, 2),
                            "offset": round(off, 2), "strip": strip,
                            "superelevation_pct": round(d.superelevation(ch) * 100, 2), "current_level": o.attr(key),
                            "road_surface_level": round(z, 3), "difference_m": round(diff, 3)})
    return out
