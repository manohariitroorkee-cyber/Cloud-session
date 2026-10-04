"""Road alignment and curve design – every curve type, vertical curves, checks."""

import math
import random
import unittest

from cityinfra.engineering.roads import alignment as hz
from cityinfra.engineering.roads.design import design_road, level_impacts
from cityinfra.engineering.roads.vertical import TIN, VIP, VerticalAlignment, crest_length_for, ssd
from cityinfra.rules.framework import CheckStatus, RuleContext, RuleSet
from cityinfra.samples import sample_road_project

PIS = [(0, 0), (0, 300), (300, 500), (300, 800)]


def road_rules() -> RuleContext:
    return RuleContext([RuleSet.load("irc_geometric_design.yaml"), RuleSet.load("project_road_defaults.yaml")])


def continuous(al, tol_pos=1e-6, tol_head=1e-9):
    for e1, e2 in zip(al.elements, al.elements[1:]):
        x, y, b = e1.end()
        assert math.hypot(x - e2.x0, y - e2.y0) < tol_pos, (e1, e2)
        assert abs(hz.wrap(b - e2.b0)) < tol_head
    return True


def closes(al, end):
    x, y, _ = al.elements[-1].end()
    return math.hypot(x - end[0], y - end[1])


class PiCurveTypeTests(unittest.TestCase):
    def test_simple_curve_elements(self):
        al = hz.from_pis(PIS, {1: {"R": 200}, 2: {"R": 200}})
        g = al.groups[0]
        d = abs(g.delta)
        self.assertEqual(g.kind, "simple circular")
        self.assertAlmostEqual(g.t_in, 200 * math.tan(d / 2), places=9)
        self.assertAlmostEqual(g.arc_length, 200 * d, places=9)
        self.assertAlmostEqual(g.ch_start, 300 - g.t_in, places=9)
        self.assertLess(closes(al, PIS[-1]), 1e-9)

    def test_symmetric_spiral_matches_classical_formulae(self):
        al = hz.from_pis(PIS, {1: [200, 60], 2: [200, 60]})
        g = al.groups[0]
        R, Ls, D = 200, 60, abs(g.delta)
        p = Ls ** 2 / (24 * R) - Ls ** 4 / (2688 * R ** 3)
        k = Ls / 2 - Ls ** 3 / (240 * R ** 2)
        self.assertAlmostEqual(g.t_in, (R + p) * math.tan(D / 2) + k, delta=1e-4)
        self.assertAlmostEqual(g.length, 2 * Ls + R * (D - Ls / R), places=9)
        self.assertTrue(continuous(al))
        self.assertLess(closes(al, PIS[-1]), 1e-8)

    def test_unequal_transitions(self):
        al = hz.from_pis(PIS, {1: {"R": 200, "Ls_in": 80, "Ls_out": 30}, 2: {"R": 150}})
        g = al.groups[0]
        self.assertIn("unequal", g.kind)
        self.assertNotAlmostEqual(g.t_in, g.t_out, places=1)
        self.assertTrue(continuous(al))
        self.assertLess(closes(al, PIS[-1]), 1e-8)

    def test_spiral_spiral(self):
        pis = [(0, 0), (0, 500), (400, 800), (400, 1400)]
        al = hz.from_pis(pis, {1: {"type": "spiral_spiral", "R": 300}, 2: {"R": 300}})
        g = al.groups[0]
        self.assertEqual(g.kind, "spiral–spiral")
        self.assertAlmostEqual(g.elements[0].length, 300 * abs(g.delta), places=9)
        self.assertEqual(al.errors, [])
        self.assertLess(closes(al, pis[-1]), 1e-8)

    def test_compound_with_transitions(self):
        spec = {"arcs": [{"R": 300, "deflection_deg": 20}, {"R": 150}], "Ls_in": 40, "Ls_between": [30], "Ls_out": 40}
        al = hz.from_pis(PIS, {1: spec, 2: {"R": 150}})
        g = al.groups[0]
        self.assertEqual(g.kind, "compound curve with transitions")
        self.assertEqual(sorted(round(r) for r in g.radii), [150, 300])
        self.assertAlmostEqual(sum(e.deflection for e in g.elements), g.delta, places=9)
        self.assertTrue(continuous(al))
        self.assertLess(closes(al, PIS[-1]), 1e-8)

    def test_overlap_reports_largest_radius_that_fits(self):
        al = hz.from_pis(PIS, {1: {"R": 900}, 2: {"R": 200}})
        msg = " ".join(al.errors)
        self.assertIn("overlap", msg)
        self.assertIn("largest radius at PI1", msg)
        rmax = float(msg.split("largest radius at PI1: ")[1].split(" m")[0])
        self.assertEqual(hz.from_pis(PIS, {1: {"R": rmax - 1}, 2: {"R": 200}}).errors, [])

    def test_too_long_transitions_rejected(self):
        self.assertTrue(any("deflects only" in e for e in hz.from_pis(PIS, {1: {"R": 100, "Ls": 150}, 2: {"R": 100}}).errors))

    def test_exact_reverse_curve_without_tangent(self):
        # PIs placed so that the two tangents meet exactly: T2(PI1) + T1(PI2) = distance
        b = hz.from_pis(PIS, {1: {"R": 200}, 2: {"R": 200}})
        t = b.groups[0].t_out + b.groups[1].t_in
        scale = math.dist(PIS[1], PIS[2]) / t
        al = hz.from_pis(PIS, {1: {"R": 200 * scale}, 2: {"R": 200 * scale}})
        self.assertEqual(al.errors, [])
        self.assertAlmostEqual(al.groups[1].ch_start, al.groups[0].ch_end, places=6)


class ElementChainTests(unittest.TestCase):
    def test_hairpin_over_180_degrees(self):
        al = hz.from_elements((0, 0), 0.0, [{"line": 100}, {"spiral": 40, "to_R": 30, "turn": "left"},
                                             {"arc_deg": 160, "R": 30, "turn": "left"},
                                             {"spiral": 40, "from_R": 30, "turn": "left"}, {"line": 100}])
        turn = sum(e.deflection for e in al.elements)
        self.assertAlmostEqual(math.degrees(turn), -(160 + 2 * math.degrees(40 / 60)), places=9)
        self.assertTrue(continuous(al))
        self.assertEqual(al.warnings, [])

    def test_full_circle_closes(self):
        al = hz.from_elements((10, 20), 0.3, [{"arc_deg": 360, "R": 25, "turn": "right"}])
        x, y, b = al.at(al.length)
        self.assertLess(math.hypot(x - 10, y - 20), 1e-9)
        self.assertAlmostEqual(al.length, 2 * math.pi * 25, places=9)

    def test_s_spiral_through_zero_curvature(self):
        al = hz.from_elements((0, 0), 0.0, [{"arc": 50, "R": 200},
                                             {"spiral": 60, "from_R": 200, "to_R": 200, "turn": "right", "to_turn": "left"},
                                             {"arc": 50, "R": 200, "turn": "left"}])
        self.assertEqual(al.groups[0].kind, "reverse (S) curve")
        self.assertAlmostEqual(al.curvature(80), 0.0, places=12)       # inflection at mid-spiral
        self.assertTrue(continuous(al))

    def test_spiral_against_series_expansion(self):
        R, Ls = 150.0, 80.0
        al = hz.from_elements((0, 0), 0.0, [{"spiral": Ls, "to_R": R}])
        x_series = Ls - Ls ** 5 / (40 * R ** 2 * Ls ** 2) + Ls ** 9 / (3456 * R ** 4 * Ls ** 4)
        y_series = Ls ** 3 / (6 * R * Ls) - Ls ** 7 / (336 * R ** 3 * Ls ** 3) + Ls ** 11 / (42240 * R ** 5 * Ls ** 5)
        x, y, _ = al.at(Ls)
        # exact reference: Simpson's rule on the clothoid heading θ = s²/(2·R·Ls)
        N, hh = 20000, Ls / 20000
        sx = sy = 0.0
        for i in range(N + 1):
            w = 1 if i in (0, N) else (4 if i % 2 else 2)
            t = (i * hh) ** 2 / (2 * R * Ls)
            sx += w * math.sin(t); sy += w * math.cos(t)
        self.assertAlmostEqual(y, sy * hh / 3, delta=1e-9)       # along the start bearing (north)
        self.assertAlmostEqual(x, sx * hh / 3, delta=1e-9)       # offset to the right
        # the textbook series (three terms) agrees to its own truncation error
        self.assertAlmostEqual(y, x_series, delta=1e-5)
        self.assertAlmostEqual(x, y_series, delta=1e-5)

    def test_curvature_jump_warned(self):
        al = hz.from_elements((0, 0), 0.0, [{"line": 50}, {"arc": 50, "R": 100}])
        self.assertTrue(al.warnings)


class CadBulgeTests(unittest.TestCase):
    def _poly(self):
        R, th = 100.0, math.radians(60)
        ex, ey = R - R * math.cos(th), 100 + R * math.sin(th)
        v = [(0, 0), (0, 100), (ex, ey), (ex + 200 * math.sin(th), ey + 200 * math.cos(th))]
        return v, [0.0, -math.tan(th / 4), 0.0]

    def test_tangent_arcs_have_no_kinks(self):
        v, b = self._poly()
        al = hz.from_bulges(v, b)
        self.assertEqual(al.kinks, [])
        self.assertAlmostEqual(al.groups[0].radius, 100.0, places=9)

    def test_angle_points_are_reported(self):
        v, _ = self._poly()
        al = hz.from_bulges(v, [0, 0, 0])
        self.assertEqual([round(math.degrees(a), 6) for _, a in al.kinks], [30.0, 30.0])


class FreehandFitTests(unittest.TestCase):
    def test_noise_free_trace_recovers_design(self):
        true = hz.from_pis(PIS, {1: {"R": 150}, 2: {"R": 250}})
        _, specs, rep = hz.fit_drawn(true.coordinates(3.0))
        self.assertEqual([round(r) for r in rep["radii_m"]], [150, 250])
        self.assertLess(rep["max_deviation_m"], 0.05)
        self.assertTrue(rep["within_tolerance"])

    def test_noisy_trace(self):
        random.seed(1)
        true = hz.from_pis(PIS, {1: {"R": 150}, 2: {"R": 250}})
        pts = [(x + random.gauss(0, 0.2), y + random.gauss(0, 0.2)) for x, y in true.coordinates(3.0)]
        _, _, rep = hz.fit_drawn(pts)
        self.assertEqual(rep["errors"], [])
        for got, want in zip(rep["radii_m"], [150, 250]):
            self.assertLess(abs(got - want) / want, 0.02)

    def test_reverse_curve_without_tangent(self):
        rc = hz.from_elements((0, 0), 0.0, [{"line": 150}, {"arc": 120, "R": 180},
                                             {"arc": 120, "R": 220, "turn": "left"}, {"line": 150}])
        _, _, rep = hz.fit_drawn(rc.coordinates(2.0))
        self.assertEqual([round(r) for r in rep["radii_m"]], [180, 220])
        self.assertIn("Reverse curve detected", " ".join(rep["notes"]))


class VerticalTests(unittest.TestCase):
    def test_parabola_midpoint_offset(self):
        v = VerticalAlignment([VIP(0, 100), VIP(200, 104, 100), VIP(400, 100)])
        A = abs(v.grade(1) - v.grade(0))
        self.assertAlmostEqual(v.level(200), 104 - A * 100 / 8, places=9)
        self.assertAlmostEqual(v.level(150), 103, places=9)
        self.assertAlmostEqual(v.level(300), 102, places=9)

    def test_unsymmetrical_curve(self):
        v = VerticalAlignment([VIP(0, 100), VIP(200, 104, 80, 40), VIP(400, 100)])
        A = v.grade(1) - v.grade(0)
        self.assertAlmostEqual(v.level(200), 104 + A * 80 * 40 / (2 * 120), places=9)
        h = 1e-6
        self.assertAlmostEqual((v.level(200) - v.level(200 - h)) / h, (v.level(200 + h) - v.level(200)) / h, places=4)
        self.assertAlmostEqual(v.level(240), 104 + v.grade(1) * 40, places=9)     # meets the tangent at EVC
        self.assertAlmostEqual(v.level(120), 104 - v.grade(0) * 80, places=9)     # and at BVC

    def test_ssd_and_crest_length(self):
        S = ssd(50, 2.5, 0.37)
        self.assertAlmostEqual(S, 50 / 3.6 * 2.5 + (50 / 3.6) ** 2 / (2 * 9.81 * 0.37))
        k = (math.sqrt(2.4) + math.sqrt(0.3)) ** 2
        L = crest_length_for(S, 0.10, 1.2, 0.15)
        self.assertGreater(L, S)
        self.assertAlmostEqual(L, 0.10 * S * S / k)
        L = crest_length_for(S, 0.06, 1.2, 0.15)
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

    def fails(self, d):
        return {c.check for c in d.checks if c.status == CheckStatus.FAIL}

    def test_sample_passes_all_checks(self):
        self.assertEqual(self.d.errors, [])
        bad = [c.message for c in self.d.checks if c.status not in (CheckStatus.PASS,)]
        self.assertEqual(bad, [])

    def test_failures_are_detected(self):
        self.road.attributes["design_speed_kmh"] = 80      # R_min ≈ 229 m > 200 m
        f = self.fails(design_road(self.pr, self.road, road_rules()))
        self.assertIn("min_radius", f)
        self.assertIn("transition_length", f)

    def test_missing_transition_detected(self):
        self.road.attributes["curves"] = {"1": {"R": 200}, "2": {"R": 200}}
        self.assertIn("transition_missing", self.fails(design_road(self.pr, self.road, road_rules())))

    def test_reverse_curve_tangent_check(self):
        self.road.attributes["curves"] = {"1": {"R": 260}, "2": {"R": 260}}   # opposite hands, short straight, no transitions
        d = design_road(self.pr, self.road, road_rules())
        rc = [c for c in d.checks if c.check == "reverse_curve"]
        self.assertTrue(rc)
        self.assertEqual(rc[0].status, CheckStatus.FAIL)

    def test_cad_polyline_kink_fails(self):
        self.road.attributes.update(horizontal_mode="bulges", bulges=[0, 0, 0])
        d = design_road(self.pr, self.road, road_rules())
        self.assertIn("kink", self.fails(d))

    def test_element_mode_and_end_chainage(self):
        self.road.attributes.update(horizontal_mode="elements", start_bearing_deg=90, elements=[
            {"line": 150}, {"spiral": 60, "to_R": 200, "turn": "left"}, {"arc": 60, "R": 200, "turn": "left"},
            {"spiral": 60, "from_R": 200, "turn": "left"}, {"line": 150}],
            profile=[[0, 216.4, 0], [200, 215.6, 80], ["end", 216.9, 0]])
        d = design_road(self.pr, self.road, road_rules())
        self.assertEqual(d.errors, [])
        self.assertAlmostEqual(d.v.vips[-1].chainage, d.h.length)

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


class RoadAuditRegressionTests(unittest.TestCase):
    def setUp(self):
        self.pr = sample_road_project()
        self.road = self.pr.by_name("R1")

    def test_spiral_spiral_gets_min_radius_check(self):
        self.road.attributes["curves"] = {"1": {"type": "spiral_spiral", "R": 40}, "2": [200, 60]}
        d = design_road(self.pr, self.road, road_rules())
        mr = [c for c in d.checks if c.check == "min_radius" and "PI1" in c.object_label]
        self.assertEqual([c.status for c in mr], [CheckStatus.FAIL])
        self.assertAlmostEqual(mr[0].actual, 40.0)

    def test_unsymmetrical_vertical_curve_checked_by_sharper_leg(self):
        self.road.attributes["profile"] = [[0, 216.4, 0], [200, 215.6, 5, 145], ["end", 216.9, 0]]
        d = design_road(self.pr, self.road, road_rules())
        vc = next(c for c in d.checks if c.check == "vertical_curve_length")
        self.assertEqual(vc.status, CheckStatus.FAIL)
        self.assertAlmostEqual(vc.actual, 5 * 150 / 145, places=9)

    def test_one_sided_vertical_curve_rejected(self):
        self.road.attributes["profile"] = [[0, 216.4, 0], [200, 214.6, 40, 0], ["end", 216.9, 0]]
        d = design_road(self.pr, self.road, road_rules())
        self.assertTrue(any("zero length" in e for e in d.errors))

    def test_superelevation_on_curve(self):
        d = design_road(self.pr, self.road, road_rules())
        from cityinfra.engineering.roads import cross_section as xs
        tpl = self.road.attr("template")
        g = d.h.groups[0]                                           # left-hand curve at PI1
        mid = (g.ch_start + g.ch_end) / 2
        E = min(50 ** 2 / (225 * 200), 0.07)
        self.assertAlmostEqual(d.superelevation(mid), -E, places=9)
        sl = d.slopes(mid)
        _, inner = xs.surface_at(tpl, -7.6, sl)                     # inside of a left-hand curve is lower
        _, outer = xs.surface_at(tpl, 7.6, sl)
        self.assertAlmostEqual(inner, -7.0 * E, places=9)
        self.assertAlmostEqual(outer, +7.0 * E, places=9)
        self.assertEqual(d.superelevation(50), 0.0)                 # straight: normal camber

    def test_superelevation_has_no_steps(self):
        # audit N1: the outer edge must rise smoothly through the transition – no jump anywhere
        d = design_road(self.pr, self.road, road_rules())
        from cityinfra.engineering.roads import cross_section as xs
        tpl = self.road.attr("template")
        prev = None
        ch = 100.0
        while ch < 300.0:
            z = {o: xs.surface_at(tpl, o, d.slopes(ch))[1] for o in (-7.6, 7.6)}
            if prev:
                for o in z:
                    self.assertLess(abs(z[o] - prev[o]), 0.01, f"step at ch {ch:.1f} offset {o}")
            prev, ch = z, ch + 0.1

    def test_empirical_transition_criterion(self):
        # undivided 7 m road at 50 km/h, R = 200 m: 2.7·V²/R = 33.75 m governs over run-off and v³/CR
        self.road.attributes["template"] = {"strips": [{"type": "carriageway", "width": 3.5, "crossfall_pct": -2.5}]}
        self.road.attributes["curves"] = {"1": [200, 30], "2": [200, 30]}
        d = design_road(self.pr, self.road, road_rules())
        tl = [c for c in d.checks if c.check == "transition_length"]
        self.assertTrue(all(c.status == CheckStatus.FAIL for c in tl))
        self.assertAlmostEqual(tl[0].limit, 2.7 * 50 ** 2 / 200, places=6)

    def test_terrain_is_required(self):
        del self.road.attributes["terrain"]
        with self.assertRaises(ValueError):
            design_road(self.pr, self.road, road_rules())

    def test_missing_design_speed_is_reported(self):
        del self.road.attributes["design_speed_kmh"]
        with self.assertRaises(ValueError):
            design_road(self.pr, self.road, road_rules())
