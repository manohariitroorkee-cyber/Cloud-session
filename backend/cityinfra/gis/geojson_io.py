"""GeoJSON import/export for the common model.

Import expects a FeatureCollection in the project's projected CRS.  Each
feature carries ``properties.kind`` (an :class:`ObjectKind` value) and
optionally ``name``, ``status`` and ``attributes``; all other properties
are taken as attributes.  Link topology is given by ``properties.from`` /
``properties.to`` naming node features.

DXF/DWG, Shapefile and KML/KMZ import go through GDAL/ezdxf in the API
layer (stage 2) and are converted to this same structure.
"""

from __future__ import annotations

import json
from typing import Any

from ..model.core import EngineeringObject, ObjectKind, Project, RelationType
from .geometry import require_projected

RESERVED = {"kind", "name", "status", "attributes", "from", "to", "id"}


def import_feature_collection(pr: Project, fc: dict[str, Any] | str) -> list[str]:
    """Add features to the project. Returns a list of problems (empty = clean)."""
    if isinstance(fc, str):
        fc = json.loads(fc)
    problems: list[str] = []
    crs = (fc.get("crs") or {}).get("properties", {}).get("name", "")
    if "EPSG" in crs:
        epsg = int(crs.rsplit(":", 1)[-1])
        require_projected(epsg)
        if epsg != pr.crs_epsg:
            problems.append(f"File CRS EPSG:{epsg} differs from project EPSG:{pr.crs_epsg}; reproject before import.")
            return problems
    links: list[tuple[EngineeringObject, str | None, str | None]] = []
    for i, f in enumerate(fc.get("features", [])):
        props = dict(f.get("properties") or {})
        try:
            kind = ObjectKind(props.get("kind"))
        except ValueError:
            problems.append(f"feature {i}: unknown kind {props.get('kind')!r}")
            continue
        attrs = dict(props.get("attributes") or {})
        attrs.update({k: v for k, v in props.items() if k not in RESERVED})
        try:
            obj = EngineeringObject(kind, f["geometry"], attrs, props.get("status", "proposed"),
                                    **({"id": props["id"]} if props.get("id") else {}), name=props.get("name"))
        except (ValueError, KeyError) as e:
            problems.append(f"feature {i}: {e}")
            continue
        pr.add(obj)
        if props.get("from") or props.get("to"):
            links.append((obj, props.get("from"), props.get("to")))
    for obj, a, b in links:
        for name, rel in ((a, RelationType.UPSTREAM_NODE), (b, RelationType.DOWNSTREAM_NODE)):
            try:
                pr.relate(obj, pr.by_name(name), rel)
            except KeyError:
                problems.append(f"{obj.label}: node '{name}' not found")
    return problems


def export_feature_collection(pr: Project, results: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Export objects (optionally merged with per-object results for map styling)."""
    feats = []
    for o in pr.objects.values():
        props: dict[str, Any] = {"id": o.id, "kind": o.kind.value, "name": o.name,
                                 "status": o.status.value, **o.attributes}
        for r in pr.relationships:
            if r.source_id == o.id and r.type == RelationType.UPSTREAM_NODE:
                props["from"] = pr.objects[r.target_id].name
            if r.source_id == o.id and r.type == RelationType.DOWNSTREAM_NODE:
                props["to"] = pr.objects[r.target_id].name
        if results and o.id in results:
            props["results"] = results[o.id]
        feats.append({"type": "Feature", "geometry": o.geometry, "properties": props})
    return {"type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": f"urn:ogc:def:crs:EPSG::{pr.crs_epsg}"}},
            "features": feats}
