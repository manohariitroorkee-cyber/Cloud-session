"""The command line must describe every option (docs/platform/UI_GUIDELINES.md)."""

import contextlib
import io
import unittest

from cityinfra import cli


class CliHelpTests(unittest.TestCase):
    def test_every_option_has_help(self):
        import argparse
        captured = {}
        real = argparse.ArgumentParser.parse_args

        def grab(self, *a, **k):
            captured["p"] = self
            raise SystemExit(0)

        argparse.ArgumentParser.parse_args = grab
        try:
            with self.assertRaises(SystemExit):
                cli.main([])
        finally:
            argparse.ArgumentParser.parse_args = real
        parser = captured["p"]
        undocumented = [a.dest for a in parser._actions if not (a.help and a.help.strip())]
        self.assertEqual(undocumented, [])
        self.assertTrue(parser.description and parser.epilog)

    def test_help_text_prints(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            cli.main(["-h"])
        self.assertIn("not a certified", out.getvalue())
        self.assertIn("Examples:", out.getvalue())


if __name__ == "__main__":
    unittest.main()
