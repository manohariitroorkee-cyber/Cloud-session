"""Common model, GIS geometry, rules framework and GeoJSON I/O."""

import math
import unittest

from cityinfra.engineering.sewer.design import design_network
from cityinfra.engineering.sewer.network import build_network
from cityinfra.gis.geojson_io import export_feature_collection, import_feature_collection
from cityinfra.gis.geometry import (bearing_deg, deflection_deg, line_length, polygon_area,
                                    require_projected)
from cityinfra.model.core import EngineeringObject, ObjectKind, Project, RelationType
from cityinfra.rules.framework import RuleContext, RuleSet, Verification
from cityinfra.samples import sample_sewer_project


def sewer_rules() -> RuleContext:
    return RuleContext([RuleSet.load("cpheeo_sewerage_2013.yaml"), RuleSet.load("dda_project_defaults.yaml")])


class ModelTests(unittest.TestCase):
    def test_geometry_type_enforced(self):
        with self.assertRaises(ValueError):
            EngineeringObject(ObjectKind.MANHOLE, {"type": "LineString", "coordinates": [[0, 0], [1, 1]]})

    def test_relationship_requires_known_objects(self):
        pr = Project("p", 32643)
        a = pr.add(EngineeringObject(ObjectKind.MANHOLE, {"type": "Point", "coordinates": [0, 0]}))
        with self.assertRaises(KeyError):
            pr.relate(a, "missing", RelationType.SERVES)

    def test_change_impact_traversal(self):
        pr = sample_sewer_project()
        mh3 = pr.by_name("MH3")
        affected = {pr.objects[i].name for i in pr.affected_by(mh3.id, depth=1)}
        self.assertEqual(affected, {"S2", "S3", "S4"})


class GeometryTests(unittest.TestCase):
    def test_measurements(self):
        self.assertAlmostEqual(line_length({"type": "LineString", "coordinates": [[0, 0], [3, 4], [3, 10]]}), 11.0)
        sq = {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
                                                  [[2, 2], [4, 2], [4, 4], [2, 4], [2, 2]]]}
        self.assertAlmostEqual(polygon_area(sq), 96.0)
        self.assertAlmostEqual(bearing_deg((0, 0), (1, 0)), 90.0)
        self.assertAlmostEqual(deflection_deg((0, 0), (0, 10), (10, 20)), 45.0)

    def test_geographic_crs_rejected(self):
        with self.assertRaises(ValueError):
            require_projected(4326)
        require_projected(32643)


class RulesTests(unittest.TestCase):
    def test_step_table_and_provenance(self):
        r = sewer_rules()
        pf = r.get("peak_factor")
        self.assertEqual(pf.lookup(20000), 3.0)
        self.assertEqual(pf.lookup(20001), 2.5)
        self.assertEqual(pf.lookup(10_000_000), 2.0)
        self.assertIn("Table 3.2", pf.source.cite())
        self.assertEqual(pf.verification, Verification.REQUIRES_VERIFICATION)

    def test_override_records_reason_and_author(self):
        r = sewer_rules()
        r.override("max_depth_ratio", 0.75, reason="Conservative for trunk sewer", by="SE/NCC-2")
        p = r.get("max_depth_ratio")
        self.assertEqual(p.value, 0.75)
        self.assertEqual(p.verification, Verification.PROJECT_DECISION)
        self.assertEqual(p.verified_by, "SE/NCC-2")
        self.assertNotIn("max_depth_ratio", [q.id for q in r.unverified()])

    def test_unverified_parameters_are_listed(self):
        ids = {p.id for p in sewer_rules().unverified()}
        self.assertIn("peak_factor", ids)
        self.assertNotIn("water_supply_lpcd", ids)   # project decision, not a code value


class GeoJsonTests(unittest.TestCase):
    def test_roundtrip_preserves_topology_and_design(self):
        pr = sample_sewer_project()
        fc = export_feature_collection(pr)
        pr2 = Project("copy", 32643)
        self.assertEqual(import_feature_collection(pr2, fc), [])
        r1 = design_network(build_network(pr), sewer_rules())
        r2 = design_network(build_network(pr2), sewer_rules())
        rows1 = sorted((d.row()["pipe"], d.row()["design_flow_lps"], d.row()["depth_ratio"]) for d in r1.pipes)
        rows2 = sorted((d.row()["pipe"], d.row()["design_flow_lps"], d.row()["depth_ratio"]) for d in r2.pipes)
        self.assertEqual(rows1, rows2)

    def test_crs_mismatch_reported(self):
        fc = export_feature_collection(sample_sewer_project())
        fc["crs"]["properties"]["name"] = "urn:ogc:def:crs:EPSG::32644"
        probs = import_feature_collection(Project("x", 32643), fc)
        self.assertTrue(probs and "differs" in probs[0])


if __name__ == "__main__":
    unittest.main()


class AuditRegressionTests(unittest.TestCase):
    """Findings of the independent audit of 4 Oct 2026 – kept as regression tests."""

    def _fc(self, crs=None, status=None):
        from cityinfra.samples import sample_sewer_project
        fc = export_feature_collection(sample_sewer_project())
        if crs is None:
            fc.pop("crs")
        else:
            fc["crs"]["properties"]["name"] = crs
        if status:
            fc["features"][0]["properties"]["status"] = status
        return fc

    def test_geojson_without_crs_is_refused(self):
        probs = import_feature_collection(Project("x", 32643), self._fc(crs=None))
        self.assertIn("declares no coordinate system", probs[0])

    def test_geographic_geojson_is_refused(self):
        for name in ("urn:ogc:def:crs:OGC:1.3:CRS84", "urn:ogc:def:crs:EPSG::4326"):
            probs = import_feature_collection(Project("x", 32643), self._fc(crs=name))
            self.assertIn("geographic", probs[0])

    def test_lonlat_values_with_projected_crs_refused(self):
        fc = self._fc(crs="urn:ogc:def:crs:EPSG::32643")
        for f in fc["features"]:
            g = f["geometry"]
            if g["type"] == "Point":
                g["coordinates"] = [77.1, 28.85]
            else:
                g["coordinates"] = [[77.1, 28.85], [77.1001, 28.8501]]
        probs = import_feature_collection(Project("x", 32643), fc)
        self.assertIn("look like longitude/latitude", probs[0])

    def test_project_must_use_projected_crs(self):
        with self.assertRaises(ValueError):
            Project("x", 4326)

    def test_import_cannot_set_approved(self):
        pr = Project("x", 32643)
        probs = import_feature_collection(pr, self._fc(crs="urn:ogc:def:crs:EPSG::32643", status="approved"))
        self.assertTrue(any("cannot be imported" in p for p in probs))
        self.assertFalse(any(o.status.value == "approved" for o in pr.objects.values()))

    def test_unclosed_ring_area(self):
        tri_open = {"type": "Polygon", "coordinates": [[[0, 0], [90, 0], [0, 70]]]}
        tri_closed = {"type": "Polygon", "coordinates": [[[0, 0], [90, 0], [0, 70], [0, 0]]]}
        self.assertAlmostEqual(polygon_area(tri_open), 3150.0)
        self.assertAlmostEqual(polygon_area(tri_closed), 3150.0)

    def test_verified_needs_a_name(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as t:
            f = pathlib.Path(t) / "r.yaml"
            f.write_text("id: x\nparameters:\n  a: {value: 1, verification: verified}\n")
            with self.assertRaises(ValueError):
                RuleSet.load(f)
            f.write_text("id: x\nparameters:\n  a: {value: 1, verification: verified, verified_by: 'EE (Design), 4.10.2026'}\n")
            self.assertEqual(RuleSet.load(f).parameters["a"].verified_by, "EE (Design), 4.10.2026")
