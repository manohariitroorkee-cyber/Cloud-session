"""Junction geometric design: at-grade intersections and roundabouts.

ROAD_JUNCTION object (Point at the junction centre) attributes:

    type:  "intersection" (T, Y, cross, multi-leg, staggered) or "roundabout"
    arms:  [{"road": "R1"} ...]  – arm taken from a road alignment that starts or ends here
           or explicit {"name": "N", "bearing_deg": 0, "width_left": 7.6, "width_right": 7.6,
                        "speed_kmh": 50, "priority": "major"}
           width_left / width_right: carriageway edge offsets left / right of the arm
           centreline looking AWAY from the junction (include the median half-width).
    control: "uncontrolled" | "priority" | "signal"            (intersection)
    design_vehicle: key of corner_radius_by_vehicle             (intersection)
    corner: {"type": "simple"} | {"type": "three_centred", "ratio": 2, "end_deflection_deg": 15}
            or {"R": 12} to override the radius at every corner, or per corner "corners": {"N-E": {...}}
    roundabout: {"central_island_radius_m": 20, "circulatory_width_m": 9, "entry_radius_m": 20,
                 "exit_radius_m": 25, "setting": "urban", "flows_pcu_h": {"N-E": {"total": 1800,
                 "weaving": 900}}}           (flows optional – enables the capacity check)

Traffic keeps LEFT and circulates CLOCKWISE (India).  All geometry is in the
project's projected CRS.  Swept-path (turning template) analysis and
signal phasing are not covered.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ...gis.geometry import point_coord
from ...model.core import EngineeringObject, ObjectKind, Project, RelationType
from ...rules.framework import CheckResult, CheckStatus, RuleContext
from . import alignment as hz
from . import cross_section as xs
from .vertical import ssd

ARM_LENGTH_M = 80.0          # how far along each arm the geometry is built


@dataclass
class Arm:
    name: str
    bearing: float           # rad, pointing away from the junction
    w_left: float            # edge offset left of the outward direction (m)
    w_right: float           # edge offset right of the outward direction (m)
    speed: float             # approach design speed km/h
    priority: str = "minor"
    road: EngineeringObject | None = None

    def u(self):
        return math.sin(self.bearing), math.cos(self.bearing)

    def r(self):                                   # right-hand normal of the outward direction
        return math.cos(self.bearing), -math.sin(self.bearing)

    def edge_point(self, c, t: float, side: int):
        """Point at distance t along the arm on its right (+1) or left (−1) edge."""
        ux, uy = self.u(); rx, ry = self.r()
        w = self.w_right if side > 0 else -self.w_left
        return c[0] + t * ux + w * rx, c[1] + t * uy + w * ry

    def lane_point(self, c, t: float):
        """Centre of the INBOUND half (traffic keeps left: inbound side is the outward right side)."""
        ux, uy = self.u(); rx, ry = self.r()
        w = self.w_right / 2
        return c[0] + t * ux + w * rx, c[1] + t * uy + w * ry


@dataclass
class Corner:
    name: str
    arm_a: Arm
    arm_b: Arm
    angle: float             # sector angle between the arms (rad, clockwise a → b)
    curve: hz.Alignment | None
    group: hz.CurveGroup | None
    radius_required: float
    pi: tuple | None


@dataclass
class SightTriangle:
    name: str
    polygon: list[tuple[float, float]]
    distances: tuple[float, float]
    obstructions: list[str] = field(default_factory=list)


@dataclass
class JunctionDesign:
    junction: EngineeringObject
    kind: str
    centre: tuple[float, float]
    arms: list[Arm]
    corners: list[Corner] = field(default_factory=list)
    triangles: list[SightTriangle] = field(default_factory=list)
    roundabout: dict[str, Any] | None = None
    checks: list[CheckResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ arms

def _arm_from_road(pr: Project, j: EngineeringObject, spec: dict, centre) -> Arm:
    from .design import horizontal_of
    road = pr.by_name(spec["road"]) if not isinstance(spec["road"], EngineeringObject) else spec["road"]
    h = horizontal_of(road)
    p0, p1 = h.at(0)[:2], h.at(h.length)[:2]
    d0, d1 = math.dist(p0, centre), math.dist(p1, centre)
    if min(d0, d1) > 2.0:
        raise ValueError(f"road {road.label} does not start or end at the junction (nearest end {min(d0, d1):.1f} m away)")
    # outward bearing: the road's own direction if it starts here, reversed if it ends here
    b = h.at(0)[2] if d0 <= d1 else h.at(h.length)[2] + math.pi
    # templates are symmetric about the centreline, so both edges sit at the same offset
    half = xs.half_section(road.attr("template"))
    w = sum(s.x1 - s.x0 for s in half if s.type in ("median", "carriageway"))
    priority = spec.get("priority", road.attr("priority", "minor"))
    j_rel = (road.id, j.id, RelationType.LOCATED_IN)
    if j_rel not in {(r.source_id, r.target_id, r.type) for r in pr.relationships}:
        pr.relate(road, j, RelationType.LOCATED_IN)
    return Arm(spec.get("name", road.label), hz.wrap(b), w, w, float(road.attr("design_speed_kmh")), priority, road)


def arms_of(pr: Project, j: EngineeringObject) -> list[Arm]:
    centre = tuple(point_coord(j.geometry)[:2])
    arms = []
    for spec in j.attr("arms") or []:
        if "road" in spec:
            arms.append(_arm_from_road(pr, j, spec, centre))
        else:
            arms.append(Arm(spec["name"], math.radians(float(spec["bearing_deg"])), float(spec["width_left"]),
                            float(spec["width_right"]), float(spec.get("speed_kmh", 30)), spec.get("priority", "minor")))
    return sorted(arms, key=lambda a: a.bearing % (2 * math.pi))


# --------------------------------------------------------------- geometry helpers

def _seg_intersect(p1, p2, q1, q2) -> bool:
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2 = orient(q1, q2, p1), orient(q1, q2, p2)
    d3, d4 = orient(p1, p2, q1), orient(p1, p2, q2)
    return (d1 * d2 < 0) and (d3 * d4 < 0)


def point_in_polygon(pt, poly) -> bool:
    x, y = pt
    inside = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def polygons_overlap(a, b) -> bool:
    if any(point_in_polygon(p, b) for p in a) or any(point_in_polygon(p, a) for p in b):
        return True
    ea = list(zip(a, a[1:] + a[:1])); eb = list(zip(b, b[1:] + b[:1]))
    return any(_seg_intersect(p, q, r, s) for p, q in ea for r, s in eb)


def _line_intersection(p, d, q, e):
    den = d[0] * e[1] - d[1] * e[0]
    if abs(den) < 1e-12:
        return None
    t = ((q[0] - p[0]) * e[1] - (q[1] - p[1]) * e[0]) / den
    return p[0] + t * d[0], p[1] + t * d[1]


# ----------------------------------------------------------- intersection

def _corner_spec(j: EngineeringObject, name: str, R: float) -> dict:
    per = (j.attr("corners") or {}).get(name)
    c = per or j.attr("corner") or {"type": "simple"}
    if "R" in c:
        R = float(c["R"])
    if c.get("type") == "three_centred":
        k = float(c.get("ratio", 2.0))
        de = float(c.get("end_deflection_deg", 15.0))
        # centre arc (radius R) is solved to close the corner's deflection
        return {"arcs": [{"R": k * R, "deflection_deg": de}, {"R": R}, {"R": k * R, "deflection_deg": de}],
                "Ls_in": 0, "Ls_out": 0, "Ls_between": [0, 0]}
    return {"R": R}


def design_intersection(pr: Project, j: EngineeringObject, rules: RuleContext) -> JunctionDesign:
    c = tuple(point_coord(j.geometry)[:2])
    try:
        arms = arms_of(pr, j)
    except (KeyError, ValueError) as e:
        return JunctionDesign(j, "intersection", c, [], errors=[f"Junction {j.label}: {e}"])
    d = JunctionDesign(j, "intersection", c, arms)
    if len(arms) < 3:
        d.errors.append(f"Junction {j.label}: an intersection needs at least three arms ({len(arms)} given).")
        return d
    veh = j.attr("design_vehicle", "bus")
    table = rules.value("corner_radius_by_vehicle")
    if veh not in table:
        d.errors.append(f"Junction {j.label}: no corner radius configured for design vehicle '{veh}'.")
        return d
    R_req = float(table[veh])
    # corners between clockwise-adjacent arms
    for i, a in enumerate(arms):
        b = arms[(i + 1) % len(arms)]
        sector = (b.bearing - a.bearing) % (2 * math.pi)
        name = f"{a.name}-{b.name}"
        if sector >= math.pi - 1e-6:
            d.notes.append(f"Corner {name}: arms {math.degrees(sector):.0f}° apart – continuous kerb, no corner curve.")
            d.corners.append(Corner(name, a, b, sector, None, None, R_req, None))
            continue
        pa = a.edge_point(c, ARM_LENGTH_M, +1)      # far point on A's right edge (faces B)
        pb = b.edge_point(c, ARM_LENGTH_M, -1)      # far point on B's left edge (faces A)
        ua, ub = a.u(), b.u()
        pi = _line_intersection(pa, ua, pb, ub)
        spec = _corner_spec(j, name, R_req)
        curve = hz.from_pis([pa, pi, pb], {1: spec})
        if curve.errors:
            d.errors += [f"Corner {name}: {e}" for e in curve.errors]
            d.corners.append(Corner(name, a, b, sector, None, None, R_req, pi))
            continue
        d.corners.append(Corner(name, a, b, sector, curve, curve.groups[0], R_req, pi))
    _intersection_checks(pr, d, rules)
    return d


def _intersection_checks(pr: Project, d: JunctionDesign, rules: RuleContext) -> None:
    j = d.junction
    # angle of intersection: each minor arm against the major road axis
    amin = rules.get("min_intersection_angle_deg")
    majors = [a for a in d.arms if a.priority == "major"]
    for a in d.arms:
        if a.priority == "major" or not majors:
            continue
        ang = min(abs(((a.bearing - m.bearing) % math.pi)) for m in majors)
        acute = math.degrees(min(ang, math.pi - ang))
        d.checks.append(CheckResult("intersection_angle", j.id, f"{j.label} arm {a.name}",
                                    CheckStatus.PASS if acute >= amin.value - 1e-9 else CheckStatus.FAIL,
                                    f"Arm {a.name} meets the major road at {acute:.1f}° vs minimum {amin.value}°",
                                    acute, amin.value, "°", amin))
    if len(d.arms) > 4:
        d.checks.append(CheckResult("number_of_arms", j.id, j.label, CheckStatus.WARNING,
                                    f"{len(d.arms)} arms: multi-leg junction – consider a roundabout or realignment.",
                                    len(d.arms), 4, "arms"))
    # corner radii
    for cn in d.corners:
        if cn.group is None:
            continue
        rmin = min(cn.group.radii)
        par = rules.get("corner_radius_by_vehicle")
        d.checks.append(CheckResult("corner_radius", j.id, f"{j.label} corner {cn.name}",
                                    CheckStatus.PASS if rmin >= cn.radius_required - 1e-9 else CheckStatus.FAIL,
                                    f"Kerb radius {rmin:.1f} m vs {cn.radius_required:.1f} m for design vehicle "
                                    f"'{j.attr('design_vehicle', 'bus')}' ({cn.group.kind})",
                                    rmin, cn.radius_required, "m", par))
        t_avail = ARM_LENGTH_M
        if max(cn.group.t_in, cn.group.t_out) > t_avail:
            d.errors.append(f"Corner {cn.name}: kerb curve needs {max(cn.group.t_in, cn.group.t_out):.1f} m of arm.")
    # sight triangles
    control = j.attr("control", "uncontrolled")
    if control == "signal":
        d.notes.append("Signal control: approach sight triangles are not checked; check stop-line and signal-head visibility.")
        return
    fpar = rules.get("f_longitudinal")
    obstacles = _obstacles(pr, j)
    for i, a in enumerate(d.arms):
        b = d.arms[(i + 1) % len(d.arms)]
        sector = (b.bearing - a.bearing) % (2 * math.pi)
        if sector >= math.pi - 1e-6:
            continue
        # inbound lane lines of A and B meet at the conflict point
        la0, lb0 = a.lane_point(d.centre, 0), b.lane_point(d.centre, 0)
        cp = _line_intersection(la0, a.u(), lb0, b.u())
        if cp is None:
            continue
        if control == "priority" and (a.priority == "major") != (b.priority == "major"):
            minor, major = (a, b) if a.priority != "major" else (b, a)
            da = rules.value("minor_road_setback_m")
            db = major.speed / 3.6 * rules.value("major_road_visibility_time_s")
            dist = {minor.name: da, major.name: db}
            basis = (f"priority: minor set-back {da:.1f} m, major visibility "
                     f"{db:.0f} m = V·{rules.value('major_road_visibility_time_s')} s")
            par = rules.get("major_road_visibility_time_s")
        else:
            dist = {x.name: ssd(x.speed, rules.value("reaction_time_s"), fpar.lookup(x.speed)) for x in (a, b)}
            basis = "uncontrolled: stopping sight distance on both approaches"
            par = fpar
        pa = _along(cp, a, dist[a.name]); pb = _along(cp, b, dist[b.name])
        tri = [cp, pa, pb]
        st = SightTriangle(f"{a.name}/{b.name}", tri, (dist[a.name], dist[b.name]))
        for name, poly in obstacles:
            if (len(poly) == 1 and point_in_polygon(poly[0], tri)) or (len(poly) > 2 and polygons_overlap(tri, poly)):
                st.obstructions.append(name)
        d.triangles.append(st)
        d.checks.append(CheckResult("sight_triangle", j.id, f"{j.label} {st.name}",
                                    CheckStatus.PASS if not st.obstructions else CheckStatus.FAIL,
                                    f"Sight triangle ({basis}; {dist[a.name]:.0f} m × {dist[b.name]:.0f} m) "
                                    + ("clear." if not st.obstructions else "obstructed by " + ", ".join(st.obstructions)),
                                    len(st.obstructions), 0, "objects", par))


def _along(cp, arm: Arm, dist: float):
    ux, uy = arm.u()
    return cp[0] + dist * ux, cp[1] + dist * uy


def _obstacles(pr: Project, j: EngineeringObject) -> list[tuple[str, list]]:
    out = []
    for o in pr.objects.values():
        if o.id == j.id:
            continue
        g = o.geometry
        if o.kind in (ObjectKind.PLOT, ObjectKind.PARCEL, ObjectKind.SUBSTATION) and g["type"] == "Polygon":
            out.append((o.label, [tuple(p[:2]) for p in g["coordinates"][0][:-1]]))
        elif o.kind in (ObjectKind.TRANSFORMER, ObjectKind.FEEDER_PILLAR, ObjectKind.NETWORK_CABINET,
                        ObjectKind.POLE) and g["type"] == "Point":
            out.append((o.label, [tuple(g["coordinates"][:2])]))
        elif o.attr("sight_obstruction") and g["type"] in ("Point", "Polygon"):
            pts = [tuple(g["coordinates"][:2])] if g["type"] == "Point" else [tuple(p[:2]) for p in g["coordinates"][0][:-1]]
            out.append((o.label, pts))
    return out


# -------------------------------------------------------------- roundabout

def _fillet_line_circle(c, R_o: float, arm: Arm, side: int, r_f: float):
    """Kerb arc of radius r_f tangent to an arm edge (side +1 right, −1 left) and
    externally tangent to the inscribed circle (radius R_o) about centre c.
    Returns (fillet centre, tangent point on edge, tangent point on circle)."""
    ux, uy = arm.u(); rx, ry = arm.r()
    w = arm.w_right if side > 0 else arm.w_left
    off = side * (w + r_f)                             # fillet centre lies beyond the edge
    # centre = c + t·u + off·r with |centre − c| = R_o + r_f
    D = R_o + r_f
    if abs(off) > D:
        return None
    t = math.sqrt(D * D - off * off)
    fc = (c[0] + t * ux + off * rx, c[1] + t * uy + off * ry)
    te = (c[0] + t * ux + side * w * rx, c[1] + t * uy + side * w * ry)
    k = R_o / D
    tc = (c[0] + (fc[0] - c[0]) * k, c[1] + (fc[1] - c[1]) * k)
    return fc, te, tc


def design_roundabout(pr: Project, j: EngineeringObject, rules: RuleContext) -> JunctionDesign:
    c = tuple(point_coord(j.geometry)[:2])
    try:
        arms = arms_of(pr, j)
    except (KeyError, ValueError) as e:
        return JunctionDesign(j, "roundabout", c, [], errors=[f"Junction {j.label}: {e}"])
    d = JunctionDesign(j, "roundabout", c, arms)
    p = j.attr("roundabout") or {}
    try:
        Rci = float(p["central_island_radius_m"]); Wc = float(p["circulatory_width_m"])
        Ren = float(p["entry_radius_m"]); Rex = float(p["exit_radius_m"])
    except KeyError as e:
        d.errors.append(f"Roundabout {j.label}: {e.args[0]} missing.")
        return d
    setting = p.get("setting", "urban")
    Ro = Rci + Wc
    # clockwise circulation, keep left: inbound traffic is on the arm's outward-right side,
    # so the ENTRY kerb is the right edge and the EXIT kerb the left edge of each arm.
    fil = {}
    for a in arms:
        en = _fillet_line_circle(c, Ro, a, +1, Ren)
        ex = _fillet_line_circle(c, Ro, a, -1, Rex)
        if en is None or ex is None:
            d.errors.append(f"Arm {a.name}: entry/exit kerb radius cannot reach the circle – arm too wide for the island.")
            continue
        fil[a.name] = (en, ex)
    ang = lambda pt: math.atan2(pt[0] - c[0], pt[1] - c[1])        # bearing from centre
    weave = []
    for i, a in enumerate(arms):
        b = arms[(i + 1) % len(arms)]
        if a.name not in fil or b.name not in fil:
            continue
        # traffic entering from A circulates clockwise; the next exit is arm B's exit kerb
        start = ang(fil[a.name][0][2]); end = ang(fil[b.name][1][2])
        sweep = (end - start) % (2 * math.pi)
        length = Ro * sweep
        weave.append({"section": f"{a.name}→{b.name}", "length_m": length, "width_m": Wc,
                      "entry_width_m": a.w_right, "exit_width_m": b.w_left})
    d.roundabout = {"central_island_radius_m": Rci, "circulatory_width_m": Wc, "inscribed_radius_m": Ro,
                    "inscribed_diameter_m": 2 * Ro, "entry_radius_m": Ren, "exit_radius_m": Rex,
                    "setting": setting, "fillets": fil, "weaving": weave}
    _roundabout_checks(d, rules, p)
    return d


def _roundabout_checks(d: JunctionDesign, rules: RuleContext, p: dict) -> None:
    j, rb = d.junction, d.roundabout
    setting = rb["setting"]
    er = rules.get("roundabout_entry_radius_range_m")
    lo, hi = er.value[setting]
    d.checks.append(CheckResult("entry_radius", j.id, j.label,
                                CheckStatus.PASS if lo <= rb["entry_radius_m"] <= hi else CheckStatus.FAIL,
                                f"Entry radius {rb['entry_radius_m']:.1f} m vs {lo}–{hi} m ({setting})",
                                rb["entry_radius_m"], lo, "m", er))
    xr = rules.get("roundabout_exit_to_entry_ratio_min")
    d.checks.append(CheckResult("exit_radius", j.id, j.label,
                                CheckStatus.PASS if rb["exit_radius_m"] >= xr.value * rb["entry_radius_m"] - 1e-9 else CheckStatus.FAIL,
                                f"Exit radius {rb['exit_radius_m']:.1f} m vs ≥ {xr.value} × entry radius",
                                rb["exit_radius_m"], xr.value * rb["entry_radius_m"], "m", xr))
    cr = rules.get("roundabout_central_island_to_entry_ratio")
    need = cr.value * rb["entry_radius_m"]
    d.checks.append(CheckResult("central_island_radius", j.id, j.label,
                                CheckStatus.PASS if rb["central_island_radius_m"] >= need - 1e-9 else CheckStatus.FAIL,
                                f"Central island radius {rb['central_island_radius_m']:.1f} m vs {cr.value} × entry radius = {need:.1f} m",
                                rb["central_island_radius_m"], need, "m", cr))
    wl = rules.get("weaving_length_to_width_min")
    for w in rb["weaving"]:
        need = wl.value * w["width_m"]
        d.checks.append(CheckResult("weaving_length", j.id, f"{j.label} {w['section']}",
                                    CheckStatus.PASS if w["length_m"] >= need - 1e-9 else CheckStatus.FAIL,
                                    f"Weaving length {w['length_m']:.1f} m vs {wl.value} × width {w['width_m']:.1f} m = {need:.1f} m",
                                    w["length_m"], need, "m", wl))
    flows = p.get("flows_pcu_h") or {}
    wp = rules.get("wardrop_coefficient")
    for w in rb["weaving"]:
        f = flows.get(w["section"].replace("→", "-"))
        if not f:
            continue
        e = (w["entry_width_m"] + w["exit_width_m"]) / 2
        ww, l = w["width_m"], w["length_m"]
        pr_ = float(f["weaving"]) / float(f["total"])
        Qp = wp.value * ww * (1 + e / ww) * (1 - pr_ / 3) / (1 + ww / l)
        w["capacity_pcu_h"] = Qp
        d.checks.append(CheckResult("weaving_capacity", j.id, f"{j.label} {w['section']}",
                                    CheckStatus.PASS if float(f["total"]) <= Qp else CheckStatus.FAIL,
                                    f"Design flow {f['total']} PCU/h vs capacity {Qp:.0f} PCU/h "
                                    f"(Wardrop: {wp.value}·w(1+e/w)(1−p/3)/(1+w/l), w={ww:.1f}, e={e:.1f}, l={l:.1f}, p={pr_:.2f})",
                                    float(f["total"]), Qp, "PCU/h", wp))


def design_junction(pr: Project, j: EngineeringObject, rules: RuleContext) -> JunctionDesign:
    t = j.attr("type", "intersection")
    if t == "roundabout":
        return design_roundabout(pr, j, rules)
    if t == "intersection":
        return design_intersection(pr, j, rules)
    return JunctionDesign(j, t, tuple(point_coord(j.geometry)[:2]), [], errors=[f"Unknown junction type {t!r}."])


def junction_features(d: JunctionDesign) -> list[dict]:
    """GeoJSON features for the map: kerb returns, sight triangles, roundabout circles."""
    feats = []
    for cn in d.corners:
        if cn.curve and cn.group:
            g = cn.group
            pts = []
            for e in g.elements:
                n = max(2, math.ceil(e.length / 1.0))
                pts += [e.point(e.length * i / n) for i in range(n)]
            pts.append(g.elements[-1].end()[:2])
            feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": [list(p) for p in pts]},
                          "properties": {"kind": "kerb_return", "corner": cn.name, "radii_m": g.radii}})
    for st in d.triangles:
        ring = [list(p) for p in st.polygon] + [list(st.polygon[0])]
        feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
                      "properties": {"kind": "sight_triangle", "name": st.name, "obstructions": st.obstructions}})
    if d.roundabout:
        for key, R in (("central_island", d.roundabout["central_island_radius_m"]),
                       ("inscribed_circle", d.roundabout["inscribed_radius_m"])):
            ring = [[d.centre[0] + R * math.sin(t * math.pi / 36), d.centre[1] + R * math.cos(t * math.pi / 36)] for t in range(73)]
            feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
                          "properties": {"kind": key, "radius_m": R}})
        for name, ((fc_e, te_e, tc_e), (fc_x, te_x, tc_x)) in d.roundabout["fillets"].items():
            for kind, fc, te, tc, R in (("entry_kerb", fc_e, te_e, tc_e, d.roundabout["entry_radius_m"]),
                                        ("exit_kerb", fc_x, te_x, tc_x, d.roundabout["exit_radius_m"])):
                a0 = math.atan2(te[0] - fc[0], te[1] - fc[1]); a1 = math.atan2(tc[0] - fc[0], tc[1] - fc[1])
                sw = hz.wrap(a1 - a0)
                pts = [[fc[0] + R * math.sin(a0 + sw * i / 20), fc[1] + R * math.cos(a0 + sw * i / 20)] for i in range(21)]
                feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": pts},
                              "properties": {"kind": kind, "arm": name, "radius_m": R}})
    return feats
