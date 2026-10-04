"""Propose sizes and levels for the NEW (proposed) storm drains of a layout.

Inputs are the drawn layout and the facts around it: ground levels at the drain points
(entered, or interpolated from survey points), existing drains and their levels (kept as
they are), villages whose drain mouths are at fixed levels, and the outfall bed and flood
level.  Nothing is written to the model: the result is a proposal for the designer to accept,
change and then check with design_network().

For each new drain, upstream first (Rational method, as in network.design_network):
  1. design flow Q from the catchments and drains above it;
  2. the smallest section (pipe diameters, or open/box drain widths) that carries Q with
     the required d/D or freeboard and at least the self-cleansing velocity, at the slope
       s = max(ground slope, slope needed for self-cleansing and capacity),
     limited so the velocity stays below the maximum (steep ground then needs drops);
  3. the upstream bed level as the lowest of
       ground − cover − depth (pipes, box drains) or ground − depth (open drains), at both ends,
       the beds of the drains arriving (no step up; crowns matched),
       the level that keeps a village drain mouth discharging freely;
  4. downstream bed = upstream bed − s × length, and the drop into the existing drain or
     outfall below is checked.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ...gis.geometry import line_length, polygon_area
from ...model.core import ObjectKind, Project, RelationType
from ...rules.framework import RuleContext
from ..common.open_channel import Section, normal_flow
from .network import NODE_KINDS, composite_c, fill_ground_from_survey, section_of
from .rainfall import IDF, kirpich_tc_min


@dataclass
class Proposal:
    drains: dict[str, dict] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _ok(sec: Section, s: float, n: float, q: float, rules: RuleContext, open_top: bool) -> tuple[bool, object]:
    st = normal_flow(sec, s, n, q)
    if not st.capacity_ok or st.velocity < rules.value("min_velocity") - 1e-9:
        return False, st
    if sec.shape == "circular":
        return st.depth_ratio <= rules.value("max_depth_ratio_pipe") + 1e-9, st
    return True, st


def _min_slope(sec, n, q, rules, open_top) -> float | None:
    lo, hi = 1e-5, 0.2
    if not _ok(sec, hi, n, q, rules, open_top)[0]:
        return None
    for _ in range(60):
        mid = math.sqrt(lo * hi)
        if _ok(sec, mid, n, q, rules, open_top)[0]:
            hi = mid
        else:
            lo = mid
    return hi


def _max_slope_for_v(sec, n, q, vmax) -> float:
    lo, hi = 1e-5, 0.5
    for _ in range(60):
        mid = math.sqrt(lo * hi)
        st = normal_flow(sec, mid, n, q)
        if st.capacity_ok and st.velocity <= vmax:
            lo = mid
        else:
            hi = mid
    return lo


def _round_up(x: float, step: float) -> float:
    return math.ceil(x / step - 1e-9) * step


def propose(pr: Project, rules: RuleContext, idf: IDF, return_period: float, default_shape: str = "circular",
            default_lining: str = "rcc") -> Proposal:
    out = Proposal()
    nodes = {o.id: o for o in pr.of_kind(*NODE_KINDS)}
    out.notes += fill_ground_from_survey(pr, nodes.values())
    vmin, vmax = rules.value("min_velocity"), rules.value("max_velocity")
    fb, cover = rules.value("min_freeboard_m"), rules.value("drain_pipe_min_cover_m")
    step, drop = rules.value("drain_depth_step_m"), rules.value("village_outlet_min_drop_m")
    ntab = rules.value("manning_n_drains")
    links = {}
    for o in pr.of_kind(ObjectKind.STORM_DRAIN):
        us, ds = pr.related(o, RelationType.UPSTREAM_NODE), pr.related(o, RelationType.DOWNSTREAM_NODE)
        if len(us) != 1 or len(ds) != 1 or us[0].id not in nodes or ds[0].id not in nodes:
            out.issues.append(f"Drain {o.label}: join both ends to drain points first.")
            continue
        links[o.id] = (o, us[0], ds[0])
    for n in nodes.values():
        if n.attr("ground_level") is None:
            out.issues.append(f"{n.label}: ground level missing (enter it, or add survey points around it).")
    if any("ground level missing" in i for i in out.issues):
        return out
    at_node: dict[str, list[tuple[float, float, float]]] = {}
    villages: dict[str, list[float]] = {}
    for c in pr.of_kind(ObjectKind.CATCHMENT):
        tgt = pr.related(c, RelationType.DRAINS_TO)
        if len(tgt) != 1:
            out.issues.append(f"Rain area {c.label}: choose the drain point its rain goes to.")
            continue
        try:
            cc = composite_c(c, rules)
            tc = float(c.attr("inlet_time_min")) if c.attr("inlet_time_min") is not None else max(
                kirpich_tc_min(float(c.attr("flow_length_m")), float(c.attr("overland_slope"))),
                rules.value("min_inlet_time_min"))
        except (TypeError, ValueError) as e:
            out.issues.append(f"Rain area {c.label}: {e}")
            continue
        a = polygon_area(c.geometry) / 10_000
        at_node.setdefault(tgt[0].id, []).append((cc * a, a, tc))
        if c.attr("levels_fixed") and c.attr("outlet_level") is not None:
            villages.setdefault(tgt[0].id, []).append(float(c.attr("outlet_level")))
    # upstream-first order
    indeg = {k: sum(1 for x in links.values() if x[2].id == v[1].id) for k, v in links.items()}
    ready = sorted((k for k, v in indeg.items() if v == 0), key=lambda k: links[k][0].label)
    order = []
    while ready:
        k = ready.pop(0)
        order.append(k)
        for k2, v2 in links.items():
            if v2[1].id == links[k][2].id:
                indeg[k2] -= 1
                if indeg[k2] == 0:
                    ready.append(k2)
    if len(order) != len(links):
        out.issues.append("The drains form a loop; each drain point must have one way out.")
        return out

    done: dict[str, dict] = {}      # drain id -> {ca, area, tc_end, ext, ds_inv, h, existing}
    for k in order:
        o, us, ds = links[k]
        L = line_length(o.geometry)
        ca = sum(x[0] for x in at_node.get(us.id, []))
        area = sum(x[1] for x in at_node.get(us.id, []))
        tcs = [x[2] for x in at_node.get(us.id, [])]
        ext = float(us.attr("external_inflow_m3s") or 0.0)
        inc = [done[j] for j, v in links.items() if v[2].id == us.id and j in done]
        for x in inc:
            ca += x["ca"]; area += x["area"]; tcs.append(x["tc"]); ext += x["ext"]
        tc = max(tcs) if tcs else rules.value("min_inlet_time_min")
        q = ca * idf.intensity(tc, return_period) / 360.0 + ext
        lining = str(o.attr("lining") or default_lining).lower()
        n = ntab.get(lining)
        if n is None:
            out.issues.append(f"Drain {o.label}: no Manning n for lining '{lining}'.")
            break
        if o.status.value == "existing":
            try:
                sec = section_of(o)
                usi, dsi = float(o.attr("us_invert")), float(o.attr("ds_invert"))
            except (TypeError, ValueError):
                out.issues.append(f"Existing drain {o.label}: give its size and bed levels.")
                break
            silt = float(o.attr("silt_depth_m") or 0.0)
            st = normal_flow(sec, max((usi - dsi) / L, 1e-6), n, q)
            v = st.velocity if st.capacity_ok else max(st.q_capacity, q) / sec.full_area()
            done[k] = {"ca": ca, "area": area, "tc": tc + L / v / 60, "ext": ext, "ds_inv": dsi, "us_inv": usi + silt,
                       "h": sec.depth, "existing": True}
            continue
        gA, gB = float(us.attr("ground_level")), float(ds.attr("ground_level"))
        s_ground = (gA - gB) / L
        shape = o.attr("shape") or default_shape
        closed = shape == "circular" or bool(o.attr("closed", False))
        z = float(o.attr("side_slope", 1.0)) if shape == "trapezoidal" else 0.0
        min_h = max([x["h"] for x in inc if not x["existing"]], default=0.0)
        cands = []
        if shape == "circular":
            for dia in rules.value("drain_pipe_diameters_mm"):
                if dia >= rules.value("min_pipe_diameter_mm") and dia / 1000 >= min_h - 1e-9:
                    cands.append(Section("circular", dia / 1000, dia / 1000, closed=True))
        else:
            for b in rules.value("open_drain_widths_m"):
                cands.append(Section(shape, 20.0, b, z, False))      # depth fixed after the flow depth is known
        # prefer the smallest section that can follow the ground (keeps drains shallow); on flat or
        # rising ground take the section that needs the flattest slope
        feas = [(sec, _min_slope(sec, n, q, rules, not closed)) for sec in cands]
        feas = [(sec, sr) for sec, sr in feas if sr is not None]
        if shape != "circular":
            feas = [(sec, sr) for sec, sr in feas
                    if normal_flow(sec, max(s_ground, sr), n, q).depth <= 1.2 * sec.width] or feas[-1:]
        follow = [x for x in feas if x[1] <= max(s_ground, 0) + 1e-12]
        ranked = follow[:1] + sorted(feas, key=lambda x: (round(x[1], 6), x[0].width))
        choice = None
        for sec, s_req in ranked:
            s = max(s_ground, s_req)
            st = normal_flow(sec, s, n, q)
            drops = False
            if st.velocity > vmax:
                s_cap = _max_slope_for_v(sec, n, q, vmax)
                if s_cap < s_req:
                    continue
                s, drops = s_cap, s_ground > s_cap
                st = normal_flow(sec, s, n, q)
            if shape != "circular":
                h = max(_round_up(st.depth + fb, step), 0.3)
                sec = Section(shape, h, sec.width, z, closed)
                st = normal_flow(sec, s, n, q)
            choice = (sec, s, st, drops)
            break
        if choice is None:
            out.issues.append(f"Drain {o.label}: no listed size carries {q:.3f} m³/s within the velocity limits; "
                              "use a bigger open channel or split the flow.")
            break
        sec, s, st, drops = choice
        h = sec.depth
        top = (lambda g: g - cover - h) if closed else (lambda g: g - h)
        lim = [top(gA), top(gB) + s * L]
        for x in inc:
            lim += [x["ds_inv"], x["ds_inv"] + x["h"] - h] if not x["existing"] else [x["ds_inv"]]
        for lvl in villages.get(us.id, []):
            lim.append(lvl - drop - st.depth)
        usi = min(lim)
        dsi = usi - s * L
        rec = {"shape": shape, "lining": lining, "us_invert": round(usi, 3), "ds_invert": round(dsi, 3),
               "slope_1_in": round(1 / s), "flow_m3s": round(q, 4), "velocity_ms": round(st.velocity, 2),
               "depth_at_start_m": round(gA - usi, 2), "depth_at_end_m": round(gB - dsi, 2)}
        if shape == "circular":
            rec["diameter_mm"] = round(sec.depth * 1000)
            rec["depth_ratio"] = round(st.depth_ratio, 2)
        else:
            rec.update({"width_m": sec.width, "height_m": round(h, 2), "flow_depth_m": round(st.depth, 2)})
            if shape == "trapezoidal":
                rec["side_slope"] = z
            if closed:
                rec["closed"] = True
        if drops:
            rec["note"] = "Ground falls faster than the drain may; provide drops at the drain points."
        out.drains[o.id] = rec
        done[k] = {"ca": ca, "area": area, "tc": tc + L / st.velocity / 60, "ext": ext, "ds_inv": dsi, "h": h,
                   "existing": False}
        # what the drain runs into
        nxt = [j for j, v in links.items() if v[1].id == ds.id]
        if ds.kind == ObjectKind.DRAIN_OUTFALL and ds.attr("invert_level") is not None and dsi < float(ds.attr("invert_level")) - 1e-6:
            out.issues.append(f"Drain {o.label} would reach the outfall {ds.label} at {dsi:.2f} m, "
                              f"{float(ds.attr('invert_level')) - dsi:.2f} m below its bed. The area cannot drain there by "
                              "gravity at these depths: try open drains instead of pipes, a lower outfall, a shorter "
                              "route, or pumping.")
        for j in nxt:
            e = links[j][0]
            if e.status.value == "existing" and e.attr("us_invert") is not None:
                bed = float(e.attr("us_invert")) + float(e.attr("silt_depth_m") or 0.0)
                if dsi < bed - 1e-6:
                    out.issues.append(f"Drain {o.label} would arrive {bed - dsi:.2f} m below the bed of the existing "
                                      f"drain {e.label}. Try open drains instead of pipes (they need no earth cover), "
                                      "connect further downstream, or regrade that drain.")
    return out
