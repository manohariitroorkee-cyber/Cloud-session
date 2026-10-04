"""Uniform (normal-depth) flow in prismatic sections by Manning's equation.

Shared by storm drainage (pipes, box drains, open channels) and usable by
any gravity conduit.  Circular sections delegate to the sewer hydraulics.

    Q = (1/n) · A · R^(2/3) · S^(1/2)

For closed sections (pipe, box) Q(y) peaks below the soffit; flow above that
peak cannot be carried in open-channel conditions and is reported as
``capacity_ok = False``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..sewer import hydraulics as circ


@dataclass(frozen=True)
class Section:
    shape: str                 # "circular" | "rectangular" | "trapezoidal"
    depth: float               # internal height / diameter (m)
    width: float = 0.0         # bottom width (m); diameter for circular
    side_slope: float = 0.0    # trapezoid H:V
    closed: bool = False       # box culvert vs open drain

    def geometry(self, y: float) -> tuple[float, float]:
        """(area, wetted perimeter) at depth y."""
        y = max(0.0, min(y, self.depth))
        if self.shape == "circular":
            a, p, _ = circ.section(self.depth, y)
            return a, p
        b, z = self.width, self.side_slope
        a = (b + z * y) * y
        p = b + 2 * y * math.sqrt(1 + z * z)
        if self.closed and y >= self.depth - 1e-12:
            p += b + 2 * z * y    # soffit wetted when full
        return a, p

    def full_area(self) -> float:
        return self.geometry(self.depth)[0]


def q_at(sec: Section, y: float, slope: float, n: float) -> float:
    a, p = sec.geometry(y)
    if a <= 0 or slope <= 0:
        return 0.0
    return a * (a / p) ** (2 / 3) * math.sqrt(slope) / n


@dataclass(frozen=True)
class ChannelFlow:
    flow: float
    depth: float
    depth_ratio: float
    velocity: float
    q_capacity: float          # max open-channel discharge of the section
    capacity_ok: bool


def _y_qmax(sec: Section, slope: float, n: float) -> float:
    if sec.shape == "circular":
        return circ.Y_QMAX * sec.depth
    if not sec.closed:
        return sec.depth          # open: Q increases monotonically to the top
    # closed box: soffit friction makes Q peak just below full; golden-section search
    lo, hi = 0.5 * sec.depth, sec.depth * (1 - 1e-9)
    g = (math.sqrt(5) - 1) / 2
    for _ in range(80):
        a, b = hi - g * (hi - lo), lo + g * (hi - lo)
        if q_at(sec, a, slope, n) < q_at(sec, b, slope, n):
            lo = a
        else:
            hi = b
    return 0.5 * (lo + hi)


def normal_flow(sec: Section, slope: float, n: float, Q: float) -> ChannelFlow:
    if slope <= 0:
        raise ValueError("gravity drain slope must be positive (falling downstream)")
    ym = _y_qmax(sec, slope, n)
    qmax = q_at(sec, ym, slope, n)
    if Q <= 0:
        return ChannelFlow(0.0, 0.0, 0.0, 0.0, qmax, True)
    if Q > qmax:
        return ChannelFlow(Q, sec.depth, 1.0, Q / sec.full_area(), qmax, False)
    lo, hi = 0.0, ym
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if q_at(sec, mid, slope, n) < Q:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-10:
            break
    y = 0.5 * (lo + hi)
    return ChannelFlow(Q, y, y / sec.depth, Q / sec.geometry(y)[0], qmax, True)
