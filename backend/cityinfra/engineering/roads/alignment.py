"""General horizontal alignment engine: any combination of straights, circular
arcs and clothoid transitions.

Every horizontal geometry is reduced to a chain of ELEMENTS, each with a
start point, start bearing, length and a curvature that varies linearly
along it (clothoid):

    line      k0 = k1 = 0
    arc       k0 = k1 = ±1/R
    spiral    k0 → k1 (any two curvatures: tangent→arc, arc→tangent,
              arc→arc of different radius (compound / egg), +k → −k (S-curve))

Sign convention: bearings are measured from grid north, clockwise; positive
curvature turns RIGHT (clockwise), negative turns LEFT.

    heading(s)  = b0 + k0·s + (k1 − k0)·s² / (2L)
    position(s) = start + ∫₀ˢ (sin h, cos h) dt     (closed form for lines and
                                                       arcs; Gauss–Legendre for
                                                       spirals, error < 1e-9 m)

This covers every curve type drawn in practice: simple circular, spiral–
curve–spiral (equal or unequal transitions), spiral–spiral, compound
curves (with or without transitions between arcs), reverse and S-curves,
broken-back curves, hairpin bends (deflection ≥ 180°) and full circles.

Builders
--------
from_pis(...)       PI polyline + a curve specification at each PI
from_elements(...)  explicit element chain (hairpins, loops, any sequence)
from_bulges(...)    CAD polyline with arc bulges (DXF LWPOLYLINE)
fit_drawn(...)      freehand / traced centreline → tangents + fitted radii
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# 5-point Gauss–Legendre nodes and weights on [-1, 1]
_GL_X = (-0.9061798459386640, -0.5384693101056831, 0.0, 0.5384693101056831, 0.9061798459386640)
_GL_W = (0.2369268850561891, 0.4786286704993665, 0.5688888888888889, 0.4786286704993665, 0.2369268850561891)
SPIRAL_PIECE_M = 5.0
G1_TOL_RAD = 1e-4          # heading mismatch treated as a kink (≈ 0.006°)


def _u(b: float) -> tuple[float, float]:
    return math.sin(b), math.cos(b)


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def bearing(a, b) -> float:
    return math.atan2(b[0] - a[0], b[1] - a[1])


@dataclass
class Element:
    kind: str                  # line | arc | spiral
    length: float
    k0: float
    k1: float
    x0: float = 0.0
    y0: float = 0.0
    b0: float = 0.0
    ch0: float = 0.0
    tag: str = ""              # e.g. "PI2" – the curve group it belongs to

    def heading(self, s: float) -> float:
        if self.length <= 0:
            return self.b0
        return self.b0 + self.k0 * s + (self.k1 - self.k0) * s * s / (2 * self.length)

    def curvature(self, s: float) -> float:
        return self.k0 if self.length <= 0 else self.k0 + (self.k1 - self.k0) * s / self.length

    def point(self, s: float) -> tuple[float, float]:
        if s <= 0:
            return self.x0, self.y0
        if self.kind == "line" or (abs(self.k0) < 1e-15 and abs(self.k1) < 1e-15):
            ux, uy = _u(self.b0)
            return self.x0 + s * ux, self.y0 + s * uy
        if self.kind == "arc":
            k = self.k0
            chord = 2 * math.sin(k * s / 2) / k
            ux, uy = _u(self.b0 + k * s / 2)
            return self.x0 + chord * ux, self.y0 + chord * uy
        n = max(1, math.ceil(s / SPIRAL_PIECE_M))
        h = s / n
        x, y = self.x0, self.y0
        for i in range(n):
            a = i * h
            for xi, wi in zip(_GL_X, _GL_W):
                t = a + h * (xi + 1) / 2
                hx, hy = _u(self.heading(t))
                x += wi * h / 2 * hx
                y += wi * h / 2 * hy
        return x, y

    def end(self) -> tuple[float, float, float]:
        x, y = self.point(self.length)
        return x, y, self.heading(self.length)

    @property
    def radius(self) -> float | None:
        return 1 / abs(self.k0) if self.kind == "arc" and self.k0 else None

    @property
    def deflection(self) -> float:
        return (self.k0 + self.k1) / 2 * self.length


@dataclass
class CurveGroup:
    """Curved elements between two tangents (one PI in PI mode)."""
    tag: str
    kind: str                 # simple | spiral-curve-spiral | spiral-spiral | compound | ...
    elements: list[Element]
    delta: float = 0.0        # signed total deflection (rad)
    pi: tuple | None = None
    t_in: float = 0.0         # tangent lengths PI→start, PI→end (PI mode)
    t_out: float = 0.0
    pi_index: int | None = None

    @property
    def radii(self) -> list[float]:
        return [e.radius for e in self.elements if e.kind == "arc" and e.radius]

    @property
    def radius(self) -> float:
        r = self.radii
        return min(r) if r else min(1 / max(abs(e.k0), abs(e.k1)) for e in self.elements if max(abs(e.k0), abs(e.k1)) > 0)

    @property
    def spiral_in(self) -> float:
        e = self.elements[0]
        return e.length if e.kind == "spiral" else 0.0

    @property
    def spiral_out(self) -> float:
        e = self.elements[-1]
        return e.length if e.kind == "spiral" else 0.0

    @property
    def arc_length(self) -> float:
        return sum(e.length for e in self.elements if e.kind == "arc")

    @property
    def length(self) -> float:
        return sum(e.length for e in self.elements)

    @property
    def ch_start(self) -> float:
        return self.elements[0].ch0

    @property
    def ch_end(self) -> float:
        return self.elements[-1].ch0 + self.elements[-1].length


@dataclass
class Alignment:
    elements: list[Element]
    groups: list[CurveGroup] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    kinks: list[tuple[float, float]] = field(default_factory=list)   # (chainage, angle rad) where heading jumps
    pis: list[tuple] = field(default_factory=list)
    source: str = ""          # pi | elements | bulges | fit
    fit_report: dict | None = None

    @property
    def length(self) -> float:
        if not self.elements:
            return 0.0
        e = self.elements[-1]
        return e.ch0 + e.length

    def _find(self, ch: float) -> tuple[Element, float]:
        ch = min(max(ch, 0.0), self.length)
        for e in self.elements:
            if ch <= e.ch0 + e.length + 1e-9:
                return e, ch - e.ch0
        e = self.elements[-1]
        return e, e.length

    def at(self, ch: float) -> tuple[float, float, float]:
        e, s = self._find(ch)
        x, y = e.point(s)
        return x, y, e.heading(s)

    def curvature(self, ch: float) -> float:
        e, s = self._find(ch)
        return e.curvature(s)

    def offset_point(self, ch: float, offset: float) -> tuple[float, float]:
        """Point at chainage ch, offset right (+) or left (−) of the centreline."""
        x, y, b = self.at(ch)
        rx, ry = math.cos(b), -math.sin(b)
        return x + offset * rx, y + offset * ry

    def station(self, pt, step: float = 1.0) -> tuple[float, float]:
        """Nearest (chainage, signed offset) of a point; right of the direction of travel = +."""
        n = max(2, int(self.length / step) + 1)
        best_ch, best_d = 0.0, float("inf")
        for i in range(n + 1):
            ch = self.length * i / n
            x, y, _ = self.at(ch)
            d = math.hypot(pt[0] - x, pt[1] - y)
            if d < best_d:
                best_ch, best_d = ch, d
        lo, hi = max(0.0, best_ch - 2 * step), min(self.length, best_ch + 2 * step)
        f = lambda c: math.hypot(pt[0] - self.at(c)[0], pt[1] - self.at(c)[1])
        g = (math.sqrt(5) - 1) / 2
        for _ in range(70):
            a, b = hi - g * (hi - lo), lo + g * (hi - lo)
            if f(a) < f(b):
                hi = b
            else:
                lo = a
        ch = 0.5 * (lo + hi)
        x, y, brg = self.at(ch)
        right = (pt[0] - x) * math.cos(brg) - (pt[1] - y) * math.sin(brg)
        return ch, math.copysign(f(ch), right if abs(right) > 1e-12 else 1.0)

    def coordinates(self, step: float = 2.0) -> list[tuple[float, float]]:
        """Densified centreline for drawing / export (every element end included)."""
        pts = []
        for e in self.elements:
            n = 1 if e.kind == "line" else max(2, math.ceil(e.length / step))
            for i in range(n):
                pts.append(e.point(e.length * i / n))
        x, y, _ = self.elements[-1].end()
        pts.append((x, y))
        return pts


def _place(chain: list[Element], x: float, y: float, b: float, ch: float = 0.0) -> tuple[float, float, float, float]:
    for e in chain:
        e.x0, e.y0, e.b0, e.ch0 = x, y, b, ch
        x, y, b = e.end()
        ch += e.length
    return x, y, b, ch


def _classify(els: list[Element]) -> str:
    arcs = [e for e in els if e.kind == "arc" and e.length > 1e-9]
    spirals = [e for e in els if e.kind == "spiral"]
    signs = {math.copysign(1, e.k0 + e.k1) for e in els if abs(e.k0) + abs(e.k1) > 0}
    if len(signs) > 1:
        return "reverse (S) curve"
    radii = {round(1 / abs(e.k0), 6) for e in arcs}
    if len(radii) > 1:
        return "compound curve" + (" with transitions" if spirals else "")
    if not arcs:
        return "spiral–spiral"
    if not spirals:
        return "simple circular"
    s_in = els[0].length if els[0].kind == "spiral" else 0
    s_out = els[-1].length if els[-1].kind == "spiral" else 0
    if s_in and s_out and abs(s_in - s_out) > 1e-6:
        return "spiral–curve–spiral (unequal transitions)"
    if s_in and s_out:
        return "spiral–curve–spiral"
    return "curve with one-sided transition"


# ---------------------------------------------------------------- PI mode

def normalise_spec(spec) -> dict:
    """Accepts the forms a designer may give for a PI:
        [R, Ls]                                   legacy symmetric
        {"R": 200}                                simple
        {"R": 200, "Ls": 60}                      symmetric transitions
        {"R": 200, "Ls_in": 60, "Ls_out": 40}     unequal transitions
        {"type": "spiral_spiral", "R": 200}       spiral–spiral (no arc); Ls solved
        {"arcs": [{"R": 400, "deflection_deg": 15}, {"R": 200}],
         "Ls_in": 60, "Ls_between": [40], "Ls_out": 50}   compound (any number of arcs)
    The last arc's length is solved so the curve fits the PI's deflection;
    every other arc needs "deflection_deg" or "length"."""
    if isinstance(spec, (list, tuple)):
        R, Ls = float(spec[0]), float(spec[1]) if len(spec) > 1 else 0.0
        return {"arcs": [{"R": R}], "Ls_in": Ls, "Ls_out": Ls, "Ls_between": []}
    s = dict(spec)
    if s.get("type") == "spiral_spiral":
        return {"arcs": [{"R": float(s["R"]), "length": 0.0}], "spiral_spiral": True, "Ls_between": []}
    if "arcs" not in s:
        s["arcs"] = [{"R": float(s["R"])}]
    ls = float(s.get("Ls", 0.0))
    s.setdefault("Ls_in", ls)
    s.setdefault("Ls_out", ls)
    s.setdefault("Ls_between", [0.0] * (len(s["arcs"]) - 1))
    if len(s["Ls_between"]) != len(s["arcs"]) - 1:
        raise ValueError("Ls_between needs one value per junction between arcs")
    return s


def _group_elements(spec: dict, delta: float) -> list[Element]:
    sgn = 1.0 if delta > 0 else -1.0
    D = abs(delta)
    arcs = spec["arcs"]
    ks = [sgn / float(a["R"]) for a in arcs]
    if spec.get("spiral_spiral"):
        Ls = abs(1 / ks[0]) * D            # each spiral turns D/2 = Ls/(2R)
        return [Element("spiral", Ls, 0.0, ks[0]), Element("spiral", Ls, ks[0], 0.0)]
    els: list[Element] = []
    if spec["Ls_in"] > 0:
        els.append(Element("spiral", float(spec["Ls_in"]), 0.0, ks[0]))
    close_idx = None
    for i, (a, k) in enumerate(zip(arcs, ks)):
        if "length" in a:
            L = float(a["length"])
        elif "deflection_deg" in a:
            L = math.radians(float(a["deflection_deg"])) / abs(k)
        elif close_idx is None:
            L, close_idx = None, len(els)
        else:
            raise ValueError("only one arc may be left without deflection_deg/length (it is solved to fit the PI)")
        els.append(Element("arc", L if L is not None else 0.0, k, k))
        if i < len(arcs) - 1 and spec["Ls_between"][i] > 0:
            els.append(Element("spiral", float(spec["Ls_between"][i]), k, ks[i + 1]))
    if spec["Ls_out"] > 0:
        els.append(Element("spiral", float(spec["Ls_out"]), ks[-1], 0.0))
    if close_idx is not None:
        known = sum(abs(e.deflection) for j, e in enumerate(els) if j != close_idx)
        rest = D - known
        if rest < -1e-9:
            raise ValueError(f"transitions/arcs turn {math.degrees(known):.2f}° but the PI deflects only "
                             f"{math.degrees(D):.2f}° – shorten transitions or reduce radius")
        els[close_idx].length = max(rest, 0.0) / abs(els[close_idx].k0)
    else:
        total = sum(abs(e.deflection) for e in els)
        if abs(total - D) > 1e-6:
            raise ValueError(f"curve elements turn {math.degrees(total):.3f}° but the PI deflects "
                             f"{math.degrees(D):.3f}° – leave one arc without deflection to close the curve")
    return els


def _fit_group(els: list[Element], pi, b_in: float, b_out: float) -> tuple[float, float]:
    """Tangent lengths (PI→start along incoming, PI→end along outgoing)."""
    _, _, _, _ = _place(els, 0.0, 0.0, b_in)
    ex, ey, eb = els[-1].end()
    if abs(wrap(eb - b_out)) > 1e-7:
        raise ValueError("curve does not close on the outgoing tangent")
    ui, uo = _u(b_in), _u(b_out)
    det = ui[0] * uo[1] - ui[1] * uo[0]
    t1 = (ex * uo[1] - ey * uo[0]) / det
    t2 = (ui[0] * ey - ui[1] * ex) / det
    return t1, t2


def from_pis(pis: list[tuple[float, float]], specs: dict[int, object]) -> Alignment:
    """pis = [start, PI1, …, PIn, end]; specs = {pi_index: spec} (see normalise_spec)."""
    errors: list[str] = []
    if len(pis) < 2:
        raise ValueError("alignment needs at least a start and an end point")
    groups: list[CurveGroup] = []
    for i in range(1, len(pis) - 1):
        b_in, b_out = bearing(pis[i - 1], pis[i]), bearing(pis[i], pis[i + 1])
        delta = wrap(b_out - b_in)
        if abs(delta) < 1e-9:
            continue
        if abs(abs(delta) - math.pi) < 1e-6:
            errors.append(f"PI{i}: the alignment doubles back (180°). Use element mode for hairpins.")
            continue
        if i not in specs:
            errors.append(f"PI{i}: deflection {math.degrees(delta):+.2f}° but no curve given.")
            continue
        try:
            spec = normalise_spec(specs[i])
            els = _group_elements(spec, delta)
            t1, t2 = _fit_group(els, pis[i], b_in, b_out)
        except (ValueError, KeyError, ZeroDivisionError) as e:
            errors.append(f"PI{i}: {e}")
            continue
        for e in els:
            e.tag = f"PI{i}"
        g = CurveGroup(f"PI{i}", _classify(els), els, delta, tuple(pis[i]), t1, t2, i)
        groups.append(g)
    # tangents between consecutive curves / ends
    chain: list[Element] = []
    by_i = {g.pi_index: g for g in groups}
    pos = tuple(pis[0])
    for i in range(1, len(pis)):
        b = bearing(pis[i - 1], pis[i])
        g = by_i.get(i) if i < len(pis) - 1 else None
        if g:
            ux, uy = _u(b)
            start = (pis[i][0] - g.t_in * ux, pis[i][1] - g.t_in * uy)
        else:
            start = tuple(pis[i])
        tl = (start[0] - pos[0]) * math.sin(b) + (start[1] - pos[1]) * math.cos(b)
        if tl < -1e-6:
            name = lambda j: "start" if j == 0 else ("end" if j == len(pis) - 1 else f"PI{j}")
            prev = by_i.get(i - 1)
            who = " and ".join(x.tag for x in (prev, g) if x)
            hints = []
            for x in (prev, g):
                if x:
                    rmax, alone = _max_radius(pis, specs, x.pi_index)
                    hints.append(f"largest radius at {x.tag}: {rmax:.0f} m" + (" if the neighbouring curve is also reduced" if alone else ""))
            errors.append(f"Tangent {name(i-1)}–{name(i)}: {who} overlap by {-tl:.2f} m. Reduce radius or transition "
                          f"length, or move the PIs apart ({'; '.join(hints)}).")
        if tl > 1e-9:
            chain.append(Element("line", tl, 0.0, 0.0))
        if g:
            chain.extend(g.elements)
            ux, uy = _u(bearing(pis[i], pis[i + 1]))
            pos = (pis[i][0] + g.t_out * ux, pis[i][1] + g.t_out * uy)
        else:
            pos = tuple(pis[i])
    a = Alignment(chain, groups, errors, pis=[tuple(p) for p in pis], source="pi")
    if chain:
        _place(chain, pis[0][0], pis[0][1], bearing(pis[0], pis[1]))
        ex, ey, _ = chain[-1].end()
        if not errors and math.hypot(ex - pis[-1][0], ey - pis[-1][1]) > 1e-4:
            errors.append(f"Internal check: alignment closes {math.hypot(ex - pis[-1][0], ey - pis[-1][1]):.4f} m from the end point.")
    return a


def _max_radius(pis, specs, i: int) -> tuple[float, bool]:
    """Largest radius (scaling every radius at PI i, transitions fixed) whose tangents fit.
    Returns (radius, assumes_neighbours_reduced)."""
    base = normalise_spec(specs[i])
    b_in, b_out = bearing(pis[i - 1], pis[i]), bearing(pis[i], pis[i + 1])
    delta = wrap(b_out - b_in)
    full_in, full_out = math.dist(pis[i - 1], pis[i]), math.dist(pis[i], pis[i + 1])
    avail_in = full_in - _t_other(pis, specs, i - 1, "out")
    avail_out = full_out - _t_other(pis, specs, i + 1, "in")
    alone = avail_in <= 0 or avail_out <= 0
    if alone:
        avail_in, avail_out = full_in / (2 if i - 1 > 0 and (i - 1) in specs else 1), \
                              full_out / (2 if i + 1 < len(pis) - 1 and (i + 1) in specs else 1)

    def fits(scale: float) -> bool:
        s = dict(base, arcs=[dict(a, R=float(a["R"]) * scale) for a in base["arcs"]])
        try:
            t1, t2 = _fit_group(_group_elements(s, delta), pis[i], b_in, b_out)
        except ValueError:
            return False
        return t1 <= avail_in + 1e-9 and t2 <= avail_out + 1e-9

    lo, hi = 1e-4, 1.0
    if not fits(lo):
        return 0.0, alone
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if fits(mid) else (lo, mid)
    return min(float(a["R"]) for a in base["arcs"]) * lo, alone


def _t_other(pis, specs, j: int, which: str) -> float:
    if j <= 0 or j >= len(pis) - 1 or j not in specs:
        return 0.0
    b_in, b_out = bearing(pis[j - 1], pis[j]), bearing(pis[j], pis[j + 1])
    delta = wrap(b_out - b_in)
    if abs(delta) < 1e-9:
        return 0.0
    try:
        t1, t2 = _fit_group(_group_elements(normalise_spec(specs[j]), delta), pis[j], b_in, b_out)
    except ValueError:
        return 0.0
    return t2 if which == "out" else t1


# ---------------------------------------------------------- element mode

def from_elements(start: tuple[float, float], start_bearing_rad: float, specs: list[dict]) -> Alignment:
    """Element chain, e.g.
        [{"line": 120},
         {"spiral": 50, "to_R": 30, "turn": "left"},
         {"arc": 150, "R": 30, "turn": "left"},          # hairpin: arc may turn > 180°
         {"spiral": 50, "from_R": 30, "turn": "left"},
         {"line": 200},
         {"arc_deg": 360, "R": 25, "turn": "right"}]       # full circle
    Spiral ends default to a straight (R = ∞); "to_turn" lets an S-spiral change direction."""
    chain: list[Element] = []
    errors: list[str] = []
    for n, s in enumerate(specs, 1):
        sg = 1.0 if s.get("turn", "right") == "right" else -1.0
        try:
            if "line" in s:
                chain.append(Element("line", float(s["line"]), 0.0, 0.0, tag=f"E{n}"))
            elif "arc" in s or "arc_deg" in s:
                R = float(s["R"])
                L = float(s["arc"]) if "arc" in s else math.radians(float(s["arc_deg"])) * R
                chain.append(Element("arc", L, sg / R, sg / R, tag=f"E{n}"))
            elif "spiral" in s:
                sg_to = (1.0 if s.get("to_turn", s.get("turn", "right")) == "right" else -1.0)
                k0 = sg / float(s["from_R"]) if s.get("from_R") else 0.0
                k1 = sg_to / float(s["to_R"]) if s.get("to_R") else 0.0
                chain.append(Element("spiral", float(s["spiral"]), k0, k1, tag=f"E{n}"))
            else:
                raise ValueError(f"unknown element {s}")
        except (KeyError, ValueError, ZeroDivisionError) as e:
            errors.append(f"Element {n}: {e}")
    if chain and any(e.length <= 0 for e in chain):
        errors.append("Every element needs a positive length.")
    _place(chain, start[0], start[1], start_bearing_rad)
    a = Alignment(chain, _groups_from_chain(chain), errors, source="elements")
    for k, (e1, e2) in enumerate(zip(chain, chain[1:]), 1):
        if abs(e1.k1 - e2.k0) > 1e-9:
            a.warnings.append(f"Curvature jumps between elements {k} and {k+1} "
                              f"(R {_r(e1.k1)} → {_r(e2.k0)}); a transition may be needed.")
    return a


def _r(k: float) -> str:
    return "∞" if abs(k) < 1e-12 else f"{1/abs(k):.0f} m"


def _groups_from_chain(chain: list[Element]) -> list[CurveGroup]:
    groups, cur = [], []
    for e in chain + [Element("line", 0, 0, 0)]:
        if e.kind == "line":
            if cur:
                tag = f"C{len(groups)+1}"
                for x in cur:
                    x.tag = x.tag or tag
                groups.append(CurveGroup(tag, _classify(cur), cur, sum(x.deflection for x in cur)))
                cur = []
        else:
            cur.append(e)
    return groups


# -------------------------------------------------------- CAD bulge mode

def from_bulges(vertices: list[tuple[float, float]], bulges: list[float]) -> Alignment:
    """CAD polyline: straight segments and arcs given by bulge = tan(θ/4),
    positive = counter-clockwise (left turn) as in DXF.  Heading breaks at
    vertices are recorded as kinks (angle points without a curve)."""
    if len(bulges) < len(vertices) - 1:
        bulges = list(bulges) + [0.0] * (len(vertices) - 1 - len(bulges))
    chain: list[Element] = []
    ch = 0.0
    for i in range(len(vertices) - 1):
        a, b, bu = vertices[i], vertices[i + 1], float(bulges[i])
        c = math.dist(a, b)
        bc = bearing(a, b)
        if abs(bu) < 1e-12:
            e = Element("line", c, 0.0, 0.0, a[0], a[1], bc, ch)
        else:
            th = 4 * math.atan(bu)               # signed included angle, + = CCW (left)
            R = c / (2 * math.sin(abs(th) / 2))
            k = -math.copysign(1 / R, th)        # left turn = negative curvature here
            e = Element("arc", R * abs(th), k, k, a[0], a[1], bc + abs(th) / 2 * (1 if th > 0 else -1), ch)
        chain.append(e)
        ch += e.length
    al = Alignment(chain, _groups_from_chain(chain), [], source="bulges")
    for e1, e2 in zip(chain, chain[1:]):
        jump = wrap(e2.b0 - e1.heading(e1.length))
        if abs(jump) > G1_TOL_RAD:
            al.kinks.append((e2.ch0, jump))
    return al


# ----------------------------------------------------- freehand fitting

def _resample(pts: list[tuple[float, float]], ds: float) -> list[tuple[float, float]]:
    out = [tuple(pts[0])]
    carry = 0.0
    for a, b in zip(pts, pts[1:]):
        seg = math.dist(a, b)
        if seg == 0:
            continue
        t = ds - carry
        while t <= seg + 1e-12:
            f = t / seg
            out.append((a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])))
            t += ds
        carry = seg - (t - ds)
    if math.dist(out[-1], pts[-1]) > 1e-6:
        out.append(tuple(pts[-1]))
    return out


def _fit_line(p):
    n = len(p)
    mx, my = sum(q[0] for q in p) / n, sum(q[1] for q in p) / n
    sxx = sum((q[0] - mx) ** 2 for q in p); syy = sum((q[1] - my) ** 2 for q in p)
    sxy = sum((q[0] - mx) * (q[1] - my) for q in p)
    ang = 0.5 * math.atan2(2 * sxy, sxx - syy)
    d = (math.cos(ang), math.sin(ang))
    if (p[-1][0] - p[0][0]) * d[0] + (p[-1][1] - p[0][1]) * d[1] < 0:
        d = (-d[0], -d[1])
    return (mx, my), d


def _fit_circle(p):
    """Algebraic (Kåsa) fit refined by Gauss–Newton on geometric distance."""
    n = len(p)
    mx, my = sum(q[0] for q in p) / n, sum(q[1] for q in p) / n
    u = [(q[0] - mx, q[1] - my) for q in p]
    suu = sum(a * a for a, _ in u); svv = sum(b * b for _, b in u); suv = sum(a * b for a, b in u)
    suuu = sum(a ** 3 for a, _ in u); svvv = sum(b ** 3 for _, b in u)
    suvv = sum(a * b * b for a, b in u); svuu = sum(b * a * a for a, b in u)
    det = suu * svv - suv * suv
    uc = (0.5 * (suuu + suvv) * svv - 0.5 * (svvv + svuu) * suv) / det
    vc = (0.5 * (svvv + svuu) * suu - 0.5 * (suuu + suvv) * suv) / det
    cx, cy = uc + mx, vc + my
    r = sum(math.dist((cx, cy), q) for q in p) / n
    for _ in range(20):
        J, res = [], []
        for q in p:
            d = math.dist((cx, cy), q) or 1e-12
            J.append(((cx - q[0]) / d, (cy - q[1]) / d, -1.0))
            res.append(d - r)
        A = [[sum(J[k][i] * J[k][j] for k in range(n)) for j in range(3)] for i in range(3)]
        g = [sum(J[k][i] * res[k] for k in range(n)) for i in range(3)]
        try:
            step = _solve3(A, g)
        except ZeroDivisionError:
            break
        cx, cy, r = cx - step[0], cy - step[1], r - step[2]
        if max(abs(s) for s in step) < 1e-9:
            break
    return (cx, cy), r


def _solve3(A, b):
    M = [row[:] + [bb] for row, bb in zip(A, b)]
    for i in range(3):
        piv = max(range(i, 3), key=lambda r: abs(M[r][i]))
        M[i], M[piv] = M[piv], M[i]
        if abs(M[i][i]) < 1e-18:
            raise ZeroDivisionError
        for r in range(3):
            if r != i:
                f = M[r][i] / M[i][i]
                M[r] = [a - f * c for a, c in zip(M[r], M[i])]
    return [M[i][3] / M[i][i] for i in range(3)]


def _intersect(p, d, q, e):
    den = d[0] * e[1] - d[1] * e[0]
    if abs(den) < 1e-12:
        return None
    t = ((q[0] - p[0]) * e[1] - (q[1] - p[1]) * e[0]) / den
    return (p[0] + t * d[0], p[1] + t * d[1])


def _common_tangent(ca, ra, sa, cb, rb, sb):
    """Line tangent to circle A (centre to the side sa of travel) and B (side sb),
    directed from A towards B. Returns (point on line, unit direction)."""
    Dx, Dy = cb[0] - ca[0], cb[1] - ca[1]
    D = math.hypot(Dx, Dy)
    rhs = (sb * rb - sa * ra)
    if abs(rhs) > D:
        if abs(rhs) > 1.25 * D:
            return None
        rhs = math.copysign(D * (1 - 1e-9), rhs)   # fitted circles overlap slightly (drawing noise)
    phi = math.atan2(Dy, Dx)           # D·r = Dx cos b − Dy sin b = D cos(b + phi)
    best = None
    for sgn in (1, -1):
        b = sgn * math.acos(rhs / D) - phi
        u = (math.sin(b), math.cos(b))
        if u[0] * Dx + u[1] * Dy > 0:
            r = (math.cos(b), -math.sin(b))
            P = (ca[0] - sa * ra * r[0], ca[1] - sa * ra * r[1])
            best = (P, u)
    return best


def _fillet_fit(X, b1: float, b2: float, defl: float, pts: list, R0: float) -> float:
    """Radius of the circular curve tangent to both tangents (meeting at X) that
    minimises the squared distance to the drawn points."""
    sg = 1.0 if defl > 0 else -1.0
    D = abs(defl)
    u1, u2 = _u(b1), _u(b2)

    def cost(R: float) -> float:
        T = R * math.tan(D / 2)
        tc = (X[0] - T * u1[0], X[1] - T * u1[1])          # start of curve on tangent 1
        r1 = (math.cos(b1), -math.sin(b1))
        c = (tc[0] + sg * R * r1[0], tc[1] + sg * R * r1[1])
        ct = (X[0] + T * u2[0], X[1] + T * u2[1])
        tot = 0.0
        for q in pts:
            a1 = (q[0] - tc[0]) * u1[0] + (q[1] - tc[1]) * u1[1]
            a2 = (q[0] - ct[0]) * u2[0] + (q[1] - ct[1]) * u2[1]
            if a1 <= 0:     # on tangent 1
                d = abs((q[0] - X[0]) * u1[1] - (q[1] - X[1]) * u1[0])
            elif a2 >= 0:   # on tangent 2
                d = abs((q[0] - X[0]) * u2[1] - (q[1] - X[1]) * u2[0])
            else:
                d = abs(math.dist(q, c) - R)
            tot += d * d
        return tot

    lo, hi = math.log(max(1.0, R0 / 4)), math.log(R0 * 4)
    g = (math.sqrt(5) - 1) / 2
    for _ in range(80):
        a, b = hi - g * (hi - lo), lo + g * (hi - lo)
        if cost(math.exp(a)) < cost(math.exp(b)):
            hi = b
        else:
            lo = a
    return math.exp((lo + hi) / 2)


def _dp(xs: list[float], ys: list[float], eps: float) -> list[int]:
    """Douglas–Peucker on a function y(x), vertical tolerance eps; returns kept indices."""
    keep = {0, len(xs) - 1}
    stack = [(0, len(xs) - 1)]
    while stack:
        i, j = stack.pop()
        if j - i < 2:
            continue
        best, k = 0.0, None
        for m in range(i + 1, j):
            yl = ys[i] + (ys[j] - ys[i]) * (xs[m] - xs[i]) / (xs[j] - xs[i])
            d = abs(ys[m] - yl)
            if d > best:
                best, k = d, m
        if best > eps:
            keep.add(k)
            stack += [(i, k), (k, j)]
    return sorted(keep)


def fit_drawn(points: list[tuple[float, float]], straight_radius_m: float = 2000.0,
              smooth_m: float = 20.0, heading_tol_deg: float = 1.5, min_run_m: float = 20.0,
              ds: float = 1.0, tolerance_m: float = 0.5) -> tuple[list, dict, dict]:
    """Turn a freehand / traced centreline into PIs and fitted radii.

    Method: heading is measured over a sliding chord (smooth_m) to suppress
    drawing noise; the heading-versus-chainage profile is simplified by
    Douglas–Peucker (tolerance heading_tol_deg) into pieces of constant slope.
    Flat pieces (|dθ/ds| < 1/straight_radius_m) are tangents, sloping pieces
    are circular curves.  Each tangent is fitted by least squares and each
    curve by a least-squares circle, using only the interior of the piece.
    Adjacent curves of opposite hand (reverse curves) are joined by their
    common tangent; adjacent curves of the same hand are fitted as one
    radius (enter a compound curve explicitly if intended).  Transitions are
    not guessed: the designer adds them, guided by the transition checks.
    Returns (pis, specs, report) – the report gives the deviation between
    the drawn line and the fitted alignment."""
    p = _resample(points, ds)
    if len(p) < 10:
        raise ValueError("drawn line too short to fit")
    n = len(p)
    hw = max(1, int(round(smooth_m / ds / 2)))
    hd = [bearing(p[max(0, i - hw)], p[min(n - 1, i + hw)]) for i in range(n)]
    for i in range(1, n):                                  # unwrap
        while hd[i] - hd[i - 1] > math.pi: hd[i] -= 2 * math.pi
        while hd[i] - hd[i - 1] < -math.pi: hd[i] += 2 * math.pi
    sc = [i * ds for i in range(n)]
    brk = _dp(sc, hd, math.radians(heading_tol_deg))
    kth = 1.0 / straight_radius_m
    runs = []
    for i, j in zip(brk, brk[1:]):
        slope = (hd[j] - hd[i]) / (sc[j] - sc[i])
        c = 0 if abs(slope) < kth else (1 if slope > 0 else -1)
        if runs and runs[-1][0] == c:
            runs[-1][2] = j
        else:
            runs.append([c, i, j])
    minn = max(2, int(min_run_m / ds))
    changed = True
    while changed and len(runs) > 1:                       # absorb short runs into neighbours
        changed = False
        for j, r in enumerate(runs):
            if r[2] - r[1] < minn:
                nb = j - 1 if j > 0 else j + 1
                runs[nb][1], runs[nb][2] = min(runs[nb][1], r[1]), max(runs[nb][2], r[2])
                del runs[j]
                changed = True
                break
        merged = [runs[0]]
        for r in runs[1:]:
            if r[0] == merged[-1][0]:
                merged[-1][2] = r[2]
            else:
                merged.append(r)
        runs = merged

    def interior(a: int, b: int) -> list:
        t = int(1.5 * hw) if (b - a) > 6 * hw else max(0, (b - a) // 4)
        return p[a + t: b - t + 1]

    notes: list[str] = []
    # tangent lines: fitted straights, plus synthetic ones at curved ends and between reverse curves
    lines: list[tuple] = []
    circles: list[tuple] = []
    if runs[0][0] != 0:
        lines.append((p[0], (math.sin(hd[0]), math.cos(hd[0]))))
        notes.append("Drawn line starts on a curve: a tangent was assumed at the start point.")
    j = 0
    while j < len(runs):
        c, a, b = runs[j]
        seg = interior(a, b)
        if c == 0:
            lines.append(_fit_line(seg))
        else:
            centre, r = _fit_circle(seg)
            circles.append((centre, r, c, len(lines), (max(0, a - hw), min(n - 1, b + hw))))
            nxt = runs[j + 1] if j + 1 < len(runs) else None
            if nxt and nxt[0] == -c:                       # reverse curve: common tangent
                cb, rb = _fit_circle(interior(nxt[1], nxt[2]))
                t = _common_tangent(centre, r, c, cb, rb, -c)
                if t:
                    lines.append(t)
                    notes.append("Reverse curve detected: curves joined by their common tangent.")
        j += 1
    if runs[-1][0] != 0:
        lines.append((p[-1], (math.sin(hd[-1]), math.cos(hd[-1]))))
        notes.append("Drawn line ends on a curve: a tangent was assumed at the end point.")
    # PIs from consecutive tangents; each radius refined as the curve TANGENT TO BOTH
    # fitted tangents that best matches the drawn points (one-parameter least squares)
    pis = [p[0]]
    specs: dict[int, dict] = {}
    zones: dict[int, tuple] = {}
    for k in range(len(lines) - 1):
        (P, d), (Q, e) = lines[k], lines[k + 1]
        X = _intersect(P, d, Q, e)
        if X is None:
            continue
        b1, b2 = math.atan2(d[0], d[1]), math.atan2(e[0], e[1])
        defl = wrap(b2 - b1)
        if abs(defl) < math.radians(0.5):
            continue
        cands = [ci for ci in circles if ci[3] == k + 1]
        R0 = cands[0][1] if cands else straight_radius_m
        zone = p[cands[0][4][0]: cands[0][4][1] + 1] if cands else []
        R = _fillet_fit(X, b1, b2, defl, zone, R0) if len(zone) >= 5 else R0
        pis.append(X)
        specs[len(pis) - 1] = {"R": round(R, 1)}
        zones[len(pis) - 1] = zone
    pis.append(p[-1])
    # curves that overlap on a shared (e.g. reverse-curve) tangent: shrink both radii together just enough
    for _ in range(6):
        al = from_pis(pis, specs)
        bad = [i for i in range(1, len(pis) - 2) if i in specs and i + 1 in specs and
               _t_other(pis, specs, i, "out") + _t_other(pis, specs, i + 1, "in") > math.dist(pis[i], pis[i + 1]) + 1e-6]
        if not bad:
            break
        for i in bad:
            ri, rj = specs[i]["R"], specs[i + 1]["R"]
            lo, hi = 0.01, 1.0
            for _ in range(50):
                mid = (lo + hi) / 2
                specs[i]["R"], specs[i + 1]["R"] = ri * mid, rj * mid
                ok = _t_other(pis, specs, i, "out") + _t_other(pis, specs, i + 1, "in") <= math.dist(pis[i], pis[i + 1])
                lo, hi = (mid, hi) if ok else (lo, mid)
            specs[i]["R"], specs[i + 1]["R"] = round(ri * lo, 1) - 0.05, round(rj * lo, 1) - 0.05
            specs[i]["R"], specs[i + 1]["R"] = round(specs[i]["R"], 1), round(specs[i + 1]["R"], 1)
            notes.append(f"Curves at PI{i} and PI{i+1} reduced together to meet on their common tangent.")
    # a curve at either end of the drawing must also fit between the end point and its PI
    for j, which, other in ((1, "in", 0), (len(pis) - 2, "out", len(pis) - 1)):
        if j not in specs or _t_other(pis, specs, j, which) <= math.dist(pis[j], pis[other]):
            continue
        r0, lo, hi = specs[j]["R"], 0.01, 1.0
        for _ in range(50):
            mid = (lo + hi) / 2
            specs[j]["R"] = r0 * mid
            lo, hi = (mid, hi) if _t_other(pis, specs, j, which) <= math.dist(pis[j], pis[other]) else (lo, mid)
        specs[j]["R"] = math.floor(r0 * lo * 10) / 10
        notes.append(f"Curve at PI{j} reduced to {specs[j]['R']} m so it ends within the drawn line.")
    al = from_pis(pis, specs)
    dev = []
    if not al.errors:
        for q in p[:: max(1, int(5 / ds))]:
            dev.append(abs(al.station(q, step=2.0)[1]))
    errs = list(al.errors)
    if errs:
        errs.insert(0, "The drawn line could not be fitted cleanly (too noisy or curves too close). Redraw "
                       "more smoothly, draw short straights between curves, or increase smoothing.")
    mx = max(dev) if dev else None
    if mx is not None and mx > tolerance_m:
        notes.append(f"Fitted alignment departs from the drawing by up to {mx:.2f} m (tolerance {tolerance_m} m): "
                     "check the fitted radii against what was intended.")
    report = {"curves": len(specs), "radii_m": [s["R"] for s in specs.values()], "tolerance_m": tolerance_m,
              "within_tolerance": (mx is not None and mx <= tolerance_m),
              "max_deviation_m": round(max(dev), 3) if dev else None,
              "mean_deviation_m": round(sum(dev) / len(dev), 3) if dev else None,
              "notes": notes, "errors": errs}
    return pis, specs, report
