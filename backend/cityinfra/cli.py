"""Command-line entry points (until the HTTP API exists).

    python -m cityinfra.cli sewer  <network.geojson> [--epsg 32643] [--no-swmm] [-o report.md]
    python -m cityinfra.cli sewer  --sample            # synthetic demonstration network
    python -m cityinfra.cli water  --sample
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .engineering.sewer.design import design_network
from .engineering.sewer.network import build_network
from .engines.base import EngineUnavailable
from .gis.geojson_io import import_feature_collection
from .model.core import Project
from .reports.sewer_report import render
from .rules.framework import RuleContext, RuleSet


def _project(args) -> Project:
    if args.sample:
        from .samples import sample_sewer_project, sample_water_project
        return sample_sewer_project() if args.cmd == "sewer" else sample_water_project()
    pr = Project(Path(args.file).stem, args.epsg)
    problems = import_feature_collection(pr, json.loads(Path(args.file).read_text()))
    if problems:
        sys.exit("Import problems:\n" + "\n".join(problems))
    return pr


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cityinfra")
    ap.add_argument("cmd", choices=["sewer", "water"])
    ap.add_argument("file", nargs="?")
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--epsg", type=int, default=32643)
    ap.add_argument("--no-swmm", action="store_true")
    ap.add_argument("-o", "--output")
    args = ap.parse_args(argv)
    if not args.sample and not args.file:
        ap.error("give a GeoJSON file or --sample")
    pr = _project(args)

    if args.cmd == "sewer":
        rules = RuleContext([RuleSet.load("cpheeo_sewerage_2013.yaml"), RuleSet.load("dda_project_defaults.yaml")])
        net = build_network(pr)
        res = design_network(net, rules)
        swmm_res = None
        if not args.no_swmm and res.pipes:
            try:
                from .engines.swmm.adapter import run_sewer
                swmm_res = run_sewer(net, res, rules.value("swmm_simulation_hours"))
            except EngineUnavailable as e:
                print(f"SWMM pending: {e}", file=sys.stderr)
        text = render(pr.name, res, rules, swmm_res)
    else:
        from .engines.epanet.adapter import run_water
        from .engineering.water.checks import pressure_checks
        res = run_water(pr)
        rules = RuleContext([RuleSet.load("cpheeo_water_supply.yaml")])
        lines = [f"# Water network check – {pr.name}", "", "CALCULATION – NOT CHECKED, NOT APPROVED.", "",
                 f"Engine: EPANET {res.run.engine_version} ({res.run.status})", ""]
        lines += [f"- {c.object_label}: {c.status.value} – {c.message} [{c.parameter.source.cite()}; "
                  f"{c.parameter.verification.value}]" for c in pressure_checks(pr, res, rules)]
        text = "\n".join(lines) + "\n"

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
