"""Application layer for the simple web app.

Turns a drawing sent by the browser (a GeoJSON FeatureCollection plus a few
settings) into a full design check, and returns everything the screen needs:
a one-line headline, traffic-light items in plain language with the technical
detail and suggested fix, the status of every object for colouring the drawing,
calculated values to show when an object is selected, overlays (designed road
centrelines, junction kerbs) and the full report.
"""

from __future__ import annotations

import math
from typing import Any

from ..engines.base import EngineError, EngineUnavailable
from ..gis.geojson_io import export_feature_collection, import_feature_collection
from ..model.core import ObjectKind, Project
from ..rules.framework import CheckResult, RuleContext, RuleSet
from .plain import ADVICE, STATUS_WORD, plain

PROJECT_EPSG = 32643

MODULES = [
    {"id": "sewer", "title": "Sewer lines", "icon": "sewer",
     "what": "Underground pipes that carry wastewater from houses to the treatment plant.",
     "steps": ["Place manholes where pipes meet or turn", "Place the outfall where the sewage leaves the area",
               "Join them with pipes, in the direction the sewage flows", "Tell us how many people live near each manhole",
               "Press Check my design"]},
    {"id": "water", "title": "Water supply", "icon": "water",
     "what": "Pipes that bring drinking water from a tank to every street, with enough pressure.",
     "steps": ["Place the water tank or source", "Place points where water is used",
               "Join them with pipes", "Tell us how many people use water at each point", "Press Check my design"]},
    {"id": "drainage", "title": "Rainwater drains", "icon": "rain",
     "what": "Drains that carry rainwater away so streets do not flood – fitted to existing drains, villages and the outfall.",
     "steps": ["Place the outfall, and draw the existing drains and villages, if any",
               "Place new drain points and join them with new drains, in the direction the water flows",
               "Draw the areas whose rain flows into each drain point",
               "Choose the storm, then press 'Design the new drains for me' (or enter sizes yourself)",
               "Press Check my design"]},
    {"id": "road", "title": "Roads", "icon": "road",
     "what": "The road's path, its bends and its up-and-down slopes, checked for safe driving.",
     "steps": ["Choose the Road tool and click along the road's path", "Double-click to finish the road",
               "Set the speed, road type and the bends' radius", "Press Check my design"]},
    {"id": "junction", "title": "Junctions", "icon": "junction",
     "what": "Where roads meet: corners, visibility and roundabouts.",
     "steps": ["Place a junction", "Choose its type: crossroad, T, or roundabout",
               "Adjust the directions and widths of the roads", "Press Check my design"]},
    {"id": "electrical", "title": "Electricity", "icon": "power",
     "what": "Cables from the substation to transformers and buildings, checked for overload and low voltage.",
     "steps": ["Place the substation, transformers and buildings", "Join them with cables, from supply to building",
               "Choose the cable size and enter each building's load", "Press Check my design"]},
]

_SEVERITY = {"fail": 3, "warning": 2, "not_evaluated": 1, "pass": 0}


def modules() -> list[dict]:
    return MODULES


# ----------------------------------------------------------------- rules

def _rules(module: str, settings: dict | None = None) -> RuleContext:
    sets = {
        "sewer": ["cpheeo_sewerage_2013.yaml", "dda_project_defaults.yaml"],
        "water": ["cpheeo_water_supply.yaml", "project_water_defaults.yaml"],
        "drainage": ["cpheeo_storm_water_2019.yaml", "project_drainage_defaults.yaml"],
        "road": ["irc_geometric_design.yaml", "project_road_defaults.yaml"],
        "junction": ["irc_geometric_design.yaml", "project_road_defaults.yaml", "junction_design.yaml"],
        "electrical": ["electrical_cables_sample.yaml", "project_electrical_defaults.yaml"],
    }[module]
    return RuleContext([RuleSet.load(s) for s in sets])


def options() -> dict[str, Any]:
    """Choice lists the screen offers (taken from the rule sets, never hard-coded in the page)."""
    el = _rules("electrical")
    jn = _rules("junction")
    sw = _rules("sewer")
    dr = _rules("drainage")
    lib = el.value("cable_library")
    return {
        "cables": [{"value": k, "label": v.get("description", k), "grade_kv": v["grade_kv"]} for k, v in lib.items()],
        "cable_library_verified": el.get("cable_library").verification.value == "verified",
        "load_categories": list(el.value("demand_factors")),
        "transformer_ratings_kva": el.value("transformer_ratings_kva"),
        "design_vehicles": list(jn.value("corner_radius_by_vehicle")),
        "sewer_materials": list(sw.value("manning_n")),
        "sewer_diameters_mm": sw.value("commercial_diameters_mm"),
        "drain_linings": list(dr.value("manning_n_drains")),
        "drain_diameters_mm": dr.value("drain_pipe_diameters_mm"),
        "area_types": list(dr.value("return_period_years")),
        "surfaces": list(dr.value("runoff_coefficients")),
        "terrains": list(_rules("road").value("transition_empirical_coeff")),
    }


# -------------------------------------------------------------- examples

def example(module: str) -> dict[str, Any]:
    from .. import samples
    pr = {"sewer": samples.sample_sewer_project, "water": samples.sample_water_project,
          "drainage": samples.sample_drainage_with_existing, "road": samples.sample_road_project,
          "junction": samples.sample_junction_project, "electrical": samples.sample_electrical_project}[module]()
    settings: dict[str, Any] = {}
    if module == "drainage":
        settings = {"return_period": 5, "area_type": "residential", "idf": "example"}
    if module == "water":
        settings = {"litres_per_person_per_day": 150}
    return {"features": export_feature_collection(pr), "settings": settings, "name": pr.name}


# ------------------------------------------------------------------ check

def _project(payload: dict) -> tuple[Project | None, list[str]]:
    fc = payload.get("features") or {}
    pr = Project(payload.get("name") or "My design", PROJECT_EPSG)
    problems = import_feature_collection(pr, fc)
    blocking = [p for p in problems if "cannot be imported" not in p]
    return (None if blocking and not pr.objects else pr), problems


def _item(c: CheckResult) -> dict:
    title, why = plain(c.check, c.status.value)
    return {"object_id": c.object_id, "object": c.object_label, "check": c.check, "status": c.status.value,
            "status_word": STATUS_WORD[c.status.value], "title": title, "why": why, "detail": c.message,
            "fix": ADVICE.get(c.check) if c.status.value in ("fail", "warning") else None,
            "source": c.parameter.source.cite() if c.parameter else None,
            "verification": c.parameter.verification.value if c.parameter else None}


def _finish(module: str, pr: Project, checks: list[CheckResult], errors: list[str], notes: list[str],
            fixes: dict[str, list[str]], values: dict[str, dict], overlays: list[dict], report_md: str,
            rules: RuleContext, extra_items: list[dict] | None = None) -> dict[str, Any]:
    items = [_item(c) for c in checks] + (extra_items or [])
    for it in items:
        f = fixes.get(it["object_id"])
        if f and it["status"] in ("fail", "warning"):
            it["fix"] = " ".join(f) + (f" {it['fix']}" if it.get("fix") else "")
    status: dict[str, str] = {}
    for it in items:
        cur = status.get(it["object_id"])
        if cur is None or _SEVERITY[it["status"]] > _SEVERITY[cur]:
            status[it["object_id"]] = it["status"]
    # objects attached to a check through a group label (e.g. road curves) keep their own id
    items.sort(key=lambda i: (-_SEVERITY[i["status"]], i["object"]))
    n = {k: sum(1 for i in items if i["status"] == k) for k in _SEVERITY}
    if errors:
        headline = "Some information is missing or wrong – see 'Fix these first'."
        tone = "error"
    elif n["fail"]:
        headline = f"{n['fail']} problem{'s' if n['fail'] != 1 else ''} found" + (
            f", and {n['warning']} thing{'s' if n['warning'] != 1 else ''} to check" if n["warning"] else "") + "."
        tone = "fail"
    elif n["warning"]:
        headline = f"No problems, but {n['warning']} thing{'s' if n['warning'] != 1 else ''} to check."
        tone = "warning"
    else:
        headline = "Everything checked is OK." + (f" {n['not_evaluated']} item(s) could not be checked." if n["not_evaluated"] else "")
        tone = "pass" if not n["not_evaluated"] else "warning"
    unverified = len(rules.unverified())
    return {"module": module, "headline": headline, "tone": tone, "counts": n, "items": items,
            "errors": errors, "notes": notes, "object_status": status, "values": values, "overlays": overlays,
            "report_markdown": report_md, "unverified_rules": unverified,
            "disclaimer": "This is a calculation to help an engineer. It is not an approved design."}


def _fixes_by_label(pr: Project, texts: list[str]) -> dict[str, list[str]]:
    """Attach free-text proposals to the object whose name they mention first."""
    by_name = sorted(((o.label, o.id) for o in pr.objects.values() if o.name), key=lambda t: -len(t[0]))
    out: dict[str, list[str]] = {}
    for t in texts:
        best = None
        for name, oid in by_name:
            k = t.find(name)
            if k >= 0 and (best is None or k < best[0]):
                best = (k, oid)
        if best:
            out.setdefault(best[1], []).append(t)
    return out


def check(module: str, payload: dict) -> dict[str, Any]:
    if module not in {m["id"] for m in MODULES}:
        raise ValueError(f"unknown module {module!r}")
    settings = payload.get("settings") or {}
    pr, problems = _project(payload)
    rules = _rules(module, settings)
    if pr is None:
        return _finish(module, Project("empty", PROJECT_EPSG), [], problems, [], {}, {}, [], "", rules)
    try:
        return globals()[f"_check_{module}"](pr, rules, settings, problems)
    except (ValueError, KeyError, EngineError) as e:
        return _finish(module, pr, [], problems + [str(e)], [], {}, {}, [], "", rules)


# ---------------------------------------------------------------- modules

def _engine_note(e: Exception, what: str) -> str:
    return (f"The detailed {what} simulation could not run on this computer ({e.__class__.__name__}). "
            "The basic design check above is complete; install the calculation engines to add the simulation.")


def _check_sewer(pr, rules, settings, problems):
    from ..engineering.sewer.design import design_network
    from ..engineering.sewer.network import build_network
    from ..reports.sewer_report import render
    net = build_network(pr)
    res = design_network(net, rules)
    errors = problems + net.errors + res.errors
    notes, extra, values = list(net.warnings), [], {}
    fixes = {d.pipe.obj.id: d.alternatives for d in res.pipes if d.alternatives}
    for d in res.pipes:
        s = d.state
        values[d.pipe.obj.id] = {"Sewage flow (L/s)": round(d.design_flow * 1000, 2),
                                 "People served": round(d.population),
                                 "Water speed (m/s)": round(s.velocity, 2) if s.capacity_ok else "pipe overfull",
                                 "How full (d/D)": round(s.depth_ratio, 2) if s.capacity_ok else "full",
                                 "Slope": f"1 in {round(1 / d.pipe.slope)}"}
    swmm = None
    if res.pipes and not errors:
        try:
            from ..engines.swmm.adapter import run_sewer
            swmm = run_sewer(net, res, rules.value("swmm_simulation_hours"))
            for oid, n in swmm.nodes.items():
                if n.max_overflow > 1e-6:
                    extra.append({"object_id": oid, "object": pr.objects[oid].label, "check": "simulation_flooding",
                                  "status": "fail", "status_word": "Problem",
                                  "title": "Sewage overflows from this manhole in the simulation",
                                  "why": "The network simulation shows more sewage arriving than the pipes below can take.",
                                  "detail": f"Peak overflow {n.max_overflow*1000:.1f} L/s (EPA SWMM)", "fix": None,
                                  "source": "EPA SWMM simulation", "verification": None})
                elif n.surcharged:
                    extra.append({"object_id": oid, "object": pr.objects[oid].label, "check": "simulation_surcharge",
                                  "status": "warning", "status_word": "Check this",
                                  "title": "Pipes here run completely full in the simulation",
                                  "why": "Water backs up from a pipe further down that is too small or too flat.",
                                  "detail": f"Highest water level {n.max_head:.2f} m (EPA SWMM)", "fix": None,
                                  "source": "EPA SWMM simulation", "verification": None})
        except (EngineUnavailable, OSError) as e:
            notes.append(_engine_note(e, "sewer"))
        except EngineError as e:
            notes.append(f"The sewer simulation reported a problem: {e}")
    return _finish("sewer", pr, res.all_checks(), errors, notes, fixes, values, [],
                   render(pr.name, res, rules, swmm), rules, extra)


def _check_water(pr, rules, settings, problems):
    from ..engineering.water.checks import pressure_checks
    from ..engines.epanet.adapter import run_water, validate
    lpcd = settings.get("litres_per_person_per_day")
    for n in pr.of_kind(ObjectKind.WATER_JUNCTION):
        if n.attr("people") is not None and lpcd:
            n.attributes["demand_lps"] = float(n.attr("people")) * float(lpcd) / 86400
    errors = problems + validate(pr)
    if errors:
        return _finish("water", pr, [], errors, [], {}, {}, [], "", rules)
    try:
        res = run_water(pr)
    except (EngineUnavailable, OSError) as e:
        return _finish("water", pr, [], [], [_engine_note(e, "water network")], {}, {}, [], "", rules)
    checks = pressure_checks(pr, res, rules)
    values = {}
    for oid, r in res.nodes.items():
        values[oid] = {"Lowest pressure (m of water)": round(r.min_pressure, 2), "Water level (m)": round(max(r.head), 2)}
    for oid, r in res.links.items():
        values[oid] = {"Flow (L/s)": round(abs(r.flow[0]), 3), "Water speed (m/s)": round(abs(r.velocity[0]), 2),
                       "Pressure lost (m)": round(r.headloss[0], 3)}
    lines = [f"# Water supply check – {pr.name}", "", "> **CALCULATION – NOT CHECKED, NOT APPROVED.**", "",
             f"Engine: EPANET {res.run.engine_version}", "", "| Point | Result | Detail | Source |", "|---|---|---|---|"]
    lines += [f"| {c.object_label} | {c.status.value} | {c.message} | {c.parameter.source.cite()} ({c.parameter.verification.value}) |"
              for c in checks]
    return _finish("water", pr, checks, [], [], {}, values, [], "\n".join(lines), rules)


def _idf(settings):
    from ..engineering.drainage.rainfall import IDF
    from ..samples import SYNTHETIC_IDF
    spec = settings.get("idf", "example")
    return IDF(SYNTHETIC_IDF if spec in (None, "example") else spec), spec in (None, "example")


def _check_drainage(pr, rules, settings, problems):
    from ..engineering.drainage.network import build_network, design_network
    from ..reports.design_reports import drainage as report
    idf, synthetic = _idf(settings)
    rp = float(settings.get("return_period", 5))
    area = settings.get("area_type", "residential")
    net = build_network(pr, rules)
    res = design_network(net, rules, idf, rp, area)
    errors = problems + res.errors
    notes = list(res.notes)
    if synthetic:
        notes.insert(0, "Rainfall: the EXAMPLE rainfall data was used. It is invented for trying the tool – "
                        "enter real rainfall (IMD / hydrology report) for an actual design.")
    fixes = {d.drain.obj.id: d.alternatives for d in res.drains if d.alternatives}
    values, extra = {}, []
    for d in res.drains:
        s = d.state
        values[d.drain.obj.id] = {"Rain water flow (m³/s)": round(d.flow, 3), "Area draining here (ha)": round(d.area_ha, 2),
                                  "Water speed (m/s)": round(s.velocity, 2) if s.capacity_ok else "overfull",
                                  "Can carry (m³/s)": round(s.q_capacity, 3)}
    overlays = []
    for a in res.existing:
        oid = a.drain.obj.id
        values[oid] = {"Can carry now (m³/s)": round(a.q_usable, 3),
                       **({"Could carry if desilted (m³/s)": round(a.q_desilted, 3)} if a.q_desilted else {}),
                       "Flow today (m³/s)": round(a.q_existing, 3), "Spare capacity today (m³/s)": round(a.residual, 3),
                       "Added by the new areas (m³/s)": round(a.added, 3), "Total after (m³/s)": round(a.q_total, 3),
                       "Share of capacity used": f"{100 * a.utilisation:.0f} %"}
        cs = a.drain.obj.geometry["coordinates"]
        mid = [(cs[0][0] + cs[-1][0]) / 2, (cs[0][1] + cs[-1][1]) / 2]
        overlays.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": mid},
                         "properties": {"kind": "capacity_label",
                                        "text": f"spare today {a.residual:.2f} · after {a.q_usable - a.q_total:.2f} m³/s"}})
    for c in net.catchments:
        values[c.obj.id] = {"Area (ha)": round(c.area_ha, 3), "Runoff share C": round(c.c, 2), "Time to reach drain (min)": round(c.tc_min, 1)}
    swmm = None
    if res.drains and not errors:
        try:
            from ..engines.swmm.drainage import run_drainage
            swmm = run_drainage(net, rules, idf, rp)
            for oid, n in swmm.nodes.items():
                if n.peak_flooding > 1e-6:
                    extra.append({"object_id": oid, "object": pr.objects[oid].label, "check": "simulation_flooding",
                                  "status": "fail", "status_word": "Problem", "title": "Street floods here in the storm simulation",
                                  "why": "The storm simulation shows more water arriving than the drains can take away.",
                                  "detail": f"Peak flooding {n.peak_flooding:.3f} m³/s (EPA SWMM)", "fix": None,
                                  "source": "EPA SWMM simulation", "verification": None})
        except (EngineUnavailable, OSError) as e:
            notes.append(_engine_note(e, "storm"))
        except EngineError as e:
            notes.append(f"The storm simulation needs more information: {e}")
    return _finish("drainage", pr, res.all_checks(), errors, notes, fixes, values, overlays,
                   report(pr.name, res, rules, area, swmm), rules, extra)


_ROAD_ERRORS = [
    (r"Tangent ([^–]+)–([^:]+): .*?overlap by ([\d.]+) m.*?(?:\((.*)\))?\.?",
     "The curve does not fit between {0} and {1}: it is {2} m too long for the straight there. Make the radius or the "
     "easing curve smaller, or move the bend points further apart. ({3})"),
    (r"(bend \d+): deflection .* but no curve given\.", "{0} has no radius. Enter a radius for it."),
    (r"(bend \d+): the alignment doubles back.*", "The road turns back on itself at {0}. Move that bend point."),
]


def _plain_road_error(msg: str) -> str:
    """Road geometry messages in everyday words (bend numbers as shown on the screen)."""
    import re
    m0 = re.sub(r"\bPI(\d+)\b", r"bend \1", msg)
    road = re.match(r"(Road [^:]+: )(.*)", m0)
    prefix, body = (road.group(1), road.group(2)) if road else ("", m0)
    for pat, text in _ROAD_ERRORS:
        m = re.fullmatch(pat, body)
        if m:
            ends = {"start": "the start of the road", "end": "the end of the road"}
            g = [ends.get(x, x) if i < 2 else (x or "") for i, x in enumerate(m.groups())]
            out = text.format(*g).replace(" ()", "")
            return prefix + out.replace("(largest radius", "(Largest radius that fits").replace("if the neighbouring curve is also reduced", "if the next curve is also made smaller").replace("; largest radius at", "; at")
    return m0


def design_drainage(payload: dict) -> dict[str, Any]:
    """Proposed sizes and levels for the new drains (nothing is changed until the user accepts)."""
    from ..engineering.drainage.autodesign import propose
    settings = payload.get("settings") or {}
    pr, problems = _project(payload)
    if pr is None:
        return {"drains": {}, "issues": problems, "notes": []}
    rules = _rules("drainage", settings)
    idf, synthetic = _idf(settings)
    try:
        p = propose(pr, rules, idf, float(settings.get("return_period", 5)))
    except (KeyError, ValueError) as e:
        return {"drains": {}, "issues": problems + [str(e)], "notes": []}
    notes = p.notes + (["The EXAMPLE rainfall was used – enter real rainfall figures for an actual design."] if synthetic else [])
    return {"drains": p.drains, "issues": problems + p.issues, "notes": notes}


def _check_road(pr, rules, settings, problems):
    from ..engineering.roads.design import design_road, level_impacts, terrain
    from ..reports.design_reports import road as report
    roads = pr.of_kind(ObjectKind.ROAD_ALIGNMENT)
    if not roads:
        return _finish("road", pr, [], problems + ["Draw a road first: choose the Road tool and click along its path."],
                       [], {}, {}, [], "", rules)
    checks, errors, notes, overlays, extra, parts, values = [], list(problems), [], [], [], [], {}
    tin = terrain(pr)
    for r in roads:
        try:
            d = design_road(pr, r, rules)
        except ValueError as e:
            errors.append(str(e))
            continue
        for e in d.errors:
            (notes if e.startswith("No terrain points") else errors).append(
                "Ground levels were not given, so cross-sections are not drawn." if e.startswith("No terrain points") else e)
        checks += d.checks
        if d.h.elements:
            overlays.append({"type": "Feature", "geometry": {"type": "LineString",
                             "coordinates": [list(p) for p in d.h.coordinates(2.0)]},
                             "properties": {"kind": "designed_centreline", "road": r.label}})
            for g in d.h.groups:
                mid = d.h.at((g.ch_start + g.ch_end) / 2)
                tag = g.tag.replace("PI", "bend ") if d.h.source != "fit" else f"curve {g.tag.replace('PI', '')}"
                overlays.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [mid[0], mid[1]]},
                                 "properties": {"kind": "curve_label", "text": f"{tag}: R {g.radius:.0f} m"}})
            fr = getattr(d.h, "fit_report", None)
            if fr:
                radii = ", ".join(f"{x:.0f}" for x in fr.get("radii_m", []))
                dev = fr.get("max_deviation_m")
                notes.append(f"Road {r.label} was drawn freehand: {fr.get('curves', 0)} curve(s) were fitted"
                             + (f" (radius {radii} m)" if radii else "")
                             + (f"; the fitted road is up to {dev:.1f} m from your drawing" if dev is not None else "")
                             + ". Check that this is the road you meant (blue line).")
        values[r.id] = {"Length (m)": round(d.h.length, 1), "Curves": len(d.h.groups),
                        "Design speed (km/h)": r.attr("design_speed_kmh")}
        if not d.errors or all(e.startswith("No terrain points") for e in d.errors):
            for imp in level_impacts(pr, d):
                extra.append({"object_id": imp["object_id"], "object": imp["object"], "check": "level_impact",
                              "status": "warning", "status_word": "Check this",
                              "title": f"Cover of this {imp['kind'].replace('_', ' ')} must be {'raised' if imp['difference_m'] > 0 else 'lowered'} "
                                       f"by {abs(imp['difference_m'])*100:.0f} cm to match the new road",
                              "why": "Manhole and chamber covers inside the road must be level with the finished road.",
                              "detail": f"Road surface {imp['road_surface_level']:.3f} m, cover {imp['current_level']:.3f} m at "
                                        f"chainage {imp['chainage']:.1f} m", "fix": None, "source": None, "verification": None})
        parts.append(report(pr.name, d, rules, [], tin))
    errors = [_plain_road_error(e) for e in errors]
    notes = list(dict.fromkeys(notes))
    return _finish("road", pr, checks, errors, notes, {}, values, overlays, "\n\n".join(parts), rules, extra)


def _check_junction(pr, rules, settings, problems):
    from ..engineering.roads.junction import design_junction, junction_features
    from ..reports.design_reports import junction as report
    js = pr.of_kind(ObjectKind.ROAD_JUNCTION)
    if not js:
        return _finish("junction", pr, [], problems + ["Place a junction first."], [], {}, {}, [], "", rules)
    checks, errors, notes, overlays, parts = [], list(problems), [], [], []
    for j in js:
        d = design_junction(pr, j, rules)
        errors += d.errors
        notes += d.notes
        checks += d.checks
        overlays += junction_features(d)
        parts.append(report(pr.name, d, rules))
    return _finish("junction", pr, checks, errors, notes, {}, {}, overlays, "\n\n".join(parts), rules)


def _check_electrical(pr, rules, settings, problems):
    from ..engineering.electrical.network import analyse, build_network, schedules
    from ..reports.design_reports import electrical as report
    net = build_network(pr, rules)
    res = analyse(net, rules)
    errors = problems + res.errors
    notes = []
    if rules.get("cable_library").verification.value != "verified":
        notes.append("Cable data: the SAMPLE cable list was used. Replace it with your cable maker's data sheet "
                     "before relying on current or voltage figures.")
    values = {}
    for cr in res.cables.values():
        values[cr.cable.obj.id] = {"Current (A)": round(cr.current_a, 1), "Cable can carry (A)": round(cr.capacity_a, 1),
                                   "Voltage lost on this cable (%)": round(cr.drop_pct, 2),
                                   "Voltage lost from the source (%)": round(cr.cum_drop_pct, 2)}
    for oid, d in res.demand.items():
        values[oid] = {"Demand (kVA)": round(d.s_kva, 1), "Buildings served": d.loads}
    sched = schedules(net, res, rules) if not res.errors else {}
    return _finish("electrical", pr, res.checks, errors, notes, _fixes_by_label(pr, res.proposals), values, [],
                   report(pr.name, net, res, rules, sched), rules)
