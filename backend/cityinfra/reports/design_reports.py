"""Design-check reports for storm drainage and road alignment (Markdown)."""

from __future__ import annotations

import math

from ..rules.framework import CheckStatus, RuleContext
from .sewer_report import BANNER


def _criteria(rules: RuleContext, checks, extra: list[str]) -> list[str]:
    ids = sorted({c.parameter.id for c in checks if c.parameter} | set(extra))
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
    L += ["", "## 3. Rational-method sheet", "",
          "| Drain | From | To | L (m) | Section | Slope 1 in | ΣA (ha) | ΣCA (ha) | tc (min) | i (mm/h) | Q (m³/s) | Q cap (m³/s) | d/D | V (m/s) | Result |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for d in res.drains:
        r = d.row()
        L.append(f"| {r['drain']} | {r['from']} | {r['to']} | {r['length_m']} | {r['section']} | {r['slope_1_in']} | "
                 f"{r['area_ha']} | {r['ca_ha']} | {r['tc_min']} | {r['i_mm_h']} | {r['q_m3s']} | {r['q_cap_m3s']} | "
                 f"{r['depth_ratio']} | {r['velocity_ms']} | {r['result']} |")
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
             "object_height_m", "headlight_height_m", "headlight_beam_deg", "min_vertical_curve_m"])
    if d.errors:
        L += ["", "## Errors", ""] + [f"- {e}" for e in d.errors]
    L += ["", "## 3. Horizontal curves", "",
          "| PI | Δ (°) | R (m) | Ls (m) | Ts (m) | Lc (m) | E (m) | Ch TS | Ch SC | Ch CS | Ch ST |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in d.h.curves:
        L.append(f"| PI{c.pi_index} | {math.degrees(c.delta):+.3f} | {c.radius:.0f} | {c.spiral:.1f} | {c.ts:.3f} | "
                 f"{c.lc:.3f} | {c.external:.3f} | {c.ch_ts:.3f} | {c.ch_sc:.3f} | {c.ch_cs:.3f} | {c.ch_st:.3f} |")
    L += ["", "## 4. Vertical alignment", "", "| VIP ch | Level | VC length (m) | Grade out (%) |", "|---|---|---|---|"]
    for i, v in enumerate(d.v.vips):
        g = f"{d.v.grade(i)*100:+.3f}" if i < len(d.v.vips) - 1 else "–"
        L.append(f"| {v.chainage:.3f} | {v.level:.3f} | {v.curve_length:.0f} | {g} |")
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
