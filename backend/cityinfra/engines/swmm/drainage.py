"""EPA SWMM adapter for storm-water drainage.

Builds subcatchments (from catchment polygons), a rain gauge carrying the
design-storm hyetograph (alternating block from the project IDF), drain
nodes, outfalls and conduits (circular, rectangular open/closed,
trapezoidal), runs SWMM with dynamic-wave routing, and returns peak flows,
depths, surcharge and flooding per object.

Catchments need, for SWMM: impervious_pct, overland_slope (m/m) and
flow_length_m (subcatchment width = area / flow length).  Missing values are
reported as errors – they are never assumed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...engineering.drainage.network import DrainageNetwork
from ...engineering.drainage.rainfall import IDF, alternating_block
from ...gis.geometry import line_coords, point_coord
from ...model.core import ObjectKind
from ...rules.framework import RuleContext
from ..base import EngineError, EngineRun, IdMap, fnum
from .runner import run_swmm


@dataclass
class DrainResult:
    object_id: str
    peak_flow: float          # m³/s
    max_depth_ratio: float
    peak_velocity: float


@dataclass
class DrainNodeResult:
    object_id: str
    max_head: float
    peak_flooding: float      # m³/s
    surcharged: bool


@dataclass
class DrainageSwmmResult:
    run: EngineRun
    drains: dict[str, DrainResult] = field(default_factory=dict)
    nodes: dict[str, DrainNodeResult] = field(default_factory=dict)
    catchment_peak_runoff: dict[str, float] = field(default_factory=dict)   # m³/s
    hyetograph_mm_h: list[float] = field(default_factory=list)
    runoff_continuity_error_pct: float | None = None
    flow_continuity_error_pct: float | None = None


def _xsection(sec) -> str:
    if sec.shape == "circular":
        return f"CIRCULAR {fnum(sec.depth)} 0 0 0 1"
    if sec.shape == "rectangular":
        return f"{'RECT_CLOSED' if sec.closed else 'RECT_OPEN'} {fnum(sec.depth)} {fnum(sec.width)} 0 0 1"
    return f"TRAPEZOIDAL {fnum(sec.depth)} {fnum(sec.width)} {fnum(sec.side_slope)} {fnum(sec.side_slope)} 1"


def build_inp(net: DrainageNetwork, rules: RuleContext, idf: IDF, return_period: float):
    errs = []
    for c in net.catchments:
        for k in ("impervious_pct", "overland_slope", "flow_length_m"):
            if c.obj.attr(k) is None:
                errs.append(f"Catchment {c.obj.label}: {k} required for SWMM.")
    if errs:
        raise EngineError("\n".join(errs))
    storm = rules.value("design_storm")
    hz = rules.value("horton_infiltration")
    sf = rules.value("subcatchment_surface")
    hyeto = alternating_block(idf, return_period, storm["duration_min"], storm["step_min"], storm["peak_position"])
    step = storm["step_min"]
    end_min = storm["duration_min"] + 180
    hm = lambda m: f"{int(m // 60):02d}:{int(m % 60):02d}:00"
    nmap, lmap, smap = IdMap("N"), IdMap("C"), IdMap("S")

    inv: dict[str, float] = {}
    for d in net.drains.values():
        inv[d.us.id] = min(inv.get(d.us.id, 1e9), d.us_invert)
        inv[d.ds.id] = min(inv.get(d.ds.id, 1e9), d.ds_invert)
    for nid, n in net.nodes.items():
        if n.kind == ObjectKind.DRAIN_OUTFALL and n.attr("invert_level") is not None:
            inv[nid] = min(inv.get(nid, 1e9), float(n.attr("invert_level")))

    L = ["[TITLE]", f"Storm drainage – {net.project.name} – {return_period}-yr design storm", "",
         "[OPTIONS]", "FLOW_UNITS CMS", "INFILTRATION HORTON", "FLOW_ROUTING DYNWAVE", "LINK_OFFSETS ELEVATION",
         "MIN_SLOPE 0", "ALLOW_PONDING NO", "START_DATE 01/01/2026", "START_TIME 00:00:00",
         "REPORT_START_DATE 01/01/2026", "REPORT_START_TIME 00:00:00", "END_DATE 01/01/2026",
         f"END_TIME {hm(end_min)}", "REPORT_STEP 00:01:00", "WET_STEP 00:01:00", "DRY_STEP 00:05:00",
         "ROUTING_STEP 0:00:02", "VARIABLE_STEP 0.75", "NORMAL_FLOW_LIMITED BOTH", "INERTIAL_DAMPING PARTIAL", "",
         "[RAINGAGES]", f"RG1 INTENSITY 0:{step:02d} 1.0 TIMESERIES DESIGN_STORM", "",
         "[SUBCATCHMENTS]", ";Name RainGage Outlet Area PctImperv Width PctSlope CurbLen"]
    sub, are, inf, poly = [], [], [], []
    for c in net.catchments:
        s = smap.name(c.obj.id, c.obj.name)
        width = c.area_ha * 10_000 / float(c.obj.attr("flow_length_m"))
        L.append(f"{s} RG1 {nmap.name(c.node.id, c.node.name)} {fnum(c.area_ha, 5)} "
                 f"{fnum(c.obj.attr('impervious_pct'))} {fnum(width, 2)} {fnum(100 * c.obj.attr('overland_slope'), 3)} 0")
        are.append(f"{s} {sf['n_imperv']} {sf['n_perv']} {sf['dstore_imperv_mm']} {sf['dstore_perv_mm']} "
                   f"{sf['pct_zero_storage']} OUTLET")
        inf.append(f"{s} {hz['max_rate_mm_h']} {hz['min_rate_mm_h']} {hz['decay_per_h']} {hz['dry_days']} 0")
        ring = c.obj.geometry["coordinates"][0] if c.obj.geometry["type"] == "Polygon" else c.obj.geometry["coordinates"][0][0]
        poly += [f"{s} {fnum(x, 3)} {fnum(y, 3)}" for x, y, *_ in ring]
    L += ["", "[SUBAREAS]", ";Subcatch N-Imperv N-Perv S-Imperv S-Perv PctZero RouteTo"] + are
    L += ["", "[INFILTRATION]", ";Subcatch MaxRate MinRate Decay DryTime MaxInfil"] + inf
    L += ["", "[JUNCTIONS]", ";Name Invert MaxDepth InitDepth SurDepth Aponded"]
    for nid, n in net.nodes.items():
        if n.kind == ObjectKind.DRAIN_NODE:
            L.append(f"{nmap.name(nid, n.name)} {fnum(inv[nid])} {fnum(n.attr('ground_level') - inv[nid])} 0 0 0")
    L += ["", "[OUTFALLS]", ";Name Invert Type Stage Gated"]
    for nid, n in net.nodes.items():
        if n.kind == ObjectKind.DRAIN_OUTFALL:
            tw = n.attr("tailwater_level")
            L.append(f"{nmap.name(nid, n.name)} {fnum(inv[nid])} " + (f"FIXED {fnum(tw)} NO" if tw is not None else "FREE NO"))
    L += ["", "[CONDUITS]", ";Name From To Length Roughness InOffset OutOffset InitFlow MaxFlow"]
    xs = []
    n_tab = rules.value("manning_n_drains")
    for k in net.order:
        d = net.drains[k]
        c = lmap.name(d.obj.id, d.obj.name)
        L.append(f"{c} {nmap.name(d.us.id, d.us.name)} {nmap.name(d.ds.id, d.ds.name)} {fnum(d.length, 3)} "
                 f"{n_tab[d.lining]} {fnum(d.us_invert + d.silt_m)} {fnum(d.ds_invert + d.silt_m)} 0 0")
        xs.append(f"{c} {_xsection(d.flow_section)}")      # silt raises the bed of an existing drain
    L += ["", "[XSECTIONS]", ";Link Shape Geom1 Geom2 Geom3 Geom4 Barrels"] + xs
    dwf = [f"{nmap.name(nid, n.name)} FLOW {fnum(float(n.attr('external_inflow_m3s')), 4)}"
           for nid, n in net.nodes.items()
           if n.kind == ObjectKind.DRAIN_NODE and n.attr("external_inflow_m3s")]
    if dwf:
        L += ["", "[DWF]", ";Node Constituent Baseline (inflow from outside the drawing, constant)"] + dwf
    L += ["", "[TIMESERIES]", ";Name Time Value"]
    for j, i in enumerate(hyeto):
        L.append(f"DESIGN_STORM {hm(j * step)[:-3]} {i:.4f}")
    L.append(f"DESIGN_STORM {hm(len(hyeto) * step)[:-3]} 0")
    L += ["", "[REPORT]", "INPUT NO", "CONTROLS NO", "SUBCATCHMENTS ALL", "NODES ALL", "LINKS ALL",
          "", "[COORDINATES]"]
    for nid, n in net.nodes.items():
        x, y = point_coord(n.geometry)[:2]
        L.append(f"{nmap.name(nid, n.name)} {fnum(x, 3)} {fnum(y, 3)}")
    L += ["", "[VERTICES]"]
    for d in net.drains.values():
        for x, y, *_ in line_coords(d.obj.geometry)[1:-1]:
            L.append(f"{lmap.name(d.obj.id, d.obj.name)} {fnum(x, 3)} {fnum(y, 3)}")
    L += ["", "[Polygons]"] + poly + [""]
    return "\n".join(L), nmap, lmap, smap, hyeto


def run_drainage(net: DrainageNetwork, rules: RuleContext, idf: IDF, return_period: float) -> DrainageSwmmResult:
    if net.errors:
        raise EngineError("Network not ready:\n" + "\n".join(net.errors))
    inp, nmap, lmap, smap, hyeto = build_inp(net, rules, idf, return_period)
    raw = run_swmm(inp, list(nmap.to_object), list(lmap.to_object), list(smap.to_object),
                   notes=[f"Design storm: alternating block from IDF ({idf.source}), {return_period}-yr."])
    res = DrainageSwmmResult(raw.run, hyetograph_mm_h=hyeto,
                             runoff_continuity_error_pct=raw.runoff_continuity_error_pct,
                             flow_continuity_error_pct=raw.flow_continuity_error_pct)
    top: dict[str, float] = {}
    for d in net.drains.values():
        top[d.us.id] = max(top.get(d.us.id, -1e9), d.us_invert + d.section.depth)
        top[d.ds.id] = max(top.get(d.ds.id, -1e9), d.ds_invert + d.section.depth)
    for name, oid in nmap.to_object.items():
        s = raw.nodes[name]
        closed = any(d.section.closed for d in net.drains.values() if oid in (d.us.id, d.ds.id))
        res.nodes[oid] = DrainNodeResult(oid, s.max["head"], s.max["overflow"],
                                         closed and s.max["head"] > top.get(oid, 1e9) + 1e-3)
    for name, oid in lmap.to_object.items():
        s, d = raw.links[name], net.drains[oid]
        res.drains[oid] = DrainResult(oid, s.max["flow"], s.max["depth"] / d.section.depth, s.max["velocity"])
    for name, oid in smap.to_object.items():
        res.catchment_peak_runoff[oid] = raw.subcatchments[name].max["runoff"]
    return res
