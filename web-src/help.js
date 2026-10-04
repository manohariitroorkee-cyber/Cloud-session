// Help layer for the EPANET Network Designer.
//
// Every control on the page is described ONCE in the HELP registry below:
// its name, what it does, and its keyboard shortcut. The same registry drives
//   • the tooltip shown on hover, keyboard focus or long-press (touch),
//   • the status line at the bottom of the window,
//   • the "Help" guide, which lists every control,
//   • the audit (web-src/check-help.mjs) that fails if any control has no description.
//
// Plain JavaScript with no dependencies; build.mjs inlines it after app.js.
// Controls created later (inspector fields, dialogs) are picked up automatically.

(() => {
  "use strict";

  const K = (k) => `<kbd class="hl-kbd">${k}</kbd>`;

  // [selector, group, name, what it does, shortcut]
  const HELP = [
    // ---- top bar
    ["#net-title", "Top bar", "Network name", "Name of this network. Used in the exported file name.", ""],
    ["#btn-new", "Top bar", "New network", "Clears the drawing and starts an empty network. Asks before clearing; Undo brings it back.", ""],
    ["#btn-sample", "Top bar", "Load sample", "Loads a small example (colony supply from an ESR) so you can see how everything works.", ""],
    ["label[for=inp-import]", "Top bar", "Import .INP", "Opens an EPANET input file (.inp) from your computer and draws it on the plan.", ""],
    ["#btn-export", "Top bar", "Export .INP", "Shows the EPANET input file for this drawing, to copy or download. Opens in EPANET 2.2 / 2.3.", ""],
    ["#btn-run", "Top bar", "Run simulation", "Runs the EPANET hydraulic analysis on this computer and shows pressures, flows and velocities. No internet needed.", ""],
    ["#btn-help", "Top bar", "Help", "Opens this guide: the four steps to get started and what every button and field does.", "F1"],

    // ---- drawing tools
    ["[data-tool=select]", "Drawing tools", "Select", "Click an item to see and edit its properties. Drag a node to move it; drag empty space to pan.", "S"],
    ["[data-tool=junction]", "Drawing tools", "Junction", "Adds a demand point: a place where water is drawn, such as a colony or a block of houses. Click on the plan.", "J"],
    ["[data-tool=reservoir]", "Drawing tools", "Reservoir", "Adds a source with a fixed water level, such as a sump, river intake or main supply point. Click on the plan.", "R"],
    ["[data-tool=tank]", "Drawing tools", "Tank", "Adds a storage tank whose level rises and falls, such as an ESR or GLSR. Click on the plan.", "T"],
    ["[data-tool=pipe]", "Drawing tools", "Pipe", "Draws a pipe: click the start node, then the end node. Clicking empty space adds a junction there. Esc finishes.", "P"],
    ["[data-tool=pump]", "Drawing tools", "Pump", "Adds a pump: click the suction node, then the delivery node.", "M"],
    ["[data-tool=valve]", "Drawing tools", "Valve", "Adds a control valve (pressure-reducing, flow-control, etc.): click the upstream node, then the downstream node.", "V"],
    ["#btn-undo", "Drawing tools", "Undo", "Reverses the last change.", "Ctrl+Z"],
    ["#btn-redo", "Drawing tools", "Redo", "Repeats the change you just undid.", "Ctrl+Y"],

    // ---- plan
    ["#canvas", "Plan", "Drawing area", "The network plan. Scroll to zoom, drag empty space to pan. After a run, junctions are coloured by pressure.", ""],
    ["#zoom-in", "Plan", "Zoom in", "Enlarges the plan around its centre.", "scroll up"],
    ["#zoom-out", "Plan", "Zoom out", "Shrinks the plan around its centre.", "scroll down"],
    ["#zoom-fit", "Plan", "Fit", "Zooms so the whole network fits in the window.", ""],
    ["#legend", "Plan", "Pressure legend", "Colour key for junction pressures. Red outline = below the minimum pressure set in Settings.", ""],

    // ---- results panel
    ["[data-tab=log]", "Results panel", "Log", "Messages from the program: what was loaded, run progress, warnings and errors.", ""],
    ["[data-tab=nodes]", "Results panel", "Nodes", "Table of pressure, head and demand at every node for the selected time.", ""],
    ["[data-tab=links]", "Results panel", "Links", "Table of flow, velocity and head loss in every pipe, pump and valve for the selected time.", ""],
    ["[data-tab=graph]", "Results panel", "Graph", "Plots the selected item's result over the whole simulation period. Click the graph to jump to that time.", ""],
    ["#run-state", "Results panel", "Run status", "Shows whether the results match the drawing. 'Results out of date' means something changed: run again.", ""],
    ["#play", "Results panel", "Play", "Steps through the simulation hours one after another so you can watch pressures change.", ""],
    ["#time-range", "Results panel", "Time slider", "Chooses the simulation time whose results are shown on the plan and in the tables.", ""],
    ["#time-select", "Results panel", "Time step", "Picks an exact simulation time from the list.", ""],

    // ---- properties panel (appears when something is selected)
    ["#btn-delete", "Properties panel", "Delete", "Removes the selected item (and pipes attached to a deleted node). Undo brings it back.", "Del"],
    ["#btn-reverse", "Properties panel", "Reverse", "Swaps the start and end nodes, so the positive flow direction is reversed.", ""],
    ["[data-goto-link]", "Properties panel", "Connected pipe", "Opens the properties of this connected pipe, pump or valve.", ""],
    ["#pat-add", "Properties panel", "Add 24-hour pattern", "Adds a daily demand pattern: 24 hourly multipliers (1 = average demand) to model peak and off-peak hours.", ""],
    ["[data-pat-del]", "Properties panel", "Remove pattern", "Deletes this pattern. Junctions that used it return to constant demand.", ""],
    ["[data-pat-id]", "Properties panel", "Pattern name", "Name of the pattern, chosen in a junction's Demand pattern box.", ""],
    ["[data-pat-mult]", "Properties panel", "Multipliers", "One multiplier per pattern time step, separated by commas. 1.0 = average; 2.0 = twice the average demand.", ""],

    // ---- notices and dialogs
    ["#nb-yes", "Dialogs", "Confirm", "Goes ahead with the action described in the message.", ""],
    ["#nb-no", "Dialogs", "Cancel", "Keeps things as they are.", "Esc"],
    ["#export-text", "Dialogs", "Input file text", "The EPANET .inp text for this network. You can select and copy any part of it.", ""],
    ["#export-copy", "Dialogs", "Copy text", "Copies the whole input file to the clipboard.", ""],
    ["#export-download", "Dialogs", "Download .inp", "Saves the input file to your computer.", ""],
    ["#export-close", "Dialogs", "Close", "Closes this window.", "Esc"],
  ];

  // Item and setting fields, by the data-k key the app gives each input.
  const FIELDS = {
    id: ["ID", "Short name of the item (no spaces, up to 31 characters). Used in tables and the .inp file."],
    elev: ["Elevation", "Level above datum. For a junction, its ground level (pressure is measured above it); for a tank, the level of its floor."],
    demand: ["Base demand", "Average water drawn at this junction. Multiplied hour by hour by the demand pattern, if one is chosen."],
    pattern: ["Pattern", "How the demand (or reservoir level) varies through the day. 'None' keeps it constant."],
    head: ["Water level (head)", "Fixed water surface level of the source, above datum."],
    initLevel: ["Initial level", "Water depth in the tank at the start of the simulation."],
    minLevel: ["Minimum level", "Lowest allowed water depth. Below this the tank is treated as empty."],
    maxLevel: ["Maximum level", "Highest water depth (overflow). Above this the tank cannot fill."],
    diameter: ["Diameter", "Internal diameter of the pipe or valve, or of the tank for a cylindrical tank."],
    autoLength: ["Length from drawing", "When ticked, the pipe length is taken from the drawn distance. Untick to type the real length."],
    length: ["Length", "Pipe length used in the calculation."],
    roughness: ["Roughness", "Pipe wall roughness for the head-loss formula: Hazen-Williams C (higher = smoother, e.g. 130–140 for DI/HDPE)."],
    minorLoss: ["Minor loss coefficient", "Extra losses from bends and fittings. 0 if not known."],
    status: ["Status", "Whether the pipe, pump or valve starts open, closed or (for a pipe) as a one-way check valve."],
    pumpFlow: ["Design flow", "Flow at the pump's duty point (from the pump data sheet)."],
    pumpHead: ["Design head", "Head the pump delivers at its duty point."],
    controlTank: ["Controlled by tank", "Switches the pump on and off by the water level in this tank."],
    startLevel: ["Start level", "The pump starts when the tank falls below this level."],
    stopLevel: ["Stop level", "The pump stops when the tank rises above this level."],
    valveType: ["Valve type", "PRV limits downstream pressure; PSV keeps upstream pressure; FCV limits flow; TCV adds a fixed loss; PBV adds a fixed pressure drop."],
    setting: ["Setting", "The valve's target: pressure for PRV/PSV/PBV, flow for FCV, loss coefficient for TCV."],
    units: ["Flow units", "Units for flow. Choosing an SI unit (L/s, m³/h, MLD …) makes lengths and levels metres."],
    headloss: ["Head-loss formula", "Formula used for pipe friction. Hazen-Williams is usual for water mains in India."],
    duration: ["Duration", "Length of the simulation in hours. 0 gives a single snapshot at average demand."],
    hydStep: ["Hydraulic time step", "How often, in minutes, results are calculated and reported during the run."],
    patStep: ["Pattern time step", "Time covered by each multiplier in a demand pattern (60 min = hourly)."],
    minPressure: ["Minimum pressure", "Pressure target. Junctions below it are outlined in red on the plan and in the tables."],
  };

  /* ----------------------------------------------------------- styles */
  // Plain CSS (no Tailwind) so this layer works without the page build.
  const css = `
  .hl-tip{position:fixed;z-index:60;max-width:19rem;pointer-events:none;border-radius:.5rem;padding:.55rem .7rem;
    background:var(--ink);color:var(--panel);font:12.5px/1.45 system-ui,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.22);
    opacity:0;transform:translateY(2px);transition:opacity .12s,transform .12s}
  .hl-tip.on{opacity:1;transform:none}
  .hl-tip b{display:block;font-size:13px;margin-bottom:.15rem}
  .hl-kbd{display:inline-block;margin-left:.35rem;padding:0 .3rem;border-radius:.25rem;border:1px solid currentColor;
    font:11px/1.4 ui-monospace,monospace;opacity:.85}
  .hl-status{display:flex;align-items:center;gap:.5rem;min-height:1.9rem;padding:.25rem 1rem;border-top:1px solid var(--line);
    background:var(--sunk);color:var(--muted);font:12px/1.4 system-ui,sans-serif}
  .hl-status b{color:var(--ink);font-weight:600}
  .hl-status .hl-i{flex:none;width:1.05rem;height:1.05rem;border-radius:50%;display:grid;place-items:center;
    background:var(--accent-soft);color:var(--accent);font-weight:700;font-size:11px}
  .hl-has-help{text-decoration:underline dotted var(--muted);text-underline-offset:3px;cursor:help}
  .hl-help-btn{font-weight:600}
  .hl-drawer-bg{position:fixed;inset:0;z-index:50;background:rgba(0,0,0,.35);display:flex;justify-content:flex-end}
  .hl-drawer{width:min(34rem,100%);height:100%;overflow-y:auto;background:var(--panel);color:var(--ink);
    box-shadow:-8px 0 32px rgba(0,0,0,.25);font:14px/1.5 system-ui,sans-serif}
  .hl-drawer header{position:sticky;top:0;display:flex;align-items:center;gap:.5rem;padding:.9rem 1.1rem;
    border-bottom:1px solid var(--line);background:var(--panel)}
  .hl-drawer h2{font-size:17px;font-weight:650;margin:0}
  .hl-drawer h3{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:1.3rem 0 .5rem}
  .hl-drawer section{padding:0 1.1rem 1rem}
  .hl-x{margin-left:auto;border:0;background:none;color:var(--muted);font-size:18px;cursor:pointer;padding:.2rem .4rem}
  .hl-steps{list-style:none;margin:0;padding:0;counter-reset:s}
  .hl-steps li{counter-increment:s;display:grid;grid-template-columns:1.8rem 1fr auto;gap:.6rem;align-items:start;
    padding:.6rem 0;border-bottom:1px solid var(--line)}
  .hl-steps li::before{content:counter(s);width:1.6rem;height:1.6rem;border-radius:50%;display:grid;place-items:center;
    background:var(--accent);color:var(--accent-ink);font-weight:700;font-size:13px}
  .hl-steps p{margin:.1rem 0 0;color:var(--muted);font-size:13px}
  .hl-go{border:1px solid var(--accent);color:var(--accent);background:none;border-radius:.4rem;padding:.25rem .6rem;
    font-size:12.5px;cursor:pointer;white-space:nowrap}
  .hl-go:hover{background:var(--accent-soft)}
  .hl-table{width:100%;border-collapse:collapse;font-size:13px}
  .hl-table td{padding:.4rem .3rem;border-bottom:1px solid var(--line);vertical-align:top}
  .hl-table td:first-child{font-weight:600;white-space:nowrap;padding-right:.8rem}
  .hl-table td:last-child{color:var(--muted)}
  .hl-note{font-size:12.5px;color:var(--muted);background:var(--sunk);border-radius:.4rem;padding:.6rem .75rem}
  .hl-flash{outline:3px solid var(--select)!important;outline-offset:2px;transition:outline-color .3s}`;
  const style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  /* ---------------------------------------------------- attach help */
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function describe(el) {
    if (el.dataset.k && FIELDS[el.dataset.k]) {
      const [name, what] = FIELDS[el.dataset.k];
      const label = el.closest("label.field")?.querySelector("span")?.textContent?.trim();
      return { name: label || name, what, key: "" };
    }
    for (const [sel, , name, what, key] of HELP) if (el.matches(sel)) return { name, what, key };
    return null;
  }

  function attach(root = document) {
    for (const [sel] of HELP) root.querySelectorAll?.(sel).forEach(mark);
    root.querySelectorAll?.("[data-k]").forEach((el) => {
      mark(el);
      const span = el.closest("label.field")?.querySelector(":scope > span");
      if (span && !span.classList.contains("hl-has-help")) { span.classList.add("hl-has-help"); span.dataset.hlFor = el.id; }
    });
  }
  function mark(el) {
    if (el.dataset.hl) return;
    const d = describe(el);
    if (!d) return;
    el.dataset.hl = "1";
    if (el.title) el.removeAttribute("title");     // our tooltip replaces the slow native one
    if (!el.getAttribute("aria-description")) el.setAttribute("aria-description", d.what);
  }

  /* ------------------------------------------- tooltip + status line */
  const tip = document.createElement("div");
  tip.className = "hl-tip";
  tip.setAttribute("role", "tooltip");
  document.body.appendChild(tip);

  const status = document.createElement("div");
  status.className = "hl-status";
  status.setAttribute("aria-live", "polite");
  const idle = `<span class="hl-i">i</span><span>Point at any button or field to see what it does. Press ${K("F1")} or <b>Help</b> for the full guide.</span>`;
  status.innerHTML = idle;
  document.getElementById("app")?.appendChild(status);

  let tipFor = null, hideT = 0;
  function target(e) {
    let el = e.target instanceof Element ? e.target : null;
    if (!el) return null;
    const lab = el.closest(".hl-has-help");
    if (lab?.dataset.hlFor) return document.getElementById(lab.dataset.hlFor);
    return el.closest("[data-hl]");
  }
  function show(el, viaFocus) {
    const d = describe(el);
    if (!d) return;
    clearTimeout(hideT);
    tipFor = el;
    tip.innerHTML = `<b>${esc(d.name)}${d.key ? K(esc(d.key)) : ""}</b>${esc(d.what)}`;
    status.innerHTML = `<span class="hl-i">i</span><span><b>${esc(d.name)}</b> — ${esc(d.what)}${d.key ? ` Shortcut ${K(esc(d.key))}` : ""}</span>`;
    if (el.id === "canvas") return;                // status line only; a tooltip would cover the plan
    const r = el.getBoundingClientRect();
    tip.style.left = "0px"; tip.style.top = "0px"; tip.classList.add("on");
    const t = tip.getBoundingClientRect();
    let x = r.left + r.width / 2 - t.width / 2;
    let y = r.bottom + 8;
    if (y + t.height > innerHeight - 4) y = r.top - t.height - 8;
    // a field being typed in: put the tip beside the whole panel so no labels are covered
    const panel = el.closest("#inspector");
    if (viaFocus && el.matches("input,select,textarea") && panel) {
      const pr = panel.getBoundingClientRect();
      if (pr.left > t.width + 16) { x = pr.left - t.width - 10; y = r.top + r.height / 2 - t.height / 2; }
    }
    tip.style.left = `${Math.max(6, Math.min(x, innerWidth - t.width - 6))}px`;
    tip.style.top = `${Math.max(6, y)}px`;
  }
  function hide() {
    hideT = setTimeout(() => { tip.classList.remove("on"); tipFor = null; status.innerHTML = idle; }, 80);
  }
  document.addEventListener("pointerover", (e) => { if (e.pointerType === "mouse") { const el = target(e); if (el) show(el); } });
  document.addEventListener("pointerout", (e) => { if (e.pointerType === "mouse" && tipFor && !tipFor.contains(e.relatedTarget)) hide(); });
  document.addEventListener("focusin", (e) => { const el = target(e); if (el && el.matches(":focus-visible, input, select, textarea")) show(el, true); });
  document.addEventListener("focusout", hide);
  // touch: long-press shows the tooltip without triggering the button
  let pressT = 0;
  document.addEventListener("pointerdown", (e) => {
    if (e.pointerType !== "touch") return;
    const el = target(e);
    if (!el || el.id === "canvas") return;
    pressT = setTimeout(() => { show(el); el.dataset.hlLong = "1"; setTimeout(hide, 3500); }, 550);
  });
  document.addEventListener("pointerup", () => clearTimeout(pressT));
  document.addEventListener("click", (e) => {
    const el = target(e);
    if (el?.dataset.hlLong) { e.preventDefault(); e.stopPropagation(); delete el.dataset.hlLong; }
  }, true);
  addEventListener("scroll", () => tip.classList.remove("on"), true);

  /* --------------------------------------------------------- guide */
  const GROUP_ORDER = ["Top bar", "Drawing tools", "Plan", "Results panel", "Properties panel", "Dialogs"];
  function guideHTML() {
    const groups = GROUP_ORDER.map((g) => {
      const rows = HELP.filter((h) => h[1] === g).map(([, , n, w, k]) =>
        `<tr><td>${esc(n)}${k ? K(esc(k)) : ""}</td><td>${esc(w)}</td></tr>`).join("");
      return `<h3>${g}</h3><table class="hl-table">${rows}</table>`;
    }).join("");
    const fields = Object.values(FIELDS).map(([n, w]) => `<tr><td>${esc(n)}</td><td>${esc(w)}</td></tr>`).join("");
    return `
      <header><h2 id="hl-title">How to use the Network Designer</h2><button class="hl-x" id="hl-close" aria-label="Close help">✕</button></header>
      <section>
        <h3>Get started in four steps</h3>
        <ol class="hl-steps">
          <li><div><b>Start</b><p>Load the sample to explore, or start a new network.</p></div><button class="hl-go" data-go="#btn-sample">Load sample</button></li>
          <li><div><b>Draw</b><p>Place a reservoir or tank, then junctions, then join them with pipes. The tools are on the left (at the top on a phone).</p></div><button class="hl-go" data-go="[data-tool=pipe]">Show tools</button></li>
          <li><div><b>Enter data</b><p>Click any item to fill in levels, demands and pipe sizes in the properties panel (on the right, or below the plan on a phone).</p></div><button class="hl-go" data-go="#inspector">Show panel</button></li>
          <li><div><b>Run and read results</b><p>Press Run simulation. Junctions turn colour by pressure; tables and graphs appear below.</p></div><button class="hl-go" data-go="#btn-run">Show Run</button></li>
        </ol>
        <p class="hl-note">Tip: point at any button or field — or long-press on a touch screen — to see what it does. The line at the bottom of the window explains whatever you are pointing at.</p>
        ${groups}
        <h3>Fields in the properties panel</h3><table class="hl-table">${fields}</table>
        <h3>Keyboard</h3>
        <p class="hl-note">S select · J junction · R reservoir · T tank · P pipe · M pump · V valve · Del delete · Esc cancel / close · Ctrl+Z undo · Ctrl+Y redo · F1 help · hold Alt while placing to turn off snapping.</p>
      </section>`;
  }
  let drawer = null;
  function openGuide() {
    if (drawer) return;
    drawer = document.createElement("div");
    drawer.className = "hl-drawer-bg";
    drawer.innerHTML = `<div class="hl-drawer" role="dialog" aria-modal="true" aria-labelledby="hl-title">${guideHTML()}</div>`;
    document.body.appendChild(drawer);
    drawer.addEventListener("click", (e) => {
      if (e.target === drawer || e.target.id === "hl-close") return closeGuide();
      const go = e.target.closest("[data-go]");
      if (go) {
        const sel = go.dataset.go;
        closeGuide();
        const el = document.querySelector(sel);
        if (!el) return;
        el.scrollIntoView({ block: "nearest" });
        el.classList.add("hl-flash");
        setTimeout(() => el.classList.remove("hl-flash"), 1600);
        if (sel === "#btn-sample") el.click();
        else show(el);
        setTimeout(hide, 2500);
      }
    });
    drawer.querySelector("#hl-close").focus();
    try { localStorage.setItem("epanet-designer-help-seen", "1"); } catch {}
  }
  function closeGuide() { drawer?.remove(); drawer = null; document.getElementById("btn-help")?.focus(); }
  document.addEventListener("keydown", (e) => {
    if (e.key === "F1") { e.preventDefault(); drawer ? closeGuide() : openGuide(); }
    else if (e.key === "Escape" && drawer) { e.stopImmediatePropagation(); closeGuide(); }
  }, true);
  document.getElementById("btn-help")?.addEventListener("click", openGuide);

  /* ------------------------------------------------- keep up to date */
  attach();
  new MutationObserver((muts) => { for (const m of muts) m.addedNodes.forEach((n) => n.nodeType === 1 && attach(n.parentElement || n)); })
    .observe(document.body, { childList: true, subtree: true });

  // First visit on this browser: open the guide once.
  let seen = false;
  try { seen = localStorage.getItem("epanet-designer-help-seen") === "1"; } catch {}
  if (!seen) setTimeout(openGuide, 400);

  // For the automated audit.
  window.__help = { HELP, FIELDS, describe, openGuide, closeGuide };
})();
