"""Junction geometric design: intersections and roundabouts."""

import math
import unittest

from cityinfra.engineering.roads.junction import (_fillet_line_circle, design_junction, junction_features,
                                                  point_in_polygon)
from cityinfra.model.core import EngineeringObject, ObjectKind
from cityinfra.rules.framework import CheckStatus, RuleContext, RuleSet
from cityinfra.samples import E0, N0, sample_junction_project


def j_rules() -> RuleContext:
    return RuleContext([RuleSet.load("irc_geometric_design.yaml"), RuleSet.load("project_road_defaults.yaml"),
                        RuleSet.load("junction_design.yaml")])


def status(d, check, label_part=""):
    return [c.status for c in d.checks if c.check == check and label_part in c.object_label]


class IntersectionTests(unittest.TestCase):
    def setUp(self):
        self.pr = sample_junction_project()
        self.rules = j_rules()

    def test_t_junction_from_road_alignments(self):
        d = design_junction(self.pr, self.pr.by_name("J-T"), self.rules)
        self.assertEqual(d.errors, [])
        side = next(a for a in d.arms if a.name == "SIDE")
        self.assertAlmostEqual(math.degrees(side.bearing) % 360, 0.0, places=6)
        self.assertAlmostEqual(side.w_right, 3.5)
        # simple 90° corner: tangent length = R, PI at the meeting of the two carriageway edges
        c = next(c for c in d.corners if c.name == "SIDE-MAIN-E")
        self.assertEqual(c.group.kind, "simple circular")
        self.assertAlmostEqual(c.group.t_in, 12.0, places=9)
        self.assertAlmostEqual(c.pi[0] - (E0 + 600), 3.5, places=9)
        self.assertAlmostEqual(c.pi[1] - N0, 3.5, places=9)
        # the road is linked to the junction for change-impact queries
        main = self.pr.by_name("SIDE")
        self.assertIn(self.pr.by_name("J-T").id, self.pr.affected_by(main.id, depth=1))

    def test_kerb_return_is_tangent_to_both_edges(self):
        d = design_junction(self.pr, self.pr.by_name("J-T"), self.rules)
        c = next(c for c in d.corners if c.name == "SIDE-MAIN-E")
        arc = next(e for e in c.group.elements if e.kind == "arc")
        x0, y0 = arc.x0, arc.y0
        # start of arc lies on SIDE's right edge (x = 603.5) and starts parallel to it (heading south)
        self.assertAlmostEqual(x0 - E0, 603.5, places=9)
        self.assertAlmostEqual(math.degrees(arc.b0) % 360, 180.0, places=9)
        xe, ye, be = arc.end()
        self.assertAlmostEqual(ye - N0, 3.5, places=9)                   # ends on MAIN's north edge
        self.assertAlmostEqual(math.degrees(be) % 360, 90.0, places=9)   # heading east

    def test_three_centred_corner(self):
        d = design_junction(self.pr, self.pr.by_name("J-CROSS"), self.rules)
        c = next(c for c in d.corners if c.name == "N-E")
        self.assertEqual(sorted(c.group.radii), [12.0, 24.0, 24.0])
        self.assertAlmostEqual(math.degrees(c.group.delta), math.degrees(c.angle) - 180, places=9)
        self.assertAlmostEqual(c.group.t_in, c.group.t_out, places=9)    # symmetric 2R-R-2R

    def test_skew_and_obstruction_detected(self):
        d = design_junction(self.pr, self.pr.by_name("J-CROSS"), self.rules)
        self.assertEqual(status(d, "intersection_angle", "arm W"), [CheckStatus.FAIL])
        self.assertEqual(status(d, "intersection_angle", "arm E"), [CheckStatus.PASS])
        tri = next(t for t in d.triangles if t.name == "N/E")
        self.assertEqual(tri.obstructions, ["PLOT-NE"])
        self.pr.by_name("PLOT-NE").geometry["coordinates"][0] = [[E0 + x, N0 + y] for x, y in
                                                                  ((60, 60), (90, 60), (90, 90), (60, 90), (60, 60))]
        d2 = design_junction(self.pr, self.pr.by_name("J-CROSS"), self.rules)
        self.assertEqual(next(t for t in d2.triangles if t.name == "N/E").obstructions, [])

    def test_sight_distances(self):
        d = design_junction(self.pr, self.pr.by_name("J-CROSS"), self.rules)
        tri = next(t for t in d.triangles if t.name == "N/E")
        v = 40 / 3.6
        self.assertAlmostEqual(tri.distances[0], v * 2.5 + v * v / (2 * 9.81 * 0.38), places=9)
        dt = design_junction(self.pr, self.pr.by_name("J-T"), self.rules)
        t = next(t for t in dt.triangles if t.name == "SIDE/MAIN-E")
        self.assertAlmostEqual(t.distances[0], 4.5)
        self.assertAlmostEqual(t.distances[1], 40 / 3.6 * 7.5)
        self.assertTrue(point_in_polygon(((t.polygon[0][0] + t.polygon[1][0] + t.polygon[2][0]) / 3,
                                          (t.polygon[0][1] + t.polygon[1][1] + t.polygon[2][1]) / 3), t.polygon))

    def test_errors(self):
        j = self.pr.by_name("J-CROSS")
        j.attributes["design_vehicle"] = "spaceship"
        self.assertTrue(design_junction(self.pr, j, self.rules).errors)
        j.attributes["design_vehicle"] = "bus"
        j.attributes["arms"] = j.attributes["arms"][:2]
        self.assertTrue(any("at least three arms" in e for e in design_junction(self.pr, j, self.rules).errors))
        jt = self.pr.by_name("J-T")
        jt.geometry["coordinates"] = [E0 + 650, N0]
        self.assertTrue(any("does not start or end" in e for e in design_junction(self.pr, jt, self.rules).errors))


class RoundaboutTests(unittest.TestCase):
    def setUp(self):
        self.pr = sample_junction_project()
        self.d = design_junction(self.pr, self.pr.by_name("J-RB"), j_rules())

    def test_fillet_tangency(self):
        rb = self.d.roundabout
        c = self.d.centre
        Ro = rb["inscribed_radius_m"]
        for a in self.d.arms:
            (fc, te, tc), (fx, tx, cx) = rb["fillets"][a.name]
            self.assertAlmostEqual(math.dist(fc, c), Ro + rb["entry_radius_m"], places=9)
            self.assertAlmostEqual(math.dist(fc, te), rb["entry_radius_m"], places=9)
            self.assertAlmostEqual(math.dist(tc, c), Ro, places=9)
            self.assertAlmostEqual(math.dist(fx, c), Ro + rb["exit_radius_m"], places=9)

    def test_weaving_length_by_hand(self):
        Ro, Ren, Rex, w = 37.0, 20.0, 25.0, 7.0
        a_en = math.atan2(w + Ren, math.sqrt((Ro + Ren) ** 2 - (w + Ren) ** 2))         # N entry tangent bearing
        a_ex = math.atan2(math.sqrt((Ro + Rex) ** 2 - (w + Rex) ** 2), w + Rex)         # E exit tangent bearing
        expect = Ro * (a_ex - a_en)
        got = next(x for x in self.d.roundabout["weaving"] if x["section"] == "N→E")["length_m"]
        self.assertAlmostEqual(got, expect, places=9)
        self.assertEqual(set(status(self.d, "weaving_length")), {CheckStatus.FAIL})

    def test_wardrop_capacity(self):
        w = next(x for x in self.d.roundabout["weaving"] if x["section"] == "N→E")
        ww, e, l, p = 10.0, 7.0, w["length_m"], 0.5
        self.assertAlmostEqual(w["capacity_pcu_h"], 280 * ww * (1 + e / ww) * (1 - p / 3) / (1 + ww / l), places=9)

    def test_island_and_radius_checks(self):
        self.assertEqual(status(self.d, "central_island_radius"), [CheckStatus.PASS])
        self.assertEqual(status(self.d, "entry_radius"), [CheckStatus.PASS])

    def test_features_for_map(self):
        kinds = {f["properties"]["kind"] for f in junction_features(self.d)}
        self.assertEqual(kinds, {"central_island", "inscribed_circle", "entry_kerb", "exit_kerb"})

    def test_missing_parameter(self):
        j = self.pr.by_name("J-RB")
        del j.attributes["roundabout"]["entry_radius_m"]
        self.assertTrue(any("entry_radius_m" in e for e in design_junction(self.pr, j, j_rules()).errors))


if __name__ == "__main__":
    unittest.main()
