"""Configurable, traceable design-rule framework.

A *rule set* is a YAML file holding named design parameters.  Each parameter
records its value, unit, the document and clause it comes from, and whether
an engineer has verified it against the primary source.  Projects layer
their own overrides on top of a base rule set; every override records who
made it and why.

Engineering modules never hard-code a design criterion: they ask the
:class:`RuleContext` for a parameter by ID and attach the parameter's
provenance to every check they report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

RULESET_DIR = Path(__file__).parent / "rulesets"


class Verification(str, Enum):
    REQUIRES_VERIFICATION = "requires_verification"  # transcribed, not yet checked against the primary text
    VERIFIED = "verified"                            # checked against the primary text by a named engineer
    PROJECT_DECISION = "project_decision"            # value adopted by project decision, not from a code


@dataclass(frozen=True)
class Source:
    document: str
    clause: str = ""
    note: str = ""

    def cite(self) -> str:
        return f"{self.document}{', ' + self.clause if self.clause else ''}"


@dataclass(frozen=True)
class Parameter:
    id: str
    value: Any
    unit: str
    description: str
    source: Source
    verification: Verification
    ruleset: str
    verified_by: str | None = None
    override_reason: str | None = None

    def lookup(self, key: float) -> Any:
        """For a step table ``[[upper_bound_or_null, value], ...]`` return the
        value of the first row whose bound is >= key (null = no upper bound)."""
        if not isinstance(self.value, list):
            raise TypeError(f"parameter {self.id} is not a table")
        for bound, val in self.value:
            if bound is None or key <= bound:
                return val
        raise ValueError(f"{key} outside table {self.id}")


@dataclass
class RuleSet:
    id: str
    title: str
    parameters: dict[str, Parameter]

    @classmethod
    def load(cls, path: str | Path) -> "RuleSet":
        p = Path(path)
        if not p.is_absolute() and not p.exists():
            p = RULESET_DIR / p
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        rid = data["id"]
        default_doc = data.get("source_document", "")
        params: dict[str, Parameter] = {}
        for pid, d in data["parameters"].items():
            src = d.get("source", {})
            if d.get("verification") == "verified" and not d.get("verified_by"):
                raise ValueError(f"{p.name}: parameter '{pid}' is marked verified but does not say who verified it "
                                 f"(add verified_by: name / designation and date)")
            params[pid] = Parameter(
                id=pid,
                value=d["value"],
                unit=d.get("unit", ""),
                description=d.get("description", ""),
                source=Source(src.get("document", default_doc), src.get("clause", ""), src.get("note", "")),
                verification=Verification(d.get("verification", "requires_verification")),
                ruleset=rid,
                verified_by=d.get("verified_by"),
            )
        return cls(rid, data.get("title", rid), params)


@dataclass
class RuleContext:
    """Base rule set(s) plus project overrides, resolved in order."""

    layers: list[RuleSet]
    overrides: dict[str, Parameter] = field(default_factory=dict)

    def override(self, pid: str, value: Any, *, reason: str, by: str, unit: str | None = None) -> None:
        base = self.get(pid)
        self.overrides[pid] = Parameter(
            id=pid, value=value, unit=unit or base.unit, description=base.description,
            source=Source("Project override", note=reason),
            verification=Verification.PROJECT_DECISION, ruleset="project",
            verified_by=by, override_reason=reason)

    def get(self, pid: str) -> Parameter:
        if pid in self.overrides:
            return self.overrides[pid]
        for layer in reversed(self.layers):
            if pid in layer.parameters:
                return layer.parameters[pid]
        raise KeyError(f"design parameter '{pid}' is not defined in rule sets "
                       f"{[l.id for l in self.layers]}")

    def value(self, pid: str) -> Any:
        return self.get(pid).value

    def unverified(self) -> list[Parameter]:
        ids = {pid for l in self.layers for pid in l.parameters} | set(self.overrides)
        return [p for p in (self.get(i) for i in sorted(ids))
                if p.verification == Verification.REQUIRES_VERIFICATION]


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    NOT_EVALUATED = "not_evaluated"   # input missing – never silently treated as pass


@dataclass
class CheckResult:
    check: str
    object_id: str
    object_label: str
    status: CheckStatus
    message: str
    actual: float | None = None
    limit: float | None = None
    unit: str = ""
    parameter: Parameter | None = None

    def as_dict(self) -> dict[str, Any]:
        p = self.parameter
        return {
            "check": self.check, "object_id": self.object_id, "object": self.object_label,
            "status": self.status.value, "message": self.message,
            "actual": self.actual, "limit": self.limit, "unit": self.unit,
            "parameter": p.id if p else None,
            "source": p.source.cite() if p else None,
            "verification": p.verification.value if p else None,
        }
