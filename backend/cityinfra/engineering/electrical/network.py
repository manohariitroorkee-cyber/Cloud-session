"""Electrical distribution: radial HT/LT network, demand, transformer loading,
cable current and voltage-drop checks, cable-size proposals, equipment schedules.

Objects
-------
SUBSTATION       Point. voltage_kv (HT distribution voltage, e.g. 11).
TRANSFORMER      Point. rating_kva, hv_kv, lv_v (line-to-line, e.g. 433).
FEEDER_PILLAR    Point.
POLE             Point (treated like a feeder pillar: a junction on the network).
ELECTRICAL_LOAD  Point. connected_load_kw, category (key in demand_factors),
                 demand_factor (optional override), power_factor (optional), phases (3 or 1).
ELECTRICAL_CABLE LineString drawn from the supply end to the load end.
                 cable_type (key in the cable library), runs (parallel cables, default 1).
                 relationships UPSTREAM_NODE (supply end) / DOWNSTREAM_NODE (load end).

Method (hand-calculation method for radial networks; no load-flow engine)
-------------------------------------------------------------------------
* Demand at a load: P = connected kW × demand factor; Q = P·tan(acos pf).
* Demand at a pillar / transformer / substation: (ΣP, ΣQ of the maximum demands of
  ALL loads downstream) ÷ the diversity factor for that level.  Diversity is applied
  once per level to the load sum – never compounded on already-diversified figures –
  and only where more than one load is served.  A node's demand is never taken
  below the largest demand it passes on to a single outgoing cable.
* Current in a three-phase cable: I = S / (√3 · V_LL); single-phase service: I = S / V_ph.
* Voltage drop: three-phase ΔV = √3 · I · L · (R cosφ + X sinφ) / runs;
  single-phase ΔV = 2 · I · L · (R cosφ + X sinφ) / runs, as % of the nominal voltage.
  Cumulative from the substation bus (HT) and from each transformer's LV terminals (LT).
* Cable current check: I ≤ runs × rating × derating factor.
Short-circuit, protection discrimination and earthing are NOT covered (pending).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ...gis.geometry import distance, endpoints, line_length, point_coord
from ...model.core import EngineeringObject, ObjectKind, Project, RelationType
from ...rules.framework import CheckResult, CheckStatus, RuleContext

METHOD = ("Radial hand-calculation: demand × diversity, I = S/(√3·V), "
          "ΔV = √3·I·L·(R·cosφ + X·sinφ) (2·I·L·… for single-phase), cumulative from the source bus")
NODE_KINDS = (ObjectKind.SUBSTATION, ObjectKind.TRANSFORMER, ObjectKind.FEEDER_PILLAR,
              ObjectKind.POLE, ObjectKind.ELECTRICAL_LOAD)
TOL = 0.5
SQ3 = math.sqrt(3)


@dataclass
class Cable:
    obj: EngineeringObject
    up: EngineeringObject
    down: EngineeringObject
    length_km: float
    type: str
    runs: int
    level: str = ""          # "HT" | "LT"
    v_nominal: float = 0.0   # line-to-line volts on this cable
    phases: int = 3


@dataclass
class ElectricalNetwork:
    project: Project
    nodes: dict[str, EngineeringObject]
    cables: dict[str, Cable]
    feeding: dict[str, Cable]                 # node id -> cable that feeds it
    children: dict[str, list[Cable]]          # node id -> cables leaving it
    roots: list[EngineeringObject]
    errors: list[str] = field(default_factory=list)


def build_network(pr: Project, rules: RuleContext) -> ElectricalNetwork:
    lib = rules.value("cable_library")
    nodes = {o.id: o for o in pr.of_kind(*NODE_KINDS)}
    errors: list[str] = []
    cables: dict[str, Cable] = {}
    for o in pr.of_kind(ObjectKind.ELECTRICAL_CABLE):
        up, dn = pr.related(o, RelationType.UPSTREAM_NODE), pr.related(o, RelationType.DOWNSTREAM_NODE)
        if len(up) != 1 or len(dn) != 1 or up[0].id not in nodes or dn[0].id not in nodes:
            errors.append(f"Cable {o.label}: needs one supply-end and one load-end node.")
            continue
        up, dn = up[0], dn[0]
        t = o.attr("cable_type")
        if t not in lib:
            errors.append(f"Cable {o.label}: cable type {t!r} is not in the cable library.")
            continue
        a, b = endpoints(o.geometry)
        for end, node, which in ((a, up, "start"), (b, dn, "end")):
            gap = distance(end, point_coord(node.geometry))
            if gap > TOL:
                errors.append(f"Cable {o.label}: {which} vertex {gap:.2f} m from {node.label}. "
                              f"Draw cables from the supply end to the load end and snap to nodes.")
        runs = int(o.attr("runs", 1))
        if runs < 1:
            errors.append(f"Cable {o.label}: runs must be at least 1.")
        cables[o.id] = Cable(o, up, dn, line_length(o.geometry) / 1000.0, t, max(runs, 1))

    feeding: dict[str, Cable] = {}
    children: dict[str, list[Cable]] = {}
    for c in cables.values():
        if c.down.id in feeding:
            errors.append(f"{c.down.label}: fed by more than one cable ({feeding[c.down.id].obj.label}, "
                          f"{c.obj.label}); the network must be radial.")
        feeding[c.down.id] = c
        children.setdefault(c.up.id, []).append(c)
        if c.down.kind == ObjectKind.SUBSTATION:
            errors.append(f"Cable {c.obj.label}: a substation cannot be at the load end.")
        if c.up.kind == ObjectKind.ELECTRICAL_LOAD:
            errors.append(f"Cable {c.obj.label}: a load cannot be at the supply end.")

    roots = [n for n in nodes.values() if n.kind == ObjectKind.SUBSTATION]
    if not roots:
        errors.append("No substation: add the 11 kV (or other HT) source.")
    for n in nodes.values():
        if n.kind != ObjectKind.SUBSTATION and n.id not in feeding:
            errors.append(f"{n.label}: not fed by any cable.")
        if n.kind == ObjectKind.TRANSFORMER:
            for k in ("rating_kva", "hv_kv", "lv_v"):
                if n.attr(k) is None:
                    errors.append(f"Transformer {n.label}: {k} missing.")
        if n.kind == ObjectKind.ELECTRICAL_LOAD and n.attr("connected_load_kw") is None:
            errors.append(f"Load {n.label}: connected_load_kw missing.")
        if n.kind == ObjectKind.ELECTRICAL_LOAD and n.attr("demand_factor") is None and n.attr("category") is None:
            errors.append(f"Load {n.label}: give a category (for the demand factor) or a demand_factor.")
        if n.kind == ObjectKind.SUBSTATION and n.attr("voltage_kv") is None:
            errors.append(f"Substation {n.label}: voltage_kv missing.")

    # walk from each root: assign level and voltage, detect loops / unreachable parts
    seen: set[str] = set()
    for r in roots:
        stack = [(r, "HT", float(r.attr("voltage_kv") or 0) * 1000)]
        while stack:
            n, level, v = stack.pop()
            if n.id in seen:
                errors.append(f"Loop detected at {n.label}.")
                continue
            seen.add(n.id)
            if n.kind == ObjectKind.TRANSFORMER:
                if level != "HT":
                    errors.append(f"Transformer {n.label}: fed from the LT side.")
                elif n.attr("hv_kv") and abs(float(n.attr("hv_kv")) * 1000 - v) > 1:
                    errors.append(f"Transformer {n.label}: HV rating {n.attr('hv_kv')} kV ≠ supply {v/1000:g} kV.")
                # currents and % drops on the LT side use the system nominal voltage (a project
                # parameter), not the transformer's no-load secondary voltage
                level, v = "LT", float(rules.value("lt_nominal_voltage_v"))
            for c in children.get(n.id, []):
                c.level, c.v_nominal = level, v
                spec = lib[c.type]
                if level == "LT" and spec["grade_kv"] > 3.3 or level == "HT" and spec["grade_kv"] * 1000 < v * 0.99:
                    errors.append(f"Cable {c.obj.label}: {spec['grade_kv']} kV grade cable used on the {level} side ({v/1000:g} kV).")
                c.phases = int(c.down.attr("phases", 3)) if c.down.kind == ObjectKind.ELECTRICAL_LOAD else 3
                if level == "HT" and c.down.kind == ObjectKind.ELECTRICAL_LOAD:
                    errors.append(f"Load {c.down.label}: connected directly to HT; supply loads through a transformer.")
                stack.append((c.down, level, v))
    for n in nodes.values():
        if n.id not in seen and n.kind != ObjectKind.SUBSTATION and n.id in feeding:
            errors.append(f"{n.label}: not connected to any substation.")
    return ElectricalNetwork(pr, nodes, cables, feeding, children, roots, errors)


# --------------------------------------------------------------- demand and checks

@dataclass
class NodeDemand:
    obj: EngineeringObject
    p_kw: float               # diversified maximum demand at this node
    q_kvar: float
    loads: int
    raw_p_kw: float = 0.0     # sum of the maximum demands of all loads downstream
    raw_q_kvar: float = 0.0
    diversity: float = 1.0    # effective factor applied (raw / diversified)

    @property
    def s_kva(self) -> float:
        return math.hypot(self.p_kw, self.q_kvar)

    @property
    def pf(self) -> float:
        return self.p_kw / self.s_kva if self.s_kva else 1.0


@dataclass
class CableResult:
    cable: Cable
    s_kva: float
    pf: float
    current_a: float
    capacity_a: float
    drop_v: float
    drop_pct: float            # this cable, % of nominal
    cum_drop_pct: float        # source bus → load end
    checks: list[CheckResult] = field(default_factory=list)


@dataclass
class ElectricalResult:
    method: str
    demand: dict[str, NodeDemand]
    cables: dict[str, CableResult]
    checks: list[CheckResult]
    proposals: list[str]
    errors: list[str]
    unverified: list[str]

    def failing(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status == CheckStatus.FAIL]


def _diversity(rules: RuleContext, kind: ObjectKind) -> float:
    return float(rules.value("diversity_factors").get(kind.value, 1.0))


def analyse(net: ElectricalNetwork, rules: RuleContext) -> ElectricalResult:
    unverified = [f"{p.id} ({p.source.cite()})" for p in rules.unverified()]
    if net.errors:
        return ElectricalResult(METHOD, {}, {}, [], [], list(net.errors), unverified)
    lib = rules.value("cable_library")
    dfs = rules.value("demand_factors")
    pf_default = float(rules.value("default_power_factor"))
    errors: list[str] = []

    demand: dict[str, NodeDemand] = {}

    def node_demand(n: EngineeringObject) -> NodeDemand:
        if n.id in demand:
            return demand[n.id]
        if n.kind == ObjectKind.ELECTRICAL_LOAD:
            df = n.attr("demand_factor")
            if df is None:
                cat = n.attr("category")
                if cat not in dfs:
                    errors.append(f"Load {n.label}: no demand factor configured for category '{cat}'.")
                    df = 1.0
                else:
                    df = dfs[cat]
            pf = float(n.attr("power_factor", pf_default))
            p = float(n.attr("connected_load_kw")) * float(df)
            q = p * math.tan(math.acos(pf))
            d = NodeDemand(n, p, q, 1, p, q, 1.0)
        else:
            parts = [node_demand(c.down) for c in net.children.get(n.id, [])]
            rp, rq = sum(x.raw_p_kw for x in parts), sum(x.raw_q_kvar for x in parts)
            loads = sum(x.loads for x in parts)
            s_raw = math.hypot(rp, rq)
            div = _diversity(rules, n.kind) if loads > 1 else 1.0
            f = 1.0 / div
            s_child = max((x.s_kva for x in parts), default=0.0)
            if s_raw > 0 and s_raw * f < s_child:
                f = s_child / s_raw            # never below what one outgoing cable carries
            d = NodeDemand(n, rp * f, rq * f, loads, rp, rq, 1.0 / f if f else 1.0)
        demand[n.id] = d
        return d

    for r in net.roots:
        node_demand(r)

    derate = float(rules.value("cable_derating_factor"))
    vd = rules.get("voltage_drop_limit_pct")
    results: dict[str, CableResult] = {}
    checks: list[CheckResult] = []

    def walk(n: EngineeringObject, cum: float) -> None:
        for c in net.children.get(n.id, []):
            spec = lib[c.type]
            d = demand[c.down.id]
            v = c.v_nominal
            s_va = d.s_kva * 1000
            if c.phases == 1:
                vph = v / SQ3
                i = s_va / vph
                dv = 2 * i * c.length_km * (spec["r_ohm_km"] * d.pf + spec["x_ohm_km"] * math.sqrt(max(0, 1 - d.pf ** 2))) / c.runs
                pct = dv / vph * 100
            else:
                i = s_va / (SQ3 * v)
                dv = SQ3 * i * c.length_km * (spec["r_ohm_km"] * d.pf + spec["x_ohm_km"] * math.sqrt(max(0, 1 - d.pf ** 2))) / c.runs
                pct = dv / v * 100
            cap = spec["rating_a"] * derate * c.runs
            # cumulative drop restarts at transformer LV terminals
            base = 0.0 if (c.level == "LT" and n.kind == ObjectKind.TRANSFORMER) else cum
            cr = CableResult(c, d.s_kva, d.pf, i, cap, dv, pct, base + pct)
            lbl = c.obj.label
            cr.checks.append(CheckResult(
                "cable_current", c.obj.id, lbl, CheckStatus.PASS if i <= cap else CheckStatus.FAIL,
                f"{i:.1f} A vs {cap:.1f} A ({c.runs} × {spec['rating_a']} A × derating {derate})",
                i, cap, "A", rules.get("cable_library")))
            if c.down.kind in (ObjectKind.ELECTRICAL_LOAD, ObjectKind.TRANSFORMER):
                lim = vd.value[c.level.lower()]
                what = "at load" if c.down.kind == ObjectKind.ELECTRICAL_LOAD else "at transformer HV terminals"
                cr.checks.append(CheckResult(
                    "voltage_drop", c.down.id, c.down.label,
                    CheckStatus.PASS if cr.cum_drop_pct <= lim + 1e-9 else CheckStatus.FAIL,
                    f"Cumulative drop {cr.cum_drop_pct:.2f} % {what} vs {lim} % ({c.level})",
                    cr.cum_drop_pct, lim, "%", vd))
            results[c.obj.id] = cr
            checks.extend(cr.checks)
            walk(c.down, cr.cum_drop_pct)

    for r in net.roots:
        walk(r, 0.0)

    tl = rules.get("transformer_max_loading")
    for n in net.nodes.values():
        if n.kind == ObjectKind.TRANSFORMER:
            s = demand[n.id].s_kva
            rating = float(n.attr("rating_kva"))
            checks.append(CheckResult(
                "transformer_loading", n.id, n.label,
                CheckStatus.PASS if s <= tl.value * rating + 1e-9 else CheckStatus.FAIL,
                f"Demand {s:.0f} kVA = {s/rating*100:.0f} % of {rating:.0f} kVA vs maximum {tl.value*100:.0f} %",
                s / rating, tl.value, "-", tl))

    res = ElectricalResult(METHOD, demand, results, checks, [], errors, unverified)
    res.proposals = _proposals(net, res, rules)
    return res


def _family(lib: dict, t: str) -> list[str]:
    s = lib[t]
    same = [k for k, v in lib.items() if v["grade_kv"] == s["grade_kv"] and v["conductor"] == s["conductor"]
            and v["cores"] == s["cores"]]
    return sorted(same, key=lambda k: lib[k]["size_mm2"])


def _proposals(net: ElectricalNetwork, res: ElectricalResult, rules: RuleContext) -> list[str]:
    """Cable sizes that would clear the failures. Proposals only – nothing is changed."""
    lib = rules.value("cable_library")
    derate = float(rules.value("cable_derating_factor"))
    out: list[str] = []
    for cr in res.cables.values():
        if any(c.check == "cable_current" and c.status == CheckStatus.FAIL for c in cr.checks):
            c = cr.cable
            for t in _family(lib, c.type):
                if lib[t]["rating_a"] * derate * c.runs >= cr.current_a:
                    out.append(f"Cable {c.obj.label}: {c.type} carries {cr.current_a:.0f} A > {cr.capacity_a:.0f} A; "
                               f"{t} ({lib[t]['rating_a']} A) would suffice with {c.runs} run(s).")
                    break
            else:
                out.append(f"Cable {c.obj.label}: no {lib[c.type]['grade_kv']} kV cable in the library carries "
                           f"{cr.current_a:.0f} A with {c.runs} run(s); add a parallel run or split the load.")
    # voltage drop: upsize the cable with the largest drop on the path, repeat
    lim = rules.value("voltage_drop_limit_pct")
    for chk in [c for c in res.checks if c.check == "voltage_drop" and c.status == CheckStatus.FAIL]:
        path: list[CableResult] = []
        node = net.nodes[chk.object_id]
        while node.id in net.feeding:
            cab = net.feeding[node.id]
            cr = res.cables[cab.obj.id]
            if path and cr.cable.level != path[-1].cable.level:
                break
            path.append(cr)
            node = cab.up
        level = path[0].cable.level
        sizes = {cr.cable.obj.id: cr.cable.type for cr in path}
        drop = {cr.cable.obj.id: cr.drop_pct for cr in path}
        changes: list[str] = []
        note = ""
        maxed: set[str] = set()
        for _ in range(40):
            if sum(drop.values()) <= lim[level.lower()] + 1e-9:
                break
            cand = [cr for cr in path if cr.cable.obj.id not in maxed]
            if not cand:
                note = (" Still above the limit with the largest sizes: add parallel runs or move the "
                        "feeder pillar / transformer closer to the load.")
                break
            worst = max(cand, key=lambda cr: drop[cr.cable.obj.id])
            fam = _family(lib, sizes[worst.cable.obj.id])
            idx = fam.index(sizes[worst.cable.obj.id])
            if idx + 1 >= len(fam):
                maxed.add(worst.cable.obj.id)
                continue
            new = fam[idx + 1]
            drop[worst.cable.obj.id] *= _z(lib[new], worst.pf) / _z(lib[sizes[worst.cable.obj.id]], worst.pf)
            sizes[worst.cable.obj.id] = new
        changes += [f"{cr.cable.obj.label} → {sizes[cr.cable.obj.id]}" for cr in path if sizes[cr.cable.obj.id] != cr.cable.type]
        if changes or note:
            out.append(f"Voltage drop at {chk.object_label} ({chk.actual:.2f} % > {chk.limit} %): "
                       f"{'; '.join(changes) or 'no larger size available'} → about {sum(drop.values()):.2f} %.{note}")
    # overloaded transformers: next standard rating
    tl = rules.value("transformer_max_loading")
    for chk in [c for c in res.checks if c.check == "transformer_loading" and c.status == CheckStatus.FAIL]:
        s_kva = res.demand[chk.object_id].s_kva
        for r in rules.value("transformer_ratings_kva"):
            if s_kva <= tl * r:
                out.append(f"Transformer {chk.object_label}: demand {s_kva:.0f} kVA needs at least {r} kVA "
                           f"at {tl*100:.0f} % loading, or move part of the load to another transformer.")
                break
        else:
            out.append(f"Transformer {chk.object_label}: demand {s_kva:.0f} kVA exceeds the largest configured rating; split the load.")
    return out


def _z(spec: dict, pf: float) -> float:
    return spec["r_ohm_km"] * pf + spec["x_ohm_km"] * math.sqrt(max(0, 1 - pf * pf))


def schedules(net: ElectricalNetwork, res: ElectricalResult, rules: RuleContext) -> dict[str, list[dict[str, Any]]]:
    lib = rules.value("cable_library")
    tx = []
    for n in net.nodes.values():
        if n.kind == ObjectKind.TRANSFORMER:
            d = res.demand[n.id]
            tx.append({"transformer": n.label, "rating_kva": n.attr("rating_kva"),
                       "ratio": f"{n.attr('hv_kv')} kV / {n.attr('lv_v')} V", "fed_by": net.feeding[n.id].obj.label,
                       "loads": d.loads, "connected_md_kva": round(math.hypot(d.raw_p_kw, d.raw_q_kvar), 1),
                       "diversity": round(d.diversity, 3), "demand_kva": round(d.s_kva, 1),
                       "loading_pct": round(d.s_kva / float(n.attr("rating_kva")) * 100, 1)})
    pillars = []
    for n in net.nodes.values():
        if n.kind in (ObjectKind.FEEDER_PILLAR, ObjectKind.POLE):
            d = res.demand[n.id]
            pillars.append({"pillar": n.label, "kind": n.kind.value, "fed_by": net.feeding[n.id].obj.label,
                            "outgoing_ways": len(net.children.get(n.id, [])), "loads": d.loads,
                            "diversity": round(d.diversity, 3), "demand_kva": round(d.s_kva, 1)})
    cables = []
    for cr in res.cables.values():
        c, spec = cr.cable, lib[cr.cable.type]
        cables.append({"cable": c.obj.label, "from": c.up.label, "to": c.down.label, "level": c.level,
                       "type": c.type, "description": spec.get("description", ""), "runs": c.runs,
                       "length_m": round(c.length_km * 1000, 1), "current_a": round(cr.current_a, 1),
                       "capacity_a": round(cr.capacity_a, 1), "drop_pct": round(cr.drop_pct, 2),
                       "cum_drop_pct": round(cr.cum_drop_pct, 2)})
    loads = []
    for n in net.nodes.values():
        if n.kind == ObjectKind.ELECTRICAL_LOAD:
            d = res.demand[n.id]
            loads.append({"load": n.label, "category": n.attr("category", "–"),
                          "connected_kw": n.attr("connected_load_kw"), "demand_kw": round(d.p_kw, 2),
                          "pf": round(d.pf, 2), "phases": n.attr("phases", 3), "fed_by": net.feeding[n.id].obj.label})
    return {"transformers": tx, "feeder_pillars": pillars, "cables": cables, "loads": loads}
