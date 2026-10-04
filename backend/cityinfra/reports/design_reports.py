"""Design-check reports for storm drainage and road alignment (Markdown)."""

from __future__ import annotations

import math

from ..rules.framework import CheckStatus, RuleContext
from .sewer_report import BANNER


def _criteria(rules: RuleContext, checks, extra: list[str], skip: tuple[str, ...] = ()) -> list[str]:
    ids = sorted(({c.parameter.id for c in checks if c.parameter} | set(extra)) - set(skip))
    L = ["| Parameter | Value | Unit | Source | Status |", "|---|---|---|---|---|"]
    for pid in ids:
        p = rules.get(pid)
        L.append(f"| {pid} | `{p.value}` | {p.unit} | {p.source.cite()} | {p.verification.value} |")
    return L


def _failed(checks) -> list[str]:
    rows = [c for c in checks if c.status != CheckStatus.PASS]
    if not rows:
        return ["All checks passed."]
    L = ["| Object | Check | Status | Detail |", "|---|---|---|---|"]
    L += [f"| {c.object_label} | {c.check} | {c.status.value} | {c.message} |" for c in rows]
    return L


def drainage(project_name: str, res, rules: RuleContext, area_type: str, swmm=None) -> str:
    L = [f"# Storm-water drainage – hydraulic design check – {project_name}", "", BANNER, "",
         "Scope: hydraulic design only. Structural (RCC) design of drains, culverts and chambers is outside this report.", "",
         "## 1. Method and rainfall", "", f"- {res.method}.",
         f"- Design return period: {res.return_period} years; area type: {area_type}.",
         f"- IDF source: **{res.idf_source}**."]
    if swmm is not None:
        L.append(f"- Network simulation: {swmm.run.engine} {swmm.run.engine_version}, dynamic wave, alternating-block "
                 f"design storm (peak {max(swmm.hyetograph_mm_h):.0f} mm/h). Continuity errors: runoff "
                 f"{swmm.runoff_continuity_error_pct:.3f} %, routing {swmm.flow_continuity_error_pct:.3f} %.")
    else:
        L.append("- Network simulation (SWMM): **not run**.")
    L += ["", "## 2. Design criteria used", ""] + _criteria(rules, res.all_checks(), ["runoff_coefficients", "manning_n_drains"])
    if res.errors:
        L += ["", "## Errors – calculation incomplete", ""] + [f"- {e}" for e in res.errors]
    if getattr(res, "notes", None):
        L += ["", "Notes:"] + [f"- {n}" for n in res.notes]
    L += ["", "## 3. Rational-method sheet", "",
          "| Drain | From | To | L (m) | Section | Slope 1 in | ΣA (ha) | ΣCA (ha) | tc (min) | i (mm/h) | Q (m³/s) | Q cap (m³/s) | d/D | V (m/s) | Result |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for d in res.drains:
        r = d.row()
        r['drain'] += " (existing)" if d.drain.existing else ""
        L.append(f"| {r['drain']} | {r['from']} | {r['to']} | {r['length_m']} | {r['section']} | {r['slope_1_in']} | "
                 f"{r['area_ha']} | {r['ca_ha']} | {r['tc_min']} | {r['i_mm_h']} | {r['q_m3s']} | {r['q_cap_m3s']} | "
                 f"{r['depth_ratio']} | {r['velocity_ms']} | {r['result']} |")
    if getattr(res, "existing", None):
        L += ["", "## 3a. Existing drains – capacity and residual capacity", "",
              "Usable capacity: Manning discharge of the section available today (bed raised by the recorded silt) at "
              "the depth leaving the design freeboard. Flow today: existing catchments and recorded inflows only. "
              "Residual = usable − flow today. Added = full design flow − flow today.", "",
              "| Drain | Section | Silt (m) | Slope 1 in | Usable (m³/s) | Flow today (m³/s) | Residual (m³/s) | Added by new areas (m³/s) | Total (m³/s) | Used |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for a in res.existing:
            r = a.row()
            L.append(f"| {r['drain']} | {r['section']} | {r['silt_m']} | {r['slope_1_in']} | {r['q_usable_m3s']} | "
                     f"{r['q_existing_m3s']} | {r['residual_m3s']} | {r['q_added_m3s']} | {r['q_total_m3s']} | "
                     f"{r['utilisation_pct']} % |")
    L += ["", "## 4. Checks not passed", ""] + _failed(res.all_checks())
    alts = [(d.drain.obj.label, a) for d in res.failing for a in d.alternatives]
    if alts:
        L += ["", "## 5. Proposed alternatives (not applied)", ""] + [f"- **{n}**: {a}" for n, a in alts]
    if swmm is not None:
        L += ["", "## 6. SWMM results", "", "| Drain | Peak Q (m³/s) | Max d/D | Peak V (m/s) |", "|---|---|---|---|"]
        for d in res.drains:
            s = swmm.drains[d.drain.obj.id]
            L.append(f"| {d.drain.obj.label} | {s.peak_flow:.3f} | {s.max_depth_ratio:.3f} | {s.peak_velocity:.2f} |")
        fl = [(oid, n) for oid, n in swmm.nodes.items() if n.peak_flooding > 1e-6 or n.surcharged]
        L.append("")
        if fl:
            L += ["| Node | Max HGL (m) | Peak flooding (m³/s) | Surcharged |", "|---|---|---|---|"]
            names = {d.drain.us.id: d.drain.us.label for d in res.drains} | {d.drain.ds.id: d.drain.ds.label for d in res.drains}
            L += [f"| {names.get(oid, oid[:8])} | {n.max_head:.3f} | {n.peak_flooding:.3f} | {'yes' if n.surcharged else 'no'} |"
                  for oid, n in fl]
        else:
            L.append("No flooding or surcharge at any node.")
        L += ["", "Rational-method flows are peak design flows for sizing; SWMM peaks include storage, routing and "
              "flooding losses and are normally lower. Both are reported; neither replaces the other."]
    L += ["", "## Review and approval", "", "| Role | Name / designation | Decision | Date |", "|---|---|---|---|",
          "| Designed by | | | |", "| Checked by | | | |", "| Approved by | | | |", ""]
    return "\n".join(L)


def road(project_name: str, d, rules: RuleContext, impacts: list[dict], tin=None) -> str:
    r = d.road
    L = [f"# Road alignment and curve design check – {r.label} – {project_name}", "", BANNER, "",
         "Scope: horizontal and vertical alignment and curve design. Pavement thickness design, structural (RCC) "
         "design, earthwork and quantities are outside this report.", "",
         "## 1. Basis", "", f"- Design speed {r.attr('design_speed_kmh')} km/h; alignment length {d.h.length:.3f} m.",
         f"- Method: {__import__('cityinfra.engineering.roads.design', fromlist=['METHOD']).METHOD}.",
         "", "## 2. Design criteria used", ""] + _criteria(rules, d.checks, [
             "f_lateral", "e_design_divisor", "superelevation_runoff_N", "reaction_time_s", "eye_height_m",
             "object_height_m", "headlight_height_m", "headlight_beam_deg", "min_vertical_curve_m",
             "transition_required_shift_m", "broken_back_min_tangent_m", "compound_radius_ratio_max"])
    if d.errors:
        L += ["", "## Errors", ""] + [f"- {e}" for e in d.errors]
    L += ["", "## 3. Horizontal alignment", "",
          f"Geometry entered as: **{ {'pi': 'PI polyline with curve at each PI', 'elements': 'element chain', 'bulges': 'CAD polyline with arcs', 'fit': 'freehand trace, fitted'}.get(d.h.source, d.h.source) }**.", ""]
    if d.h.fit_report:
        fr = d.h.fit_report
        L += [f"Fitted from the drawing: {fr['curves']} curve(s), radii {fr['radii_m']} m; deviation from the drawn "
              f"line max {fr['max_deviation_m']} m, mean {fr['mean_deviation_m']} m (tolerance {fr['tolerance_m']} m)."]
        L += [f"- {n}" for n in fr["notes"]] + [""]
    L += ["| Curve | Type | Δ (°) | Radii (m) | Ls in (m) | Ls out (m) | T in (m) | T out (m) | Arc (m) | Length (m) | Ch start | Ch end |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for g in d.h.groups:
        radii = ", ".join(f"{r:.0f}" for r in g.radii) or "–"
        t_a = f"{g.t_in:.3f}" if g.pi is not None else "–"
        t_b = f"{g.t_out:.3f}" if g.pi is not None else "–"
        L.append(f"| {g.tag} | {g.kind} | {math.degrees(g.delta):+.3f} | {radii} | {g.spiral_in:.1f} | {g.spiral_out:.1f} | "
                 f"{t_a} | {t_b} | {g.arc_length:.3f} | {g.length:.3f} | {g.ch_start:.3f} | {g.ch_end:.3f} |")
    L += ["", "Element schedule:", "", "| # | Element | Ch start | Length (m) | Radius start → end | Start E | Start N | Start bearing (°) |",
          "|---|---|---|---|---|---|---|---|"]
    from ..engineering.roads.alignment import _r
    for i, e in enumerate(d.h.elements, 1):
        L.append(f"| {i} | {e.kind} {e.tag} | {e.ch0:.3f} | {e.length:.3f} | {_r(e.k0)} → {_r(e.k1)} | {e.x0:.3f} | {e.y0:.3f} | "
                 f"{math.degrees(e.b0) % 360:.4f} |")
    L += ["", "## 4. Vertical alignment", "", "| VIP ch | Level | VC before VIP (m) | VC after VIP (m) | Grade out (%) |", "|---|---|---|---|---|"]
    for i, v in enumerate(d.v.vips):
        g = f"{d.v.grade(i)*100:+.3f}" if i < len(d.v.vips) - 1 else "–"
        L.append(f"| {v.chainage:.3f} | {v.level:.3f} | {v.la:.1f} | {v.lb:.1f} | {g} |")
    L += ["", "## 5. Checks not passed", ""] + _failed(d.checks)
    if tin is not None:
        L += ["", "## 6. Long-section (every 20 m)", "", "| Ch | FRL | Ground | FRL − ground |", "|---|---|---|---|"]
        for row in d.long_section(20, tin):
            L.append(f"| {row['chainage']:.1f} | {row['frl']:.3f} | {row['ground'] if row['ground'] is not None else '–'} | "
                     f"{row['cut_fill'] if row['cut_fill'] is not None else '–'} |")
    L += ["", "## 7. Utilities whose top level must follow the road", ""]
    if impacts:
        L += ["| Object | Kind | Ch | Offset | Strip | Current level | Road surface | Difference (m) |",
              "|---|---|---|---|---|---|---|---|"]
        L += [f"| {i['object']} | {i['kind']} | {i['chainage']} | {i['offset']} | {i['strip']} | {i['current_level']} | "
              f"{i['road_surface_level']} | {i['difference_m']:+.3f} |" for i in impacts]
    else:
        L.append("None found within the right of way.")
    L += ["", "## Review and approval", "", "| Role | Name / designation | Decision | Date |", "|---|---|---|---|",
          "| Designed by | | | |", "| Checked by | | | |", "| Approved by | | | |", ""]
    return "\n".join(L)


def electrical(project_name: str, net, res, rules: RuleContext, sched: dict) -> str:
    L = [f"# Electrical distribution check – {project_name}", "", BANNER, "",
         "Scope: radial HT/LT network – demand, transformer loading, cable current and voltage drop. "
         "Short-circuit, protection discrimination and earthing are not covered.", "",
         "## 1. Method", "", f"- {res.method}.", "",
         "## 2. Design criteria and data used", ""] + _criteria(rules, res.checks, [
             "demand_factors", "diversity_factors", "default_power_factor", "cable_derating_factor",
             "lt_nominal_voltage_v"],
             skip=("cable_library",))
    cl = rules.get("cable_library")
    lib = cl.value
    used = sorted({cr.cable.type for cr in res.cables.values()})
    L += ["", f"Cable data used – source: {cl.source.cite()} ({cl.verification.value})", "",
          "| Cable type | Description | R (Ω/km) | X (Ω/km) | Rating (A) |", "|---|---|---|---|---|"]
    L += [f"| {t} | {lib[t].get('description', '')} | {lib[t]['r_ohm_km']} | {lib[t]['x_ohm_km']} | {lib[t]['rating_a']} |"
          for t in used]
    if cl.verification.value != "verified":
        L += ["", "> The cable data is **not verified**. Replace it with the approved manufacturer's datasheet "
                  "values before relying on any current or voltage-drop figure."]
    if res.errors:
        L += ["", "## Errors – calculation incomplete", ""] + [f"- {e}" for e in res.errors]
        return "\n".join(L) + "\n"
    L += ["", "## 3. Transformer schedule", "",
          "| Transformer | Rating (kVA) | Ratio | Fed by | Loads | Σ load MD (kVA) | Diversity | Demand (kVA) | Loading |",
          "|---|---|---|---|---|---|---|---|---|"]
    L += [f"| {t['transformer']} | {t['rating_kva']} | {t['ratio']} | {t['fed_by']} | {t['loads']} | {t['connected_md_kva']} | "
          f"{t['diversity']} | {t['demand_kva']} | {t['loading_pct']} % |" for t in sched["transformers"]]
    L += ["", "## 4. Feeder pillar schedule", "", "| Pillar | Fed by | Outgoing ways | Loads | Diversity | Demand (kVA) |",
          "|---|---|---|---|---|---|"]
    L += [f"| {p['pillar']} | {p['fed_by']} | {p['outgoing_ways']} | {p['loads']} | {p['diversity']} | {p['demand_kva']} |"
          for p in sched["feeder_pillars"]]
    L += ["", "## 5. Cable schedule", "",
          "| Cable | From | To | Level | Type | Runs | Length (m) | Current (A) | Capacity (A) | ΔV (%) | Cumulative ΔV (%) |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    L += [f"| {c['cable']} | {c['from']} | {c['to']} | {c['level']} | {c['type']} | {c['runs']} | {c['length_m']} | "
          f"{c['current_a']} | {c['capacity_a']} | {c['drop_pct']} | {c['cum_drop_pct']} |" for c in sched["cables"]]
    L += ["", "## 6. Load schedule", "", "| Load | Category | Connected (kW) | Demand (kW) | pf | Phases | Fed by |",
          "|---|---|---|---|---|---|---|"]
    L += [f"| {l['load']} | {l['category']} | {l['connected_kw']} | {l['demand_kw']} | {l['pf']} | {l['phases']} | {l['fed_by']} |"
          for l in sched["loads"]]
    L += ["", "## 7. Checks not passed", ""] + _failed(res.checks)
    if res.proposals:
        L += ["", "## 8. Proposed changes (not applied)", ""] + [f"- {p}" for p in res.proposals]
    L += ["", "## Review and approval", "", "| Role | Name / designation | Decision | Date |", "|---|---|---|---|",
          "| Designed by | | | |", "| Checked by | | | |", "| Approved by | | | |", ""]
    return "\n".join(L)


def junction(project_name: str, d, rules: RuleContext) -> str:
    j = d.junction
    L = [f"# Junction design check – {j.label} ({d.kind}) – {project_name}", "", BANNER, "",
         "Scope: geometric design – arm angles, kerb returns, sight triangles; for roundabouts the circle, "
         "entry/exit kerbs, weaving sections and (if flows are given) weaving capacity. Swept-path analysis, "
         "signal design and structural design are not covered.", "",
         "## 1. Design criteria used", ""] + _criteria(rules, d.checks, (
             ["reaction_time_s", "f_longitudinal", "minor_road_setback_m", "major_road_visibility_time_s",
              "corner_radius_by_vehicle", "min_intersection_angle_deg"] if d.kind == "intersection" else
             ["roundabout_entry_radius_range_m", "weaving_length_to_width_min", "wardrop_coefficient", "wardrop_validity"]))
    if d.errors:
        L += ["", "## Errors", ""] + [f"- {e}" for e in d.errors]
    L += ["", "## 2. Arms", "", "| Arm | Bearing (°) | Edge left (m) | Edge right (m) | Speed (km/h) | Priority | Road |",
          "|---|---|---|---|---|---|---|"]
    L += [f"| {a.name} | {math.degrees(a.bearing) % 360:.2f} | {a.w_left:.2f} | {a.w_right:.2f} | {a.speed:.0f} | {a.priority} | "
          f"{a.road.label if a.road else '–'} |" for a in d.arms]
    if d.corners:
        L += ["", "## 3. Kerb returns", "", "| Corner | Sector (°) | Type | Radii (m) | Tangent in (m) | Tangent out (m) | Kerb length (m) | PI E | PI N |",
              "|---|---|---|---|---|---|---|---|---|"]
        for c in d.corners:
            if c.group is None:
                L.append(f"| {c.name} | {math.degrees(c.angle):.1f} | continuous kerb | – | – | – | – | – | – |")
                continue
            g = c.group
            L.append(f"| {c.name} | {math.degrees(c.angle):.1f} | {g.kind} | {', '.join(f'{r:.1f}' for r in g.radii)} | "
                     f"{g.t_in:.2f} | {g.t_out:.2f} | {g.length:.2f} | {c.pi[0]:.3f} | {c.pi[1]:.3f} |")
    if d.triangles:
        L += ["", "## 4. Sight triangles", "", "| Approaches | Distances (m) | Obstructions |", "|---|---|---|"]
        L += [f"| {t.name} | {t.distances[0]:.1f} × {t.distances[1]:.1f} | {', '.join(t.obstructions) or 'none'} |" for t in d.triangles]
    if d.roundabout:
        rb = d.roundabout
        L += ["", "## 5. Roundabout", "",
              f"- Central island radius {rb['central_island_radius_m']:.1f} m; circulatory width {rb['circulatory_width_m']:.1f} m; "
              f"inscribed circle diameter {rb['inscribed_diameter_m']:.1f} m.",
              f"- Entry kerb radius {rb['entry_radius_m']:.1f} m; exit kerb radius {rb['exit_radius_m']:.1f} m ({rb['setting']}).",
              "- Weaving length is measured along the middle of the circulating carriageway, between the radial lines "
              "through the end of one arm's entry kerb and the start of the next arm's exit kerb (clockwise circulation).", "",
              "| Weaving section | Length (m) | Width (m) | Capacity (PCU/h) |", "|---|---|---|---|"]
        L += [f"| {w['section']} | {w['length_m']:.1f} | {w['width_m']:.1f} | "
              f"{w['capacity_pcu_h']:.0f}" + (f" – not reliable: {w['capacity_note']}" if 'capacity_note' in w else "") + " |"
              if 'capacity_pcu_h' in w else
              f"| {w['section']} | {w['length_m']:.1f} | {w['width_m']:.1f} | – (no flows given) |" for w in rb["weaving"]]
    if d.notes:
        L += ["", "Notes:"] + [f"- {n}" for n in d.notes]
    L += ["", "## Checks not passed", ""] + _failed(d.checks)
    L += ["", "## Review and approval", "", "| Role | Name / designation | Decision | Date |", "|---|---|---|---|",
          "| Designed by | | | |", "| Checked by | | | |", "| Approved by | | | |", ""]
    return "\n".join(L)
