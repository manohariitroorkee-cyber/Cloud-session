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
from .geometry import looks_geographic, require_projected

RESERVED = {"kind", "name", "status", "attributes", "from", "to", "id"}
IMPORT_STATUSES = {"existing", "proposed"}      # checked / approved can only be set by a review record
GEOGRAPHIC_NAMES = ("CRS84", "EPSG::4326", "EPSG:4326", "OGC:1.3")


def import_feature_collection(pr: Project, fc: dict[str, Any] | str) -> list[str]:
    """Add features to the project. Returns a list of problems (empty = clean)."""
    if isinstance(fc, str):
        fc = json.loads(fc)
    problems: list[str] = []
    crs = (fc.get("crs") or {}).get("properties", {}).get("name", "")
    # RFC 7946 GeoJSON without a "crs" member is longitude/latitude (WGS84): never accept it as metres
    if not crs:
        problems.append("The file declares no coordinate system. Standard GeoJSON is longitude/latitude (WGS84); "
                        f"reproject to the project CRS EPSG:{pr.crs_epsg} and declare it in a \"crs\" member.")
        return problems
    if any(g in crs.upper() for g in GEOGRAPHIC_NAMES):
        problems.append(f"The file is in geographic coordinates ({crs}); reproject to the project CRS EPSG:{pr.crs_epsg}.")
        return problems
    try:
        epsg = int(crs.replace("::", ":").rsplit(":", 1)[-1])
    except ValueError:
        problems.append(f"Unrecognised coordinate system {crs!r}; declare it as urn:ogc:def:crs:EPSG::<code>.")
        return problems
    try:
        require_projected(epsg)
    except ValueError as e:
        problems.append(str(e))
        return problems
    if epsg != pr.crs_epsg:
        problems.append(f"File CRS EPSG:{epsg} differs from project EPSG:{pr.crs_epsg}; reproject before import.")
        return problems
    feats = fc.get("features", [])
    if looks_geographic([f["geometry"]["coordinates"] for f in feats if f.get("geometry")]):
        problems.append(f"The file declares EPSG:{epsg} but its coordinates look like longitude/latitude; "
                        "reproject the data before import.")
        return problems
    links: list[tuple[EngineeringObject, str | None, str | None]] = []
    for i, f in enumerate(feats):
        props = dict(f.get("properties") or {})
        try:
            kind = ObjectKind(props.get("kind"))
        except ValueError:
            problems.append(f"feature {i}: unknown kind {props.get('kind')!r}")
            continue
        attrs = dict(props.get("attributes") or {})
        attrs.update({k: v for k, v in props.items() if k not in RESERVED})
        status = props.get("status", "proposed")
        if status not in IMPORT_STATUSES:
            problems.append(f"feature {i} ({props.get('name') or kind.value}): status {status!r} cannot be imported – "
                            "imported as 'proposed'. Checked/approved status comes only from a review record.")
            status = "proposed"
        try:
            obj = EngineeringObject(kind, f["geometry"], attrs, status,
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
