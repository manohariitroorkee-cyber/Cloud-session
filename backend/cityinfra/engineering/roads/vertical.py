"""Vertical alignment (grades and symmetric parabolic vertical curves),
terrain surface (TIN) and sight-distance requirements."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


@dataclass
class VIP:
    chainage: float
    level: float
    curve_length: float = 0.0


@dataclass
class VerticalAlignment:
    vips: list[VIP]
    errors: list[str] = field(default_factory=list)

    def __post_init__(self):
        v = self.vips
        if len(v) < 2:
            raise ValueError("profile needs at least two VIPs")
        for a, b in zip(v, v[1:]):
            if b.chainage <= a.chainage:
                self.errors.append(f"VIPs must increase in chainage ({a.chainage} → {b.chainage}).")
        for i in range(1, len(v) - 1):
            lo = v[i].chainage - v[i].curve_length / 2
            hi = v[i].chainage + v[i].curve_length / 2
            prev_end = v[i - 1].chainage + v[i - 1].curve_length / 2
            if lo < prev_end - 1e-9:
                self.errors.append(f"Vertical curve at ch {v[i].chainage:.1f} overlaps the previous curve.")
            if i == len(v) - 2 and hi > v[-1].chainage + 1e-9:
                self.errors.append(f"Vertical curve at ch {v[i].chainage:.1f} runs past the profile end.")

    def grade(self, i: int) -> float:
        a, b = self.vips[i], self.vips[i + 1]
        return (b.level - a.level) / (b.chainage - a.chainage)

    def level(self, ch: float) -> float:
        v = self.vips
        for i in range(1, len(v) - 1):
            L = v[i].curve_length
            if L > 0 and v[i].chainage - L / 2 <= ch <= v[i].chainage + L / 2:
                g1, g2 = self.grade(i - 1), self.grade(i)
                x = ch - (v[i].chainage - L / 2)
                z0 = v[i].level - g1 * L / 2
                return z0 + g1 * x + (g2 - g1) / (2 * L) * x * x
        for i in range(len(v) - 1):
            if ch <= v[i + 1].chainage or i == len(v) - 2:
                return v[i].level + self.grade(i) * (ch - v[i].chainage)
        raise AssertionError

    def curves(self):
        """(index, g1, g2, L, kind) for every interior VIP."""
        out = []
        for i in range(1, len(self.vips) - 1):
            g1, g2 = self.grade(i - 1), self.grade(i)
            out.append((i, g1, g2, self.vips[i].curve_length, "crest" if g2 < g1 else "sag"))
        return out


def ssd(speed_kmh: float, reaction_s: float, f_long: float) -> float:
    """Stopping sight distance: v·t + v²/(2·g·f)  (v in m/s)."""
    v = speed_kmh / 3.6
    return v * reaction_s + v * v / (2 * 9.81 * f_long)


def crest_length_for(S: float, A: float, h1: float, h2: float) -> float:
    """Minimum crest curve length for sight distance S (A = |g2 − g1| as a fraction)."""
    if A <= 0:
        return 0.0
    k = (math.sqrt(2 * h1) + math.sqrt(2 * h2)) ** 2
    L = A * S * S / k
    return L if L >= S else max(0.0, 2 * S - k / A)


def sag_length_for(S: float, A: float, h: float, beam_deg: float) -> float:
    """Minimum sag curve length for headlight sight distance S."""
    if A <= 0:
        return 0.0
    d = 2 * h + 2 * S * math.tan(math.radians(beam_deg))
    L = A * S * S / d
    return L if L >= S else max(0.0, 2 * S - d / A)


class TIN:
    """Linear interpolation on a Delaunay triangulation of surveyed points."""

    def __init__(self, pts: list[tuple[float, float, float]]):
        from scipy.spatial import Delaunay
        if len(pts) < 3:
            raise ValueError("terrain needs at least three surveyed points")
        a = np.asarray(pts, float)
        self.xy, self.z = a[:, :2], a[:, 2]
        self.tri = Delaunay(self.xy)

    def level(self, x: float, y: float) -> float | None:
        s = int(self.tri.find_simplex([[x, y]])[0])
        if s < 0:
            return None                       # outside surveyed area: never extrapolated
        T = self.tri.transform[s]
        b = T[:2].dot(np.array([x, y]) - T[2])
        w = np.append(b, 1 - b.sum())
        return float(w.dot(self.z[self.tri.simplices[s]]))
