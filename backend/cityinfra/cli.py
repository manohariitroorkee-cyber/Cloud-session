"""Command-line entry points (until the HTTP API exists).

    python -m cityinfra.cli sewer  <network.geojson> [--epsg 32643] [--no-swmm] [-o report.md]
    python -m cityinfra.cli sewer  --sample            # synthetic demonstration network
    python -m cityinfra.cli water  --sample
    python -m cityinfra.cli drainage --sample [--idf idf.json] [--return-period 5] [--area-type residential]
    python -m cityinfra.cli road   --sample
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
        from .samples import sample_drainage_project, sample_electrical_project, sample_road_project
        return {"sewer": sample_sewer_project, "water": sample_water_project, "drainage": sample_drainage_project,
                "road": sample_road_project, "electrical": sample_electrical_project}[args.cmd]()
    pr = Project(Path(args.file).stem, args.epsg)
    problems = import_feature_collection(pr, json.loads(Path(args.file).read_text()))
    if problems:
        sys.exit("Import problems:\n" + "\n".join(problems))
    return pr


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="cityinfra",
        description="Run a design check on a network and write a report. Every report is a calculation for "
                    "review – not a certified or approved design.",
        epilog="Examples:\n"
               "  cityinfra sewer --sample -o sewer.md        try the sewer check on the built-in example\n"
               "  cityinfra sewer mynet.geojson -o sewer.md   check your own network (GeoJSON, metres)\n"
               "  cityinfra drainage mynet.geojson --idf idf.json --return-period 5 --area-type residential\n"
               "  cityinfra road --sample                     alignment and curve checks for the example road\n"
               "  cityinfra electrical mynet.geojson --cables cables.yaml -o electrical.md",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["sewer", "water", "drainage", "road", "electrical"], metavar="CHECK",
                    help="what to check: sewer (design sheet + SWMM), water (EPANET pressures), "
                         "drainage (Rational method + SWMM storm), road (alignment and curves), "
                         "electrical (demand, transformer loading, cable current and voltage drop)")
    ap.add_argument("--cables", metavar="CABLES.yaml",
                    help="electrical only: cable library from manufacturers' datasheets "
                         "(default: the built-in SAMPLE library, illustrative values only)")
    ap.add_argument("file", nargs="?", metavar="NETWORK.geojson",
                    help="your network as a GeoJSON FeatureCollection in the project's projected CRS (metres)")
    ap.add_argument("--sample", action="store_true",
                    help="use the built-in synthetic example instead of a file (for trying the tool)")
    ap.add_argument("--epsg", type=int, default=32643, metavar="CODE",
                    help="projected coordinate system of the file (default 32643 = UTM 43N, Delhi)")
    ap.add_argument("--no-swmm", action="store_true",
                    help="skip the SWMM network simulation; report the design sheet only")
    ap.add_argument("--idf", metavar="IDF.json",
                    help="drainage only: rainfall intensity-duration-frequency data from IMD / hydrology report")
    ap.add_argument("--return-period", type=float, default=5, metavar="YEARS",
                    help="drainage only: design storm return period in years (default 5)")
    ap.add_argument("--area-type", default="residential", metavar="TYPE",
                    help="drainage only: residential, commercial, arterial_road, underpass or "
                         "critical_infrastructure – used to check the return period (default residential)")
    ap.add_argument("-o", "--output", metavar="REPORT.md",
                    help="write the report to this file instead of the screen")
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
    elif args.cmd == "drainage":
        from .engineering.drainage.network import build_network as build_dn, design_network as design_dn
        from .engineering.drainage.rainfall import IDF
        from .reports.design_reports import drainage as drainage_report
        if args.idf:
            idf = IDF(json.loads(Path(args.idf).read_text()))
        elif args.sample:
            from .samples import SYNTHETIC_IDF
            idf = IDF(SYNTHETIC_IDF)
        else:
            sys.exit("Drainage design needs --idf (project IDF from IMD / hydrology report).")
        rules = RuleContext([RuleSet.load("cpheeo_storm_water_2019.yaml"), RuleSet.load("project_drainage_defaults.yaml")])
        net = build_dn(pr, rules)
        res = design_dn(net, rules, idf, args.return_period, args.area_type)
        swmm_res = None
        if not args.no_swmm and res.drains:
            try:
                from .engines.swmm.drainage import run_drainage
                swmm_res = run_drainage(net, rules, idf, args.return_period)
            except EngineUnavailable as e:
                print(f"SWMM pending: {e}", file=sys.stderr)
        text = drainage_report(pr.name, res, rules, args.area_type, swmm_res)
    elif args.cmd == "road":
        from .engineering.roads.design import design_road, level_impacts, terrain
        from .model.core import ObjectKind
        from .reports.design_reports import road as road_report
        rules = RuleContext([RuleSet.load("irc_geometric_design.yaml"), RuleSet.load("project_road_defaults.yaml")])
        tin = terrain(pr)
        parts = []
        for r in pr.of_kind(ObjectKind.ROAD_ALIGNMENT):
            d = design_road(pr, r, rules)
            parts.append(road_report(pr.name, d, rules, level_impacts(pr, d) if not d.errors else [], tin))
        text = "\n\n".join(parts) or "No road alignments found."
    elif args.cmd == "electrical":
        from .engineering.electrical.network import analyse, build_network as build_el, schedules
        from .reports.design_reports import electrical as electrical_report
        cables = RuleSet.load(args.cables) if args.cables else RuleSet.load("electrical_cables_sample.yaml")
        rules = RuleContext([cables, RuleSet.load("project_electrical_defaults.yaml")])
        net = build_el(pr, rules)
        res = analyse(net, rules)
        text = electrical_report(pr.name, net, res, rules, schedules(net, res, rules) if not res.errors else {})
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
