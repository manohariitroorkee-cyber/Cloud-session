"""Common pieces of the engineering-engine adapters.

An adapter takes an engineering network built from the common model,
writes the engine's native input, runs the engine in an isolated work
directory and maps results back onto object IDs.  The UI and API never talk
to an engine directly.

Every run returns an :class:`EngineRun` record (engine, version, input text,
report text, status, messages) so that results can be traced and reproduced.
"""

from __future__ import annotations

import ctypes
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LIB_DIR = REPO_ROOT / "engines" / "lib"


class EngineUnavailable(RuntimeError):
    """The engine library is not installed/built.  Callers must surface this
    as 'calculation pending', never substitute results."""


class EngineError(RuntimeError):
    pass


def load_library(env_var: str, names: list[str]) -> ctypes.CDLL:
    candidates: list[Path] = []
    if os.environ.get(env_var):
        candidates.append(Path(os.environ[env_var]))
    candidates += [DEFAULT_LIB_DIR / n for n in names]
    for c in candidates:
        if c.exists():
            return ctypes.CDLL(str(c))
    raise EngineUnavailable(
        f"Engine library not found (looked for {', '.join(str(c) for c in candidates)}). "
        f"Run engines/build_engines.sh or set {env_var}.")


# SWMM keeps its project in C globals: one run at a time per process.
# (EPANET's project-handle API is re-entrant, but a lock is kept for symmetry
# and because file-based I/O shares the work directory.)  For concurrent use
# the API layer runs engine jobs in worker processes.
SWMM_LOCK = threading.Lock()


@dataclass
class EngineRun:
    engine: str
    engine_version: str
    status: str                       # "ok" | "warning" | "error"
    input_text: str
    report_text: str = ""
    messages: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


_SAFE = re.compile(r"^[A-Za-z0-9_.\-]{1,31}$")


class IdMap:
    """Maps object IDs to engine-safe names (no spaces, ≤31 chars) and back."""

    def __init__(self, prefix: str):
        self.prefix = prefix
        self.to_engine: dict[str, str] = {}
        self.to_object: dict[str, str] = {}

    def name(self, obj_id: str, label: str | None) -> str:
        if obj_id in self.to_engine:
            return self.to_engine[obj_id]
        cand = label if label and _SAFE.match(label) and label not in self.to_object else None
        if cand is None:
            i = len(self.to_engine) + 1
            cand = f"{self.prefix}{i}"
            while cand in self.to_object:
                i += 1
                cand = f"{self.prefix}{i}"
        self.to_engine[obj_id] = cand
        self.to_object[cand] = obj_id
        return cand


def fnum(v: float, d: int = 4) -> str:
    s = f"{v:.{d}f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s
