"""Engine adapters against the real EPA SWMM and EPANET libraries.

Skipped (not faked) when the engine libraries have not been built; run
engines/build_engines.sh first.
"""

import math
import unittest

from cityinfra.engineering.sewer.design import design_network
from cityinfra.engineering.sewer.network import build_network
from cityinfra.engineering.water.checks import pressure_checks
from cityinfra.engines.base import EngineUnavailable
from cityinfra.rules.framework import CheckStatus, RuleContext, RuleSet
from cityinfra.samples import sample_sewer_project, sample_water_project
from tests.test_foundation import sewer_rules


def _available(mod) -> bool:
    try:
        mod.engine_version()
        return True
    except EngineUnavailable:
        return False


from cityinfra.engines.epanet import adapter as epanet  # noqa: E402
from cityinfra.engines.swmm import adapter as swmm      # noqa: E402


def free_flowing_project():
    """The sample network with its two deliberate defects corrected."""
    pr = sample_sewer_project()
    pr.by_name("S2").attributes["ds_invert"] = 214.70
    pr.by_name("S3").attributes["ds_invert"] = 214.75
    pr.by_name("S4").attributes.update(us_invert=214.68, ds_invert=214.52)
    pr.by_name("S5").attributes.update(us_invert=214.50, ds_invert=214.34)
    pr.by_name("S6").attributes.update(diameter_mm=300, material="rcc", us_invert=214.32, ds_invert=214.16)
    pr.by_name("OUT1").attributes["invert_level"] = 214.16
    return pr


@unittest.skipUnless(_available(swmm), "SWMM library not built")
class SwmmTests(unittest.TestCase):
    def test_steady_flows_reproduce_design_flows(self):
        net = build_network(free_flowing_project())
        des = design_network(net, sewer_rules())
        res = swmm.run_sewer(net, des)
        self.assertEqual(res.run.engine_version, "5.2.4")
        self.assertLess(abs(res.flow_continuity_error_pct), 1.0)
        for d in des.pipes:
            link = res.links[d.pipe.obj.id]
            self.assertAlmostEqual(link.final_flow, d.design_flow, delta=0.01 * d.design_flow, msg=d.pipe.obj.name)
            # depths differ from uniform flow only through backwater; must stay close
            self.assertLess(abs(link.final_depth_ratio - d.state.depth_ratio), 0.1, d.pipe.obj.name)
        self.assertFalse(any(n.surcharged for n in res.nodes.values()))

    def test_bottleneck_causes_surcharge_and_flooding(self):
        pr = sample_sewer_project()                      # S6 is 150 mm: undersized
        net = build_network(pr)
        res = swmm.run_sewer(net, design_network(net, sewer_rules()))
        mh6 = res.nodes[pr.by_name("MH6").id]
        self.assertTrue(mh6.surcharged)
        self.assertGreater(mh6.max_overflow, 0.0)
        self.assertTrue(res.nodes[pr.by_name("MH5").id].surcharged)   # backwater propagates upstream

    def test_input_file_is_kept_for_traceability(self):
        net = build_network(free_flowing_project())
        res = swmm.run_sewer(net, design_network(net, sewer_rules()))
        self.assertIn("[CONDUITS]", res.run.input_text)
        self.assertIn("FLOW_ROUTING DYNWAVE", res.run.input_text)
        self.assertIn("EPA STORM WATER MANAGEMENT MODEL", res.run.report_text.upper())


@unittest.skipUnless(_available(epanet), "EPANET library not built")
class EpanetTests(unittest.TestCase):
    def setUp(self):
        self.pr = sample_water_project()
        self.res = epanet.run_water(self.pr)

    def test_mass_balance(self):
        demand = sum(o.attr("demand_lps") for o in self.pr.of_kind(epanet.ObjectKind.WATER_JUNCTION))
        supply = self.res.links[self.pr.by_name("W1").id].flow[0]
        self.assertAlmostEqual(supply, demand, places=4)

    def test_headloss_matches_hazen_williams(self):
        # SI Hazen–Williams: hf = 10.67 L Q^1.852 / (C^1.852 D^4.87)
        q, d, c, length = 0.017, 0.25, 130, 150.0
        hf = 10.67 * length * q ** 1.852 / (c ** 1.852 * d ** 4.87)
        self.assertAlmostEqual(self.res.links[self.pr.by_name("W1").id].headloss[0], hf, delta=0.01 * hf)

    def test_pressure_checks_cite_rules(self):
        rules = RuleContext([RuleSet.load("cpheeo_water_supply.yaml")])
        checks = pressure_checks(self.pr, self.res, rules)
        self.assertEqual(len(checks), 5)
        self.assertTrue(all(c.status == CheckStatus.PASS for c in checks))
        self.pr.by_name("J5").attributes["storeys"] = 6        # needs 22 m
        self.pr.objects[self.pr.by_name("ESR").id].attributes["head"] = 236.0
        res = epanet.run_water(self.pr)
        j5 = next(c for c in pressure_checks(self.pr, res, rules) if c.object_label == "J5")
        self.assertEqual(j5.status, CheckStatus.FAIL)


if __name__ == "__main__":
    unittest.main()
