// Audit: every visible control on the page must have a help description.
//
//   NODE_PATH=$(npm root -g) node web-src/check-help.cjs [path/to/index.html] [screenshot-dir]
//
// Opens the page in Chromium (Playwright), walks through the main states –
// start, each item type selected, after a run, export dialog, confirmation
// bar, help guide – and lists any button, field, tab or link that has no
// entry in web-src/help.js. Exits 1 if any are missing.

const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const file = path.resolve(process.argv[2] || path.join(__dirname, "..", "index.html"));
const shots = process.argv[3];

const CONTROLS = "button, input, select, textarea, label[for], [role=tab], a[href]";

(async () => {
  const browser = await chromium.launch(process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {});
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto("file://" + file);
  await page.waitForFunction(() => window.__help);
  await page.waitForTimeout(600);

  const missing = new Map();
  async function audit(state) {
    const found = await page.evaluate((sel) => {
      const out = [];
      for (const el of document.querySelectorAll(sel)) {
        if (el.closest(".hl-drawer")) continue;              // the guide's own controls
        if (el.type === "file") continue;                     // described through its label
        const r = el.getBoundingClientRect();
        if (!r.width && !r.height) continue;                  // not visible
        // a label is covered when it has its own entry or the field it labels has one
        const covered = window.__help.describe(el) ||
          (el.matches("label[for]") && document.getElementById(el.htmlFor) && window.__help.describe(document.getElementById(el.htmlFor)));
        if (!covered) {
          out.push(el.id ? `#${el.id}` : `${el.tagName.toLowerCase()}${[...el.attributes].filter((a) => a.name.startsWith("data-")).map((a) => `[${a.name}=${a.value}]`).join("")} "${(el.textContent || el.getAttribute("aria-label") || "").trim().slice(0, 30)}"`);
        }
      }
      return out;
    }, CONTROLS);
    for (const f of found) missing.set(f, state);
    return found.length;
  }
  const shot = async (name) => shots && page.screenshot({ path: path.join(shots, name) });

  // First visit opens the guide automatically.
  const guideOpen = await page.isVisible(".hl-drawer");
  await shot("01-guide.png");
  await page.keyboard.press("Escape");

  await audit("start (network panel)");
  await page.hover("#btn-run");
  await page.waitForTimeout(250);
  const runTip = await page.textContent(".hl-tip");
  await shot("02-tooltip-run.png");

  // Select one item of each kind through the canvas.
  for (const sel of ['[data-node="J2"]', '[data-node="ESR"]', '[data-node="SUMP"]', '[data-link="P3"]', '[data-link="PU1"]']) {
    const el = await page.$(sel);
    if (el) { await el.click({ force: true }); await page.waitForTimeout(150); await audit(`selected ${sel}`); }
  }
  // focus a field to show its tooltip
  await page.click('[data-node="J2"]', { force: true });
  await page.focus('[data-k="demand"]');
  await page.waitForTimeout(250);
  const fieldTip = await page.textContent(".hl-tip");
  await shot("03-field-help.png");

  // Add a valve so the valve panel is audited too.
  await page.keyboard.press("Escape");
  await page.click("[data-tool=valve]");
  await page.click('[data-node="J7"]', { force: true });
  await page.click('[data-node="J8"]', { force: true });
  await page.waitForTimeout(150);
  await audit("valve selected");
  await page.keyboard.press("Escape");
  await page.click("[data-tool=select]");

  // Run, then audit results panel tabs and time controls.
  await page.click("#btn-run");
  await page.waitForFunction(() => !document.getElementById("time-ctl").hidden, null, { timeout: 30000 });
  for (const t of ["nodes", "links", "graph", "log"]) { await page.click(`[data-tab=${t}]`); await audit(`after run – ${t} tab`); }
  await page.hover("#time-range");
  await page.waitForTimeout(200);
  await shot("04-after-run.png");

  // Export dialog
  await page.click("#btn-export");
  await audit("export dialog");
  await page.click("#export-close");

  // Confirmation bar
  await page.click("#btn-new");
  await audit("confirm bar");
  await page.click("#nb-no");

  // Guide via button
  await page.click("#btn-help");
  const guideRows = await page.$$eval(".hl-drawer .hl-table tr", (r) => r.length);
  await shot("05-guide-button.png");

  await browser.close();
  const report = {
    file, guideOpenedOnFirstVisit: guideOpen, runTooltip: runTip, demandFieldTooltip: fieldTip,
    guideRows, pageErrors: errors, missing: [...missing].map(([k, v]) => `${k}  (${v})`),
  };
  console.log(JSON.stringify(report, null, 2));
  process.exit(missing.size || errors.length ? 1 : 0);
})();
