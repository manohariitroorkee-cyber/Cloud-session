"""Small SYNTHETIC networks for tests and demonstrations.

Coordinates are UTM 43N (EPSG:32643) values in the general Narela area,
chosen only to be realistic in magnitude.  Levels, populations and demands
are invented.  Nothing here represents a real scheme.
"""

from __future__ import annotations

from .engineering.sewer.network import connect_pipe
from .model.core import EngineeringObject, ObjectKind, Project, RelationType

E0, N0 = 704_000.0, 3_193_000.0


def _pt(x: float, y: float) -> dict:
    return {"type": "Point", "coordinates": [E0 + x, N0 + y]}


def _ln(*pts: tuple[float, float]) -> dict:
    return {"type": "LineString", "coordinates": [[E0 + x, N0 + y] for x, y in pts]}


def sample_sewer_project() -> Project:
    """Branched sewer: MH1→MH2→MH3, MH4→MH3, MH3→MH5→MH6→OUT1.

    Pipe S2 is laid deliberately flat (fails self-cleansing velocity) and
    pipe S6 is deliberately undersized (fails d/D), so checks and
    alternatives can be exercised.
    """
    pr = Project("Synthetic sector sewer", crs_epsg=32643)
    mh = {}
    spec = {
        # name: (x, y, ground, population, present_population)
        "MH1": (0, 0, 216.40, 1800, 900),
        "MH2": (0, -28, 216.25, 1500, 800),
        "MH3": (0, -56, 216.10, 1200, 600),
        "MH4": (28, -56, 216.30, 2500, 1200),
        "MH5": (0, -84, 215.95, 3000, 1500),
        "MH6": (0, -112, 215.80, 2500, 1000),
    }
    for name, (x, y, gl, pop, pres) in spec.items():
        mh[name] = pr.add(EngineeringObject(ObjectKind.MANHOLE, _pt(x, y), name=name, attributes={
            "ground_level": gl, "population": pop, "present_population": pres}))
    mh["OUT1"] = pr.add(EngineeringObject(ObjectKind.SEWER_OUTFALL, _pt(0, -140), name="OUT1",
                                          attributes={"ground_level": 215.60, "invert_level": 212.30}))
    pipes = [
        # name, from, to, dia mm, material, us inv, ds inv, vertices
        ("S1", "MH1", "MH2", 200, "upvc", 215.000, 214.860, [(0, 0), (0, -28)]),
        ("S2", "MH2", "MH3", 200, "upvc", 214.850, 214.830, [(0, -28), (0, -56)]),   # flat
        ("S3", "MH4", "MH3", 200, "upvc", 215.100, 214.900, [(28, -56), (0, -56)]),
        ("S4", "MH3", "MH5", 250, "upvc", 214.800, 214.630, [(0, -56), (0, -84)]),
        ("S5", "MH5", "MH6", 300, "rcc", 214.600, 214.440, [(0, -84), (0, -112)]),
        ("S6", "MH6", "OUT1", 150, "upvc", 214.420, 214.300, [(0, -112), (0, -140)]),  # undersized
    ]
    for name, a, b, dia, mat, ui, di, pts in pipes:
        p = pr.add(EngineeringObject(ObjectKind.SEWER_PIPE, _ln(*pts), name=name, attributes={
            "diameter_mm": dia, "material": mat, "us_invert": ui, "ds_invert": di}))
        connect_pipe(pr, p, mh[a], mh[b])
    return pr


def sample_water_project() -> Project:
    """Looped distribution network fed by gravity from a service reservoir."""
    pr = Project("Synthetic sector water supply", crs_epsg=32643)
    n = {}
    n["ESR"] = pr.add(EngineeringObject(ObjectKind.RESERVOIR, _pt(-150, 0), name="ESR",
                                        attributes={"head": 246.0}))
    jn = {"J1": (0, 0, 216.0, 3.0), "J2": (300, 0, 215.0, 4.0), "J3": (300, -300, 214.5, 3.5),
          "J4": (0, -300, 215.5, 4.0), "J5": (600, -300, 214.0, 2.5)}
    for name, (x, y, el, q) in jn.items():
        n[name] = pr.add(EngineeringObject(ObjectKind.WATER_JUNCTION, _pt(x, y), name=name,
                                           attributes={"elevation": el, "demand_lps": q}))
    pipes = [("W1", "ESR", "J1", 250), ("W2", "J1", "J2", 200), ("W3", "J2", "J3", 150),
             ("W4", "J1", "J4", 150), ("W5", "J4", "J3", 100), ("W6", "J3", "J5", 100)]
    for name, a, b, dia in pipes:
        ga, gb = n[a].geometry["coordinates"], n[b].geometry["coordinates"]
        p = pr.add(EngineeringObject(ObjectKind.WATER_PIPE, {"type": "LineString", "coordinates": [ga, gb]},
                                     name=name, attributes={"diameter_mm": dia, "roughness": 130}))
        pr.relate(p, n[a], RelationType.UPSTREAM_NODE)
        pr.relate(p, n[b], RelationType.DOWNSTREAM_NODE)
    return pr


# SYNTHETIC IDF – invented coefficients of plausible magnitude, NOT for design.
SYNTHETIC_IDF = {
    "form": "power",
    "source": "SYNTHETIC test IDF (invented coefficients) – replace with IMD/project hydrology data",
    "return_periods": {"2": {"a": 1100.0, "b": 15.0, "n": 0.8},
                       "5": {"a": 1500.0, "b": 15.0, "n": 0.8},
                       "10": {"a": 1800.0, "b": 15.0, "n": 0.8}},
}


def _poly(*pts: tuple[float, float]) -> dict:
    ring = [[E0 + x, N0 + y] for x, y in pts]
    return {"type": "Polygon", "coordinates": [ring + [ring[0]]]}


def sample_drainage_project() -> Project:
    """Three catchments → two pipes → an open trapezoidal drain → outfall.

    Pipe D2 is deliberately undersized so failure, alternatives and SWMM
    flooding can be exercised.
    """
    pr = Project("Synthetic sector storm drainage", crs_epsg=32643)
    nd = {}
    for name, (x, y, gl) in {"DN1": (0, 0, 216.5), "DN2": (120, 0, 216.2), "DN3": (240, 0, 215.9)}.items():
        nd[name] = pr.add(EngineeringObject(ObjectKind.DRAIN_NODE, _pt(x, y), name=name, attributes={"ground_level": gl}))
    nd["OF1"] = pr.add(EngineeringObject(ObjectKind.DRAIN_OUTFALL, _pt(400, 0), name="OF1",
                                         attributes={"ground_level": 215.2, "invert_level": 213.20}))
    cts = [("C1", _poly((-100, 10), (110, 10), (110, 160), (-100, 160)), "DN1",
            {"paved": 0.4, "roof": 0.35, "lawn_clay": 0.25}, 55),
           ("C2", _poly((110, 10), (230, 10), (230, 160), (110, 160)), "DN2",
            {"paved": 0.5, "roof": 0.3, "lawn_clay": 0.2}, 60),
           ("C3", _poly((230, -150), (390, -150), (390, -10), (230, -10)), "DN3",
            {"paved": 0.3, "roof": 0.3, "open_ground": 0.4}, 45)]
    for name, geom, node, surf, imp in cts:
        c = pr.add(EngineeringObject(ObjectKind.CATCHMENT, geom, name=name, attributes={
            "surfaces": surf, "impervious_pct": imp, "flow_length_m": 120, "overland_slope": 0.01}))
        pr.relate(c, nd[node], RelationType.DRAINS_TO)
    drains = [("D1", "DN1", "DN2", {"shape": "circular", "diameter_mm": 600, "lining": "rcc",
                                    "us_invert": 215.00, "ds_invert": 214.70}),
              ("D2", "DN2", "DN3", {"shape": "circular", "diameter_mm": 600, "lining": "rcc",     # undersized
                                    "us_invert": 214.65, "ds_invert": 214.35}),
              ("D3", "DN3", "OF1", {"shape": "trapezoidal", "width_m": 1.0, "height_m": 1.0, "side_slope": 1.0,
                                    "lining": "rcc", "us_invert": 214.20, "ds_invert": 213.40})]
    for name, a, b, attrs in drains:
        ga, gb = nd[a].geometry["coordinates"], nd[b].geometry["coordinates"]
        d = pr.add(EngineeringObject(ObjectKind.STORM_DRAIN, {"type": "LineString", "coordinates": [ga, gb]},
                                     name=name, attributes=attrs))
        pr.relate(d, nd[a], RelationType.UPSTREAM_NODE)
        pr.relate(d, nd[b], RelationType.DOWNSTREAM_NODE)
    return pr


SAMPLE_ROAD_TEMPLATE = {
    "median": {"width": 1.2, "raised_m": 0.15},
    "strips": [
        {"type": "carriageway", "width": 7.0, "crossfall_pct": -2.5},
        {"type": "cycle_track", "width": 2.0, "crossfall_pct": -2.0, "step_m": 0.15},
        {"type": "footpath", "width": 2.0, "crossfall_pct": 2.0, "step_m": 0.10},
        {"type": "drain", "width": 1.0, "crossfall_pct": 0.0},
        {"type": "utility_corridor", "width": 2.0, "crossfall_pct": 2.0},
        {"type": "verge", "width": 1.0, "crossfall_pct": 4.0},
    ],
}


def sample_road_project() -> Project:
    """A 45 m ROW road with two curves over a synthetic gently undulating TIN,
    and two manholes inside the corridor (one at a stale ground level)."""
    import math as _m
    pr = Project("Synthetic sector road", crs_epsg=32643)
    for i in range(-6, 30):
        for j in range(-4, 13):
            x, y = i * 20.0, j * 20.0
            z = 216.0 - 0.002 * x + 0.3 * _m.sin(x / 60) + 0.1 * _m.cos(y / 40)
            pr.add(EngineeringObject(ObjectKind.TERRAIN_POINT, {"type": "Point", "coordinates": [E0 + x, N0 + y, z]}))
    from .engineering.roads.horizontal import build as _build
    pis = [(-50, 30), (150, 30), (300, 120), (500, 120)]
    curves = {"1": [200, 60], "2": [200, 60]}
    length = _build([(E0 + x, N0 + y) for x, y in pis], {int(k): tuple(v) for k, v in curves.items()}).length
    road = pr.add(EngineeringObject(ObjectKind.ROAD_ALIGNMENT, _ln(*pis), name="R1", attributes={
        "design_speed_kmh": 50, "terrain": "plain", "kerbed": True,
        "curves": curves,
        "profile": [[0, 216.40, 0], [200, 215.60, 80], [round(length, 3), 216.90, 0]],
        "template": SAMPLE_ROAD_TEMPLATE, "section_interval_m": 20}))
    pr.add(EngineeringObject(ObjectKind.MANHOLE, _pt(60, 34), name="MH-R1", attributes={"ground_level": 215.70}))
    pr.add(EngineeringObject(ObjectKind.MANHOLE, _pt(100, 26), name="MH-R2", attributes={"ground_level": 216.122}))
    return pr


def sample_electrical_project() -> Project:
    """11 kV substation → two transformers → feeder pillars → loads.

    Deliberate defects so that checks and proposals can be exercised:
    TX2 (250 kVA) is overloaded, and cable L5 is too small and too long
    (current and voltage drop both fail).
    """
    pr = Project("Synthetic sector electrical", crs_epsg=32643)
    n = {}

    def node(kind, name, x, y, **attrs):
        n[name] = pr.add(EngineeringObject(kind, _pt(x, y), name=name, attributes=attrs))

    node(ObjectKind.SUBSTATION, "SS1", 0, 0, voltage_kv=11)
    node(ObjectKind.TRANSFORMER, "TX1", 400, 0, rating_kva=630, hv_kv=11, lv_v=433)
    node(ObjectKind.TRANSFORMER, "TX2", 0, 300, rating_kva=250, hv_kv=11, lv_v=433)
    node(ObjectKind.FEEDER_PILLAR, "FP1", 550, 0)
    node(ObjectKind.FEEDER_PILLAR, "FP2", 0, 450)
    for i, (x, y, kw) in enumerate([(650, 60, 150), (650, -60, 150), (550, 120, 120)], 1):
        node(ObjectKind.ELECTRICAL_LOAD, f"LD{i}", x, y, connected_load_kw=kw, category="residential", power_factor=0.9)
    node(ObjectKind.ELECTRICAL_LOAD, "SL1", 470, -40, connected_load_kw=4, category="streetlight", power_factor=0.95, phases=1)
    node(ObjectKind.ELECTRICAL_LOAD, "LD4", 120, 450, connected_load_kw=300, category="commercial", power_factor=0.9)
    node(ObjectKind.ELECTRICAL_LOAD, "LD5", 0, 800, connected_load_kw=180, category="residential", power_factor=0.9)

    cables = [("H1", "SS1", "TX1", "HT-AL-3C-185"), ("H2", "SS1", "TX2", "HT-AL-3C-185"),
              ("L1", "TX1", "FP1", "LT-AL-3.5C-300"), ("L2", "FP1", "LD1", "LT-AL-3.5C-95"),
              ("L3", "FP1", "LD2", "LT-AL-3.5C-95"), ("L4", "FP1", "LD3", "LT-AL-3.5C-95"),
              ("S1", "TX1", "SL1", "LT-AL-2C-16"),
              ("L6", "TX2", "FP2", "LT-AL-3.5C-300"), ("L7", "FP2", "LD4", "LT-AL-3.5C-185"),
              ("L5", "FP2", "LD5", "LT-AL-3.5C-70")]          # too small and too long
    for name, a, b, typ in cables:
        ga, gb = n[a].geometry["coordinates"], n[b].geometry["coordinates"]
        c = pr.add(EngineeringObject(ObjectKind.ELECTRICAL_CABLE, {"type": "LineString", "coordinates": [ga, gb]},
                                     name=name, attributes={"cable_type": typ, "runs": 2 if name in ("L1", "L6", "L7") else 1}))
        pr.relate(c, n[a], RelationType.UPSTREAM_NODE)
        pr.relate(c, n[b], RelationType.DOWNSTREAM_NODE)
    return pr


def sample_junction_project() -> Project:
    """A four-arm cross with a skewed minor arm and a plot inside one sight
    triangle; a T-junction built from two road alignments; a four-arm roundabout."""
    pr = Project("Synthetic sector junctions", crs_epsg=32643)
    # 1. cross intersection, explicit arms
    pr.add(EngineeringObject(ObjectKind.ROAD_JUNCTION, _pt(0, 0), name="J-CROSS", attributes={
        "type": "intersection", "control": "uncontrolled", "design_vehicle": "bus",
        "arms": [{"name": "N", "bearing_deg": 0, "width_left": 7.6, "width_right": 7.6, "speed_kmh": 40, "priority": "major"},
                 {"name": "E", "bearing_deg": 95, "width_left": 3.5, "width_right": 3.5, "speed_kmh": 30},
                 {"name": "S", "bearing_deg": 180, "width_left": 7.6, "width_right": 7.6, "speed_kmh": 40, "priority": "major"},
                 {"name": "W", "bearing_deg": 310, "width_left": 3.5, "width_right": 3.5, "speed_kmh": 30}],   # 50° skew
        "corner": {"type": "three_centred", "ratio": 2, "end_deflection_deg": 15}}))
    pr.add(EngineeringObject(ObjectKind.PLOT, _poly((14, 14), (40, 14), (40, 40), (14, 40)), name="PLOT-NE"))
    # 2. T-junction from road alignments (two straight roads meeting at (600, 0))
    tpl = {"strips": [{"type": "carriageway", "width": 3.5, "crossfall_pct": -2.5},
                      {"type": "footpath", "width": 1.8, "crossfall_pct": 2.0, "step_m": 0.15}]}
    main = pr.add(EngineeringObject(ObjectKind.ROAD_ALIGNMENT, _ln((400, 0), (800, 0)), name="MAIN", attributes={
        "design_speed_kmh": 40, "terrain": "plain", "priority": "major", "curves": {}, "template": tpl,
        "profile": [[0, 216.0, 0], ["end", 215.6, 0]]}))
    side = pr.add(EngineeringObject(ObjectKind.ROAD_ALIGNMENT, _ln((600, 0), (600, 250)), name="SIDE", attributes={
        "design_speed_kmh": 30, "terrain": "plain", "curves": {}, "template": tpl, "profile": [[0, 216.0, 0], ["end", 216.5, 0]]}))
    _ = (main, side)
    pr.add(EngineeringObject(ObjectKind.ROAD_JUNCTION, _pt(600, 0), name="J-T", attributes={
        "type": "intersection", "control": "priority", "design_vehicle": "bus",
        "arms": [{"road": "SIDE"}, {"name": "MAIN-E", "bearing_deg": 90, "width_left": 3.5, "width_right": 3.5,
                                    "speed_kmh": 40, "priority": "major"},
                 {"name": "MAIN-W", "bearing_deg": 270, "width_left": 3.5, "width_right": 3.5, "speed_kmh": 40,
                  "priority": "major"}]}))
    # 3. roundabout
    pr.add(EngineeringObject(ObjectKind.ROAD_JUNCTION, _pt(0, -600), name="J-RB", attributes={
        "type": "roundabout",
        "arms": [{"name": n, "bearing_deg": b, "width_left": 7.0, "width_right": 7.0, "speed_kmh": 40}
                 for n, b in (("N", 0), ("E", 90), ("S", 180), ("W", 270))],
        "roundabout": {"central_island_radius_m": 27, "circulatory_width_m": 10, "entry_radius_m": 20,
                       "exit_radius_m": 25, "setting": "urban",
                       "flows_pcu_h": {"N-E": {"total": 2200, "weaving": 1100}}}}))
    return pr
