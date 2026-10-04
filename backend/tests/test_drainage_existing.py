"""Existing drains (capacity, flow today, residual), villages at fixed levels, outfall levels,
ground levels from survey points, and proposed sizes/levels for new drains."""

import unittest

from cityinfra.engineering.common.open_channel import Section, normal_flow, q_at
from cityinfra.engineering.drainage.autodesign import propose
from cityinfra.engineering.drainage.network import build_network, design_network
from cityinfra.engineering.drainage.rainfall import IDF
from cityinfra.model.core import EngineeringObject, ObjectKind
from cityinfra.rules.framework import CheckStatus, RuleContext, RuleSet
from cityinfra.samples import E0, N0, SYNTHETIC_IDF, sample_drainage_with_existing

IDF_ = IDF(SYNTHETIC_IDF)


def rules() -> RuleContext:
    return RuleContext([RuleSet.load("cpheeo_storm_water_2019.yaml"), RuleSet.load("project_drainage_defaults.yaml")])


def run(pr, r=None):
    r = r or rules()
    net = build_network(pr, r)
    return net, design_network(net, r, IDF_, 5, "residential")


def obj(pr, name):
    return next(o for o in pr.objects.values() if o.name == name)


def check(res, name, oname):
    return next(c for c in res.all_checks() if c.check == name and c.object_label == oname)


class ExistingDrainTests(unittest.TestCase):
    def setUp(self):
        self.pr = sample_drainage_with_existing()
        self.r = rules()
        self.net, self.res = run(self.pr, self.r)
        self.ex = {a.drain.obj.name: a for a in self.res.existing}
        self.dd = {d.drain.obj.name: d for d in self.res.drains}

    def test_usable_capacity_is_the_silted_section_at_the_freeboard_depth(self):
        a = self.ex["NALLAH-2"]
        d = a.drain
        sec = Section("trapezoidal", 1.5 - 0.3, 2.0 + 2 * 1.5 * 0.3, 1.5)
        self.assertEqual(d.flow_section, sec)
        n = self.r.value("manning_n_drains")["earth"]
        self.assertAlmostEqual(a.q_usable, q_at(sec, 1.2 - self.r.value("min_freeboard_m"), d.slope, n))
        clean = Section("trapezoidal", 1.5, 2.0, 1.5)
        self.assertAlmostEqual(a.q_desilted, q_at(clean, 1.5 - self.r.value("min_freeboard_m"), d.slope, n))
        self.assertGreater(a.q_desilted, a.q_usable)

    def test_flow_today_counts_only_existing_areas_and_recorded_inflow(self):
        today = design_network(__import__("cityinfra.engineering.drainage.network", fromlist=["x"]).existing_only(self.net),
                               self.r, IDF_, 5, "residential", _assess_existing=False)
        self.assertEqual({d.drain.obj.name for d in today.drains}, {"NALLAH-1", "NALLAH-2"})
        n1 = self.ex["NALLAH-1"]
        village = next(c for c in self.net.catchments if c.obj.name == "VILLAGE")
        q_village = village.c * village.area_ha * IDF_.intensity(self.dd["NALLAH-1"].tc_min, 5) / 360
        self.assertAlmostEqual(n1.q_existing, q_village + 0.4)              # + recorded inflow at EX1
        self.assertAlmostEqual(n1.added, 0.0)                               # nothing new joins above EX2
        n2 = self.ex["NALLAH-2"]
        self.assertGreater(n2.added, 1.0)                                   # the new sector joins at EX2
        self.assertAlmostEqual(n2.residual, n2.q_usable - n2.q_existing)
        self.assertAlmostEqual(n2.q_total, self.dd["NALLAH-2"].flow)

    def test_existing_drains_are_assessed_not_redesigned(self):
        names = {c.check for c in self.dd["NALLAH-2"].checks}
        self.assertEqual(names, {"existing_capacity", "existing_silt"})
        self.assertEqual(check(self.res, "existing_capacity", "NALLAH-2").status, CheckStatus.PASS)

    def test_short_capacity_and_already_overloaded(self):
        obj(self.pr, "NALLAH-2").attributes.update(width_m=0.6, height_m=0.8)
        _, res = run(self.pr, self.r)
        c = check(res, "existing_capacity", "NALLAH-2")
        self.assertEqual(c.status, CheckStatus.FAIL)
        self.assertTrue(c.message.startswith("Short by") or c.message.startswith("Already"), c.message)
        obj(self.pr, "EX1").attributes["external_inflow_m3s"] = 20.0
        _, res = run(self.pr, self.r)
        self.assertTrue(check(res, "existing_capacity", "NALLAH-1").message.startswith("Already overloaded today"))
        a = next(x for x in res.existing if x.drain.obj.name == "NALLAH-1")
        self.assertLess(a.residual, 0)
        alts = next(d for d in res.drains if d.drain.obj.name == "NALLAH-1").alternatives
        self.assertTrue(any("Desilting" in t for t in alts))

    def test_nearly_full_is_a_warning(self):
        a = self.ex["NALLAH-2"]
        ratio = a.q_total / a.q_usable
        r = rules()
        r.override("existing_drain_warning_ratio", ratio * 0.95, reason="test", by="test")
        _, res = run(self.pr, r)
        self.assertEqual(check(res, "existing_capacity", "NALLAH-2").status, CheckStatus.WARNING)


class VillageAndOutfallTests(unittest.TestCase):
    def setUp(self):
        self.pr = sample_drainage_with_existing()

    def test_village_outlet_compares_receiving_water_level_with_fixed_mouth_level(self):
        _, res = run(self.pr)
        c = check(res, "village_outlet", "VILLAGE")
        dd = next(d for d in res.drains if d.drain.obj.name == "NALLAH-1")
        wl = dd.drain.us_invert + dd.drain.silt_m + dd.state.depth
        self.assertAlmostEqual(c.actual, wl)
        self.assertAlmostEqual(c.limit, 215.3 - 0.15)
        self.assertEqual(c.status, CheckStatus.FAIL if wl > 215.15 else CheckStatus.PASS)
        obj(self.pr, "VILLAGE").attributes["outlet_level"] = wl + 0.2
        _, res = run(self.pr)
        self.assertEqual(check(res, "village_outlet", "VILLAGE").status, CheckStatus.PASS)
        del obj(self.pr, "VILLAGE").attributes["outlet_level"]
        _, res = run(self.pr)
        self.assertEqual(check(res, "village_outlet", "VILLAGE").status, CheckStatus.NOT_EVALUATED)

    def test_outfall_flood_level_and_bed(self):
        of = obj(self.pr, "OF1")
        of.attributes["tailwater_level"] = 214.2
        _, res = run(self.pr)
        self.assertEqual(check(res, "outfall_tailwater", "NALLAH-2").status, CheckStatus.WARNING)
        of.attributes["tailwater_level"] = 214.5                    # above the ground at the outfall
        _, res = run(self.pr)
        self.assertEqual(check(res, "outfall_tailwater", "NALLAH-2").status, CheckStatus.FAIL)
        of.attributes["invert_level"] = 213.2
        _, res = run(self.pr)
        self.assertEqual(check(res, "outfall_invert", "NALLAH-2").status, CheckStatus.FAIL)

    def test_ground_level_from_survey_points(self):
        dn1 = obj(self.pr, "DN1")
        del dn1.attributes["ground_level"]
        x, y = dn1.geometry["coordinates"][:2]
        for dx, dy, z in ((-30, -30, 216.0), (30, -30, 216.6), (0, 40, 216.9)):
            self.pr.add(EngineeringObject(ObjectKind.TERRAIN_POINT, {"type": "Point", "coordinates": [x + dx, y + dy, z]}))
        net = build_network(self.pr, rules())
        self.assertNotIn("DN1: ground_level missing.", net.errors)
        self.assertTrue(any("taken from the survey points" in n for n in net.notes))
        self.assertTrue(216.0 < dn1.attr("ground_level") < 216.9)


class ProposalTests(unittest.TestCase):
    def test_proposed_drains_pass_their_own_checks_when_accepted(self):
        pr = sample_drainage_with_existing()
        r = rules()
        p = propose(pr, r, IDF_, 5)
        self.assertEqual(set(p.drains), {obj(pr, n).id for n in ("D1", "D2", "D3")})
        for oid, rec in p.drains.items():
            o = pr.objects[oid]
            for k in ("diameter_mm", "width_m", "height_m", "us_invert", "ds_invert", "side_slope", "closed"):
                if k in rec:
                    o.attributes[k] = rec[k]
            self.assertGreater(rec["us_invert"], rec["ds_invert"])
        _, res = run(pr, r)
        for d in res.drains:
            if d.drain.existing:
                continue
            bad = [c for c in d.checks if c.status != CheckStatus.PASS]
            self.assertFalse(bad, [(c.check, c.message) for c in bad])
        d1, d2 = p.drains[obj(pr, "D1").id], p.drains[obj(pr, "D2").id]
        self.assertLessEqual(d2["us_invert"], d1["ds_invert"] + 1e-9)        # no step up at DN2
        self.assertLessEqual(d2["us_invert"] + d2["diameter_mm"] / 1000,
                             d1["ds_invert"] + d1["diameter_mm"] / 1000 + 1e-9)   # crowns matched

    def test_conflict_with_existing_bed_is_reported(self):
        p = propose(sample_drainage_with_existing(), rules(), IDF_, 5)
        self.assertTrue(any("below the bed of the existing drain NALLAH-2" in i for i in p.issues), p.issues)

    def test_open_drains_follow_the_ground_and_keep_the_village_free(self):
        pr = sample_drainage_with_existing()
        for n in ("D1", "D2"):
            obj(pr, n).attributes["shape"] = "rectangular"
        p = propose(pr, rules(), IDF_, 5)
        d1 = p.drains[obj(pr, "D1").id]
        self.assertAlmostEqual(d1["us_invert"], 216.5 - d1["height_m"])         # top of an open drain at ground level
        self.assertGreaterEqual(d1["height_m"], d1["flow_depth_m"] + rules().value("min_freeboard_m") - 1e-9)

    def test_connection_below_existing_bed_fails_the_check(self):
        pr = sample_drainage_with_existing()
        obj(pr, "D3").attributes["ds_invert"] = 213.5          # existing NALLAH-2 bed 213.8 + 0.3 silt
        _, res = run(pr)
        c = check(res, "connection_level", "D3")
        self.assertEqual(c.status, CheckStatus.FAIL)
        self.assertIn("0.60 m too low", c.message)

    def test_missing_ground_level_stops_the_proposal(self):
        pr = sample_drainage_with_existing()
        del obj(pr, "DN2").attributes["ground_level"]
        p = propose(pr, rules(), IDF_, 5)
        self.assertFalse(p.drains)
        self.assertTrue(any("DN2: ground level missing" in i for i in p.issues))


if __name__ == "__main__":
    unittest.main()
