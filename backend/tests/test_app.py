"""The simple web app: plain-language coverage, examples, and the local server."""

import json
import re
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from cityinfra.app import api
from cityinfra.app.plain import ADVICE, PLAIN, markdown_to_html, plain
from cityinfra.app.server import serve

PKG = Path(api.__file__).resolve().parents[1]
MODULES = [m["id"] for m in api.MODULES]
WORDED_WHERE_MADE = {"simulation_flooding", "simulation_surcharge", "level_impact"}


def source_check_names() -> set[str]:
    names = set()
    for f in (PKG / "engineering").rglob("*.py"):
        names |= set(re.findall(r'CheckResult\(\s*"(\w+)"', f.read_text(encoding="utf-8")))
    return names


class PlainWordsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = {m: api.check(m, api.example(m)) for m in MODULES}

    def test_every_check_in_the_code_has_plain_words_and_advice(self):
        names = source_check_names()
        self.assertGreater(len(names), 20)
        self.assertFalse(names - set(PLAIN), f"no plain wording for {sorted(names - set(PLAIN))}")
        self.assertFalse(names - set(ADVICE), f"no advice for {sorted(names - set(ADVICE))}")

    def test_every_check_produced_by_the_examples_has_plain_words(self):
        for m, r in self.results.items():
            for it in r["items"]:
                self.assertTrue(it["check"] in PLAIN or it["check"] in WORDED_WHERE_MADE, (m, it["check"]))
                self.assertTrue(it["title"] and it["status_word"])

    def test_examples_check_without_errors(self):
        for m, r in self.results.items():
            with self.subTest(module=m):
                self.assertEqual(r["errors"], [])
                self.assertTrue(r["items"], "an example must produce checks")
                self.assertIn(r["tone"], ("pass", "warning", "fail"))
                self.assertTrue(r["report_markdown"].strip())
                for it in r["items"]:
                    if it["status"] in ("fail", "warning") and it["check"] in ADVICE:
                        self.assertTrue(it["fix"], f"{m}: {it['check']} has no advice")

    def test_plain_status_titles(self):
        self.assertEqual(plain("capacity", "fail")[0], PLAIN["capacity"][0])
        self.assertEqual(plain("capacity", "pass")[0], PLAIN["capacity"][1])
        self.assertTrue(plain("capacity", "not_evaluated")[0].startswith("Not checked"))
        self.assertEqual(plain("unknown_check", "fail")[0], "Unknown check")

    def test_road_geometry_errors_in_everyday_words(self):
        msg = ("Tangent PI1–PI2: PI1 and PI2 overlap by 2.00 m. Reduce radius or transition length, or move the PIs "
               "apart (largest radius at PI1: 80 m; largest radius at PI2: 90 m).")
        out = api._plain_road_error(msg)
        self.assertIn("bend 1 and bend 2", out)
        self.assertIn("2.00 m too long", out)
        self.assertNotIn("PI", out)
        self.assertEqual(api._plain_road_error("Road R1: PI3: deflection +20.00° but no curve given."),
                         "Road R1: bend 3 has no radius. Enter a radius for it.")
        self.assertEqual(api._plain_road_error("something else"), "something else")

    def test_report_html_is_escaped(self):
        h = markdown_to_html("# T <x>\n\n| a | b |\n|---|---|\n| **1** | <script> |\n\n- item")
        for part in ("<h1>T &lt;x&gt;</h1>", "<b>1</b>", "&lt;script&gt;", "<li>item</li>"):
            self.assertIn(part, h)


class CheckInputTests(unittest.TestCase):
    CRS = {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::32643"}}

    def test_missing_input_is_reported_not_crashed(self):
        fc = {"type": "FeatureCollection", "crs": self.CRS, "features": [
            {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[704000, 3193000], [704100, 3193000]]},
             "properties": {"kind": "sewer_pipe", "name": "S1"}}]}
        r = api.check("sewer", {"features": fc})
        self.assertEqual(r["tone"], "error")
        self.assertTrue(r["errors"])
        r = api.check("road", {"features": {**fc, "features": []}})
        self.assertIn("Draw a road", r["errors"][0])

    def test_lon_lat_drawing_is_refused(self):
        fc = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [77.2, 28.6]},
             "properties": {"kind": "manhole", "name": "M"}}]}
        r = api.check("sewer", {"features": fc})
        self.assertEqual(r["tone"], "error")
        self.assertIn("coordinate", r["errors"][0])

    def test_freehand_road_ending_on_a_curve_is_fitted(self):
        import math
        pts = [[704000 + 650 * k / 59, 3193000 + 120 * math.sin(math.pi * k / 59 * 1.5)] for k in range(60)]
        road = {"type": "Feature", "geometry": {"type": "LineString", "coordinates": pts},
                "properties": {"kind": "road_alignment", "name": "R1", "horizontal_mode": "fit", "design_speed_kmh": 50,
                               "terrain": "plain", "kerbed": True, "profile": [[0, 100, 0], ["end", 97, 0]],
                               "template": {"strips": [{"type": "carriageway", "width": 3.5, "crossfall_pct": -2.5}]}}}
        r = api.check("road", {"features": {"type": "FeatureCollection", "crs": self.CRS, "features": [road]}})
        self.assertEqual(r["errors"], [])
        self.assertTrue(any("drawn freehand" in n for n in r["notes"]))
        self.assertTrue(any(o["properties"]["kind"] == "designed_centreline" for o in r["overlays"]))

    def test_options_offer_what_the_page_needs(self):
        o = api.options()
        for k in ("cables", "load_categories", "transformer_ratings_kva", "design_vehicles", "sewer_materials",
                  "sewer_diameters_mm", "drain_linings", "drain_diameters_mm", "area_types", "surfaces", "terrains"):
            self.assertTrue(o[k], k)
        self.assertLessEqual({"paved", "roof", "lawn_clay", "open_ground"}, set(o["surfaces"]))  # area presets
        self.assertIn("upvc", o["sewer_materials"])
        self.assertIn("rcc", o["drain_linings"])


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = serve(0, open_browser=False)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def get(self, path):
        with urllib.request.urlopen(self.url + path) as r:
            return r.status, r.headers.get("Content-Type"), r.read()

    def post(self, path, obj):
        req = urllib.request.Request(self.url + path, json.dumps(obj).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return r.status, r.headers.get("Content-Type"), r.read()

    def test_pages_and_api(self):
        st, ct, body = self.get("/")
        self.assertEqual(st, 200)
        self.assertIn("text/html", ct)
        self.assertIn(b"app.js", body)
        self.assertIn("javascript", self.get("/static/app.js")[1])
        self.assertEqual([m["id"] for m in json.loads(self.get("/api/modules")[2])], MODULES)
        ex = json.loads(self.get("/api/example/electrical")[2])
        st, _, body = self.post("/api/check/electrical", ex)
        self.assertEqual(json.loads(body)["module"], "electrical")
        st, ct, body = self.post("/api/report", {"markdown": "# Hello", "title": "T"})
        self.assertIn("text/html", ct)
        self.assertIn(b"<h1>Hello</h1>", body)

    def test_refuses_files_outside_static_and_unknown_modules(self):
        for path in ("/static/../server.py", "/static/%2e%2e/server.py", "/api/example/nothing"):
            with self.assertRaises(urllib.error.HTTPError) as e:
                self.get(path)
            self.assertEqual(e.exception.code, 404, path)

    def test_listens_on_this_computer_only(self):
        self.assertEqual(self.httpd.server_address[0], "127.0.0.1")


class PageHelpTests(unittest.TestCase):
    def test_every_control_explains_itself(self):
        static = PKG / "app" / "static"
        for tag in re.findall(r"<(?:button|select|input)\b[^>]*>", (static / "index.html").read_text(encoding="utf-8")):
            if 'type="file"' not in tag:
                self.assertIn("data-help=", tag)
        js = (static / "app.js").read_text(encoding="utf-8")
        starts = [m.end() for m in re.finditer(r"h\('button', \{", js)]
        self.assertGreater(len(starts), 15)
        for k in starts:                      # the button's own attributes run until the next element is made
            own = js[k:js.find("h('", k)]
            self.assertIn("data-help", own, js[k - 20:k + 100])


if __name__ == "__main__":
    unittest.main()
