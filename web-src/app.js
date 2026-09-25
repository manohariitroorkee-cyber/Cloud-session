// Page logic for index.html. Bundled together with epanet-js (which carries
// the EPANET 2.3 engine as embedded WebAssembly) into one inline script.

import {
  Project,
  Workspace,
  CountType,
  NodeProperty,
  NodeType,
  InitHydOption,
  TimeParameter,
} from "epanet-js";

const PRESSURE_UNITS = ["psi", "kPa", "m", "bar", "ft"];
const OPTION_PRESS_UNITS = 25; // EN_PRESS_UNITS (EPANET 2.3)
const NODE_TYPE_LABEL = {
  [NodeType.Junction]: "Junction",
  [NodeType.Reservoir]: "Reservoir",
  [NodeType.Tank]: "Tank",
};

const $ = (id) => document.getElementById(id);
const els = {
  file: $("inp-file"),
  fileName: $("file-name"),
  run: $("run-btn"),
  log: $("log"),
  clearLog: $("clear-log"),
  engine: $("engine-status"),
  summary: $("summary"),
  results: $("results"),
  time: $("time-select"),
  filter: $("node-filter"),
  tbody: $("pressure-body"),
  unitHead: $("unit-head"),
  count: $("row-count"),
};

let workspace = null;
let inpText = null;
let inpName = "";
let results = null; // { units, nodes: [{id, type}], steps: [{t, pressures}] }

// Lets the browser repaint the log between simulation steps.
const nextFrame = () => new Promise((r) => setTimeout(r, 0));

function log(msg, kind = "info") {
  const stamp = new Date().toLocaleTimeString();
  const prefix = kind === "error" ? "ERROR  " : kind === "ok" ? "OK     " : "";
  els.log.value += `[${stamp}] ${prefix}${msg}\n`;
  els.log.scrollTop = els.log.scrollHeight;
}

function clock(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function setEngineStatus(text, tone) {
  const tones = {
    busy: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200",
    ok: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200",
    error: "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200",
  };
  els.engine.className = `rounded-full px-3 py-1 text-xs font-medium ${tones[tone]}`;
  els.engine.textContent = text;
}

function updateRunButton() {
  els.run.disabled = !(workspace && inpText);
}

async function loadEngine() {
  setEngineStatus("Loading engine…", "busy");
  log("Loading EPANET engine (embedded WebAssembly)…");
  try {
    const ws = new Workspace();
    await ws.loadModule();
    workspace = ws;
    const v = ws.version;
    const version = `${Math.floor(v / 10000)}.${Math.floor((v % 10000) / 100)}.${v % 100}`;
    setEngineStatus(`EPANET ${version} ready`, "ok");
    log(`EPANET ${version} engine loaded. No network connection required.`, "ok");
  } catch (err) {
    setEngineStatus("Engine failed", "error");
    log(`Could not load the EPANET engine: ${err.message}`, "error");
  }
  updateRunButton();
}

els.file.addEventListener("change", async () => {
  const file = els.file.files[0];
  if (!file) return;
  inpText = await file.text();
  inpName = file.name;
  els.fileName.textContent = `${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
  log(`Loaded ${file.name} (${file.size.toLocaleString()} bytes).`);
  updateRunButton();
});

els.clearLog.addEventListener("click", () => {
  els.log.value = "";
});

els.run.addEventListener("click", runSimulation);

async function runSimulation() {
  els.run.disabled = true;
  const label = els.run.textContent;
  els.run.textContent = "Running…";
  const project = new Project(workspace);
  let opened = false;
  let hydOpen = false;
  try {
    log(`Opening ${inpName}…`);
    workspace.writeFile("model.inp", inpText);
    project.open("model.inp", "model.rpt", "");
    opened = true;

    const nodeCount = project.getCount(CountType.NodeCount);
    const linkCount = project.getCount(CountType.LinkCount);
    const tankCount = project.getCount(CountType.TankCount);
    const duration = project.getTimeParameter(TimeParameter.Duration);
    const units = PRESSURE_UNITS[project.getOption(OPTION_PRESS_UNITS)] ?? "";
    log(
      `Network: ${nodeCount} nodes (${nodeCount - tankCount} junctions, ` +
        `${tankCount} tanks/reservoirs), ${linkCount} links, duration ${clock(duration)}.`,
    );

    const nodes = [];
    for (let i = 1; i <= nodeCount; i++) {
      nodes.push({ id: project.getNodeId(i), type: project.getNodeType(i) });
    }

    log("Running hydraulic simulation…");
    project.openH();
    hydOpen = true;
    project.initH(InitHydOption.NoSave);

    const steps = [];
    let tstep = 0;
    do {
      const t = project.runH();
      const pressures = new Float64Array(nodeCount);
      for (let i = 1; i <= nodeCount; i++) {
        pressures[i - 1] = project.getNodeValue(i, NodeProperty.Pressure);
      }
      steps.push({ t, pressures });
      log(`  solved t = ${clock(t)}`);
      tstep = project.nextH();
      await nextFrame();
    } while (tstep > 0);

    project.closeH();
    hydOpen = false;
    log(`Simulation complete: ${steps.length} hydraulic time steps.`, "ok");

    results = { units, nodes, steps };
    renderSummary(nodeCount, linkCount, duration, steps.length, units);
    renderTimeOptions();
    renderTable();
  } catch (err) {
    // epanet-js repeats the code ("EPANET Error 200: Error 200: …"); show it once.
    const msg = (err.message || String(err)).replace(/^EPANET Error (\d+): Error \1: /, "EPANET error $1: ");
    log(msg, "error");
  } finally {
    if (hydOpen) try { project.closeH(); } catch {}
    if (opened) try { project.close(); } catch {}
    els.run.textContent = label;
    updateRunButton();
  }
}

function renderSummary(nodes, links, duration, steps, units) {
  const items = [
    ["Nodes", nodes],
    ["Links", links],
    ["Duration", clock(duration)],
    ["Time steps", steps],
    ["Pressure units", units],
  ];
  els.summary.innerHTML = items
    .map(
      ([k, v]) => `
      <div class="rounded-xl border border-slate-200 bg-white px-4 py-3 dark:border-slate-700 dark:bg-slate-800">
        <div class="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">${k}</div>
        <div class="mt-1 text-lg font-semibold tabular-nums">${v}</div>
      </div>`,
    )
    .join("");
  els.summary.classList.remove("hidden");
}

function renderTimeOptions() {
  els.time.innerHTML = results.steps
    .map((s, i) => `<option value="${i}">${clock(s.t)}</option>`)
    .join("");
  els.time.value = "0"; // default to time 0
  els.unitHead.textContent = results.units ? `(${results.units})` : "";
  els.results.classList.remove("hidden");
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

function renderTable() {
  if (!results) return;
  const step = results.steps[Number(els.time.value)];
  const q = els.filter.value.trim().toLowerCase();
  const rows = [];
  results.nodes.forEach((node, i) => {
    if (q && !node.id.toLowerCase().includes(q)) return;
    const p = step.pressures[i];
    const low = node.type === NodeType.Junction && p < 0;
    rows.push(`
      <tr class="border-t border-slate-100 dark:border-slate-700/60 hover:bg-slate-50 dark:hover:bg-slate-700/30">
        <td class="px-4 py-2 font-medium">${escapeHtml(node.id)}</td>
        <td class="px-4 py-2 text-slate-500 dark:text-slate-400">${NODE_TYPE_LABEL[node.type] ?? "?"}</td>
        <td class="px-4 py-2 text-right tabular-nums ${low ? "font-semibold text-rose-600 dark:text-rose-400" : ""}">${p.toFixed(2)}</td>
      </tr>`);
  });
  els.tbody.innerHTML =
    rows.join("") ||
    `<tr><td colspan="3" class="px-4 py-6 text-center text-slate-500">No nodes match “${escapeHtml(q)}”.</td></tr>`;
  els.count.textContent = `${rows.length} of ${results.nodes.length} nodes at ${clock(step.t)}`;
}

els.time.addEventListener("change", renderTable);
els.filter.addEventListener("input", renderTable);

loadEngine();
