"""Horizontal alignment: tangents, circular curves and clothoid transitions.

Input: the PI polyline (start, PIs…, end) in projected coordinates and, for
every interior PI, a radius R and a transition (clothoid) length Ls (0 for
a simple circular curve).  Output: alignment elements with chainages and a
function giving (x, y, bearing) at any chainage.

Standard geometry (symmetric spiral–curve–spiral):
    θs = Ls / (2R)                 spiral angle
    p  = Ls²/(24R) − Ls⁴/(2688R³)  shift
    k  = Ls/2 − Ls³/(240R²)        tangent offset
    Ts = (R + p)·tan(Δ/2) + k      tangent length PI → TS
    Lc = R·(Δ − 2θs)               circular arc length (must be ≥ 0)
Spiral local coordinates (series, l from TS):
    x = l − l⁵/(40R²Ls²) + l⁹/(3456R⁴Ls⁴)
    y = l³/(6RLs) − l⁷/(336R³Ls³) + l¹¹/(42240R⁵Ls⁵)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


def _bearing(a, b) -> float:            # radians, from grid north clockwise
    return math.atan2(b[0] - a[0], b[1] - a[1])


def _fwd(p, brg: float, d: float):
    return (p[0] + d * math.sin(brg), p[1] + d * math.cos(brg))


def _wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


@dataclass
class CurveAtPI:
    pi_index: int
    radius: float
    spiral: float
    delta: float          # signed deflection (rad); + = right-hand
    ts: float             # tangent length
    lc: float             # circular arc length
    p: float
    k: float
    ch_ts: float = 0.0
    ch_sc: float = 0.0
    ch_cs: float = 0.0
    ch_st: float = 0.0

    @property
    def length(self) -> float:
        return 2 * self.spiral + self.lc

    @property
    def external(self) -> float:
        return (self.radius + self.p) / math.cos(abs(self.delta) / 2) - self.radius


@dataclass
class Element:
    kind: str             # tangent | spiral_in | arc | spiral_out
    ch0: float
    length: float
    start: tuple          # (x, y)
    brg0: float           # bearing at start (rad)
    radius: float = 0.0
    spiral: float = 0.0
    turn: int = 0         # +1 right, -1 left
    end: tuple = ()       # for spiral_out: ST point
    brg_end: float = 0.0  # for spiral_out: bearing at ST


@dataclass
class HorizontalAlignment:
    pis: list[tuple[float, float]]
    curves: list[CurveAtPI]
    elements: list[Element]
    length: float
    errors: list[str] = field(default_factory=list)

    def at(self, ch: float) -> tuple[float, float, float]:
        """(x, y, bearing_rad) at chainage ch (clamped to the alignment)."""
        ch = min(max(ch, 0.0), self.length)
        for e in self.elements:
            if ch <= e.ch0 + e.length + 1e-9:
                return _eval(e, ch - e.ch0)
        return _eval(self.elements[-1], self.elements[-1].length)

    def offset_point(self, ch: float, offset: float) -> tuple[float, float]:
        """Point at chainage ch, offset to the right (+) or left (−) of the centreline."""
        x, y, b = self.at(ch)
        return _fwd((x, y), b + math.pi / 2, offset)

    def station(self, pt, step: float = 1.0) -> tuple[float, float]:
        """Nearest (chainage, signed offset) of a point, right = +."""
        best = (0.0, float("inf"))
        n = max(2, int(self.length / step) + 1)
        for i in range(n + 1):
            ch = self.length * i / n
            x, y, _ = self.at(ch)
            d = math.hypot(pt[0] - x, pt[1] - y)
            if d < best[1]:
                best = (ch, d)
        lo, hi = max(0.0, best[0] - step * 2), min(self.length, best[0] + step * 2)
        g = (math.sqrt(5) - 1) / 2
        f = lambda c: math.hypot(pt[0] - self.at(c)[0], pt[1] - self.at(c)[1])
        for _ in range(60):
            a, b = hi - g * (hi - lo), lo + g * (hi - lo)
            if f(a) < f(b):
                hi = b
            else:
                lo = a
        ch = 0.5 * (lo + hi)
        x, y, brg = self.at(ch)
        side = math.sin(brg) * (pt[1] - y) - math.cos(brg) * (pt[0] - x)
        return ch, (-1 if side > 0 else 1) * f(ch)


def _spiral_xy(l: float, R: float, Ls: float) -> tuple[float, float]:
    x = l - l ** 5 / (40 * R ** 2 * Ls ** 2) + l ** 9 / (3456 * R ** 4 * Ls ** 4)
    y = l ** 3 / (6 * R * Ls) - l ** 7 / (336 * R ** 3 * Ls ** 3) + l ** 11 / (42240 * R ** 5 * Ls ** 5)
    return x, y


def _eval(e: Element, s: float) -> tuple[float, float, float]:
    if e.kind == "tangent":
        x, y = _fwd(e.start, e.brg0, s)
        return x, y, e.brg0
    if e.kind == "arc":
        phi = s / e.radius
        chord = 2 * e.radius * math.sin(phi / 2)
        x, y = _fwd(e.start, e.brg0 + e.turn * phi / 2, chord)
        return x, y, e.brg0 + e.turn * phi
    if e.kind == "spiral_in":
        lx, ly = _spiral_xy(s, e.radius, e.spiral)
        x, y = _fwd(_fwd(e.start, e.brg0, lx), e.brg0 + e.turn * math.pi / 2, ly)
        return x, y, e.brg0 + e.turn * s * s / (2 * e.radius * e.spiral)
    # spiral_out: measured back from ST along the reversed direction
    r = e.length - s
    lx, ly = _spiral_xy(r, e.radius, e.spiral)
    back = e.brg_end + math.pi
    x, y = _fwd(_fwd(e.end, back, lx), back - e.turn * math.pi / 2, ly)
    return x, y, e.brg_end - e.turn * r * r / (2 * e.radius * e.spiral)


def build(pis: list[tuple[float, float]], curves: dict[int, tuple[float, float]]) -> HorizontalAlignment:
    """pis: [start, PI1, …, end]; curves: {pi_index: (radius, spiral_length)}."""
    errors: list[str] = []
    if len(pis) < 2:
        raise ValueError("alignment needs at least a start and an end point")
    cs: list[CurveAtPI] = []
    for i in range(1, len(pis) - 1):
        if i not in curves:
            errors.append(f"PI{i}: no curve radius given.")
            continue
        R, Ls = curves[i]
        d = _wrap(_bearing(pis[i], pis[i + 1]) - _bearing(pis[i - 1], pis[i]))
        th = Ls / (2 * R) if Ls else 0.0
        p = Ls ** 2 / (24 * R) - Ls ** 4 / (2688 * R ** 3) if Ls else 0.0
        k = Ls / 2 - Ls ** 3 / (240 * R ** 2) if Ls else 0.0
        ts = (R + p) * math.tan(abs(d) / 2) + k
        lc = R * (abs(d) - 2 * th)
        if lc < -1e-9:
            errors.append(f"PI{i}: transitions too long for the deflection (arc length {lc:.1f} m < 0).")
        cs.append(CurveAtPI(i, R, Ls, d, ts, max(lc, 0.0), p, k))
    # tangent fit
    for a, b in zip([None] + cs, cs + [None]):
        i0 = a.pi_index if a else 0
        i1 = b.pi_index if b else len(pis) - 1
        avail = math.dist(pis[i0], pis[i1]) if (a or b) else 0
        need = (a.ts if a else 0) + (b.ts if b else 0)
        if (a or b) and need > avail + 1e-6 and (i1 - i0 == 1):
            errors.append(f"Tangent PI{i0}–PI{i1}: curves need {need:.1f} m but only {avail:.1f} m available.")

    elements: list[Element] = []
    ch = 0.0
    pos = tuple(pis[0])
    by_pi = {c.pi_index: c for c in cs}
    for i in range(1, len(pis)):
        brg = _bearing(pis[i - 1], pis[i])
        c = by_pi.get(i) if i < len(pis) - 1 else None
        target = _fwd(pis[i], brg + math.pi, c.ts) if c else tuple(pis[i])
        tl = math.dist(pos, target)
        if tl > 1e-9:
            elements.append(Element("tangent", ch, tl, pos, brg))
            ch += tl
        if not c:
            pos = target
            continue
        turn = 1 if c.delta > 0 else -1
        c.ch_ts = ch
        brg_out = _bearing(pis[i], pis[i + 1])
        st = _fwd(pis[i], brg_out, c.ts)
        if c.spiral:
            e = Element("spiral_in", ch, c.spiral, target, brg, c.radius, c.spiral, turn)
            elements.append(e)
            ch += c.spiral
        c.ch_sc = ch
        x, y, b = _eval(elements[-1], elements[-1].length) if c.spiral else (*target, brg)
        if c.lc > 0:
            elements.append(Element("arc", ch, c.lc, (x, y), b, c.radius, 0, turn))
            ch += c.lc
        c.ch_cs = ch
        if c.spiral:
            elements.append(Element("spiral_out", ch, c.spiral, (), 0, c.radius, c.spiral, turn, st, brg_out))
            ch += c.spiral
        c.ch_st = ch
        pos = st
    return HorizontalAlignment([tuple(p) for p in pis], cs, elements, ch, errors)
