"""Storm-water drainage network and Rational-method design.

Objects
-------
CATCHMENT     Polygon. attributes: surfaces {surface: fraction} (fractions sum to 1)
              or runoff_coefficient; inlet_time_min, or flow_length_m + overland_slope
              (Kirpich); impervious_pct, overland_slope, flow_length_m (for SWMM).
              relationship DRAINS_TO → drain node.
DRAIN_NODE    Point. ground_level (or taken from TERRAIN_POINTs around it);
              external_inflow_m3s (optional – flow arriving from outside the drawing).
DRAIN_OUTFALL Point. ground_level, invert_level, tailwater_level (optional – highest water
              level of the receiving channel, e.g. HFL; used as a fixed SWMM boundary).
Existing objects (status "existing") are surveyed facts: existing drains are not resized but
assessed for capacity, flow already carried, and residual capacity (see existing.py);
existing catchments (developed areas, villages) load them.  A catchment with levels_fixed
and outlet_level (a village) must be able to discharge freely at that level.
STORM_DRAIN   LineString drawn upstream → downstream. shape (circular | rectangular |
              trapezoidal), diameter_mm or width_m + height_m (+ side_slope H:V),
              closed (box), lining (Manning n key), us_invert, ds_invert.
              relationships UPSTREAM_NODE / DOWNSTREAM_NODE.

Design (per drain, upstream first) – Rational method, Q = C·i·A / 360
(Q m³/s, i mm/h, A ha):
    ΣCA       = Σ C·A of catchments entering upstream (incl. carried by incoming drains)
    tc        = max over contributing paths of (catchment inlet time + drain travel times)
    i         = IDF(tc, design return period)
    Q         = ΣCA · i / 360
Drains are computed upstream first: each drain's travel time (length ÷ its own
normal-flow velocity) is added to the time of concentration of the drains below it.
Where a drain cannot carry its flow, travel time uses the full-section velocity at
capacity (Q_capacity ÷ A_full) and this is noted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...gis.geometry import distance, endpoints, line_length, point_coord, polygon_area
from ...model.core import EngineeringObject, ObjectKind, Project, RelationType
from ...rules.framework import CheckResult, CheckStatus, RuleContext
from ..common.open_channel import ChannelFlow, Section, normal_flow
from .rainfall import IDF, kirpich_tc_min

METHOD = "Rational method Q = C·i·A/360 with IDF intensity at time of concentration; Manning normal-depth hydraulics"
NODE_KINDS = (ObjectKind.DRAIN_NODE, ObjectKind.DRAIN_OUTFALL)
TOL = 0.5


@dataclass
class Drain:
    obj: EngineeringObject
    us: EngineeringObject
    ds: EngineeringObject
    length: float
    section: Section
    lining: str
    us_invert: float
    ds_invert: float
    existing: bool = False
    silt_m: float = 0.0

    @property
    def flow_section(self) -> Section:
        """Section available to the flow: an open drain's bed is raised by the silt in it."""
        sec = self.section
        if self.silt_m <= 0 or sec.shape == "circular":
            return sec
        return Section(sec.shape, max(sec.depth - self.silt_m, 1e-3), sec.width + 2 * sec.side_slope * self.silt_m,
                       sec.side_slope, sec.closed)

    @property
    def slope(self) -> float:
        return (self.us_invert - self.ds_invert) / self.length


@dataclass
class Catchment:
    obj: EngineeringObject
    node: EngineeringObject
    area_ha: float
    c: float
    tc_min: float


@dataclass
class DrainageNetwork:
    project: Project
    nodes: dict[str, EngineeringObject]
    drains: dict[str, Drain]
    catchments: list[Catchment]
    order: list[str]
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def incoming(self, nid: str) -> list[Drain]:
        return [d for d in self.drains.values() if d.ds.id == nid]

    def outgoing(self, nid: str) -> list[Drain]:
        return [d for d in self.drains.values() if d.us.id == nid]


def section_of(o: EngineeringObject) -> Section:
    shape = o.attr("shape", "circular")
    if shape == "circular":
        d = o.attr("diameter_mm") / 1000.0
        return Section("circular", d, d, closed=True)
    if shape in ("rectangular", "trapezoidal"):
        return Section(shape, float(o.attr("height_m")), float(o.attr("width_m")),
                       float(o.attr("side_slope", 0.0)) if shape == "trapezoidal" else 0.0,
                       bool(o.attr("closed", False)))
    raise ValueError(f"unknown drain shape {shape!r}")


def composite_c(o: EngineeringObject, rules: RuleContext) -> float:
    if o.attr("runoff_coefficient") is not None:
        return float(o.attr("runoff_coefficient"))
    surfaces: dict[str, float] = o.attr("surfaces") or {}
    if not surfaces:
        raise ValueError(f"Catchment {o.label}: give surfaces or runoff_coefficient")
    if abs(sum(surfaces.values()) - 1) > 1e-6:
        raise ValueError(f"Catchment {o.label}: surface fractions sum to {sum(surfaces.values()):.3f}, not 1")
    table = rules.value("runoff_coefficients")
    missing = [s for s in surfaces if s not in table]
    if missing:
        raise ValueError(f"Catchment {o.label}: no runoff coefficient configured for {', '.join(missing)}")
    return sum(f * table[s] for s, f in surfaces.items())


def fill_ground_from_survey(pr: Project, objs) -> list[str]:
    """Give points without a ground level the level interpolated from the survey points (TIN)."""
    from ..roads.design import terrain
    todo = [o for o in objs if o.attr("ground_level") is None]
    tin = terrain(pr) if todo else None
    notes = []
    for o in todo:
        if tin is None:
            break
        c = point_coord(o.geometry)
        z = tin.level(c[0], c[1])
        if z is not None:
            o.attributes["ground_level"] = round(z, 3)
            notes.append(f"{o.label}: ground level {z:.3f} m taken from the survey points.")
    return notes


def build_network(pr: Project, rules: RuleContext) -> DrainageNetwork:
    nodes = {o.id: o for o in pr.of_kind(*NODE_KINDS)}
    notes = fill_ground_from_survey(pr, nodes.values())
    errors: list[str] = []
    drains: dict[str, Drain] = {}
    for o in pr.of_kind(ObjectKind.STORM_DRAIN):
        us, ds = pr.related(o, RelationType.UPSTREAM_NODE), pr.related(o, RelationType.DOWNSTREAM_NODE)
        if len(us) != 1 or len(ds) != 1 or us[0].id not in nodes or ds[0].id not in nodes:
            errors.append(f"Drain {o.label}: needs one upstream and one downstream drain node/outfall.")
            continue
        us, ds = us[0], ds[0]
        try:
            sec = section_of(o)
        except (TypeError, ValueError) as e:
            errors.append(f"Drain {o.label}: section incomplete ({e}).")
            continue
        a, b = endpoints(o.geometry)
        for end, node, which in ((a, us, "start"), (b, ds, "end")):
            gap = distance(end, point_coord(node.geometry))
            if gap > TOL:
                errors.append(f"Drain {o.label}: {which} vertex {gap:.2f} m from {node.label}.")
        if o.attr("us_invert") is None or o.attr("ds_invert") is None:
            errors.append(f"Drain {o.label}: inverts missing.")
            continue
        if o.attr("lining") is None:
            errors.append(f"Drain {o.label}: lining missing (it sets Manning's n).")
            continue
        d = Drain(o, us, ds, line_length(o.geometry), sec, str(o.attr("lining")).lower(),
                  float(o.attr("us_invert")), float(o.attr("ds_invert")), o.status.value == "existing",
                  float(o.attr("silt_depth_m") or 0.0))
        if d.silt_m and sec.shape == "circular":
            errors.append(f"Drain {o.label}: silt depth is modelled for open and box drains only; "
                          "for a silted pipe enter the clear diameter.")
        if d.slope <= 0:
            errors.append(f"Drain {o.label}: adverse or flat bed slope.")
        drains[o.id] = d
    for nid, n in nodes.items():
        if n.attr("ground_level") is None:
            errors.append(f"{n.label}: ground_level missing.")
        out = [d for d in drains.values() if d.us.id == nid]
        if n.kind == ObjectKind.DRAIN_NODE and len(out) != 1:
            errors.append(f"Drain node {n.label}: {len(out)} outgoing drains (needs exactly one).")

    catchments: list[Catchment] = []
    for o in pr.of_kind(ObjectKind.CATCHMENT):
        tgt = pr.related(o, RelationType.DRAINS_TO)
        if len(tgt) != 1 or tgt[0].id not in nodes:
            errors.append(f"Catchment {o.label}: must drain to exactly one drain node.")
            continue
        try:
            c = composite_c(o, rules)
            if o.attr("inlet_time_min") is not None:
                tc = float(o.attr("inlet_time_min"))
            else:
                tc = kirpich_tc_min(float(o.attr("flow_length_m")), float(o.attr("overland_slope")))
                tc = max(tc, rules.value("min_inlet_time_min"))
        except (TypeError, ValueError) as e:
            errors.append(str(e) if "Catchment" in str(e) else f"Catchment {o.label}: {e}")
            continue
        catchments.append(Catchment(o, tgt[0], polygon_area(o.geometry) / 10_000, c, tc))

    # topological order (Kahn) on drains
    indeg = {k: len([x for x in drains.values() if x.ds.id == d.us.id]) for k, d in drains.items()}
    ready = sorted((k for k, v in indeg.items() if v == 0), key=lambda k: drains[k].obj.label)
    order: list[str] = []
    while ready:
        k = ready.pop(0)
        order.append(k)
        for k2, d2 in drains.items():
            if d2.us.id == drains[k].ds.id:
                indeg[k2] -= 1
                if indeg[k2] == 0:
                    ready.append(k2)
    if len(order) != len(drains):
        errors.append("Loop in drainage network.")
    return DrainageNetwork(pr, nodes, drains, catchments, order, errors, notes)


@dataclass
class DrainDesign:
    drain: Drain
    ca_ha: float
    area_ha: float
    tc_min: float
    intensity: float
    flow: float
    manning_n: float
    state: ChannelFlow
    travel_min: float
    ext_flow: float = 0.0
    checks: list[CheckResult] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(c.status == CheckStatus.FAIL for c in self.checks)

    def row(self) -> dict[str, Any]:
        d, s = self.drain, self.state
        size = (f"Ø{d.section.depth*1000:.0f}" if d.section.shape == "circular"
                else f"{d.section.width:.2f}×{d.section.depth:.2f}" + (" box" if d.section.closed else ""))
        return {"drain": d.obj.label, "from": d.us.label, "to": d.ds.label, "length_m": round(d.length, 1),
                "section": size, "slope_1_in": round(1 / d.slope), "area_ha": round(self.area_ha, 3),
                "ca_ha": round(self.ca_ha, 3), "tc_min": round(self.tc_min, 1),
                "i_mm_h": round(self.intensity, 1), "q_m3s": round(self.flow, 4),
                "q_cap_m3s": round(s.q_capacity, 4), "depth_ratio": round(s.depth_ratio, 3) if s.capacity_ok else "full",
                "velocity_ms": round(s.velocity, 2) if s.capacity_ok else "surcharged",
                "result": "FAIL" if self.failed else "PASS"}


@dataclass
class DrainageDesignResult:
    method: str
    idf_source: str
    return_period: float
    drains: list[DrainDesign]
    checks: list[CheckResult]
    errors: list[str]
    notes: list[str] = field(default_factory=list)
    existing: list = field(default_factory=list)       # ExistingDrainAssessment (existing.py)

    @property
    def failing(self) -> list[DrainDesign]:
        return [d for d in self.drains if d.failed]

    def all_checks(self) -> list[CheckResult]:
        return [c for d in self.drains for c in d.checks] + self.checks


def existing_only(net: DrainageNetwork) -> DrainageNetwork:
    """The network as it is today: existing drains loaded by existing catchments only."""
    drains = {k: d for k, d in net.drains.items() if d.existing}
    return DrainageNetwork(net.project, net.nodes, drains,
                           [c for c in net.catchments if c.obj.status.value == "existing"],
                           [k for k in net.order if k in drains], list(net.errors), list(net.notes))


def design_network(net: DrainageNetwork, rules: RuleContext, idf: IDF,
                   return_period: float, area_type: str, _assess_existing: bool = True) -> DrainageDesignResult:
    general: list[CheckResult] = []
    par = rules.get("return_period_years")
    rng = par.value.get(area_type)
    if rng is None:
        general.append(CheckResult("return_period", net.project.id, net.project.name, CheckStatus.NOT_EVALUATED,
                                   f"No recommended return period configured for area type '{area_type}'",
                                   return_period, None, "years", par))
    else:
        general.append(CheckResult("return_period", net.project.id, net.project.name,
                                   CheckStatus.PASS if return_period >= rng[0] else CheckStatus.FAIL,
                                   f"Design return period {return_period} years vs recommended {rng[0]}–{rng[1]} years "
                                   f"for {area_type}", return_period, rng[0], "years", par))
    rc = rules.get("runoff_coefficient_range")
    for ct in net.catchments:
        for s, f in (ct.obj.attr("surfaces") or {}).items():
            lo_hi = rc.value.get(s)
            cval = rules.value("runoff_coefficients")[s]
            if lo_hi and not lo_hi[0] <= cval <= lo_hi[1]:
                general.append(CheckResult("runoff_coefficient", ct.obj.id, ct.obj.label, CheckStatus.WARNING,
                                           f"Adopted C={cval} for '{s}' outside guidance range {lo_hi}", cval,
                                           None, "-", rc))
    if net.errors:
        return DrainageDesignResult(METHOD, idf.source, return_period, [], general, list(net.errors))

    errors: list[str] = []
    notes: list[str] = []
    out: list[DrainDesign] = []
    # contributions entering at each node
    at_node: dict[str, list[Catchment]] = {}
    for ct in net.catchments:
        at_node.setdefault(ct.node.id, []).append(ct)
    carried: dict[str, tuple[float, float, float, float]] = {}   # drain id -> (ΣCA, ΣA, tc at its end, external Q)

    for k in net.order:
        d = net.drains[k]
        table = rules.value("manning_n_drains")
        if d.lining not in table:
            errors.append(f"Drain {d.obj.label}: no Manning n configured for lining '{d.lining}'.")
            continue
        n = float(table[d.lining])
        ca = sum(c.c * c.area_ha for c in at_node.get(d.us.id, []))
        area = sum(c.area_ha for c in at_node.get(d.us.id, []))
        tcs = [c.tc_min for c in at_node.get(d.us.id, [])]
        ext = float(d.us.attr("external_inflow_m3s") or 0.0)
        for inc in net.incoming(d.us.id):
            if inc.obj.id in carried:
                ca_i, a_i, tc_i, ext_i = carried[inc.obj.id]
                ca += ca_i; area += a_i; tcs.append(tc_i); ext += ext_i
        tc = max(tcs) if tcs else rules.value("min_inlet_time_min")
        try:
            i = idf.intensity(tc, return_period)
        except (KeyError, ValueError) as e:
            errors.append(f"Drain {d.obj.label}: {e}")
            continue
        q = ca * i / 360.0 + ext
        sec = d.flow_section
        st = normal_flow(sec, d.slope, n, q)
        if st.capacity_ok:
            v = st.velocity
        else:
            # surcharged: the true velocity is unknown until the drain is resized; use the faster of the
            # capacity velocity and Q/A_full so downstream tc (and hence intensity) is not understated
            v = max(st.q_capacity / sec.full_area(), q / sec.full_area())
            notes.append(f"Drain {d.obj.label}: surcharged – travel time uses {v:.2f} m/s (the larger of the "
                         f"capacity velocity and Q/A_full) so downstream intensity is not understated; resize and rerun.")
        travel = d.length / v / 60.0 if v > 0 else 0.0
        carried[k] = (ca, area, tc + travel, ext)
        dd = DrainDesign(d, ca, area, tc, i, q, n, st, travel, ext)
        if not d.existing:                       # existing drains are assessed, not redesigned (existing.py)
            dd.checks = _checks(dd, rules)
            if dd.failed:
                dd.alternatives = _alternatives(dd, rules)
        out.append(dd)
    res = DrainageDesignResult(METHOD, idf.source, return_period, out, general, errors)
    res.notes = list(net.notes) + notes
    if _assess_existing and not errors:
        from . import existing as ex
        ex.assess(net, res, rules, idf, return_period, area_type)
    return res


def _checks(dd: DrainDesign, rules: RuleContext) -> list[CheckResult]:
    d, s = dd.drain, dd.state
    oid, lbl = d.obj.id, d.obj.label
    res: list[CheckResult] = []
    res.append(CheckResult("capacity", oid, lbl, CheckStatus.PASS if s.capacity_ok else CheckStatus.FAIL,
                           f"Q {dd.flow:.3f} m³/s vs section capacity {s.q_capacity:.3f} m³/s",
                           dd.flow, s.q_capacity, "m³/s"))
    if d.section.shape == "circular":
        par = rules.get("max_depth_ratio_pipe")
        ok = s.capacity_ok and s.depth_ratio <= par.value + 1e-9
        res.append(CheckResult("depth_ratio", oid, lbl, CheckStatus.PASS if ok else CheckStatus.FAIL,
                               f"d/D {s.depth_ratio:.3f} vs maximum {par.value}", s.depth_ratio, par.value, "d/D", par))
        par = rules.get("min_pipe_diameter_mm")
        res.append(CheckResult("min_diameter", oid, lbl,
                               CheckStatus.PASS if d.section.depth * 1000 >= par.value else CheckStatus.FAIL,
                               f"Ø {d.section.depth*1000:.0f} mm vs minimum {par.value} mm",
                               d.section.depth * 1000, par.value, "mm", par))
    else:
        par = rules.get("min_freeboard_m")
        fb = d.section.depth - s.depth
        ok = s.capacity_ok and fb >= par.value - 1e-9
        res.append(CheckResult("freeboard", oid, lbl, CheckStatus.PASS if ok else CheckStatus.FAIL,
                               f"Freeboard {fb:.2f} m vs minimum {par.value} m", fb, par.value, "m", par))
    cap = s.capacity_ok
    par = rules.get("min_velocity")
    res.append(CheckResult("min_velocity", oid, lbl,
                           CheckStatus.NOT_EVALUATED if not cap else
                           (CheckStatus.PASS if s.velocity >= par.value else CheckStatus.FAIL),
                           f"V {s.velocity:.2f} m/s vs self-cleansing {par.value} m/s" if cap
                           else "Capacity exceeded – velocity check deferred", s.velocity if cap else None,
                           par.value, "m/s", par))
    par = rules.get("max_velocity")
    res.append(CheckResult("max_velocity", oid, lbl,
                           CheckStatus.NOT_EVALUATED if not cap else
                           (CheckStatus.PASS if s.velocity <= par.value else CheckStatus.FAIL),
                           f"V {s.velocity:.2f} m/s vs maximum {par.value} m/s" if cap
                           else "Capacity exceeded – velocity check deferred", s.velocity if cap else None,
                           par.value, "m/s", par))
    return res


def _alternatives(dd: DrainDesign, rules: RuleContext) -> list[str]:
    d = dd.drain
    fails = {c.check for c in dd.checks if c.status == CheckStatus.FAIL}
    out: list[str] = []
    if fails & {"capacity", "depth_ratio", "freeboard", "min_diameter"}:
        if d.section.shape == "circular":
            dd_max = rules.value("max_depth_ratio_pipe")
            for dia in rules.value("drain_pipe_diameters_mm"):
                if dia <= d.section.depth * 1000 or dia < rules.value("min_pipe_diameter_mm"):
                    continue
                s = normal_flow(Section("circular", dia / 1000, dia / 1000, closed=True), d.slope, dd.manning_n, dd.flow)
                if s.capacity_ok and s.depth_ratio <= dd_max:
                    out.append(f"Use Ø{dia} mm at the same slope: d/D {s.depth_ratio:.2f}, V {s.velocity:.2f} m/s.")
                    break
            else:
                out.append("No configured pipe size suffices at this slope; consider a box drain or steeper grade.")
        else:
            fb = rules.value("min_freeboard_m")
            w = d.section.width
            for _ in range(60):
                w = round(w + 0.1, 2)
                sec = Section(d.section.shape, d.section.depth, w, d.section.side_slope, d.section.closed)
                s = normal_flow(sec, d.slope, dd.manning_n, dd.flow)
                if s.capacity_ok and d.section.depth - s.depth >= fb:
                    out.append(f"Widen to {w:.2f} m (same depth {d.section.depth:.2f} m): flow depth {s.depth:.2f} m, "
                               f"V {s.velocity:.2f} m/s.")
                    break
            else:
                out.append("Widening alone insufficient within +6 m; increase depth or grade.")
    if "min_velocity" in fails:
        out.append("Velocity below self-cleansing: steepen bed, or reduce section width (low-flow channel).")
    if "max_velocity" in fails:
        out.append("Velocity above limit: provide drops/energy dissipation or flatten the bed.")
    return out
