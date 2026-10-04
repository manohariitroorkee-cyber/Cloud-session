"""City infrastructure engineering platform – backend core.

Layers (top to bottom):
    api/            HTTP application layer (stage 2)
    engineering/    discipline modules: design rules, checks, quantities
    engines/        adapters to external calculation engines (SWMM, EPANET)
    model/          the common engineering model shared by every discipline
    gis/            geometry helpers (projected-CRS measurement, GeoJSON)
    rules/          configurable, traceable design-rule framework

Nothing in this package is a professionally certified design.  Every
calculation result carries the method, the rule set and the engine that
produced it so that it can be checked and approved by a qualified engineer.
"""

__version__ = "0.1.0"
