"""Sewer network assembled from the common engineering model.

Objects used
------------
MANHOLE        Point.  attributes: ground_level (m), population (persons whose
               sewage enters at this manhole), present_population (optional),
               extra_flow_lps (optional institutional/commercial flow, L/s)
SEWER_OUTFALL  Point.  attributes: ground_level, invert_level
SEWER_PIPE     LineString drawn upstream → downstream.  attributes:
               diameter_mm, material, us_invert (m), ds_invert (m)
               relationships: UPSTREAM_NODE → manhole, DOWNSTREAM_NODE → manhole/outfall

The network must be a tree draining to one or more outfalls (no loops,
no bifurcations) – the normal form of a gravity sanitary sewer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...gis.geometry import distance, endpoints, line_length, point_coord
from ...model.core import EngineeringObject, ObjectKind, Project, RelationType

NODE_KINDS = (ObjectKind.MANHOLE, ObjectKind.SEWER_OUTFALL)
ENDPOINT_TOLERANCE_M = 0.5


@dataclass
class SewerPipe:
    obj: EngineeringObject
    us: EngineeringObject
    ds: EngineeringObject
    length: float
    diameter: float      # m
    material: str
    us_invert: float
    ds_invert: float

    @property
    def slope(self) -> float:
        return (self.us_invert - self.ds_invert) / self.length


@dataclass
class SewerNetwork:
    project: Project
    nodes: dict[str, EngineeringObject]
    pipes: dict[str, SewerPipe]
    order: list[str]                                     # pipe ids, upstream first
    errors: list[str] = field(default_factory=list)      # topology/geometry errors (block calculation)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def incoming(self, node_id: str) -> list[SewerPipe]:
        return [p for p in self.pipes.values() if p.ds.id == node_id]

    def outgoing(self, node_id: str) -> list[SewerPipe]:
        return [p for p in self.pipes.values() if p.us.id == node_id]


def connect_pipe(project: Project, pipe: EngineeringObject,
                 us: EngineeringObject, ds: EngineeringObject) -> None:
    project.relate(pipe, us, RelationType.UPSTREAM_NODE)
    project.relate(pipe, ds, RelationType.DOWNSTREAM_NODE)


def build_network(project: Project) -> SewerNetwork:
    nodes = {o.id: o for o in project.of_kind(*NODE_KINDS)}
    errors: list[str] = []
    warnings: list[str] = []
    pipes: dict[str, SewerPipe] = {}

    for obj in project.of_kind(ObjectKind.SEWER_PIPE):
        us = project.related(obj, RelationType.UPSTREAM_NODE)
        ds = project.related(obj, RelationType.DOWNSTREAM_NODE)
        if len(us) != 1 or len(ds) != 1:
            errors.append(f"Pipe {obj.label}: needs exactly one upstream and one downstream manhole "
                          f"(has {len(us)} and {len(ds)}).")
            continue
        us, ds = us[0], ds[0]
        if us.id not in nodes or ds.id not in nodes:
            errors.append(f"Pipe {obj.label}: connected to an object that is not a manhole/outfall.")
            continue
        if us.kind == ObjectKind.SEWER_OUTFALL:
            errors.append(f"Pipe {obj.label}: an outfall cannot be the upstream end.")
        missing = [k for k in ("diameter_mm", "us_invert", "ds_invert") if obj.attr(k) is None]
        if missing:
            errors.append(f"Pipe {obj.label}: missing {', '.join(missing)}.")
            continue
        # geometry must start at the upstream manhole and end at the downstream one
        a, b = endpoints(obj.geometry)
        for end, node, which in ((a, us, "start"), (b, ds, "end")):
            gap = distance(end, point_coord(node.geometry))
            if gap > ENDPOINT_TOLERANCE_M:
                errors.append(f"Pipe {obj.label}: {which} vertex is {gap:.2f} m from manhole {node.label} "
                              f"(tolerance {ENDPOINT_TOLERANCE_M} m). Draw pipes upstream → downstream and snap to manholes.")
        length = line_length(obj.geometry)
        if length <= 0:
            errors.append(f"Pipe {obj.label}: zero length.")
            continue
        p = SewerPipe(obj, us, ds, length, obj.attr("diameter_mm") / 1000.0,
                      str(obj.attr("material", "")).lower(), float(obj.attr("us_invert")),
                      float(obj.attr("ds_invert")))
        if p.slope <= 0:
            errors.append(f"Pipe {obj.label}: adverse or flat slope ({p.us_invert:.3f} → {p.ds_invert:.3f} m).")
        pipes[obj.id] = p

    for nid, n in nodes.items():
        if n.attr("ground_level") is None:
            errors.append(f"{n.label}: ground_level missing.")
        out = [p for p in pipes.values() if p.us.id == nid]
        inc = [p for p in pipes.values() if p.ds.id == nid]
        if n.kind == ObjectKind.MANHOLE and len(out) > 1:
            errors.append(f"Manhole {n.label}: {len(out)} outgoing pipes; a gravity sewer must not bifurcate.")
        if n.kind == ObjectKind.MANHOLE and not out:
            errors.append(f"Manhole {n.label}: no outgoing pipe – every manhole must drain to an outfall.")
        if n.kind == ObjectKind.SEWER_OUTFALL and out:
            errors.append(f"Outfall {n.label}: has an outgoing pipe.")
        if not out and not inc:
            warnings.append(f"{n.label}: not connected to any pipe.")

    order = _topological_order(pipes, errors)
    return SewerNetwork(project, nodes, pipes, order, errors, warnings)


def _topological_order(pipes: dict[str, SewerPipe], errors: list[str]) -> list[str]:
    """Kahn's algorithm on pipes: a pipe follows every pipe entering its upstream node."""
    by_us: dict[str, list[str]] = {}
    indeg: dict[str, int] = {}
    for pid, p in pipes.items():
        by_us.setdefault(p.us.id, []).append(pid)
        indeg[pid] = sum(1 for q in pipes.values() if q.ds.id == p.us.id)
    ready = sorted((pid for pid, d in indeg.items() if d == 0), key=lambda i: pipes[i].obj.label)
    order: list[str] = []
    while ready:
        pid = ready.pop(0)
        order.append(pid)
        for nxt in by_us.get(pipes[pid].ds.id, []):
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                ready.append(nxt)
    if len(order) != len(pipes):
        loop = sorted(pipes[p].obj.label for p in pipes if p not in order)
        errors.append(f"Loop in sewer network involving pipes: {', '.join(loop)}.")
    return order
