"""Browser audit of the City Infrastructure Designer (docs/platform/UI_GUIDELINES.md).

Starts the app on a free port, then in Chromium, for every module:
  * walks through the states a user sees – empty sheet with the first-visit guide, every
    drawing tool, the example drawing, the 'still missing' list, the check results, each kind
    of object selected, the Help guide – and fails if any visible control has no explanation;
  * checks that the example passes through the check without errors;
  * fails on any browser console error.

    pip install playwright && python -m playwright install chromium
    python ui_audit/check_app.py [screenshot-folder]
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright  # noqa: E402

from cityinfra.app.server import serve  # noqa: E402

UNEXPLAINED = """() => {
  const bad = [];
  for (const e of document.querySelectorAll('button, input, select, a[href], summary')) {
    if (e.closest('[hidden]') || e.type === 'file') continue;
    const r = e.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    if (!e.closest('[data-help]')) bad.push(e.outerHTML.slice(0, 140));
  }
  return bad;
}"""


def main(shots: Path | None) -> int:
    httpd = serve(0, open_browser=False)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    problems: list[str] = []
    console: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for width, height in ((1440, 900), (420, 860)):
            page = browser.new_page(viewport={"width": width, "height": height})
            page.on("console", lambda m: m.type == "error" and console.append(m.text))
            page.on("pageerror", lambda e: console.append(f"page error: {e}"))

            def audit(state: str) -> None:
                for b in page.evaluate(UNEXPLAINED):
                    problems.append(f"[{width}px] {state}: control without explanation: {b}")

            page.goto(url)
            page.evaluate("localStorage.clear()")
            page.reload()
            page.wait_for_selector(".tile")
            audit("start page")
            modules = page.evaluate("cityinfra.S.modules.map(m => m.id)")
            for i, m in enumerate(modules):
                page.goto(url)
                page.wait_for_selector(".tile")
                page.locator(".tile").nth(i).click()
                page.wait_for_selector("#work:not([hidden])")
                page.wait_for_timeout(150)
                if page.locator("#guide").count():
                    audit(f"{m}: first-visit guide")
                    page.keyboard.press("Escape")
                audit(f"{m}: empty sheet")
                for tool in page.evaluate("[...document.querySelectorAll('[data-tool]')].map(b => b.dataset.tool)"):
                    page.click(f"[data-tool={tool}]")
                    audit(f"{m}: tool {tool}")
                page.keyboard.press("Escape")
                page.click("#btn-example")
                page.wait_for_timeout(300)
                audit(f"{m}: example loaded")
                page.click("#btn-check")
                page.wait_for_function("!document.querySelector('#btn-check').disabled", timeout=120000)
                page.wait_for_timeout(200)
                if page.locator("#results .errors").count():
                    problems.append(f"{m}: example shows errors: {page.inner_text('#results .errors')[:300]}")
                if page.locator(".toggle-ok").count():
                    page.click(".toggle-ok")
                audit(f"{m}: results")
                if shots and width > 1000:
                    page.screenshot(path=str(shots / f"{m}-results.png"))
                kinds = page.evaluate("""[...new Set(cityinfra.S.feats.filter(f => cityinfra.KINDS[f.kind] && !cityinfra.KINDS[f.kind].passive)
                                         .map(f => f.kind))]""")
                for k in kinds:
                    page.evaluate(f"""(() => {{ const f = cityinfra.S.feats.find(x => x.kind === '{k}');
                                     cityinfra.select(f.id); }})()""")
                    page.wait_for_timeout(50)
                    for d in page.locator("#side details").all():
                        d.evaluate("e => e.open = true")
                    audit(f"{m}: {k} selected")
                page.keyboard.press("F1")
                audit(f"{m}: help guide")
                rows = page.locator("#guide tr").count()
                if rows < 10:
                    problems.append(f"{m}: help guide lists only {rows} rows")
                page.keyboard.press("Escape")
                page.click("#btn-clear")
                page.click("#btn-check")
                page.wait_for_timeout(100)
                audit(f"{m}: empty check")
            if shots:
                page.screenshot(path=str(shots / f"narrow-{width}.png"))
            page.close()
        browser.close()
    httpd.shutdown()
    problems += [f"console: {c}" for c in console]
    for pr in problems:
        print(pr)
    print(f"{len(problems)} problem(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    sys.exit(main(out))
