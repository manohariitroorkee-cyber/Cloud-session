"""Water-supply design checks on EPANET results.

Pressure is checked against the configured minimum residual pressure for
the number of storeys to be served directly: the junction attribute
``storeys``, else the project rule ``design_storeys`` if one is configured,
else the check is NOT EVALUATED (never a silent default).  Hydraulics come only from the
EPANET engine; nothing here estimates flows or pressures.
"""

from __future__ import annotations

from ...engines.epanet.adapter import EpanetResult
from ...model.core import ObjectKind, Project
from ...rules.framework import CheckResult, CheckStatus, RuleContext


def pressure_checks(pr: Project, res: EpanetResult, rules: RuleContext) -> list[CheckResult]:
    par = rules.get("min_residual_pressure_m")
    try:
        project_storeys = rules.get("design_storeys")
    except KeyError:
        project_storeys = None
    out = []
    for n in pr.of_kind(ObjectKind.WATER_JUNCTION):
        r = res.nodes[n.id]
        p = r.min_pressure
        if n.attr("storeys") is not None:
            storeys, how = int(n.attr("storeys")), "junction data"
        elif project_storeys is not None:
            storeys, how = int(project_storeys.value), "project default"
        else:
            out.append(CheckResult("min_residual_pressure", n.id, n.label, CheckStatus.NOT_EVALUATED,
                                   f"Minimum pressure {p:.2f} m; number of storeys not given for this junction and no "
                                   f"project default – check not evaluated", p, None, "m", par))
            continue
        limit = par.lookup(storeys)
        out.append(CheckResult(
            "min_residual_pressure", n.id, n.label,
            CheckStatus.PASS if p >= limit else CheckStatus.FAIL,
            f"Minimum pressure {p:.2f} m over the run vs {limit} m required for {storeys} storey(s) ({how})",
            p, limit, "m", par))
    return out
