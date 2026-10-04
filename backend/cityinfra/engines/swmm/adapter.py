"""EPA SWMM 5.2 adapter for sanitary sewers (and, later, storm drainage).

Converts a :class:`SewerNetwork` + its design flows into a SWMM input file,
runs the official SWMM engine (``libswmm5``, built from USEPA source – not
re-implemented here) through its C API, and returns per-object maxima:
flow, depth, velocity, node head (HGL), surcharge and flooding.

Scenario used for sewer checks: constant design peak inflows, dynamic-wave
routing, run long enough to reach steady state.  Lateral inflow at a
manhole = (design flow leaving it) − (design flows arriving), so SWMM's
steady pipe flows reproduce the design-sheet flows.  Where peak-factor
steps would make that negative, it is set to zero and noted (SWMM flow is
then slightly higher than the design-sheet flow – conservative).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ...model.core import ObjectKind
from ...gis.geometry import line_coords, point_coord
from ..base import EngineError, EngineRun, IdMap, fnum

from .runner import engine_version, run_swmm  # noqa: F401  (re-exported)


@dataclass
class NodeResult:
    object_id: str
    max_depth: float      # m above node invert
    max_head: float       # m (HGL)
    max_overflow: float   # m³/s flooding at the node
    surcharged: bool      # max head above crown of the highest connected pipe
    final_head: float = 0.0   # m, at end of run (steady state for constant inflows)


@dataclass
class LinkResult:
    object_id: str
    max_flow: float       # m³/s
    max_depth: float      # m
    max_velocity: float   # m/s
    max_depth_ratio: float
    final_flow: float = 0.0          # end-of-run values: steady state under
    final_velocity: float = 0.0      # constant design inflows; the maxima above
    final_depth_ratio: float = 0.0   # include the start-up transient


@dataclass
class SwmmResult:
    run: EngineRun
    nodes: dict[str, NodeResult] = field(default_factory=dict)
    links: dict[str, LinkResult] = field(default_factory=dict)
    flow_continuity_error_pct: float | None = None


def build_inp(net, design, hours: int = 6) -> tuple[str, IdMap, IdMap, list[str]]:
    """Return (inp text, node map, link map, notes)."""
    nmap, lmap = IdMap("N"), IdMap("C")
    notes: list[str] = []
    flows = {d.pipe.obj.id: d.design_flow for d in design.pipes}

    node_invert: dict[str, float] = {}
    for p in net.pipes.values():
        node_invert[p.us.id] = min(node_invert.get(p.us.id, 1e9), p.us_invert)
        node_invert[p.ds.id] = min(node_invert.get(p.ds.id, 1e9), p.ds_invert)
    for nid, n in net.nodes.items():
        if n.kind == ObjectKind.SEWER_OUTFALL and n.attr("invert_level") is not None:
            node_invert[nid] = min(node_invert.get(nid, 1e9), float(n.attr("invert_level")))

    L: list[str] = ["[TITLE]", f"Sewer network – {net.project.name}", "",
                    "[OPTIONS]", "FLOW_UNITS CMS", "INFILTRATION HORTON", "FLOW_ROUTING DYNWAVE",
                    "LINK_OFFSETS ELEVATION", "MIN_SLOPE 0", "ALLOW_PONDING NO",
                    "START_DATE 01/01/2026", "START_TIME 00:00:00",
                    "REPORT_START_DATE 01/01/2026", "REPORT_START_TIME 00:00:00",
                    "END_DATE 01/01/2026", f"END_TIME {hours:02d}:00:00",
                    "REPORT_STEP 00:05:00", "WET_STEP 00:05:00", "DRY_STEP 01:00:00",
                    "ROUTING_STEP 0:00:05", "VARIABLE_STEP 0.75", "NORMAL_FLOW_LIMITED BOTH",
                    "INERTIAL_DAMPING PARTIAL", "HEAD_TOLERANCE 0.0015", ""]

    L += ["[JUNCTIONS]", ";Name  InvertElev  MaxDepth  InitDepth  SurDepth  Aponded"]
    for nid, n in net.nodes.items():
        if n.kind != ObjectKind.MANHOLE:
            continue
        inv = node_invert[nid]
        L.append(f"{nmap.name(nid, n.name)} {fnum(inv)} {fnum(n.attr('ground_level') - inv)} 0 0 0")
    L += ["", "[OUTFALLS]", ";Name  InvertElev  Type"]
    for nid, n in net.nodes.items():
        if n.kind == ObjectKind.SEWER_OUTFALL:
            L.append(f"{nmap.name(nid, n.name)} {fnum(node_invert[nid])} FREE NO")

    L += ["", "[CONDUITS]", ";Name  From  To  Length  Roughness  InOffset  OutOffset  InitFlow  MaxFlow"]
    xs: list[str] = []
    for d in design.pipes:
        p = d.pipe
        L.append(f"{lmap.name(p.obj.id, p.obj.name)} {nmap.name(p.us.id, p.us.name)} "
                 f"{nmap.name(p.ds.id, p.ds.name)} {fnum(p.length, 3)} {d.manning_n} "
                 f"{fnum(p.us_invert)} {fnum(p.ds_invert)} 0 0")
        xs.append(f"{lmap.name(p.obj.id, p.obj.name)} CIRCULAR {fnum(p.diameter)} 0 0 0 1")
    L += ["", "[XSECTIONS]", ";Link  Shape  Geom1  Geom2  Geom3  Geom4  Barrels"] + xs

    L += ["", "[INFLOWS]", ";Node  Constituent  TimeSeries  Type  Mfactor  Sfactor  Baseline"]
    for nid, n in net.nodes.items():
        out = [p for p in net.pipes.values() if p.us.id == nid]
        if not out:
            continue
        lateral = flows.get(out[0].obj.id, 0.0) - sum(flows.get(p.obj.id, 0.0) for p in net.incoming(nid))
        if lateral < 0:
            notes.append(f"{n.label}: computed lateral inflow {lateral*1000:.3f} L/s set to 0 (peak-factor step).")
            lateral = 0.0
        if lateral > 0:
            L.append(f'{nmap.name(nid, n.name)} FLOW "" FLOW 1.0 1.0 {lateral:.6f}')

    L += ["", "[REPORT]", "INPUT NO", "CONTROLS NO", "SUBCATCHMENTS NONE", "NODES ALL", "LINKS ALL",
          "", "[COORDINATES]", ";Node  X  Y"]
    for nid, n in net.nodes.items():
        x, y = point_coord(n.geometry)[:2]
        L.append(f"{nmap.name(nid, n.name)} {fnum(x, 3)} {fnum(y, 3)}")
    L += ["", "[VERTICES]", ";Link  X  Y"]
    for d in design.pipes:
        for x, y, *_ in line_coords(d.pipe.obj.geometry)[1:-1]:
            L.append(f"{lmap.name(d.pipe.obj.id, d.pipe.obj.name)} {fnum(x, 3)} {fnum(y, 3)}")
    L.append("")
    return "\n".join(L), nmap, lmap, notes


def run_sewer(net, design, hours: int = 6) -> SwmmResult:
    if not design.pipes:
        raise EngineError("no designed pipes to simulate (fix network errors first)")
    inp, nmap, lmap, notes = build_inp(net, design, hours)
    raw = run_swmm(inp, list(nmap.to_object), list(lmap.to_object), notes=notes)
    res = SwmmResult(raw.run, flow_continuity_error_pct=raw.flow_continuity_error_pct)

    crown: dict[str, float] = {}
    for d in design.pipes:
        p = d.pipe
        crown[p.us.id] = max(crown.get(p.us.id, -1e9), p.us_invert + p.diameter)
        crown[p.ds.id] = max(crown.get(p.ds.id, -1e9), p.ds_invert + p.diameter)
    for name, oid in nmap.to_object.items():
        s = raw.nodes[name]
        res.nodes[oid] = NodeResult(oid, s.max["depth"], s.max["head"], s.max["overflow"],
                                    s.max["head"] > crown.get(oid, 1e9) + 1e-3, s.final["head"])
    dia = {d.pipe.obj.id: d.pipe.diameter for d in design.pipes}
    for name, oid in lmap.to_object.items():
        s = raw.links[name]
        res.links[oid] = LinkResult(oid, s.max["flow"], s.max["depth"], s.max["velocity"],
                                    s.max["depth"] / dia[oid], s.final["flow"], s.final["velocity"],
                                    s.final["depth"] / dia[oid])
    return res
