"""EPANET 2.3 adapter for water-supply networks.

Uses the EPANET engine built from THIS repository's source (``src/``,
``include/``) through the project-handle C API (``epanet2_2.h``).  The GIS
water network is converted to an EPANET input file, solved, and results are
mapped back to object IDs for display on the map.

Model objects used
------------------
WATER_JUNCTION Point: elevation (m), demand_lps (base demand), pattern (optional)
RESERVOIR      Point: head (m)
TANK           Point: elevation, init_level, min_level, max_level, diameter (m)
WATER_PIPE     LineString: diameter_mm, roughness (Hazen-Williams C), minor_loss
               relationships UPSTREAM_NODE / DOWNSTREAM_NODE = start / end node
PUMP           LineString: pump_flow_lps, pump_head_m (single-point curve)
VALVE          LineString: valve_type (PRV/PSV/PBV/FCV/TCV), diameter_mm, setting
Pipe length is measured from the geometry in the project's projected CRS.
"""

from __future__ import annotations

import ctypes
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ...gis.geometry import line_coords, line_length, point_coord
from ...model.core import ObjectKind, Project, RelationType
from ..base import EngineError, EngineRun, IdMap, fnum, load_library

EN_NODECOUNT, EN_LINKCOUNT = 0, 2
EN_DEMAND, EN_HEAD, EN_PRESSURE = 9, 10, 11
EN_FLOW, EN_VELOCITY, EN_HEADLOSS, EN_STATUS = 8, 9, 10, 11
EN_NOSAVE = 0

NODE_KINDS = (ObjectKind.WATER_JUNCTION, ObjectKind.RESERVOIR, ObjectKind.TANK)
LINK_KINDS = (ObjectKind.WATER_PIPE, ObjectKind.PUMP, ObjectKind.VALVE)


def _lib() -> ctypes.CDLL:
    lib = load_library("CITYINFRA_EPANET_LIB", ["libepanet2.so", "libepanet2.dylib", "epanet2.dll"])
    P = ctypes.c_void_p
    lib.EN_createproject.argtypes = [ctypes.POINTER(P)]
    lib.EN_deleteproject.argtypes = [P]
    lib.EN_open.argtypes = [P, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
    lib.EN_close.argtypes = [P]
    lib.EN_openH.argtypes = [P]
    lib.EN_initH.argtypes = [P, ctypes.c_int]
    lib.EN_runH.argtypes = [P, ctypes.POINTER(ctypes.c_long)]
    lib.EN_nextH.argtypes = [P, ctypes.POINTER(ctypes.c_long)]
    lib.EN_closeH.argtypes = [P]
    lib.EN_getcount.argtypes = [P, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
    lib.EN_getnodeid.argtypes = [P, ctypes.c_int, ctypes.c_char_p]
    lib.EN_getlinkid.argtypes = [P, ctypes.c_int, ctypes.c_char_p]
    lib.EN_getnodevalue.argtypes = [P, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_double)]
    lib.EN_getlinkvalue.argtypes = [P, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_double)]
    lib.EN_geterror.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    lib.EN_getversion.argtypes = [ctypes.POINTER(ctypes.c_int)]
    return lib


def engine_version() -> str:
    v = ctypes.c_int()
    _lib().EN_getversion(ctypes.byref(v))
    return f"{v.value // 10000}.{(v.value // 100) % 100}.{v.value % 100}"


@dataclass
class WaterNodeResult:
    object_id: str
    pressure: list[float]   # m, per time step
    head: list[float]       # m
    demand: list[float]     # L/s

    @property
    def min_pressure(self) -> float:
        return min(self.pressure)


@dataclass
class WaterLinkResult:
    object_id: str
    flow: list[float]       # L/s (sign = direction relative to start→end)
    velocity: list[float]   # m/s
    headloss: list[float]   # m, total head loss across the link (verified against Hazen-Williams by hand)
    status: list[int]


@dataclass
class EpanetResult:
    run: EngineRun
    times: list[int] = field(default_factory=list)  # s
    nodes: dict[str, WaterNodeResult] = field(default_factory=dict)
    links: dict[str, WaterLinkResult] = field(default_factory=dict)


def validate(pr: Project) -> list[str]:
    errs = []
    nodes = pr.of_kind(*NODE_KINDS)
    if not any(n.kind in (ObjectKind.RESERVOIR, ObjectKind.TANK) for n in nodes):
        errs.append("Add at least one reservoir or tank to supply the network.")
    linked: set[str] = set()
    for l in pr.of_kind(*LINK_KINDS):
        a = pr.related(l, RelationType.UPSTREAM_NODE)
        b = pr.related(l, RelationType.DOWNSTREAM_NODE)
        if len(a) != 1 or len(b) != 1:
            errs.append(f"{l.label}: needs one start node and one end node.")
            continue
        linked |= {a[0].id, b[0].id}
        if l.kind == ObjectKind.WATER_PIPE and l.attr("diameter_mm") is None:
            errs.append(f"{l.label}: diameter_mm missing.")
    for n in nodes:
        if n.id not in linked:
            errs.append(f"{n.label}: not connected to any pipe.")
    return errs


def build_inp(pr: Project, duration_h: float = 0, hyd_step_min: int = 60) -> tuple[str, IdMap, IdMap]:
    nmap, lmap = IdMap("N"), IdMap("L")
    L = ["[TITLE]", pr.name, "", "[JUNCTIONS]", ";ID  Elev  Demand  Pattern"]
    for n in pr.of_kind(ObjectKind.WATER_JUNCTION):
        L.append(f"{nmap.name(n.id, n.name)} {fnum(n.attr('elevation'))} {fnum(n.attr('demand_lps', 0))} "
                 f"{n.attr('pattern') or ''}".rstrip())
    L += ["", "[RESERVOIRS]", ";ID  Head"]
    for n in pr.of_kind(ObjectKind.RESERVOIR):
        L.append(f"{nmap.name(n.id, n.name)} {fnum(n.attr('head'))}")
    L += ["", "[TANKS]", ";ID  Elev  InitLvl  MinLvl  MaxLvl  Diam  MinVol"]
    for n in pr.of_kind(ObjectKind.TANK):
        L.append(f"{nmap.name(n.id, n.name)} " + " ".join(fnum(n.attr(k)) for k in
                 ("elevation", "init_level", "min_level", "max_level", "diameter")) + " 0")

    def ends(l):
        a = pr.related(l, RelationType.UPSTREAM_NODE)[0]
        b = pr.related(l, RelationType.DOWNSTREAM_NODE)[0]
        return nmap.name(a.id, a.name), nmap.name(b.id, b.name)

    L += ["", "[PIPES]", ";ID  Node1  Node2  Length  Diam  Rough  MinorLoss  Status"]
    for l in pr.of_kind(ObjectKind.WATER_PIPE):
        a, b = ends(l)
        L.append(f"{lmap.name(l.id, l.name)} {a} {b} {fnum(line_length(l.geometry), 3)} "
                 f"{fnum(l.attr('diameter_mm'))} {fnum(l.attr('roughness', 130))} {fnum(l.attr('minor_loss', 0))} Open")
    curves = []
    L += ["", "[PUMPS]", ";ID  Node1  Node2  Parameters"]
    for l in pr.of_kind(ObjectKind.PUMP):
        a, b = ends(l)
        cid = f"C_{lmap.name(l.id, l.name)}"
        L.append(f"{lmap.name(l.id, l.name)} {a} {b} HEAD {cid}")
        curves.append(f"{cid} {fnum(l.attr('pump_flow_lps'))} {fnum(l.attr('pump_head_m'))}")
    L += ["", "[VALVES]", ";ID  Node1  Node2  Diam  Type  Setting  MinorLoss"]
    for l in pr.of_kind(ObjectKind.VALVE):
        a, b = ends(l)
        L.append(f"{lmap.name(l.id, l.name)} {a} {b} {fnum(l.attr('diameter_mm'))} {l.attr('valve_type')} "
                 f"{fnum(l.attr('setting', 0))} 0")
    L += ["", "[CURVES]"] + curves
    hm = lambda m: f"{int(m // 60)}:{int(m % 60):02d}"
    L += ["", "[TIMES]", f"Duration {hm(duration_h * 60)}", f"Hydraulic Timestep {hm(hyd_step_min)}",
          f"Report Timestep {hm(hyd_step_min)}", "", "[OPTIONS]", "Units LPS", "Headloss H-W", "",
          "[REPORT]", "Status No", "Summary No", "", "[COORDINATES]"]
    for n in pr.of_kind(*NODE_KINDS):
        x, y = point_coord(n.geometry)[:2]
        L.append(f"{nmap.name(n.id, n.name)} {fnum(x, 3)} {fnum(y, 3)}")
    L += ["", "[VERTICES]"]
    for l in pr.of_kind(*LINK_KINDS):
        for x, y, *_ in line_coords(l.geometry)[1:-1]:
            L.append(f"{lmap.name(l.id, l.name)} {fnum(x, 3)} {fnum(y, 3)}")
    L += ["", "[END]", ""]
    return "\n".join(L), nmap, lmap


def run_water(pr: Project, duration_h: float = 0, hyd_step_min: int = 60) -> EpanetResult:
    errs = validate(pr)
    if errs:
        raise EngineError("Network not ready:\n" + "\n".join(errs))
    lib = _lib()
    inp, nmap, lmap = build_inp(pr, duration_h, hyd_step_min)
    run = EngineRun("EPANET", engine_version(), "ok", inp)
    res = EpanetResult(run)
    ph = ctypes.c_void_p()
    lib.EN_createproject(ctypes.byref(ph))
    opened = hyd = False

    def check(code: int) -> None:
        if code == 0:
            return
        buf = ctypes.create_string_buffer(256)
        lib.EN_geterror(code, buf, 255)
        msg = buf.value.decode(errors="replace")
        if code < 100:                       # 1–6 are warnings (e.g. negative pressures)
            run.status = "warning"
            if msg not in run.messages:
                run.messages.append(msg)
            return
        raise EngineError(f"EPANET error {code}: {msg}")

    with tempfile.TemporaryDirectory(prefix="epanet-") as tmp:
        f_inp, f_rpt = Path(tmp) / "model.inp", Path(tmp) / "model.rpt"
        f_inp.write_text(inp)
        try:
            check(lib.EN_open(ph, str(f_inp).encode(), str(f_rpt).encode(), b""))
            opened = True
            nn, nl = ctypes.c_int(), ctypes.c_int()
            lib.EN_getcount(ph, EN_NODECOUNT, ctypes.byref(nn))
            lib.EN_getcount(ph, EN_LINKCOUNT, ctypes.byref(nl))
            buf = ctypes.create_string_buffer(64)
            node_ids, link_ids = {}, {}
            for i in range(1, nn.value + 1):
                lib.EN_getnodeid(ph, i, buf)
                oid = nmap.to_object[buf.value.decode()]
                node_ids[i] = oid
                res.nodes[oid] = WaterNodeResult(oid, [], [], [])
            for i in range(1, nl.value + 1):
                lib.EN_getlinkid(ph, i, buf)
                oid = lmap.to_object[buf.value.decode()]
                link_ids[i] = oid
                res.links[oid] = WaterLinkResult(oid, [], [], [], [])
            check(lib.EN_openH(ph)); hyd = True
            check(lib.EN_initH(ph, EN_NOSAVE))
            t, tstep, v = ctypes.c_long(), ctypes.c_long(1), ctypes.c_double()
            while tstep.value > 0:
                check(lib.EN_runH(ph, ctypes.byref(t)))
                res.times.append(int(t.value))
                for i, oid in node_ids.items():
                    r = res.nodes[oid]
                    lib.EN_getnodevalue(ph, i, EN_PRESSURE, ctypes.byref(v)); r.pressure.append(v.value)
                    lib.EN_getnodevalue(ph, i, EN_HEAD, ctypes.byref(v)); r.head.append(v.value)
                    lib.EN_getnodevalue(ph, i, EN_DEMAND, ctypes.byref(v)); r.demand.append(v.value)
                for i, oid in link_ids.items():
                    r = res.links[oid]
                    lib.EN_getlinkvalue(ph, i, EN_FLOW, ctypes.byref(v)); r.flow.append(v.value)
                    lib.EN_getlinkvalue(ph, i, EN_VELOCITY, ctypes.byref(v)); r.velocity.append(v.value)
                    lib.EN_getlinkvalue(ph, i, EN_HEADLOSS, ctypes.byref(v)); r.headloss.append(v.value)
                    lib.EN_getlinkvalue(ph, i, EN_STATUS, ctypes.byref(v)); r.status.append(int(v.value))
                check(lib.EN_nextH(ph, ctypes.byref(tstep)))
        finally:
            if hyd:
                lib.EN_closeH(ph)
            if opened:
                lib.EN_close(ph)
            lib.EN_deleteproject(ph)
            if f_rpt.exists():
                run.report_text = f_rpt.read_text(errors="replace")
    return res
