"""Steady uniform-flow hydraulics of a circular gravity sewer (Manning).

This is the standard design-sheet calculation used to size gravity sewers:
uniform flow, Manning's equation, partially full circular section.  It is
NOT a network simulation – backwater, surcharge propagation and the
hydraulic grade line are computed by EPA SWMM through
``cityinfra.engines.swmm``.

Units: SI throughout (m, m², m/s, m³/s).

Geometry of a circular section of diameter D flowing at depth y:
    θ = 2·acos(1 − 2y/D)                (central angle, rad)
    A = D²/8 · (θ − sin θ)
    P = D·θ/2
    R = A/P
    Q = (1/n)·A·R^(2/3)·S^(1/2)
Q(y) is maximal at y/D ≈ 0.938 (≈1.076·Q_full); above that depth a uniform
flow solution does not increase capacity, so a demand above Q_max means the
pipe cannot carry the flow in open-channel conditions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Y_QMAX = 0.9382  # y/D at which a circular conduit's Manning discharge peaks


def section(D: float, y: float) -> tuple[float, float, float]:
    """Return (area, wetted perimeter, top width) at depth y."""
    if y <= 0:
        return 0.0, 0.0, 0.0
    y = min(y, D)
    theta = 2.0 * math.acos(1.0 - 2.0 * y / D)
    area = D * D / 8.0 * (theta - math.sin(theta))
    perim = D * theta / 2.0
    top = D * math.sin(theta / 2.0)
    return area, perim, top


def manning_q(D: float, y: float, slope: float, n: float) -> float:
    a, p, _ = section(D, y)
    if a == 0 or slope <= 0:
        return 0.0
    return a * (a / p) ** (2.0 / 3.0) * math.sqrt(slope) / n


def full_flow(D: float, slope: float, n: float) -> tuple[float, float]:
    """(Q_full m³/s, V_full m/s)."""
    q = manning_q(D, D, slope, n)
    return q, q / (math.pi * D * D / 4.0)


@dataclass(frozen=True)
class FlowState:
    flow: float          # m³/s
    depth: float         # m
    depth_ratio: float   # y/D
    velocity: float      # m/s
    q_full: float        # m³/s
    v_full: float        # m/s
    capacity_ok: bool    # False if flow exceeds the max open-channel capacity


def uniform_flow(D: float, slope: float, n: float, Q: float, tol: float = 1e-9) -> FlowState:
    """Normal depth and velocity for discharge Q (bisection on y ∈ (0, 0.938D])."""
    if D <= 0 or n <= 0:
        raise ValueError("diameter and Manning n must be positive")
    if slope <= 0:
        raise ValueError("gravity sewer slope must be positive (falling downstream)")
    qf, vf = full_flow(D, slope, n)
    if Q <= 0:
        return FlowState(0.0, 0.0, 0.0, 0.0, qf, vf, True)
    y_hi = Y_QMAX * D
    if Q > manning_q(D, y_hi, slope, n):
        # Uniform open-channel flow impossible: report as running full.
        return FlowState(Q, D, 1.0, Q / (math.pi * D * D / 4.0), qf, vf, False)
    lo, hi = 0.0, y_hi
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if manning_q(D, mid, slope, n) < Q:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol * D:
            break
    y = 0.5 * (lo + hi)
    a, _, _ = section(D, y)
    return FlowState(Q, y, y / D, Q / a, qf, vf, True)


def slope_for_velocity(D: float, n: float, Q: float, v_target: float) -> float:
    """Smallest slope at which flow Q reaches velocity v_target (bisection on S)."""
    lo, hi = 1e-6, 0.5
    if uniform_flow(D, hi, n, Q).velocity < v_target:
        raise ValueError("target velocity not reachable at any practical slope")
    for _ in range(200):
        mid = math.sqrt(lo * hi)
        if uniform_flow(D, mid, n, Q).velocity < v_target:
            lo = mid
        else:
            hi = mid
        if hi / lo < 1 + 1e-7:
            break
    return hi
