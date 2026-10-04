"""Existing drains, villages and outfalls – what the new design must fit around.

Existing drains (status "existing") are surveyed facts.  They are not resized; for each one:

    usable capacity   Q_use  = Manning discharge of the section actually available today
                               (bed raised by silt) at the depth that leaves the design
                               freeboard (open/box drains) or at the maximum d/D (pipes)
    existing flow     Q_ex   = Rational-method peak from existing catchments only
                               (villages, developed areas) plus any recorded inflow from
                               outside the drawing – the network as it is today
    residual capacity Q_res  = Q_use − Q_ex
    added by proposal Q_add  = Q_total − Q_ex, Q_total from the full (existing + proposed) run
    utilisation              = Q_total / Q_use

Villages: a catchment with levels_fixed = true and outlet_level (the level of the mouth of the
village drain) must discharge freely – the water level in the receiving drain at design flow
must stay at least village_outlet_min_drop_m below that level.  Village levels are inputs,
never changed by the design.

Outfalls: the drain must not arrive below the outfall bed (invert_level), and a receiving
channel flood level (tailwater_level) above the drain's water level is reported as backwater.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...model.core import ObjectKind
from ...rules.framework import CheckResult, CheckStatus, RuleContext
from ..common.open_channel import Section, _y_qmax, normal_flow, q_at


@dataclass
class ExistingDrainAssessment:
    drain: object              # network.Drain
    q_usable: float
    q_full: float              # at the brim / soffit (no freeboard)
    q_desilted: float | None   # usable capacity if the silt were removed
    q_existing: float
    q_total: float
    velocity: float | None

    @property
    def residual(self) -> float:
        return self.q_usable - self.q_existing

    @property
    def added(self) -> float:
        return self.q_total - self.q_existing

    @property
    def utilisation(self) -> float:
        return self.q_total / self.q_usable if self.q_usable > 0 else float("inf")

    def row(self) -> dict:
        d = self.drain
        sec = d.section
        size = (f"Ø{sec.depth*1000:.0f}" if sec.shape == "circular"
                else f"{sec.width:.2f}×{sec.depth:.2f}" + (f" (1:{sec.side_slope:g} sides)" if sec.side_slope else ""))
        return {"drain": d.obj.label, "section": size, "silt_m": round(d.silt_m, 2), "slope_1_in": round(1 / d.slope),
                "q_usable_m3s": round(self.q_usable, 3), "q_existing_m3s": round(self.q_existing, 3),
                "residual_m3s": round(self.residual, 3), "q_added_m3s": round(self.added, 3),
                "q_total_m3s": round(self.q_total, 3), "utilisation_pct": round(100 * self.utilisation)}


def usable_capacity(sec: Section, slope: float, n: float, rules: RuleContext) -> tuple[float, float]:
    """(usable, full) open-channel discharge of a section."""
    ym = _y_qmax(sec, slope, n)
    full = q_at(sec, ym, slope, n)
    if sec.shape == "circular":
        y = min(ym, rules.value("max_depth_ratio_pipe") * sec.depth)
    else:
        y = min(ym, sec.depth - rules.value("min_freeboard_m"))
    return (q_at(sec, y, slope, n) if y > 0 else 0.0), full


def assess(net, res, rules: RuleContext, idf, return_period: float, area_type: str) -> None:
    """Add existing-drain, village and outfall results to a design result (in place)."""
    from .network import design_network, existing_only
    by = {dd.drain.obj.id: dd for dd in res.drains}
    ex_drains = [dd for dd in res.drains if dd.drain.existing]
    if ex_drains:
        today = design_network(existing_only(net), rules, idf, return_period, area_type, _assess_existing=False)
        q_today = {dd.drain.obj.id: dd.flow for dd in today.drains}
        res.errors += [e for e in today.errors if e not in res.errors]
        warn = rules.get("existing_drain_warning_ratio")
        fb = rules.get("min_freeboard_m")
        for dd in ex_drains:
            d = dd.drain
            q_use, q_full = usable_capacity(d.flow_section, d.slope, dd.manning_n, rules)
            q_clean = usable_capacity(d.section, d.slope, dd.manning_n, rules)[0] if d.silt_m > 0 else None
            a = ExistingDrainAssessment(d, q_use, q_full, q_clean, q_today.get(d.obj.id, 0.0), dd.flow,
                                        dd.state.velocity if dd.state.capacity_ok else None)
            res.existing.append(a)
            oid, lbl = d.obj.id, d.obj.label
            basis = (f"usable capacity {a.q_usable:.3f} m³/s (freeboard {fb.value} m"
                     + (f", {d.silt_m:.2f} m silt" if d.silt_m else "") + f"); flow today {a.q_existing:.3f} m³/s, "
                     f"residual {a.residual:.3f} m³/s; new areas add {a.added:.3f} m³/s → total {a.q_total:.3f} m³/s "
                     f"({100 * a.utilisation:.0f} % of usable)")
            if a.q_existing > a.q_usable + 1e-9:
                st, msg = CheckStatus.FAIL, "Already overloaded today, before any new area is connected: " + basis
            elif a.q_total > a.q_usable + 1e-9:
                st, msg = CheckStatus.FAIL, (f"Short by {a.q_total - a.q_usable:.3f} m³/s with the new areas: " + basis)
            elif a.q_total > warn.value * a.q_usable:
                st, msg = CheckStatus.WARNING, f"Nearly full (above {100 * warn.value:.0f} %): " + basis
            else:
                st, msg = CheckStatus.PASS, basis
            dd.checks = [CheckResult("existing_capacity", oid, lbl, st, msg, a.q_total, a.q_usable, "m³/s", fb)]
            if d.silt_m > 0:
                dd.checks.append(CheckResult(
                    "existing_silt", oid, lbl, CheckStatus.WARNING,
                    f"{d.silt_m:.2f} m of silt reduces usable capacity from {q_clean:.3f} to {a.q_usable:.3f} m³/s",
                    a.q_usable, q_clean, "m³/s"))
            if st in (CheckStatus.FAIL, CheckStatus.WARNING):
                dd.alternatives = _options(a, rules)
    res.checks += village_checks(net, by, rules) + outfall_checks(net, res, by) + connection_checks(net)


def connection_checks(net) -> list[CheckResult]:
    """A new drain must not arrive below the bed of the existing drain it runs into."""
    out = []
    for d in net.drains.values():
        if d.existing:
            continue
        for e in net.outgoing(d.ds.id):
            if not e.existing:
                continue
            bed = e.us_invert + e.silt_m
            ok = d.ds_invert >= bed - 1e-6
            out.append(CheckResult(
                "connection_level", d.obj.id, d.obj.label, CheckStatus.PASS if ok else CheckStatus.FAIL,
                f"Arrives at {d.ds_invert:.3f} m; bed of existing drain {e.obj.label} at {d.ds.label} is {bed:.3f} m"
                + ("" if ok else f" – {bed - d.ds_invert:.2f} m too low: water would stand in the new drain"),
                d.ds_invert, bed, "m"))
    return out


def _options(a: ExistingDrainAssessment, rules: RuleContext) -> list[str]:
    out = []
    short = a.q_total - a.q_usable
    if a.q_desilted is not None and a.q_desilted > a.q_usable:
        gain = a.q_desilted - a.q_usable
        out.append(f"Desilting to the design bed would add {gain:.3f} m³/s"
                   + (" – enough on its own." if gain >= short else f" – not enough on its own (short {short:.3f} m³/s)."))
    if short > 0:
        out.append(f"Otherwise provide {short:.3f} m³/s more: widen or deepen this drain, build a parallel drain, "
                   "or send part of the new area's water to another outfall.")
    else:
        out.append("Keep this drain clear of silt and check its condition on site.")
    return out


def _water_level(dd) -> float | None:
    if not dd.state.capacity_ok:
        return None
    d = dd.drain
    return d.us_invert + d.silt_m + dd.state.depth


def village_checks(net, by: dict, rules: RuleContext) -> list[CheckResult]:
    out = []
    drop = rules.get("village_outlet_min_drop_m")
    for ct in net.catchments:
        o = ct.obj
        if not o.attr("levels_fixed"):
            continue
        if o.attr("outlet_level") is None:
            out.append(CheckResult("village_outlet", o.id, o.label, CheckStatus.NOT_EVALUATED,
                                   "Level of the village drain mouth (outlet_level) not given", None, None, "m", drop))
            continue
        lvl = float(o.attr("outlet_level"))
        if ct.node.kind == ObjectKind.DRAIN_OUTFALL:
            tw = ct.node.attr("tailwater_level")
            wl = float(tw) if tw is not None else float(ct.node.attr("invert_level"))
            src = f"outfall {ct.node.label}"
        else:
            nxt = [by[d.obj.id] for d in net.outgoing(ct.node.id) if d.obj.id in by]
            if not nxt:
                continue
            wl = _water_level(nxt[0])
            src = f"drain {nxt[0].drain.obj.label} at {ct.node.label}"
            if wl is None:
                out.append(CheckResult("village_outlet", o.id, o.label, CheckStatus.FAIL,
                                       f"Receiving {src} runs over-full, so the village outlet at {lvl:.3f} m would be "
                                       "drowned", None, lvl, "m", drop))
                continue
        need = lvl - drop.value
        ok = wl <= need + 1e-9
        out.append(CheckResult(
            "village_outlet", o.id, o.label, CheckStatus.PASS if ok else CheckStatus.FAIL,
            f"Water level in {src} {wl:.3f} m vs village outlet {lvl:.3f} m – needs ≤ {need:.3f} m "
            f"({drop.value} m drop)" + ("" if ok else f"; lower the receiving drain by {wl - need:.2f} m here or enlarge it"),
            wl, need, "m", drop))
    return out


def outfall_checks(net, res, by: dict) -> list[CheckResult]:
    out = []
    for nid, n in net.nodes.items():
        if n.kind != ObjectKind.DRAIN_OUTFALL:
            continue
        for d in net.incoming(nid):
            dd = by.get(d.obj.id)
            inv = n.attr("invert_level")
            if inv is not None and d.ds_invert < float(inv) - 1e-6:
                out.append(CheckResult("outfall_invert", d.obj.id, d.obj.label, CheckStatus.FAIL,
                                       f"Drain arrives at {d.ds_invert:.3f} m, below the outfall bed {float(inv):.3f} m",
                                       d.ds_invert, float(inv), "m"))
            tw = n.attr("tailwater_level")
            if tw is None or dd is None:
                continue
            tw = float(tw)
            wl = d.ds_invert + d.silt_m + dd.state.depth if dd.state.capacity_ok else d.ds_invert + d.section.depth
            gl = n.attr("ground_level")
            if gl is not None and tw >= float(gl):
                st, msg = CheckStatus.FAIL, (f"Flood level of the receiving channel {tw:.3f} m is at or above the ground "
                                             f"at the outfall {float(gl):.3f} m – the area cannot drain by gravity in a flood")
            elif tw > wl:
                st, msg = CheckStatus.WARNING, (f"Flood level of the receiving channel {tw:.3f} m is above the drain's "
                                                f"water level {wl:.3f} m at the outfall – backwater during floods")
            else:
                st, msg = CheckStatus.PASS, f"Drain water level {wl:.3f} m above the channel flood level {tw:.3f} m"
            out.append(CheckResult("outfall_tailwater", d.obj.id, d.obj.label, st, msg, wl, tw, "m"))
    return out
