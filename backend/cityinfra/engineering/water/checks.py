"""Water-supply design checks on EPANET results.

Pressure is checked against the configured minimum residual pressure for
the number of storeys to be served directly (junction attribute
``storeys``, default from the rule context).  Hydraulics come only from the
EPANET engine; nothing here estimates flows or pressures.
"""

from __future__ import annotations

from ...engines.epanet.adapter import EpanetResult
from ...model.core import ObjectKind, Project
from ...rules.framework import CheckResult, CheckStatus, RuleContext


def pressure_checks(pr: Project, res: EpanetResult, rules: RuleContext,
                    default_storeys: int = 2) -> list[CheckResult]:
    par = rules.get("min_residual_pressure_m")
    out = []
    for n in pr.of_kind(ObjectKind.WATER_JUNCTION):
        r = res.nodes[n.id]
        storeys = int(n.attr("storeys", default_storeys))
        limit = par.lookup(storeys)
        p = r.min_pressure
        out.append(CheckResult(
            "min_residual_pressure", n.id, n.label,
            CheckStatus.PASS if p >= limit else CheckStatus.FAIL,
            f"Minimum pressure {p:.2f} m over the run vs {limit} m required for {storeys} storey(s)",
            p, limit, "m", par))
    return out
