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
