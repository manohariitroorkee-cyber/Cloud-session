"""The common engineering model.

Every engineering object – a road, a manhole, a cable – is an
:class:`EngineeringObject`: one record with a unique ID, a GeoJSON geometry
in the project's projected CRS, levels where applicable, discipline-specific
design attributes, a status, and typed relationships to other objects.

This mirrors the PostGIS schema in ``database/migrations`` (table
``eng_object`` and ``eng_relationship``).  The in-memory form is what the
engineering modules and engine adapters work on; persistence maps it
one-to-one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


class Discipline(str, Enum):
    COMMON = "common"
    ROADS = "roads"
    SEWER = "sewer"
    DRAINAGE = "drainage"
    WATER = "water"
    ELECTRICAL = "electrical"
    PNG = "png"
    TELECOM = "telecom"


class ObjectKind(str, Enum):
    """Object types of the common model, with their discipline and geometry."""

    # common / planning inputs (imported, not designed here)
    DEVELOPMENT_BOUNDARY = "development_boundary"
    PLOT = "plot"
    PARCEL = "parcel"
    TERRAIN_POINT = "terrain_point"
    # roads
    ROAD = "road"
    ROAD_ALIGNMENT = "road_alignment"
    ROAD_JUNCTION = "road_junction"
    # sewer
    MANHOLE = "manhole"
    SEWER_PIPE = "sewer_pipe"
    SEWER_OUTFALL = "sewer_outfall"
    # storm-water drainage
    CATCHMENT = "catchment"
    DRAIN_NODE = "drain_node"
    STORM_DRAIN = "storm_drain"
    DRAIN_OUTFALL = "drain_outfall"
    # water supply
    WATER_JUNCTION = "water_junction"
    WATER_PIPE = "water_pipe"
    RESERVOIR = "reservoir"
    TANK = "tank"
    PUMP = "pump"
    VALVE = "valve"
    # electrical
    SUBSTATION = "substation"
    TRANSFORMER = "transformer"
    ELECTRICAL_CABLE = "electrical_cable"
    POLE = "pole"
    FEEDER_PILLAR = "feeder_pillar"
    ELECTRICAL_LOAD = "electrical_load"
    # gas
    PNG_SOURCE = "png_source"
    PNG_REGULATOR = "png_regulator"
    PNG_NODE = "png_node"
    PNG_PIPELINE = "png_pipeline"
    # telecom / fibre
    TELECOM_CHAMBER = "telecom_chamber"
    TELECOM_DUCT = "telecom_duct"
    FIBRE_CABLE = "fibre_cable"
    NETWORK_CABINET = "network_cabinet"
    # cross-discipline
    UTILITY_CROSSING = "utility_crossing"


# kind -> (discipline, allowed GeoJSON geometry types)
_POINT = ("Point",)
_LINE = ("LineString",)
_AREA = ("Polygon", "MultiPolygon")
KIND_SPEC: dict[ObjectKind, tuple[Discipline, tuple[str, ...]]] = {
    ObjectKind.DEVELOPMENT_BOUNDARY: (Discipline.COMMON, _AREA),
    ObjectKind.PLOT: (Discipline.COMMON, _AREA),
    ObjectKind.PARCEL: (Discipline.COMMON, _AREA),
    ObjectKind.TERRAIN_POINT: (Discipline.COMMON, _POINT),
    ObjectKind.ROAD: (Discipline.ROADS, _AREA + _LINE),
    ObjectKind.ROAD_ALIGNMENT: (Discipline.ROADS, _LINE),
    ObjectKind.ROAD_JUNCTION: (Discipline.ROADS, _POINT + _AREA),
    ObjectKind.MANHOLE: (Discipline.SEWER, _POINT),
    ObjectKind.SEWER_PIPE: (Discipline.SEWER, _LINE),
    ObjectKind.SEWER_OUTFALL: (Discipline.SEWER, _POINT),
    ObjectKind.CATCHMENT: (Discipline.DRAINAGE, _AREA),
    ObjectKind.DRAIN_NODE: (Discipline.DRAINAGE, _POINT),
    ObjectKind.STORM_DRAIN: (Discipline.DRAINAGE, _LINE),
    ObjectKind.DRAIN_OUTFALL: (Discipline.DRAINAGE, _POINT),
    ObjectKind.WATER_JUNCTION: (Discipline.WATER, _POINT),
    ObjectKind.WATER_PIPE: (Discipline.WATER, _LINE),
    ObjectKind.RESERVOIR: (Discipline.WATER, _POINT),
    ObjectKind.TANK: (Discipline.WATER, _POINT),
    ObjectKind.PUMP: (Discipline.WATER, _LINE),
    ObjectKind.VALVE: (Discipline.WATER, _LINE),
    ObjectKind.SUBSTATION: (Discipline.ELECTRICAL, _POINT + _AREA),
    ObjectKind.TRANSFORMER: (Discipline.ELECTRICAL, _POINT),
    ObjectKind.ELECTRICAL_CABLE: (Discipline.ELECTRICAL, _LINE),
    ObjectKind.POLE: (Discipline.ELECTRICAL, _POINT),
    ObjectKind.FEEDER_PILLAR: (Discipline.ELECTRICAL, _POINT),
    ObjectKind.ELECTRICAL_LOAD: (Discipline.ELECTRICAL, _POINT),
    ObjectKind.PNG_SOURCE: (Discipline.PNG, _POINT),
    ObjectKind.PNG_REGULATOR: (Discipline.PNG, _POINT),
    ObjectKind.PNG_NODE: (Discipline.PNG, _POINT),
    ObjectKind.PNG_PIPELINE: (Discipline.PNG, _LINE),
    ObjectKind.TELECOM_CHAMBER: (Discipline.TELECOM, _POINT),
    ObjectKind.TELECOM_DUCT: (Discipline.TELECOM, _LINE),
    ObjectKind.FIBRE_CABLE: (Discipline.TELECOM, _LINE),
    ObjectKind.NETWORK_CABINET: (Discipline.TELECOM, _POINT),
    ObjectKind.UTILITY_CROSSING: (Discipline.COMMON, _POINT),
}


class Status(str, Enum):
    """Life-cycle of an object.  Approval is a human act, never automatic."""

    EXISTING = "existing"        # surveyed / as-built input
    PROPOSED = "proposed"        # drawn, not yet calculated
    CALCULATED = "calculated"    # calculation run, results attached
    CHECKED = "checked"          # design checks reviewed by an engineer
    APPROVED = "approved"        # approved by an authorised person
    SUPERSEDED = "superseded"


class RelationType(str, Enum):
    UPSTREAM_NODE = "upstream_node"        # link -> its upstream/start node
    DOWNSTREAM_NODE = "downstream_node"    # link -> its downstream/end node
    SERVES = "serves"                      # network object -> plot/parcel it serves
    LOCATED_IN = "located_in"              # object -> road corridor it sits in
    CROSSES = "crosses"                    # utility -> utility / road it crosses
    DEPENDS_ON_LEVEL = "depends_on_level"  # object whose levels derive from another
    FEEDS = "feeds"                        # transformer -> cable, reservoir -> zone
    DRAINS_TO = "drains_to"                # catchment -> drain node / inlet


def new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class Relationship:
    source_id: str
    target_id: str
    type: RelationType
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class EngineeringObject:
    kind: ObjectKind
    geometry: dict[str, Any]                       # GeoJSON, projected CRS (metres)
    attributes: dict[str, Any] = field(default_factory=dict)
    status: Status = Status.PROPOSED
    id: str = field(default_factory=new_id)
    name: str | None = None                        # human label, e.g. "MH-12"

    def __post_init__(self) -> None:
        self.kind = ObjectKind(self.kind)
        self.status = Status(self.status)
        gtype = (self.geometry or {}).get("type")
        allowed = KIND_SPEC[self.kind][1]
        if gtype not in allowed:
            raise ValueError(f"{self.kind.value} '{self.label}' needs geometry {allowed}, got {gtype!r}")

    @property
    def discipline(self) -> Discipline:
        return KIND_SPEC[self.kind][0]

    @property
    def label(self) -> str:
        return self.name or self.id[:8]

    def attr(self, key: str, default: Any = None) -> Any:
        return self.attributes.get(key, default)


@dataclass
class Revision:
    """A named, immutable snapshot of a project's design state."""

    number: int
    label: str
    created_by: str
    note: str = ""
    id: str = field(default_factory=new_id)


@dataclass
class Project:
    name: str
    crs_epsg: int                       # projected CRS used for all engineering geometry
    id: str = field(default_factory=new_id)
    objects: dict[str, EngineeringObject] = field(default_factory=dict)
    relationships: list[Relationship] = field(default_factory=list)

    def add(self, obj: EngineeringObject) -> EngineeringObject:
        if obj.id in self.objects:
            raise ValueError(f"duplicate object id {obj.id}")
        self.objects[obj.id] = obj
        return obj

    def relate(self, source: EngineeringObject | str, target: EngineeringObject | str,
               type: RelationType, **attributes: Any) -> Relationship:
        s = source.id if isinstance(source, EngineeringObject) else source
        t = target.id if isinstance(target, EngineeringObject) else target
        for oid in (s, t):
            if oid not in self.objects:
                raise KeyError(f"relationship refers to unknown object {oid}")
        rel = Relationship(s, t, RelationType(type), attributes)
        self.relationships.append(rel)
        return rel

    def of_kind(self, *kinds: ObjectKind) -> list[EngineeringObject]:
        ks = set(kinds)
        return [o for o in self.objects.values() if o.kind in ks]

    def related(self, obj: EngineeringObject | str, type: RelationType) -> list[EngineeringObject]:
        oid = obj.id if isinstance(obj, EngineeringObject) else obj
        return [self.objects[r.target_id] for r in self.relationships
                if r.source_id == oid and r.type == type]

    def affected_by(self, obj_id: str, depth: int = 3) -> set[str]:
        """Objects reachable from ``obj_id`` through relationships (either
        direction) – the basis of change-impact queries such as "this road
        level changed; which pipes and crossings depend on it?"."""
        adj: dict[str, set[str]] = {}
        for r in self.relationships:
            adj.setdefault(r.source_id, set()).add(r.target_id)
            adj.setdefault(r.target_id, set()).add(r.source_id)
        seen, frontier = {obj_id}, {obj_id}
        for _ in range(depth):
            frontier = {n for f in frontier for n in adj.get(f, ())} - seen
            seen |= frontier
        seen.discard(obj_id)
        return seen

    def by_name(self, name: str) -> EngineeringObject:
        for o in self.objects.values():
            if o.name == name:
                return o
        raise KeyError(name)

    def extend(self, objs: Iterable[EngineeringObject]) -> None:
        for o in objs:
            self.add(o)
