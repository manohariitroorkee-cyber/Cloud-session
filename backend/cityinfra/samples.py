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
