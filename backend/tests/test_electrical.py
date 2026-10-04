"""Electrical distribution: demand, transformer loading, cable current, voltage drop."""

import math
import unittest

from cityinfra.engineering.electrical.network import analyse, build_network, schedules
from cityinfra.model.core import EngineeringObject, ObjectKind, RelationType
from cityinfra.rules.framework import CheckStatus, RuleContext, RuleSet
from cityinfra.samples import sample_electrical_project

SQ3 = math.sqrt(3)


def el_rules() -> RuleContext:
    return RuleContext([RuleSet.load("electrical_cables_sample.yaml"), RuleSet.load("project_electrical_defaults.yaml")])


class ElectricalTests(unittest.TestCase):
    def setUp(self):
        self.rules = el_rules()
        self.pr = sample_electrical_project()
        self.net = build_network(self.pr, self.rules)
        self.res = analyse(self.net, self.rules)
        self.by = {cr.cable.obj.name: cr for cr in self.res.cables.values()}
        self.lib = self.rules.value("cable_library")

    def test_network_levels(self):
        self.assertEqual(self.net.errors, [])
        self.assertEqual(self.by["H1"].cable.level, "HT")
        self.assertEqual(self.by["L1"].cable.level, "LT")
        self.assertAlmostEqual(self.by["L1"].cable.v_nominal, 433)
        self.assertAlmostEqual(self.by["H1"].cable.v_nominal, 11000)

    def test_three_phase_current_and_drop_by_hand(self):
        cr = self.by["L2"]                                   # LD1: 150 kW × 0.6, pf 0.9
        s = 150 * 0.6 / 0.9 * 1000
        i = s / (SQ3 * 433)
        self.assertAlmostEqual(cr.current_a, i, places=6)
        spec, L = self.lib["LT-AL-3.5C-95"], cr.cable.length_km
        dv = SQ3 * i * L * (spec["r_ohm_km"] * 0.9 + spec["x_ohm_km"] * math.sqrt(1 - 0.81))
        self.assertAlmostEqual(cr.drop_pct, dv / 433 * 100, places=6)
        self.assertAlmostEqual(cr.cum_drop_pct, self.by["L1"].drop_pct + cr.drop_pct, places=9)

    def test_single_phase_service(self):
        cr = self.by["S1"]
        i = 4 * 1.0 / 0.95 * 1000 / (433 / SQ3)
        self.assertAlmostEqual(cr.current_a, i, places=6)
        spec = self.lib["LT-AL-2C-16"]
        dv = 2 * i * cr.cable.length_km * (spec["r_ohm_km"] * 0.95 + spec["x_ohm_km"] * math.sqrt(1 - 0.95 ** 2))
        self.assertAlmostEqual(cr.drop_pct, dv / (433 / SQ3) * 100, places=6)

    def test_diversity_and_transformer_demand(self):
        fp1 = self.res.demand[self.pr.by_name("FP1").id]
        self.assertAlmostEqual(fp1.p_kw, (90 + 90 + 72) / 1.2)
        tx1 = self.res.demand[self.pr.by_name("TX1").id]
        self.assertAlmostEqual(tx1.p_kw, (fp1.p_kw + 4.0) / 1.3)
        h1 = self.by["H1"]
        self.assertAlmostEqual(h1.current_a, tx1.s_kva * 1000 / (SQ3 * 11000), places=6)

    def test_drop_restarts_at_transformer(self):
        self.assertAlmostEqual(self.by["L6"].cum_drop_pct, self.by["L6"].drop_pct, places=12)

    def test_expected_failures_and_proposals(self):
        fails = {(c.object_label, c.check) for c in self.res.failing()}
        self.assertEqual(fails, {("L5", "cable_current"), ("LD5", "voltage_drop"), ("TX2", "transformer_loading")})
        text = " ".join(self.res.proposals)
        self.assertIn("LT-AL-3.5C-120", text)
        self.assertIn("at least 315 kVA", text)
        self.assertIn("parallel runs", text)

    def test_schedules(self):
        s = schedules(self.net, self.res, self.rules)
        self.assertEqual(len(s["transformers"]), 2)
        self.assertEqual(len(s["cables"]), 10)
        self.assertEqual({l["load"] for l in s["loads"]}, {"LD1", "LD2", "LD3", "LD4", "LD5", "SL1"})

    def test_topology_errors(self):
        pr = sample_electrical_project()
        fp1, ld4 = pr.by_name("FP1"), pr.by_name("LD4")
        g = {"type": "LineString", "coordinates": [fp1.geometry["coordinates"], ld4.geometry["coordinates"]]}
        c = pr.add(EngineeringObject(ObjectKind.ELECTRICAL_CABLE, g, name="LX", attributes={"cable_type": "LT-AL-3.5C-95"}))
        pr.relate(c, fp1, RelationType.UPSTREAM_NODE)
        pr.relate(c, ld4, RelationType.DOWNSTREAM_NODE)
        pr.by_name("L2").attributes["cable_type"] = "HT-AL-3C-185"     # 11 kV cable on LT: flagged
        pr.by_name("H1").attributes["cable_type"] = "LT-AL-3.5C-95"    # LT cable on 11 kV: must fail
        errs = "\n".join(build_network(pr, self.rules).errors)
        self.assertIn("LD4: fed by more than one cable", errs)
        self.assertIn("H1: 1.1 kV grade cable used on the HT side", errs)
        self.assertIn("L2: 11 kV grade cable used on the LT side", errs)

    def test_unknown_cable_type_is_an_error(self):
        pr = sample_electrical_project()
        pr.by_name("L3").attributes["cable_type"] = "MYSTERY"
        self.assertTrue(any("MYSTERY" in e for e in build_network(pr, self.rules).errors))

    def test_sample_cable_data_flagged_unverified(self):
        self.assertIn("cable_library", " ".join(self.res.unverified))


if __name__ == "__main__":
    unittest.main()
