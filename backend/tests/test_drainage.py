"""Storm-water drainage: rainfall, open-channel hydraulics, Rational design, SWMM."""

import math
import unittest

from cityinfra.engineering.common.open_channel import Section, normal_flow, q_at
from cityinfra.engineering.drainage.network import build_network, design_network
from cityinfra.engineering.drainage.rainfall import IDF, alternating_block, kirpich_tc_min
from cityinfra.engines.base import EngineError, EngineUnavailable
from cityinfra.rules.framework import CheckStatus, RuleContext, RuleSet
from cityinfra.samples import SYNTHETIC_IDF, sample_drainage_project


def drain_rules() -> RuleContext:
    return RuleContext([RuleSet.load("cpheeo_storm_water_2019.yaml"), RuleSet.load("project_drainage_defaults.yaml")])


IDF_ = IDF(SYNTHETIC_IDF)


class RainfallTests(unittest.TestCase):
    def test_power_idf(self):
        self.assertAlmostEqual(IDF_.intensity(60, 5), 1500 / 75 ** 0.8)
        with self.assertRaises(KeyError):
            IDF_.intensity(60, 25)

    def test_table_idf_interpolates_and_refuses_extrapolation(self):
        t = IDF({"form": "table", "durations_min": [10, 60], "return_periods": {"5": [120.0, 40.0]}})
        self.assertAlmostEqual(t.intensity(10, 5), 120.0)
        mid = math.exp(math.log(120) + (math.log(30) - math.log(10)) / (math.log(60) - math.log(10))
                       * (math.log(40) - math.log(120)))
        self.assertAlmostEqual(t.intensity(30, 5), mid)
        with self.assertRaises(ValueError):
            t.intensity(120, 5)

    def test_alternating_block_preserves_idf_depths(self):
        blocks = alternating_block(IDF_, 5, 120, 5)
        self.assertEqual(len(blocks), 24)
        total = sum(b * 5 / 60 for b in blocks)
        self.assertAlmostEqual(total, IDF_.intensity(120, 5) * 2, places=9)
        self.assertAlmostEqual(max(blocks), IDF_.intensity(5, 5), places=9)
        self.assertEqual(blocks.index(max(blocks)), round(0.5 * 23))

    def test_kirpich(self):
        self.assertAlmostEqual(kirpich_tc_min(1000, 0.01), 0.0195 * 1000 ** 0.77 * 0.01 ** -0.385)


class OpenChannelTests(unittest.TestCase):
    def test_normal_depth_inverts_manning(self):
        for sec in (Section("rectangular", 1.5, 1.2), Section("trapezoidal", 1.2, 1.0, 1.5),
                    Section("circular", 0.9, 0.9, closed=True)):
            q = q_at(sec, 0.6, 0.002, 0.015)
            st = normal_flow(sec, 0.002, 0.015, q)
            self.assertAlmostEqual(st.depth, 0.6, places=6)

    def test_rectangular_area_and_velocity(self):
        st = normal_flow(Section("rectangular", 1.0, 2.0), 0.001, 0.015, 1.0)
        self.assertAlmostEqual(st.velocity, 1.0 / (2.0 * st.depth), places=9)

    def test_closed_box_capacity_below_full_bore_formula_peak(self):
        box = Section("rectangular", 1.0, 1.0, closed=True)
        st = normal_flow(box, 0.002, 0.015, 10.0)
        self.assertFalse(st.capacity_ok)
        self.assertLess(st.q_capacity, q_at(Section("rectangular", 1.0, 1.0), 1.0, 0.002, 0.015) * 1.2)


class RationalDesignTests(unittest.TestCase):
    def setUp(self):
        self.pr = sample_drainage_project()
        self.rules = drain_rules()
        self.net = build_network(self.pr, self.rules)
        self.res = design_network(self.net, self.rules, IDF_, 5, "residential")
        self.by = {d.drain.obj.name: d for d in self.res.drains}

    def test_network_valid(self):
        self.assertEqual(self.net.errors, [])
        self.assertEqual([self.net.drains[k].obj.name for k in self.net.order], ["D1", "D2", "D3"])

    def test_composite_c_and_rational_flow(self):
        c1 = next(c for c in self.net.catchments if c.obj.name == "C1")
        self.assertAlmostEqual(c1.c, 0.4 * 0.90 + 0.35 * 0.90 + 0.25 * 0.35)
        self.assertAlmostEqual(c1.area_ha, 210 * 150 / 10000)
        d1 = self.by["D1"]
        self.assertAlmostEqual(d1.flow, c1.c * c1.area_ha * IDF_.intensity(d1.tc_min, 5) / 360)

    def test_time_of_concentration_grows_downstream(self):
        self.assertLess(self.by["D1"].tc_min, self.by["D2"].tc_min)
        self.assertLess(self.by["D2"].tc_min, self.by["D3"].tc_min)
        self.assertAlmostEqual(self.by["D2"].tc_min, self.by["D1"].tc_min + self.by["D1"].travel_min)

    def test_undersized_pipes_fail_and_get_alternatives(self):
        self.assertEqual({d.drain.obj.name for d in self.res.failing}, {"D1", "D2"})
        self.assertTrue(any("Ø1000" in a for a in self.by["D1"].alternatives))
        self.assertEqual(next(c for c in self.by["D3"].checks if c.check == "freeboard").status, CheckStatus.PASS)

    def test_return_period_checked_against_area_type(self):
        r = design_network(self.net, self.rules, IDF_, 2, "commercial")
        rp = next(c for c in r.checks if c.check == "return_period")
        self.assertEqual(rp.status, CheckStatus.FAIL)


def _swmm_ok():
    from cityinfra.engines.swmm import runner
    try:
        runner.engine_version()
        return True
    except EngineUnavailable:
        return False


@unittest.skipUnless(_swmm_ok(), "SWMM library not built")
class DrainageSwmmTests(unittest.TestCase):
    def setUp(self):
        from cityinfra.engines.swmm.drainage import run_drainage
        self.run = run_drainage
        self.rules = drain_rules()

    def test_undersized_network_floods(self):
        pr = sample_drainage_project()
        res = self.run(build_network(pr, self.rules), self.rules, IDF_, 5)
        self.assertLess(abs(res.runoff_continuity_error_pct), 1.0)
        self.assertLess(abs(res.flow_continuity_error_pct), 1.0)
        self.assertGreater(res.nodes[pr.by_name("DN1").id].peak_flooding, 0.0)
        self.assertIn("DESIGN_STORM", res.run.input_text)
        self.assertTrue(all(q > 0 for q in res.catchment_peak_runoff.values()))

    def test_upsized_network_does_not_flood(self):
        pr = sample_drainage_project()
        pr.by_name("D1").attributes["diameter_mm"] = 1000
        pr.by_name("D2").attributes["diameter_mm"] = 1200
        res = self.run(build_network(pr, self.rules), self.rules, IDF_, 5)
        self.assertTrue(all(n.peak_flooding < 1e-6 for n in res.nodes.values()))
        # outlet peak must not exceed total catchment peak runoff (no water created)
        out = res.drains[pr.by_name("D3").id].peak_flow
        self.assertLessEqual(out, sum(res.catchment_peak_runoff.values()) * 1.02)

    def test_missing_swmm_inputs_are_errors_not_assumptions(self):
        pr = sample_drainage_project()
        del pr.by_name("C2").attributes["impervious_pct"]
        with self.assertRaises(EngineError) as cm:
            self.run(build_network(pr, self.rules), self.rules, IDF_, 5)
        self.assertIn("impervious_pct", str(cm.exception))


if __name__ == "__main__":
    unittest.main()


class DrainageAuditRegressionTests(unittest.TestCase):
    def test_kirpich_against_imperial_original(self):
        # Kirpich (1940): tc [min] = 0.0078 · L_ft^0.77 · S^-0.385 ; L in metres × 3.28084
        L_m, S = 1000.0, 0.01
        imperial = 0.0078 * (L_m * 3.28084) ** 0.77 * S ** -0.385
        self.assertAlmostEqual(kirpich_tc_min(L_m, S), imperial, delta=0.01 * imperial)

    def test_surcharged_drain_travel_time_uses_capacity_velocity(self):
        pr = sample_drainage_project()
        rules = drain_rules()
        res = design_network(build_network(pr, rules), rules, IDF_, 5, "residential")
        d2 = next(d for d in res.drains if d.drain.obj.name == "D2")
        self.assertFalse(d2.state.capacity_ok)
        v_cap = d2.state.q_capacity / d2.drain.section.full_area()
        self.assertAlmostEqual(d2.travel_min, d2.drain.length / v_cap / 60, places=9)
        self.assertTrue(any("D2: surcharged" in n for n in res.notes))

    def test_lining_is_required(self):
        pr = sample_drainage_project()
        del pr.by_name("D1").attributes["lining"]
        self.assertTrue(any("lining missing" in e for e in build_network(pr, drain_rules()).errors))
