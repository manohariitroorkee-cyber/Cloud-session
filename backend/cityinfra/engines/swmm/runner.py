"""Generic EPA SWMM run through the official C API.

Discipline adapters (sanitary sewer, storm drainage) write their own input
file and call :func:`run_swmm`; it runs SWMM to completion in a temporary
directory and returns, per named node / link / subcatchment, the maxima over
the run and the end-of-run values, plus continuity errors and the report.
"""

from __future__ import annotations

import ctypes
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..base import SWMM_LOCK, EngineError, EngineRun, load_library

_SUBCATCH, _NODE, _LINK = 1, 2, 3
SUBCATCH_RAINFALL, SUBCATCH_RUNOFF = 202, 205
NODE_DEPTH, NODE_HEAD, NODE_INFLOW, NODE_OVERFLOW = 303, 304, 307, 308
LINK_FLOW, LINK_DEPTH, LINK_VELOCITY = 410, 411, 412


def lib() -> ctypes.CDLL:
    L = load_library("CITYINFRA_SWMM_LIB", ["libswmm5.so", "libswmm5.dylib", "swmm5.dll"])
    L.swmm_open.argtypes = [ctypes.c_char_p] * 3
    L.swmm_start.argtypes = [ctypes.c_int]
    L.swmm_step.argtypes = [ctypes.POINTER(ctypes.c_double)]
    L.swmm_getValue.argtypes = [ctypes.c_int, ctypes.c_int]
    L.swmm_getValue.restype = ctypes.c_double
    L.swmm_getIndex.argtypes = [ctypes.c_int, ctypes.c_char_p]
    L.swmm_getError.argtypes = [ctypes.c_char_p, ctypes.c_int]
    L.swmm_getMassBalErr.argtypes = [ctypes.POINTER(ctypes.c_float)] * 3
    return L


def engine_version() -> str:
    v = lib().swmm_getVersion()   # e.g. 52004
    return f"{v // 10000}.{(v // 1000) % 10}.{v % 1000}"


@dataclass
class Series:
    """Max over the run and value at the end of the run, per quantity."""
    max: dict[str, float] = field(default_factory=dict)
    final: dict[str, float] = field(default_factory=dict)


@dataclass
class RawRun:
    run: EngineRun
    nodes: dict[str, Series] = field(default_factory=dict)      # by SWMM name
    links: dict[str, Series] = field(default_factory=dict)
    subcatchments: dict[str, Series] = field(default_factory=dict)
    runoff_continuity_error_pct: float | None = None
    flow_continuity_error_pct: float | None = None


_QUANT = {
    _NODE: {"depth": NODE_DEPTH, "head": NODE_HEAD, "inflow": NODE_INFLOW, "overflow": NODE_OVERFLOW},
    _LINK: {"flow": LINK_FLOW, "depth": LINK_DEPTH, "velocity": LINK_VELOCITY},
    _SUBCATCH: {"rainfall": SUBCATCH_RAINFALL, "runoff": SUBCATCH_RUNOFF},
}


def run_swmm(inp: str, nodes: list[str], links: list[str], subcatchments: list[str] = (),
             notes: list[str] | None = None) -> RawRun:
    L = lib()
    with SWMM_LOCK, tempfile.TemporaryDirectory(prefix="swmm-") as tmp:
        f_inp, f_rpt, f_out = (str(Path(tmp) / n) for n in ("model.inp", "model.rpt", "model.out"))
        Path(f_inp).write_text(inp, encoding="utf-8")
        raw = RawRun(EngineRun("EPA SWMM", engine_version(), "ok", inp, messages=list(notes or [])))

        def fail(code: int) -> None:
            buf = ctypes.create_string_buffer(512)
            L.swmm_getError(buf, 512)
            L.swmm_end(); L.swmm_close()
            rpt = Path(f_rpt).read_text(errors="replace") if Path(f_rpt).exists() else ""
            errs = "\n".join(l.strip() for l in rpt.splitlines() if "ERROR" in l.upper())[:2000]
            raise EngineError(f"SWMM error {code}: {buf.value.decode(errors='replace').strip()}\n{errs}")

        if (code := L.swmm_open(f_inp.encode(), f_rpt.encode(), f_out.encode())):
            fail(code)
        if (code := L.swmm_start(0)):
            fail(code)
        groups = []
        for otype, names, store in ((_NODE, nodes, raw.nodes), (_LINK, links, raw.links),
                                    (_SUBCATCH, subcatchments, raw.subcatchments)):
            for n in names:
                idx = L.swmm_getIndex(otype, n.encode())
                if idx < 0:
                    fail(-1)
                store[n] = Series({q: float("-inf") for q in _QUANT[otype]}, {})
                groups.append((otype, idx, store[n]))
        t = ctypes.c_double(0.0)
        while True:
            if (code := L.swmm_step(ctypes.byref(t))):
                fail(code)
            for otype, idx, s in groups:
                for q, prop in _QUANT[otype].items():
                    v = L.swmm_getValue(prop, idx)
                    if q in ("flow", "velocity"):
                        v = abs(v)
                    s.final[q] = v
                    if v > s.max[q]:
                        s.max[q] = v
            if t.value <= 0:
                break
        L.swmm_end()
        ro, fl, qu = ctypes.c_float(), ctypes.c_float(), ctypes.c_float()
        L.swmm_getMassBalErr(ctypes.byref(ro), ctypes.byref(fl), ctypes.byref(qu))
        raw.runoff_continuity_error_pct = float(ro.value)
        raw.flow_continuity_error_pct = float(fl.value)
        warnings = L.swmm_getWarnings()
        L.swmm_report()
        L.swmm_close()
        raw.run.report_text = Path(f_rpt).read_text(errors="replace")
        if warnings:
            raw.run.status = "warning"
            raw.run.messages.append(f"SWMM reported {warnings} warning(s); see report.")
        raw.run.meta.update(flow_continuity_error_pct=raw.flow_continuity_error_pct,
                            runoff_continuity_error_pct=raw.runoff_continuity_error_pct)
    return raw
