"""Sewer design calculation and checks (design-sheet method).

For every pipe, in upstream-to-downstream order:

1. Cumulative contributory population = population entering at the upstream
   manhole + populations carried by all incoming pipes.
2. Per-capita sewage = max(water supply × return factor, minimum sewage).
3. Average flow = population × per-capita sewage / 86 400.
4. Design peak flow = average flow × peak factor(cumulative population)
   × (1 + infiltration fraction) + extra (institutional) flows.
5. Uniform-flow hydraulics (Manning) at that flow → depth, d/D, velocity.
6. Checks against the configured rule set; each result cites its parameter.
7. For failing pipes, sizing alternatives are *proposed*, never applied.

Network effects (backwater, surcharge, HGL) are evaluated separately by
EPA SWMM; see ``cityinfra.engines.swmm``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...rules.framework import CheckResult, CheckStatus, RuleContext
from .hydraulics import FlowState, slope_for_velocity, uniform_flow
from .network import SewerNetwork, SewerPipe

METHOD = "Uniform flow, Manning's equation, partially-full circular section (design-sheet method)"


@dataclass
class PipeDesign:
    pipe: SewerPipe
    population: float
    present_population: float | None
    avg_flow: float              # m³/s
    peak_factor: float
    design_flow: float           # m³/s
    present_flow: float | None   # m³/s
    manning_n: float
    state: FlowState
    present_state: FlowState | None
    checks: list[CheckResult] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(c.status == CheckStatus.FAIL for c in self.checks)

    def row(self) -> dict[str, Any]:
        p, s = self.pipe, self.state
        return {
            "pipe": p.obj.label, "from": p.us.label, "to": p.ds.label,
            "length_m": round(p.length, 2), "diameter_mm": round(p.diameter * 1000),
            "material": p.material, "us_invert": p.us_invert, "ds_invert": p.ds_invert,
            "slope_1_in": round(1 / p.slope) if p.slope > 0 else None,
            "population": round(self.population), "peak_factor": self.peak_factor,
            "design_flow_lps": round(self.design_flow * 1000, 3),
            "q_full_lps": round(s.q_full * 1000, 2), "v_full_ms": round(s.v_full, 3),
            "depth_ratio": round(s.depth_ratio, 3), "velocity_ms": round(s.velocity, 3),
            "result": "FAIL" if self.failed else "PASS",
        }


@dataclass
class SewerDesignResult:
    method: str
    pipes: list[PipeDesign]
    node_checks: list[CheckResult]
    errors: list[str]
    unverified_parameters: list[str]

    @property
    def failing(self) -> list[PipeDesign]:
        return [d for d in self.pipes if d.failed]

    def all_checks(self) -> list[CheckResult]:
        return [c for d in self.pipes for c in d.checks] + self.node_checks


def _per_capita_m3s(rules: RuleContext) -> float:
    lpcd = max(rules.value("water_supply_lpcd") * rules.value("sewage_return_factor"),
               rules.value("min_sewage_lpcd"))
    return lpcd / 1000.0 / 86400.0


def _manning(rules: RuleContext, material: str) -> float:
    table = rules.value("manning_n")
    if material not in table:
        raise KeyError(f"no Manning n configured for material '{material}' "
                       f"(configured: {', '.join(sorted(table))})")
    return float(table[material])


def design_network(net: SewerNetwork, rules: RuleContext) -> SewerDesignResult:
    unverified = [f"{p.id} ({p.source.cite()})" for p in rules.unverified()]
    if not net.ok:
        return SewerDesignResult(METHOD, [], [], list(net.errors), unverified)

    q_cap = _per_capita_m3s(rules)
    inf = rules.value("infiltration_fraction")
    pf_param = rules.get("peak_factor")
    carried_pop: dict[str, float] = {}       # pipe id -> cumulative population
    carried_present: dict[str, float | None] = {}
    carried_extra: dict[str, float] = {}     # m³/s
    designs: list[PipeDesign] = []
    errors: list[str] = []

    for pid in net.order:
        p = net.pipes[pid]
        inc = net.incoming(p.us.id)
        pop = float(p.us.attr("population", 0) or 0) + sum(carried_pop[i.obj.id] for i in inc)
        pres_local = p.us.attr("present_population")
        pres_parts = [carried_present[i.obj.id] for i in inc]
        present = None if pres_local is None or any(v is None for v in pres_parts) \
            else float(pres_local) + sum(pres_parts)  # type: ignore[arg-type]
        extra = float(p.us.attr("extra_flow_lps", 0) or 0) / 1000.0 + sum(carried_extra[i.obj.id] for i in inc)
        carried_pop[pid], carried_present[pid], carried_extra[pid] = pop, present, extra

        try:
            n = _manning(rules, p.material)
        except KeyError as e:
            errors.append(f"Pipe {p.obj.label}: {e}")
            continue

        pf = pf_param.lookup(max(pop, 1))
        avg = pop * q_cap
        q = avg * pf * (1 + inf) + extra
        state = uniform_flow(p.diameter, p.slope, n, q)
        present_q = present_state = None
        if present is not None:
            present_q = present * q_cap * pf_param.lookup(max(present, 1)) * (1 + inf) + extra
            present_state = uniform_flow(p.diameter, p.slope, n, present_q)

        d = PipeDesign(p, pop, present, avg, pf, q, present_q, n, state, present_state)
        d.checks = _pipe_checks(d, rules)
        if d.failed:
            d.alternatives = _alternatives(d, rules)
        designs.append(d)

    node_checks = _cover_checks(net, rules)
    return SewerDesignResult(METHOD, designs, node_checks, errors, unverified)


def _chk(d: PipeDesign, name: str, ok: bool | None, msg: str, actual, limit, unit, param,
         fail_status: CheckStatus = CheckStatus.FAIL) -> CheckResult:
    status = CheckStatus.NOT_EVALUATED if ok is None else (CheckStatus.PASS if ok else fail_status)
    if ok is None and not d.state.capacity_ok and name in ("max_velocity", "min_velocity_design_peak"):
        msg, actual = "Pipe cannot carry the design flow in open-channel conditions – velocity check deferred until capacity is resolved", None
    return CheckResult(name, d.pipe.obj.id, d.pipe.obj.label, status, msg, actual, limit, unit, param)


def _pipe_checks(d: PipeDesign, rules: RuleContext) -> list[CheckResult]:
    s, p = d.state, d.pipe
    out: list[CheckResult] = []

    par = rules.get("min_diameter_mm")
    dmin = par.lookup(rules.value("town_population"))
    out.append(_chk(d, "min_diameter", p.diameter * 1000 >= dmin - 1e-6,
                    f"Diameter {p.diameter*1000:.0f} mm vs minimum {dmin} mm", p.diameter * 1000, dmin, "mm", par))

    out.append(_chk(d, "capacity", s.capacity_ok,
                    f"Design flow {d.design_flow*1000:.2f} L/s vs full-bore capacity {s.q_full*1000:.2f} L/s"
                    + ("" if s.capacity_ok else " – exceeds open-channel capacity"),
                    d.design_flow * 1000, s.q_full * 1000, "L/s", None))

    par = rules.get("max_depth_ratio")
    out.append(_chk(d, "depth_ratio", s.capacity_ok and s.depth_ratio <= par.value + 1e-9,
                    f"d/D {s.depth_ratio:.3f} at design peak flow vs maximum {par.value}",
                    s.depth_ratio, par.value, "d/D", par))

    # Uniform-flow velocity is meaningless once the pipe cannot carry the flow
    # in open-channel conditions; velocity checks then wait for a redesign.
    cap = None if not s.capacity_ok else True
    par = rules.get("max_velocity")
    out.append(_chk(d, "max_velocity", cap and s.velocity <= par.value,
                    f"Velocity {s.velocity:.2f} m/s vs maximum {par.value} m/s", s.velocity, par.value, "m/s", par))

    par = rules.get("min_velocity_design_peak")
    out.append(_chk(d, "min_velocity_design_peak", cap and s.velocity >= par.value,
                    f"Velocity {s.velocity:.2f} m/s at design peak vs self-cleansing {par.value} m/s",
                    s.velocity, par.value, "m/s", par))

    par = rules.get("min_velocity_present_peak")
    if d.present_state is None or not d.present_state.capacity_ok:
        out.append(_chk(d, "min_velocity_present_peak", None,
                        "Present population not entered for all upstream manholes, or pipe surcharged – check not evaluated",
                        None, par.value, "m/s", par))
    else:
        v = d.present_state.velocity
        out.append(_chk(d, "min_velocity_present_peak", v >= par.value,
                        f"Velocity {v:.2f} m/s at present peak vs {par.value} m/s", v, par.value, "m/s", par))

    par = rules.get("max_manhole_spacing_m")
    smax = par.lookup(p.diameter * 1000)
    out.append(_chk(d, "manhole_spacing", p.length <= smax + 1e-6,
                    f"Manhole spacing {p.length:.1f} m vs maximum {smax} m for {p.diameter*1000:.0f} mm",
                    p.length, smax, "m", par, fail_status=CheckStatus.WARNING))
    return out


def _alternatives(d: PipeDesign, rules: RuleContext) -> list[str]:
    """Proposed changes for a failing pipe. Proposals only – nothing is applied."""
    p, q, n = d.pipe, d.design_flow, d.manning_n
    vmax, vmin = rules.value("max_velocity"), rules.value("min_velocity_design_peak")
    dd = rules.value("max_depth_ratio")
    dmin = rules.get("min_diameter_mm").lookup(rules.value("town_population"))
    out: list[str] = []
    fails = {c.check for c in d.checks if c.status == CheckStatus.FAIL}

    if fails & {"capacity", "depth_ratio", "min_diameter"}:
        for dia in rules.value("commercial_diameters_mm"):
            if dia < dmin or dia <= p.diameter * 1000:
                continue
            s = uniform_flow(dia / 1000, p.slope, n, q)
            if s.capacity_ok and s.depth_ratio <= dd and s.velocity <= vmax:
                note = "" if s.velocity >= vmin else f" (velocity {s.velocity:.2f} m/s below self-cleansing – also review slope)"
                out.append(f"Increase diameter to {dia} mm at the same slope: d/D {s.depth_ratio:.2f}, "
                           f"V {s.velocity:.2f} m/s{note}.")
                break
        else:
            out.append("No configured diameter satisfies capacity and d/D at the present slope; review slope or route.")

    if ("min_velocity_design_peak" in fails or (fails & {"capacity", "depth_ratio"} and d.state.velocity < vmin)) and q > 0:
        try:
            smin = slope_for_velocity(p.diameter, n, q, vmin)
            out.append(f"Steepen to at least 1 in {int(1 / smin)} (S = {smin:.5f}) to reach {vmin} m/s "
                       f"at design peak flow; check downstream inverts and depths.")
        except ValueError:
            out.append("Self-cleansing velocity not reachable by steepening at this diameter and flow.")
    if "max_velocity" in fails:
        out.append("Velocity above the erosion limit: flatten the gradient using drop manholes, "
                   "or adopt an abrasion-resistant material with engineering justification.")
    return out


def _cover_checks(net: SewerNetwork, rules: RuleContext) -> list[CheckResult]:
    par = rules.get("min_cover_m")
    out = []
    for p in net.pipes.values():
        for node, inv, end in ((p.us, p.us_invert, "upstream"), (p.ds, p.ds_invert, "downstream")):
            gl = node.attr("ground_level")
            cover = gl - (inv + p.diameter)
            out.append(CheckResult(
                "min_cover", p.obj.id, p.obj.label,
                CheckStatus.PASS if cover >= par.value - 1e-9 else CheckStatus.FAIL,
                f"Cover over crown at {end} end ({node.label}) {cover:.2f} m vs minimum {par.value} m "
                f"(internal diameter used for crown; add wall thickness for final design)",
                cover, par.value, "m", par))
    for nid, n in net.nodes.items():
        inc = net.incoming(nid)
        out_p = net.outgoing(nid)
        if inc and out_p:
            low_in = min(p.ds_invert for p in inc)
            o = out_p[0]
            ok = o.us_invert <= low_in + 1e-9
            out.append(CheckResult(
                "invert_continuity", n.id, n.label, CheckStatus.PASS if ok else CheckStatus.FAIL,
                f"Outgoing invert {o.us_invert:.3f} m vs lowest incoming invert {low_in:.3f} m",
                o.us_invert, low_in, "m", None))
            # a sewer must not get smaller downstream
            d_in = max(p.diameter for p in inc)
            out.append(CheckResult(
                "diameter_reduction", n.id, n.label,
                CheckStatus.PASS if o.diameter >= d_in - 1e-9 else CheckStatus.FAIL,
                f"Outgoing pipe {o.obj.label} Ø{o.diameter*1000:.0f} mm vs largest incoming Ø{d_in*1000:.0f} mm"
                + ("" if o.diameter >= d_in - 1e-9 else " – diameter must not reduce downstream"),
                o.diameter * 1000, d_in * 1000, "mm", None))
            # where the pipe gets larger, its crown should not be above the incoming crowns (crown matching)
            crown_in = min(p.ds_invert + p.diameter for p in inc)
            crown_out = o.us_invert + o.diameter
            out.append(CheckResult(
                "crown_matching", n.id, n.label,
                CheckStatus.PASS if crown_out <= crown_in + 1e-9 else CheckStatus.WARNING,
                f"Outgoing crown {crown_out:.3f} m vs lowest incoming crown {crown_in:.3f} m"
                + ("" if crown_out <= crown_in + 1e-9 else " – outgoing crown is higher: incoming pipes will run under "
                   "backwater; match crowns (drop the outgoing invert)"),
                crown_out, crown_in, "m", None))
    return out
