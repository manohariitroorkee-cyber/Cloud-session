"""Road alignment and curve design."""

import math
import unittest

from cityinfra.engineering.roads.design import design_road, level_impacts
from cityinfra.engineering.roads.horizontal import _eval, build
from cityinfra.engineering.roads.vertical import TIN, VIP, VerticalAlignment, crest_length_for, ssd
from cityinfra.rules.framework import CheckStatus, RuleContext, RuleSet
from cityinfra.samples import sample_road_project

PIS = [(0, 0), (0, 300), (300, 500), (300, 800)]


def road_rules() -> RuleContext:
    return RuleContext([RuleSet.load("irc_geometric_design.yaml"), RuleSet.load("project_road_defaults.yaml")])


class HorizontalTests(unittest.TestCase):
    def test_simple_curve_elements(self):
        h = build(PIS, {1: (200, 0), 2: (200, 0)})
        c = h.curves[0]
        d = abs(c.delta)
        self.assertAlmostEqual(c.ts, 200 * math.tan(d / 2), places=9)
        self.assertAlmostEqual(c.lc, 200 * d, places=9)
        self.assertAlmostEqual(c.external, 200 * (1 / math.cos(d / 2) - 1), places=9)
        self.assertAlmostEqual(c.ch_ts, 300 - c.ts, places=9)

    def test_continuity_closure_and_station(self):
        for curves in ({1: (200, 0), 2: (200, 0)}, {1: (200, 50), 2: (150, 40)}):
            h = build(PIS, curves)
            self.assertEqual(h.errors, [])
            for e1, e2 in zip(h.elements, h.elements[1:]):
                a, b = _eval(e1, e1.length), _eval(e2, 0)
                self.assertLess(math.hypot(a[0] - b[0], a[1] - b[1]), 1e-4)
                self.assertLess(abs(a[2] - b[2]), 1e-6)
            x, y, _ = h.at(h.length)
            self.assertLess(math.hypot(x - 300, y - 800), 1e-6)
            ch, off = h.station(h.offset_point(250, -6.25))
            self.assertAlmostEqual(ch, 250, places=4)
            self.assertAlmostEqual(off, -6.25, places=4)

    def test_spiral_shift_formula(self):
        h = build(PIS, {1: (200, 60), 2: (200, 60)})
        c = h.curves[0]
        self.assertAlmostEqual(c.p, 60 ** 2 / (24 * 200) - 60 ** 4 / (2688 * 200 ** 3), places=9)
        self.assertAlmostEqual(c.length, 120 + 200 * (abs(c.delta) - 60 / 200), places=9)

    def test_geometry_errors_reported(self):
        self.assertTrue(any("transitions too long" in e for e in build(PIS, {1: (100, 150), 2: (200, 0)}).errors))
        self.assertTrue(any("curves need" in e for e in build(PIS, {1: (800, 0), 2: (800, 0)}).errors))


class VerticalTests(unittest.TestCase):
    def test_parabola_midpoint_offset(self):
        v = VerticalAlignment([VIP(0, 100), VIP(200, 104, 100), VIP(400, 100)])
        A = abs(v.grade(1) - v.grade(0))
        self.assertAlmostEqual(v.level(200), 104 - A * 100 / 8, places=9)
        self.assertAlmostEqual(v.level(150), 103, places=9)          # tangent point
        self.assertAlmostEqual(v.level(300), 102, places=9)

    def test_ssd_and_crest_length(self):
        S = ssd(50, 2.5, 0.37)
        self.assertAlmostEqual(S, 50 / 3.6 * 2.5 + (50 / 3.6) ** 2 / (2 * 9.81 * 0.37))
        k = (math.sqrt(2.4) + math.sqrt(0.3)) ** 2
        L = crest_length_for(S, 0.10, 1.2, 0.15)                  # L > S branch
        self.assertGreater(L, S)
        self.assertAlmostEqual(L, 0.10 * S * S / k)
        L = crest_length_for(S, 0.06, 1.2, 0.15)                  # L < S branch
        self.assertLess(L, S)
        self.assertAlmostEqual(L, 2 * S - k / 0.06)

    def test_tin_reproduces_plane_and_never_extrapolates(self):
        pts = [(x, y, 10 + 0.01 * x - 0.02 * y) for x in range(0, 101, 20) for y in range(0, 101, 20)]
        t = TIN(pts)
        self.assertAlmostEqual(t.level(37.3, 61.9), 10 + 0.373 - 1.238, places=9)
        self.assertIsNone(t.level(150, 50))


class RoadDesignTests(unittest.TestCase):
    def setUp(self):
        self.pr = sample_road_project()
        self.road = self.pr.by_name("R1")
        self.d = design_road(self.pr, self.road, road_rules())

    def test_sample_passes_all_checks(self):
        self.assertEqual(self.d.errors, [])
        bad = [c.message for c in self.d.checks if c.status != CheckStatus.PASS]
        self.assertEqual(bad, [])

    def test_failures_are_detected(self):
        self.road.attributes["design_speed_kmh"] = 80      # R_min ≈ 229 m > 200 m
        d = design_road(self.pr, self.road, road_rules())
        fails = {c.check for c in d.checks if c.status == CheckStatus.FAIL}
        self.assertIn("min_radius", fails)
        self.assertIn("transition_length", fails)

    def test_sections_are_geometry_only(self):
        s = self.d.sections[0]
        self.assertTrue(all(g is not None for _, _, g in s.points))
        self.assertFalse(hasattr(self.d, "quantities"))

    def test_level_impacts_flag_and_link_utilities(self):
        hits = {h["object"]: h for h in level_impacts(self.pr, self.d)}
        self.assertEqual(set(hits), {"MH-R1", "MH-R2"})
        self.assertEqual(hits["MH-R1"]["strip"], "carriageway")
        affected = {self.pr.objects[i].name for i in self.pr.affected_by(self.road.id, depth=1)}
        self.assertTrue({"MH-R1", "MH-R2"} <= affected)


if __name__ == "__main__":
    unittest.main()
