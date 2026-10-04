"""Sewer hydraulics, network validation and design checks."""

import math
import unittest

from cityinfra.engineering.sewer.design import design_network
from cityinfra.engineering.sewer.hydraulics import full_flow, manning_q, uniform_flow
from cityinfra.engineering.sewer.network import build_network, connect_pipe
from cityinfra.model.core import EngineeringObject, ObjectKind
from cityinfra.rules.framework import CheckStatus
from cityinfra.samples import sample_sewer_project
from tests.test_foundation import sewer_rules


class HydraulicsTests(unittest.TestCase):
    D, S, N = 0.3, 0.005, 0.013

    def test_full_flow_matches_closed_form(self):
        q, v = full_flow(self.D, self.S, self.N)
        a = math.pi * self.D ** 2 / 4
        expected = a * (self.D / 4) ** (2 / 3) * math.sqrt(self.S) / self.N
        self.assertAlmostEqual(q, expected, places=10)
        self.assertAlmostEqual(v, expected / a, places=10)

    def test_half_full_properties(self):
        # At y = D/2: A = A_full/2 and R = D/4, so V = V_full and Q = Q_full/2.
        qf, vf = full_flow(self.D, self.S, self.N)
        s = uniform_flow(self.D, self.S, self.N, qf / 2)
        self.assertAlmostEqual(s.depth_ratio, 0.5, places=6)
        self.assertAlmostEqual(s.velocity, vf, places=6)

    def test_maximum_discharge_near_0938(self):
        qf, _ = full_flow(self.D, self.S, self.N)
        q938 = manning_q(self.D, 0.938 * self.D, self.S, self.N)
        self.assertAlmostEqual(q938 / qf, 1.076, places=3)
        self.assertFalse(uniform_flow(self.D, self.S, self.N, 1.1 * qf).capacity_ok)


class NetworkValidationTests(unittest.TestCase):
    def test_sample_is_valid_tree(self):
        net = build_network(sample_sewer_project())
        self.assertEqual(net.errors, [])
        order = [net.pipes[p].obj.name for p in net.order]
        self.assertLess(order.index("S1"), order.index("S2"))
        self.assertLess(order.index("S3"), order.index("S4"))
        self.assertEqual(order[-1], "S6")

    def test_adverse_slope_and_snapping_errors(self):
        pr = sample_sewer_project()
        pr.by_name("S1").attributes["ds_invert"] = 215.2
        pr.by_name("S3").geometry["coordinates"][0][0] += 2.0   # start vertex 2 m off MH4
        errs = "\n".join(build_network(pr).errors)
        self.assertIn("S1: adverse", errs)
        self.assertIn("S3: start vertex is 2.00 m", errs)

    def test_bifurcation_and_loop_detected(self):
        pr = sample_sewer_project()
        mh1, mh3, mh5 = pr.by_name("MH1"), pr.by_name("MH3"), pr.by_name("MH5")
        g = {"type": "LineString", "coordinates": [mh5.geometry["coordinates"], mh1.geometry["coordinates"]]}
        p = pr.add(EngineeringObject(ObjectKind.SEWER_PIPE, g, name="SX", attributes={
            "diameter_mm": 200, "material": "upvc", "us_invert": 214.0, "ds_invert": 213.0}))
        connect_pipe(pr, p, mh5, mh1)          # MH5 now has two outlets and closes a loop
        errs = "\n".join(build_network(pr).errors)
        self.assertIn("MH5: 2 outgoing pipes", errs)
        self.assertIn("Loop", errs)


class DesignTests(unittest.TestCase):
    def setUp(self):
        self.res = design_network(build_network(sample_sewer_project()), sewer_rules())
        self.by = {d.pipe.obj.name: d for d in self.res.pipes}

    def test_population_accumulates_downstream(self):
        self.assertEqual(self.by["S2"].population, 1800 + 1500)
        self.assertEqual(self.by["S4"].population, 1800 + 1500 + 1200 + 2500)
        self.assertEqual(self.by["S6"].population, 12500)

    def test_design_flow_formula(self):
        # 7000 persons × max(150 × 0.8, 100) = 120 lpcd = 9.7222 L/s average;
        # × peak factor 3.0 (≤ 20 000) × 1.10 infiltration = 32.0833 L/s
        self.assertAlmostEqual(self.by["S4"].design_flow * 1000, 32.083333, places=5)

    def test_diameter_reduction_and_crown_matching(self):
        res = design_network(build_network(sample_sewer_project()), sewer_rules())
        c = {(x.object_label, x.check): x.status for x in res.node_checks}
        self.assertEqual(c[("MH6", "diameter_reduction")], CheckStatus.FAIL)      # 300 mm → 150 mm
        self.assertEqual(c[("MH5", "diameter_reduction")], CheckStatus.PASS)
        self.assertEqual(c[("MH3", "crown_matching")], CheckStatus.WARNING)       # 200 → 250 mm, crown higher

    def test_expected_failures_and_alternatives(self):
        status = lambda p, c: next(x.status for x in self.by[p].checks if x.check == c)
        self.assertEqual(status("S2", "capacity"), CheckStatus.FAIL)
        self.assertEqual(status("S6", "capacity"), CheckStatus.FAIL)
        self.assertEqual(status("S6", "max_velocity"), CheckStatus.NOT_EVALUATED)  # surcharged
        self.assertEqual(status("S4", "depth_ratio"), CheckStatus.PASS)
        self.assertTrue(any("Increase diameter to 300 mm" in a for a in self.by["S6"].alternatives))
        self.assertEqual({d.pipe.obj.name for d in self.res.failing}, {"S1", "S2", "S6"})

    def test_every_rule_check_cites_a_source(self):
        for c in self.res.all_checks():
            if c.check not in ("capacity", "invert_continuity", "diameter_reduction", "crown_matching"):
                self.assertIsNotNone(c.parameter, c.check)
                self.assertTrue(c.as_dict()["source"])

    def test_unknown_material_is_an_error_not_a_guess(self):
        pr = sample_sewer_project()
        pr.by_name("S1").attributes["material"] = "bamboo"
        res = design_network(build_network(pr), sewer_rules())
        self.assertTrue(any("bamboo" in e for e in res.errors))


if __name__ == "__main__":
    unittest.main()
