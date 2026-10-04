"""Sewer design-check report (Markdown).

The report separates, in this order: status banner, method, design
criteria used (with source and verification state), calculation sheet,
check results, proposed alternatives, network simulation (SWMM), and the
approval block, which is left blank for the responsible engineer.
"""

from __future__ import annotations

from ..engineering.sewer.design import SewerDesignResult
from ..rules.framework import CheckStatus, RuleContext

BANNER = ("> **CALCULATION – NOT CHECKED, NOT APPROVED.** Produced by software from the inputs and "
          "criteria listed below. It is not a certified design. Criteria marked *requires verification* "
          "have not been checked against the primary document.")


def render(project_name: str, res: SewerDesignResult, rules: RuleContext, swmm=None) -> str:
    L = [f"# Sewer design check – {project_name}", "", BANNER, "",
         "## 1. Method", "", f"- Pipe sizing: {res.method}."]
    if swmm is not None:
        L.append(f"- Network simulation: {swmm.run.engine} {swmm.run.engine_version}, dynamic-wave routing, "
                 f"constant design peak inflows to steady state. Flow continuity error "
                 f"{swmm.flow_continuity_error_pct:.3f} %.")
    else:
        L.append("- Network simulation (SWMM): **not run** – backwater/surcharge not evaluated.")

    L += ["", "## 2. Design criteria used", "", "| Parameter | Value | Unit | Source | Status |", "|---|---|---|---|---|"]
    used = sorted({c.parameter.id for c in res.all_checks() if c.parameter} |
                  {"water_supply_lpcd", "sewage_return_factor", "min_sewage_lpcd", "peak_factor",
                   "infiltration_fraction", "manning_n", "town_population"})
    for pid in used:
        p = rules.get(pid)
        L.append(f"| {pid} | `{p.value}` | {p.unit} | {p.source.cite()} | {p.verification.value} |")

    if res.errors:
        L += ["", "## Errors – calculation incomplete", ""] + [f"- {e}" for e in res.errors]

    L += ["", "## 3. Calculation sheet", "",
          "| Pipe | From | To | L (m) | Ø (mm) | Slope 1 in | Pop. | PF | Q design (L/s) | Q full (L/s) | d/D | V (m/s) | Result |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for d in res.pipes:
        r = d.row()
        L.append(f"| {r['pipe']} | {r['from']} | {r['to']} | {r['length_m']} | {r['diameter_mm']} | {r['slope_1_in']} | "
                 f"{r['population']} | {r['peak_factor']} | {r['design_flow_lps']} | {r['q_full_lps']} | "
                 f"{r['depth_ratio']} | {r['velocity_ms']} | {r['result']} |")

    L += ["", "## 4. Checks not passed", "", "| Object | Check | Status | Detail | Source |", "|---|---|---|---|---|"]
    for c in res.all_checks():
        if c.status != CheckStatus.PASS:
            src = c.parameter.source.cite() if c.parameter else (
                "hydraulic capacity (Manning)" if c.check == "capacity" else "network geometry rule")
            L.append(f"| {c.object_label} | {c.check} | {c.status.value} | {c.message} | {src} |")

    if res.failing:
        L += ["", "## 5. Proposed alternatives (not applied)", ""]
        for d in res.failing:
            for a in d.alternatives:
                L.append(f"- **{d.pipe.obj.label}**: {a}")

    if swmm is not None:
        L += ["", "## 6. Network simulation results (EPA SWMM)", "",
              "| Pipe | Q steady (L/s) | d/D steady | V steady (m/s) | Max d/D |", "|---|---|---|---|---|"]
        for d in res.pipes:
            k = swmm.links[d.pipe.obj.id]
            L.append(f"| {d.pipe.obj.label} | {k.final_flow*1000:.2f} | {k.final_depth_ratio:.3f} | "
                     f"{k.final_velocity:.3f} | {k.max_depth_ratio:.3f} |")
        sur = [(oid, n) for oid, n in swmm.nodes.items() if n.surcharged or n.max_overflow > 0]
        L += [""]
        if sur:
            L += ["| Node | HGL max (m) | Surcharged | Flooding (L/s) |", "|---|---|---|---|"]
            nodes = {d.pipe.us.id: d.pipe.us for d in res.pipes} | {d.pipe.ds.id: d.pipe.ds for d in res.pipes}
            for oid, n in sur:
                L.append(f"| {nodes[oid].label} | {n.max_head:.3f} | {'yes' if n.surcharged else 'no'} | {n.max_overflow*1000:.2f} |")
        else:
            L.append("No surcharge or flooding at any manhole.")
        if swmm.run.messages:
            L += ["", "Notes:"] + [f"- {m}" for m in swmm.run.messages]

    L += ["", "## 7. Review and approval", "",
          "| Role | Name / designation | Decision | Date |", "|---|---|---|---|",
          "| Designed by | | | |", "| Checked by | | | |", "| Approved by | | | |", ""]
    return "\n".join(L)
