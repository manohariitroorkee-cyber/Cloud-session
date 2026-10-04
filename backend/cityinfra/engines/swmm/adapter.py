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

import ctypes
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ...model.core import ObjectKind
from ...gis.geometry import line_coords, point_coord
from ..base import (SWMM_LOCK, EngineError, EngineRun, IdMap, fnum, load_library)

# swmm5.h enums
_NODE, _LINK = 2, 3
NODE_DEPTH, NODE_HEAD, NODE_OVERFLOW = 303, 304, 308
LINK_FLOW, LINK_DEPTH, LINK_VELOCITY = 410, 411, 412


def _lib() -> ctypes.CDLL:
    lib = load_library("CITYINFRA_SWMM_LIB", ["libswmm5.so", "libswmm5.dylib", "swmm5.dll"])
    lib.swmm_open.argtypes = [ctypes.c_char_p] * 3
    lib.swmm_start.argtypes = [ctypes.c_int]
    lib.swmm_step.argtypes = [ctypes.POINTER(ctypes.c_double)]
    lib.swmm_getValue.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.swmm_getValue.restype = ctypes.c_double
    lib.swmm_getIndex.argtypes = [ctypes.c_int, ctypes.c_char_p]
    lib.swmm_getError.argtypes = [ctypes.c_char_p, ctypes.c_int]
    lib.swmm_getMassBalErr.argtypes = [ctypes.POINTER(ctypes.c_float)] * 3
    return lib


def engine_version() -> str:
    v = _lib().swmm_getVersion()   # e.g. 52004
    return f"{v // 10000}.{(v // 1000) % 10}.{v % 1000}"


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
    lib = _lib()
    inp, nmap, lmap, notes = build_inp(net, design, hours)
    with SWMM_LOCK, tempfile.TemporaryDirectory(prefix="swmm-") as tmp:
        f_inp, f_rpt, f_out = (str(Path(tmp) / n) for n in ("model.inp", "model.rpt", "model.out"))
        Path(f_inp).write_text(inp)
        run = EngineRun("EPA SWMM", engine_version(), "ok", inp, messages=list(notes))
        res = SwmmResult(run)

        def fail(code: int) -> None:
            buf = ctypes.create_string_buffer(512)
            lib.swmm_getError(buf, 512)
            lib.swmm_end(); lib.swmm_close()
            rpt = Path(f_rpt).read_text(errors="replace") if Path(f_rpt).exists() else ""
            raise EngineError(f"SWMM error {code}: {buf.value.decode(errors='replace').strip()}\n{_rpt_errors(rpt)}")

        if (code := lib.swmm_open(f_inp.encode(), f_rpt.encode(), f_out.encode())):
            fail(code)
        if (code := lib.swmm_start(0)):
            fail(code)
        nidx = {name: lib.swmm_getIndex(_NODE, name.encode()) for name in nmap.to_object}
        lidx = {name: lib.swmm_getIndex(_LINK, name.encode()) for name in lmap.to_object}
        mx_nd = dict.fromkeys(nidx, 0.0); mx_nh = dict.fromkeys(nidx, -1e9); mx_no = dict.fromkeys(nidx, 0.0)
        mx_lq = dict.fromkeys(lidx, 0.0); mx_ld = dict.fromkeys(lidx, 0.0); mx_lv = dict.fromkeys(lidx, 0.0)
        last_nh: dict[str, float] = {}
        last_l: dict[str, tuple[float, float, float]] = {}
        t = ctypes.c_double(0.0)
        while True:
            if (code := lib.swmm_step(ctypes.byref(t))):
                fail(code)
            for name, i in nidx.items():
                mx_nd[name] = max(mx_nd[name], lib.swmm_getValue(NODE_DEPTH, i))
                last_nh[name] = h = lib.swmm_getValue(NODE_HEAD, i)
                mx_nh[name] = max(mx_nh[name], h)
                mx_no[name] = max(mx_no[name], lib.swmm_getValue(NODE_OVERFLOW, i))
            for name, i in lidx.items():
                q = abs(lib.swmm_getValue(LINK_FLOW, i))
                y = lib.swmm_getValue(LINK_DEPTH, i)
                v = abs(lib.swmm_getValue(LINK_VELOCITY, i))
                last_l[name] = (q, y, v)
                mx_lq[name] = max(mx_lq[name], q)
                mx_ld[name] = max(mx_ld[name], y)
                mx_lv[name] = max(mx_lv[name], v)
            if t.value <= 0:
                break
        lib.swmm_end()
        ro, fl, qu = ctypes.c_float(), ctypes.c_float(), ctypes.c_float()
        lib.swmm_getMassBalErr(ctypes.byref(ro), ctypes.byref(fl), ctypes.byref(qu))
        res.flow_continuity_error_pct = float(fl.value)
        warnings = lib.swmm_getWarnings()
        lib.swmm_report()
        lib.swmm_close()
        run.report_text = Path(f_rpt).read_text(errors="replace")
        if warnings:
            run.status = "warning"
            run.messages.append(f"SWMM reported {warnings} warning(s); see report.")

    crown: dict[str, float] = {}
    for d in design.pipes:
        p = d.pipe
        crown[p.us.id] = max(crown.get(p.us.id, -1e9), p.us_invert + p.diameter)
        crown[p.ds.id] = max(crown.get(p.ds.id, -1e9), p.ds_invert + p.diameter)
    for name, oid in nmap.to_object.items():
        res.nodes[oid] = NodeResult(oid, mx_nd[name], mx_nh[name], mx_no[name],
                                    mx_nh[name] > crown.get(oid, 1e9) + 1e-3, last_nh.get(name, 0.0))
    dia = {d.pipe.obj.id: d.pipe.diameter for d in design.pipes}
    for name, oid in lmap.to_object.items():
        q, y, v = last_l.get(name, (0.0, 0.0, 0.0))
        res.links[oid] = LinkResult(oid, mx_lq[name], mx_ld[name], mx_lv[name], mx_ld[name] / dia[oid],
                                    q, v, y / dia[oid])
    run.meta["flow_continuity_error_pct"] = res.flow_continuity_error_pct
    return res


def _rpt_errors(rpt: str) -> str:
    return "\n".join(l.strip() for l in rpt.splitlines() if "ERROR" in l.upper())[:2000]
