// EPANET Network Designer: draw a network, run EPANET 2.3 hydraulics in the
// browser via epanet-js (embedded WebAssembly), and inspect the results.
// Bundled with epanet-js into one inline script by build.mjs.

import {
  Project,
  Workspace,
  CountType,
  NodeProperty,
  LinkProperty,
  NodeType,
  LinkType,
  InitHydOption,
  TimeParameter,
} from "epanet-js";

/* ------------------------------------------------------------------ units */

const SI_FLOWS = ["LPS", "LPM", "MLD", "CMH", "CMD"];
const US_FLOWS = ["GPM", "CFS", "MGD", "IMGD", "AFD"];
const FLOW_LABEL = {
  LPS: "L/s", LPM: "L/min", MLD: "MLD", CMH: "m³/h", CMD: "m³/d",
  GPM: "gpm", CFS: "cfs", MGD: "mgd", IMGD: "Imgd", AFD: "ac-ft/d",
};
// Multiply a value in L/s by this to get the flow unit.
const FROM_LPS = {
  LPS: 1, LPM: 60, MLD: 0.0864, CMH: 3.6, CMD: 86.4,
  GPM: 15.8503, CFS: 0.0353147, MGD: 0.0228245, IMGD: 0.0190053, AFD: 0.0700456,
};
const FLOW_ENUM = ["CFS", "GPM", "MGD", "IMGD", "AFD", "LPS", "LPM", "MLD", "CMH", "CMD"];
const HEADLOSS = { "H-W": "Hazen-Williams", "D-W": "Darcy-Weisbach", "C-M": "Chezy-Manning" };
const VALVE_TYPES = {
  PRV: "Pressure reducing (PRV)",
  PSV: "Pressure sustaining (PSV)",
  PBV: "Pressure breaker (PBV)",
  FCV: "Flow control (FCV)",
  TCV: "Throttle control (TCV)",
};

const isSI = (o) => SI_FLOWS.includes(o.units);
function U(o = model.options) {
  const si = isSI(o);
  return {
    len: si ? "m" : "ft",
    elev: si ? "m" : "ft",
    diam: si ? "mm" : "in",
    press: si ? "m" : "psi",
    head: si ? "m" : "ft",
    vel: si ? "m/s" : "ft/s",
    flow: FLOW_LABEL[o.units],
    hlUnit: si ? "m/km" : "ft/kft",
  };
}
// Sensible starting values for new elements, in the network's units.
function defaults(o = model.options) {
  const si = isSI(o);
  const f = FROM_LPS[o.units];
  const rough = { "H-W": 130, "D-W": si ? 0.1 : 0.0003, "C-M": 0.011 }[o.headloss];
  return {
    elev: si ? 215 : 700,
    demand: round(1 * f, 3),
    head: si ? 230 : 750,
    tankElev: si ? 230 : 750,
    diam: si ? 150 : 6,
    rough,
    pumpFlow: round(30 * f, 3),
    pumpHead: si ? 30 : 100,
    minPressure: si ? 12 : 17,
  };
}

/* ------------------------------------------------------------ utilities */

const $ = (id) => document.getElementById(id);
const round = (v, d = 2) => Math.round(v * 10 ** d) / 10 ** d;
function fmt(v, d = 2) {
  if (v == null || Number.isNaN(v)) return "–";
  const r = round(v, d);
  return (Object.is(r, -0) ? 0 : r).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
}
const num = (v) => {
  const n = typeof v === "number" ? v : parseFloat(String(v).replace(",", "."));
  return Number.isFinite(n) ? n : NaN;
};
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
function clock(sec) {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  return s ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${h}:${String(m).padStart(2, "0")}`;
}
const inpNum = (v) => String(round(num(v) || 0, 6));
const validId = (s) => /^[^\s;"]{1,31}$/.test(s);
const clone = (o) => JSON.parse(JSON.stringify(o));
const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
function niceStep(raw) {
  const p = 10 ** Math.floor(Math.log10(raw));
  const m = raw / p;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p;
}

/* ---------------------------------------------------------------- model */

const STORE_KEY = "epanet-designer-v1";
const KIND_PREFIX = { junction: "J", reservoir: "R", tank: "T", pipe: "P", pump: "PU", valve: "V" };
const KIND_LABEL = { junction: "Junction", reservoir: "Reservoir", tank: "Tank", pipe: "Pipe", pump: "Pump", valve: "Valve" };

function emptyModel(units = "LPS") {
  const options = { units, headloss: "H-W", duration: 24, hydStep: 60, patStep: 60, minPressure: 12 };
  options.minPressure = defaults(options).minPressure;
  return { title: "Untitled network", options, patterns: [], nodes: [], links: [] };
}

// A small gravity-fed colony supplied by a pumped elevated service reservoir.
function sampleModel() {
  const m = emptyModel("LPS");
  m.title = "Sample: colony supply from ESR";
  m.options.minPressure = 12;
  m.patterns.push({
    id: "DOMESTIC",
    mult: [0.5, 0.4, 0.4, 0.4, 0.6, 1.2, 1.8, 2.0, 1.7, 1.3, 1.0, 0.9, 0.9, 0.8, 0.8, 0.9, 1.1, 1.4, 1.6, 1.4, 1.1, 0.9, 0.7, 0.6],
  });
  const J = (id, x, y, elev, demand) => ({ id, kind: "junction", x, y, elev, demand, pattern: "DOMESTIC" });
  m.nodes.push(
    { id: "SUMP", kind: "reservoir", x: -200, y: 300, head: 214, pattern: "" },
    { id: "ESR", kind: "tank", x: 100, y: 300, elev: 234, initLevel: 3, minLevel: 0.5, maxLevel: 5.5, diameter: 16 },
    J("J1", 350, 300, 216, 3),
    J("J2", 650, 300, 215, 4),
    J("J3", 950, 300, 214.5, 3.5),
    J("J4", 350, 0, 215.5, 4),
    J("J5", 650, 0, 214.5, 5),
    J("J6", 950, 0, 213.5, 3),
    J("J7", 650, -250, 213, 2.5),
    J("J8", 350, -250, 214, 2.5),
  );
  const P = (id, from, to, diameter, length) => ({ id, kind: "pipe", from, to, length, autoLength: false, diameter, roughness: 130, minorLoss: 0, status: "Open" });
  m.links.push(
    { id: "PU1", kind: "pump", from: "SUMP", to: "ESR", pumpFlow: 40, pumpHead: 38, status: "Open", controlTank: "ESR", startLevel: 2, stopLevel: 5.2 },
    P("P1", "ESR", "J1", 300, 250),
    P("P2", "J1", "J2", 250, 300),
    P("P3", "J2", "J3", 200, 300),
    P("P4", "J1", "J4", 200, 300),
    P("P5", "J2", "J5", 150, 300),
    P("P6", "J3", "J6", 150, 300),
    P("P7", "J4", "J5", 150, 300),
    P("P8", "J5", "J6", 100, 300),
    P("P9", "J5", "J7", 100, 250),
    P("P10", "J4", "J8", 100, 250),
    P("P11", "J8", "J7", 100, 300),
  );
  return m;
}

let model = null;
let undoStack = [];
let redoStack = [];
let selection = null; // { type: "node"|"link", id }
let results = null;
let resultsStale = false;
let timeIndex = 0;

const nodeById = (id) => model.nodes.find((n) => n.id === id);
const linkById = (id) => model.links.find((l) => l.id === id);

function nextId(kind) {
  const prefix = KIND_PREFIX[kind];
  const taken = new Set((kind === "junction" || kind === "reservoir" || kind === "tank" ? model.nodes : model.links).map((e) => e.id));
  let i = 1;
  while (taken.has(prefix + i)) i++;
  return prefix + i;
}

function save() {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(model)); } catch {}
}
function loadSaved() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return null;
    const m = JSON.parse(raw);
    return m && Array.isArray(m.nodes) && Array.isArray(m.links) && m.options ? m : null;
  } catch { return null; }
}

// Call before every change so it can be undone.
function checkpoint() {
  undoStack.push(JSON.stringify(model));
  if (undoStack.length > 100) undoStack.shift();
  redoStack = [];
}
// Call after every change.
function changed({ keepResults = false } = {}) {
  if (!keepResults && results) { results = null; resultsStale = true; }
  syncAutoLengths();
  save();
  renderAll();
}
function undo() {
  if (!undoStack.length) return;
  redoStack.push(JSON.stringify(model));
  model = JSON.parse(undoStack.pop());
  fixSelection();
  changed();
}
function redo() {
  if (!redoStack.length) return;
  undoStack.push(JSON.stringify(model));
  model = JSON.parse(redoStack.pop());
  fixSelection();
  changed();
}
function fixSelection() {
  if (!selection) return;
  if (selection.type === "node" && !nodeById(selection.id)) selection = null;
  if (selection && selection.type === "link" && !linkById(selection.id)) selection = null;
}
function syncAutoLengths() {
  for (const l of model.links) {
    if (l.kind === "pipe" && l.autoLength) {
      const a = nodeById(l.from), b = nodeById(l.to);
      if (a && b) l.length = Math.max(1, round(dist(a, b), 1));
    }
  }
}
function replaceModel(m) {
  checkpoint();
  model = m;
  selection = null;
  results = null;
  resultsStale = false;
  changed();
  fitView();
}

/* ----------------------------------------------------------- mutations */

function addNode(kind, x, y) {
  const d = defaults();
  const pat = model.patterns[0]?.id ?? "";
  const base = { id: nextId(kind), kind, x, y };
  if (kind === "junction") Object.assign(base, { elev: d.elev, demand: d.demand, pattern: pat });
  if (kind === "reservoir") Object.assign(base, { head: d.head, pattern: "" });
  if (kind === "tank") Object.assign(base, { elev: d.tankElev, initLevel: 3, minLevel: 0.5, maxLevel: 5, diameter: isSI(model.options) ? 15 : 50 });
  model.nodes.push(base);
  return base;
}

function addLink(kind, from, to) {
  const d = defaults();
  const base = { id: nextId(kind), kind, from, to, status: "Open" };
  if (kind === "pipe") Object.assign(base, { length: 100, autoLength: true, diameter: d.diam, roughness: d.rough, minorLoss: 0 });
  if (kind === "pump") Object.assign(base, { pumpFlow: d.pumpFlow, pumpHead: d.pumpHead });
  if (kind === "valve") Object.assign(base, { valveType: "PRV", diameter: d.diam, setting: isSI(model.options) ? 20 : 30, minorLoss: 0, status: "Active" });
  model.links.push(base);
  return base;
}

function deleteSelection() {
  if (!selection) return;
  checkpoint();
  if (selection.type === "node") {
    const id = selection.id;
    model.nodes = model.nodes.filter((n) => n.id !== id);
    model.links = model.links.filter((l) => l.from !== id && l.to !== id);
    for (const l of model.links) if (l.controlTank === id) l.controlTank = "";
  } else {
    model.links = model.links.filter((l) => l.id !== selection.id);
  }
  selection = null;
  changed();
}

function renameElement(el, isNode, newId) {
  if (newId === el.id) return null;
  if (!validId(newId)) return "Use 1–31 characters with no spaces, quotes or semicolons.";
  const pool = isNode ? model.nodes : model.links;
  if (pool.some((e) => e.id === newId)) return `“${newId}” is already used by another ${isNode ? "node" : "link"}.`;
  checkpoint();
  if (isNode) for (const l of model.links) { if (l.from === el.id) l.from = newId; if (l.to === el.id) l.to = newId; if (l.controlTank === el.id) l.controlTank = newId; }
  el.id = newId;
  selection = { type: isNode ? "node" : "link", id: newId };
  changed();
  return null;
}

/* ------------------------------------------------------------ view/draw */

const svg = $("canvas");
const view = { cx: 0, cy: 0, scale: 1, w: 800, h: 500 };
const toScreen = (x, y) => [view.w / 2 + (x - view.cx) * view.scale, view.h / 2 - (y - view.cy) * view.scale];
const toWorld = (sx, sy) => [view.cx + (sx - view.w / 2) / view.scale, view.cy - (sy - view.h / 2) / view.scale];
const snapStep = () => niceStep(12 / view.scale);
const snap = (v, off) => (off ? round(v, 2) : Math.round(v / snapStep()) * snapStep());

let tool = "select";
let pending = null; // start node id while drawing a link
let pointerWorld = null;

function fitView() {
  measure();
  if (!model.nodes.length) { view.cx = 0; view.cy = 0; view.scale = 1; drawCanvas(); return; }
  const xs = model.nodes.map((n) => n.x), ys = model.nodes.map((n) => n.y);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  view.cx = (x0 + x1) / 2;
  view.cy = (y0 + y1) / 2;
  const dx = Math.max(x1 - x0, 1e-9), dy = Math.max(y1 - y0, 1e-9);
  view.scale = model.nodes.length === 1 ? 1 : Math.min((view.w - 120) / dx, (view.h - 120) / dy);
  if (!Number.isFinite(view.scale) || view.scale <= 0) view.scale = 1;
  drawCanvas();
}
function measure() {
  const r = svg.getBoundingClientRect();
  view.w = Math.max(r.width, 1);
  view.h = Math.max(r.height, 1);
}
function zoomAt(factor, sx = view.w / 2, sy = view.h / 2) {
  const [wx, wy] = toWorld(sx, sy);
  view.scale = Math.min(Math.max(view.scale * factor, 1e-4), 1e5);
  view.cx = wx - (sx - view.w / 2) / view.scale;
  view.cy = wy + (sy - view.h / 2) / view.scale;
  drawCanvas();
}

function pressureClass(p) {
  const min = model.options.minPressure;
  const step = isSI(model.options) ? [5, 10, 20, 35] : [7, 14, 28, 50];
  if (p < min) return 0;
  if (p < min + step[0]) return 1;
  if (p < min + step[1]) return 2;
  if (p < min + step[2]) return 3;
  if (p < min + step[3]) return 4;
  return 5;
}
const CLASS_FILL = ["var(--crit)", "var(--seq-1)", "var(--seq-2)", "var(--seq-3)", "var(--seq-4)", "var(--seq-5)"];

function nodeShape(n, x, y, fill) {
  if (n.kind === "junction") return `<circle cx="${x}" cy="${y}" r="5.5" fill="${fill}" stroke="var(--canvas)" stroke-width="1.5"/>`;
  if (n.kind === "reservoir") return `<path d="M${x - 10} ${y - 7}h20l-3 13h-14z" fill="${fill}" stroke="var(--canvas)" stroke-width="1.5"/>`;
  return `<g><rect x="${x - 9}" y="${y - 11}" width="18" height="13" rx="2" fill="${fill}" stroke="var(--canvas)" stroke-width="1.5"/><path d="M${x - 5} ${y + 2}v8M${x + 5} ${y + 2}v8" stroke="${fill}" stroke-width="2"/></g>`;
}

function drawCanvas() {
  measure();
  const parts = [];
  // Grid
  const minor = niceStep(24 / view.scale);
  const major = minor * 5;
  const pm = minor * view.scale, pM = major * view.scale;
  const [ox, oy] = toScreen(0, 0);
  parts.push(`<defs>
    <pattern id="gmin" width="${pm}" height="${pm}" patternUnits="userSpaceOnUse" x="${ox % pm}" y="${oy % pm}"><path d="M${pm} 0V${pm}H0" fill="none" stroke="var(--grid-minor)" stroke-width="1"/></pattern>
    <pattern id="gmaj" width="${pM}" height="${pM}" patternUnits="userSpaceOnUse" x="${ox % pM}" y="${oy % pM}"><path d="M${pM} 0V${pM}H0" fill="none" stroke="var(--grid-major)" stroke-width="1"/></pattern>
    <marker id="arrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M1 1L9 5L1 9z" fill="var(--link)"/></marker>
  </defs>
  <rect width="100%" height="100%" fill="url(#gmin)"/><rect width="100%" height="100%" fill="url(#gmaj)"/>`);

  const step = results ? results.steps[timeIndex] : null;
  const showLabels = model.nodes.length <= 250 || view.scale > 0.6;

  // Links
  for (const l of model.links) {
    const a = nodeById(l.from), b = nodeById(l.to);
    if (!a || !b) continue;
    const [x1, y1] = toScreen(a.x, a.y), [x2, y2] = toScreen(b.x, b.y);
    const dmm = l.kind === "pipe" || l.kind === "valve" ? (isSI(model.options) ? l.diameter : l.diameter * 25.4) : 150;
    const w = Math.min(Math.max(1.4 + dmm / 110, 1.6), 5.5);
    let dash = "";
    let flowTxt = "";
    let q = null;
    if (step) {
      const k = results.linkIdx.get(l.id);
      q = step.Q[k];
      const closed = step.S[k] === 0; // EN_STATUS: 0 closed, 1 open
      if (closed) dash = ` stroke-dasharray="4 4"`;
      flowTxt = `\nFlow ${fmt(q)} ${results.units.flow}, velocity ${fmt(step.V[k])} ${results.units.vel}${closed ? ", closed" : ""}`;
    } else if (l.status === "Closed") dash = ` stroke-dasharray="4 4"`;
    const sel = selection?.type === "link" && selection.id === l.id;
    parts.push(`<g data-link="${esc(l.id)}">`);
    if (sel) parts.push(`<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="var(--select)" stroke-width="${w + 6}" stroke-linecap="round" opacity=".45"/>`);
    parts.push(`<line class="lnk" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke-width="${w}"${dash}/>`);
    const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
    const ang = (Math.atan2(y2 - y1, x2 - x1) * 180) / Math.PI;
    if (l.kind === "pump") {
      parts.push(`<g transform="translate(${mx} ${my}) rotate(${ang})"><circle r="9" fill="var(--panel)" stroke="var(--link)" stroke-width="2"/><path d="M-3 -5v10l8-5z" fill="var(--link)"/></g>`);
    } else if (l.kind === "valve") {
      parts.push(`<g transform="translate(${mx} ${my}) rotate(${ang})"><path d="M-9 -6v12l9-6zM9 -6v12l-9-6z" fill="var(--link)" stroke="var(--panel)" stroke-width="1"/></g>`);
    } else if (step && Math.abs(q) > 1e-6 && Math.hypot(x2 - x1, y2 - y1) > 40) {
      const dir = q >= 0 ? 0 : 180;
      parts.push(`<g transform="translate(${mx} ${my}) rotate(${ang + dir})"><path d="M-5 -4.5L4 0L-5 4.5z" fill="var(--link)"/></g>`);
    }
    parts.push(`<line class="lnk-hit" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"><title>${KIND_LABEL[l.kind]} ${esc(l.id)}${flowTxt}</title></line></g>`);
  }

  // Rubber band while drawing a link
  if (pending && pointerWorld) {
    const a = nodeById(pending);
    if (a) {
      const [x1, y1] = toScreen(a.x, a.y), [x2, y2] = toScreen(...pointerWorld);
      parts.push(`<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="var(--select)" stroke-width="2" stroke-dasharray="6 4" pointer-events="none"/>`);
    }
  }

  // Nodes
  for (const n of model.nodes) {
    const [x, y] = toScreen(n.x, n.y);
    let fill = "var(--ink)";
    let tip = `${KIND_LABEL[n.kind]} ${n.id}`;
    let val = "";
    if (step) {
      const k = results.nodeIdx.get(n.id);
      const p = step.P[k];
      if (n.kind === "junction") {
        fill = CLASS_FILL[pressureClass(p)];
        val = fmt(p, 1);
        tip += `\nPressure ${fmt(p)} ${results.units.press}, head ${fmt(step.H[k])} ${results.units.head}`;
      } else if (n.kind === "tank") {
        val = `${fmt(step.H[k] - n.elev, 2)} ${results.units.len}`;
        tip += `\nWater level ${val}, head ${fmt(step.H[k])} ${results.units.head}`;
      }
    }
    const sel = (selection?.type === "node" && selection.id === n.id) || pending === n.id;
    parts.push(`<g class="node" data-node="${esc(n.id)}">`);
    if (sel) parts.push(`<circle class="sel" cx="${x}" cy="${y}" r="${n.kind === "junction" ? 10 : 15}"/>`);
    parts.push(nodeShape(n, x, y, fill));
    if (step && n.kind === "junction" && fill === CLASS_FILL[0]) parts.push(`<circle cx="${x}" cy="${y}" r="9" fill="none" stroke="var(--crit)" stroke-width="1.5" stroke-dasharray="2 2"/>`);
    parts.push(`<circle cx="${x}" cy="${y}" r="14" fill="transparent"><title>${esc(tip)}</title></circle>`);
    if (showLabels) {
      const dy = n.kind === "junction" ? -10 : -16;
      parts.push(`<text class="lbl" x="${x + 8}" y="${y + dy}">${esc(n.id)}${val ? ` · ${esc(val)}` : ""}</text>`);
    }
    parts.push(`</g>`);
  }

  // Scale bar (top right)
  const barLen = niceStep(90 / view.scale);
  const px = barLen * view.scale;
  const bx = view.w - 16 - px, by = 22;
  parts.push(`<g pointer-events="none"><path d="M${bx} ${by}v5h${px}v-5" fill="none" stroke="var(--muted)" stroke-width="1.5"/><text x="${bx + px / 2}" y="${by - 4}" text-anchor="middle" class="lbl">${fmt(barLen, barLen < 1 ? 2 : 0)} ${U().len}</text></g>`);

  svg.innerHTML = parts.join("");
  svg.setAttribute("class", `absolute inset-0 h-full w-full touch-none select-none ${tool === "select" ? "tool-select" : "tool-add"}`);
  drawLegend();
}

function drawLegend() {
  const el = $("legend");
  if (!results) { el.hidden = true; return; }
  const u = results.units.press;
  const min = model.options.minPressure;
  const st = isSI(model.options) ? [5, 10, 20, 35] : [7, 14, 28, 50];
  const edges = [min, min + st[0], min + st[1], min + st[2], min + st[3]];
  const rows = [
    [0, `below ${fmt(min, 0)} ${u} (minimum)`],
    [1, `${fmt(edges[0], 0)}–${fmt(edges[1], 0)}`],
    [2, `${fmt(edges[1], 0)}–${fmt(edges[2], 0)}`],
    [3, `${fmt(edges[2], 0)}–${fmt(edges[3], 0)}`],
    [4, `${fmt(edges[3], 0)}–${fmt(edges[4], 0)}`],
    [5, `above ${fmt(edges[4], 0)}`],
  ];
  el.innerHTML = `<div class="eyebrow mb-1">Junction pressure (${esc(u)})</div>` +
    rows.map(([c, t]) => `<div class="flex items-center gap-2 leading-5"><span class="inline-block h-2.5 w-2.5 rounded-full" style="background:${CLASS_FILL[c]}${c === 0 ? ";outline:1.5px dashed var(--crit);outline-offset:1.5px" : ""}"></span><span class="tabular-nums">${t}</span></div>`).join("");
  el.hidden = false;
}

const HINTS = {
  select: "Drag nodes to move them. Drag the background to pan, scroll to zoom. Click an item to edit it.",
  junction: "Click on the plan to place junctions (demand points).",
  reservoir: "Click to place a reservoir: a fixed-head source such as a sump or river intake.",
  tank: "Click to place a storage tank, such as an ESR or GLSR.",
  pipe: "Click a node, then the next node. Clicking empty space adds a junction there. Press Esc to finish.",
  pump: "Click the suction node, then the delivery node.",
  valve: "Click the upstream node, then the downstream node.",
};
function setTool(t) {
  tool = t;
  pending = null;
  document.querySelectorAll("#tools .tool[data-tool]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.tool === t)));
  $("hint").textContent = HINTS[t];
  drawCanvas();
}

/* --------------------------------------------------------- interaction */

let drag = null; // { kind: "node"|"pan", id, sx, sy, moved, cx, cy }

function eventTarget(e) {
  const nodeEl = e.target.closest?.("[data-node]");
  if (nodeEl) return { type: "node", id: nodeEl.dataset.node };
  const linkEl = e.target.closest?.("[data-link]");
  if (linkEl) return { type: "link", id: linkEl.dataset.link };
  return null;
}
function localPoint(e) {
  const r = svg.getBoundingClientRect();
  return [e.clientX - r.left, e.clientY - r.top];
}

svg.addEventListener("pointerdown", (e) => {
  if (e.button !== 0 && e.pointerType === "mouse") return;
  const [sx, sy] = localPoint(e);
  const hit = eventTarget(e);
  const [wx, wy] = toWorld(sx, sy);
  svg.setPointerCapture(e.pointerId);

  if (tool === "select") {
    if (hit?.type === "node") {
      selection = hit;
      const n = nodeById(hit.id);
      drag = { kind: "node", id: hit.id, sx, sy, moved: false, ox: n.x, oy: n.y };
      renderSelection();
    } else if (hit?.type === "link") {
      selection = hit;
      drag = null;
      renderSelection();
    } else {
      drag = { kind: "pan", sx, sy, moved: false, cx: view.cx, cy: view.cy };
      svg.classList.add("panning");
    }
    return;
  }

  if (tool === "junction" || tool === "reservoir" || tool === "tank") {
    if (hit?.type === "node") { selection = hit; renderSelection(); return; }
    checkpoint();
    const n = addNode(tool, snap(wx, e.altKey), snap(wy, e.altKey));
    selection = { type: "node", id: n.id };
    changed();
    return;
  }

  // Link tools
  let target = hit?.type === "node" ? hit.id : null;
  if (!target) {
    if (tool !== "pipe") { log("Start and end a pump or valve on existing nodes.", "warn"); return; }
    checkpoint();
    target = addNode("junction", snap(wx, e.altKey), snap(wy, e.altKey)).id;
    if (!pending) { pending = target; selection = { type: "node", id: target }; changed(); return; }
  } else if (!pending) {
    pending = target;
    drawCanvas();
    return;
  } else {
    checkpoint();
  }
  if (target === pending) { undoStack.pop(); return; }
  const dup = model.links.find((l) => (l.from === pending && l.to === target) || (l.from === target && l.to === pending));
  if (dup && tool === "pipe") log(`Note: ${pending} and ${target} are already joined by ${dup.id}. A parallel pipe was added.`);
  const l = addLink(tool, pending, target);
  selection = { type: "link", id: l.id };
  pending = tool === "pipe" ? target : null;
  changed();
});

svg.addEventListener("pointermove", (e) => {
  const [sx, sy] = localPoint(e);
  pointerWorld = toWorld(sx, sy);
  if (!drag) { if (pending) drawCanvas(); return; }
  const dx = sx - drag.sx, dy = sy - drag.sy;
  if (!drag.moved && Math.hypot(dx, dy) < 3) return;
  if (drag.kind === "pan") {
    drag.moved = true;
    view.cx = drag.cx - dx / view.scale;
    view.cy = drag.cy + dy / view.scale;
    drawCanvas();
  } else if (drag.kind === "node") {
    const n = nodeById(drag.id);
    if (!drag.moved) { checkpoint(); drag.moved = true; }
    n.x = snap(drag.ox + dx / view.scale, e.altKey);
    n.y = snap(drag.oy - dy / view.scale, e.altKey);
    syncAutoLengths();
    drawCanvas();
  }
});

svg.addEventListener("pointerup", () => {
  if (!drag) return;
  if (drag.kind === "pan" && !drag.moved) { selection = null; renderSelection(); }
  if (drag.kind === "node" && drag.moved) changed();
  svg.classList.remove("panning");
  drag = null;
});
svg.addEventListener("pointerleave", () => { pointerWorld = null; if (pending) drawCanvas(); });

svg.addEventListener("wheel", (e) => {
  e.preventDefault();
  const [sx, sy] = localPoint(e);
  zoomAt(Math.exp(-e.deltaY * 0.0015), sx, sy);
}, { passive: false });

$("zoom-in").onclick = () => zoomAt(1.3);
$("zoom-out").onclick = () => zoomAt(1 / 1.3);
$("zoom-fit").onclick = fitView;
document.querySelectorAll("#tools .tool[data-tool]").forEach((b) => (b.onclick = () => setTool(b.dataset.tool)));
$("btn-undo").onclick = undo;
$("btn-redo").onclick = redo;

const KEY_TOOLS = { s: "select", j: "junction", r: "reservoir", t: "tank", p: "pipe", m: "pump", v: "valve" };
document.addEventListener("keydown", (e) => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName);
  if ((e.ctrlKey || e.metaKey) && !typing) {
    if (e.key.toLowerCase() === "z" && !e.shiftKey) { e.preventDefault(); undo(); }
    else if (e.key.toLowerCase() === "y" || (e.key.toLowerCase() === "z" && e.shiftKey)) { e.preventDefault(); redo(); }
    return;
  }
  if (e.key === "Escape") {
    if (!$("export-modal").hidden) { $("export-modal").hidden = true; return; }
    if (pending) { pending = null; drawCanvas(); return; }
    if (tool !== "select") { setTool("select"); return; }
    selection = null; renderSelection(); return;
  }
  if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
  if ((e.key === "Delete" || e.key === "Backspace") && selection) { e.preventDefault(); deleteSelection(); return; }
  const t = KEY_TOOLS[e.key.toLowerCase()];
  if (t) setTool(t);
});

new ResizeObserver(() => drawCanvas()).observe(svg);

/* ------------------------------------------------------------ inspector */

const insp = $("inspector");

function field(label, key, value, { unit = "", type = "number", step = "any", options = null, attrs = "" } = {}) {
  const id = `f-${key}`;
  let control;
  if (options) {
    control = `<select id="${id}" data-k="${key}">${Object.entries(options).map(([v, t]) => `<option value="${esc(v)}"${String(v) === String(value) ? " selected" : ""}>${esc(t)}</option>`).join("")}</select>`;
  } else if (type === "checkbox") {
    control = `<input id="${id}" type="checkbox" data-k="${key}"${value ? " checked" : ""}>`;
  } else {
    const input = `<input id="${id}" type="${type}" step="${step}" data-k="${key}" value="${esc(value ?? "")}" ${attrs}>`;
    control = unit ? `<span class="unit">${input}<i>${esc(unit)}</i></span>` : input;
  }
  return `<label class="field" for="${id}"><span>${esc(label)}</span>${control}</label>`;
}
const section = (title, body, extra = "") => `<section class="space-y-2 border-b border-line px-4 py-3"${extra}><h3 class="eyebrow">${title}</h3>${body}</section>`;
const patternOptions = () => ({ "": "None (constant)", ...Object.fromEntries(model.patterns.map((p) => [p.id, p.id])) });

function resultRows(pairs) {
  return `<dl class="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 text-[13px] tabular-nums">${pairs.map(([k, v]) => `<dt class="text-muted">${esc(k)}</dt><dd class="text-right font-medium">${v}</dd>`).join("")}</dl>`;
}

function renderInspector() {
  const u = U();
  if (!selection) { renderNetworkPanel(); return; }
  if (selection.type === "node") {
    const n = nodeById(selection.id);
    if (!n) { selection = null; renderNetworkPanel(); return; }
    let body = field("ID", "id", n.id, { type: "text", attrs: 'maxlength="31" spellcheck="false"' });
    if (n.kind === "junction") {
      body += field("Ground elevation", "elev", n.elev, { unit: u.elev });
      body += field("Base demand", "demand", n.demand, { unit: u.flow });
      body += field("Demand pattern", "pattern", n.pattern ?? "", { options: patternOptions() });
    } else if (n.kind === "reservoir") {
      body += field("Water level (head)", "head", n.head, { unit: u.head });
      body += field("Head pattern", "pattern", n.pattern ?? "", { options: patternOptions() });
    } else {
      body += field("Bottom elevation", "elev", n.elev, { unit: u.elev });
      body += field("Initial level", "initLevel", n.initLevel, { unit: u.len });
      body += field("Minimum level", "minLevel", n.minLevel, { unit: u.len });
      body += field("Maximum level", "maxLevel", n.maxLevel, { unit: u.len });
      body += field("Diameter", "diameter", n.diameter, { unit: u.len });
      const vol = Math.PI * (n.diameter / 2) ** 2 * (n.maxLevel - n.minLevel);
      body += `<p class="text-xs text-muted">Usable volume ${fmt(vol, 0)} ${isSI(model.options) ? "m³" : "ft³"}</p>`;
    }
    body += `<p id="insp-err" class="text-xs text-crit" hidden></p>`;
    let res = "";
    if (results) {
      const k = results.nodeIdx.get(n.id), s = results.steps[timeIndex];
      const pairs = [];
      if (n.kind === "junction") {
        const p = s.P[k];
        pairs.push(["Pressure", `<span class="${p < model.options.minPressure ? "text-crit" : ""}">${fmt(p)} ${u.press}</span>`], ["Head", `${fmt(s.H[k])} ${u.head}`], ["Demand", `${fmt(s.D[k], 3)} ${u.flow}`]);
      } else if (n.kind === "tank") {
        pairs.push(["Water level", `${fmt(s.H[k] - n.elev)} ${u.len}`], ["Head", `${fmt(s.H[k])} ${u.head}`], ["Net inflow", `${fmt(-s.D[k], 3)} ${u.flow}`]);
      } else {
        pairs.push(["Head", `${fmt(s.H[k])} ${u.head}`], ["Supply", `${fmt(-s.D[k], 3)} ${u.flow}`]);
      }
      res = section(`Results at ${clock(results.steps[timeIndex].t)}`, resultRows(pairs));
    }
    const links = model.links.filter((l) => l.from === n.id || l.to === n.id).map((l) => l.id);
    insp.innerHTML = header(KIND_LABEL[n.kind], n.id) + res + section("Properties", body) +
      section("Connections", `<p class="text-[13px] text-muted">${links.length ? links.map((id) => `<button class="font-mono text-ink underline decoration-line underline-offset-2 hover:decoration-accent" data-goto-link="${esc(id)}">${esc(id)}</button>`).join(", ") : "Not connected. Draw a pipe to this node before running."}</p>`);
    bindInspector(n, true);
    return;
  }
  const l = linkById(selection.id);
  if (!l) { selection = null; renderNetworkPanel(); return; }
  let body = field("ID", "id", l.id, { type: "text", attrs: 'maxlength="31" spellcheck="false"' });
  body += `<div class="field"><span>Connects</span><span class="flex items-center gap-2 font-mono text-[13px]">${esc(l.from)} → ${esc(l.to)}<button class="btn ml-auto px-2 py-0.5 text-xs" id="btn-reverse" title="Swap start and end nodes">Reverse</button></span></div>`;
  if (l.kind === "pipe") {
    body += field("Length from drawing", "autoLength", l.autoLength, { type: "checkbox" });
    body += field("Length", "length", l.length, { unit: u.len, attrs: l.autoLength ? "readonly" : "" });
    body += field("Diameter", "diameter", l.diameter, { unit: u.diam, attrs: 'list="diams"' });
    body += field(model.options.headloss === "H-W" ? "Roughness (C)" : model.options.headloss === "D-W" ? `Roughness (${isSI(model.options) ? "mm" : "millift"})` : "Roughness (n)", "roughness", l.roughness);
    body += field("Minor loss coeff.", "minorLoss", l.minorLoss);
    body += field("Initial status", "status", l.status, { options: { Open: "Open", Closed: "Closed", CV: "Check valve (one way)" } });
    body += `<datalist id="diams">${(isSI(model.options) ? [80, 100, 150, 200, 250, 300, 350, 400, 450, 500, 600, 700, 800, 900, 1000] : [3, 4, 6, 8, 10, 12, 14, 16, 18, 20, 24, 30, 36]).map((d) => `<option value="${d}">`).join("")}</datalist>`;
  } else if (l.kind === "pump") {
    body += field("Design flow", "pumpFlow", l.pumpFlow, { unit: u.flow });
    body += field("Design head", "pumpHead", l.pumpHead, { unit: u.head });
    body += `<p class="text-xs text-muted">One-point curve: EPANET fits shut-off head of 1.33 × design head and maximum flow of 2 × design flow.</p>`;
    body += field("Initial status", "status", l.status, { options: { Open: "Running", Closed: "Off" } });
    const tanks = model.nodes.filter((n) => n.kind === "tank");
    body += field("Controlled by tank", "controlTank", l.controlTank || "", { options: { "": "No level control", ...Object.fromEntries(tanks.map((t) => [t.id, t.id])) } });
    if (l.controlTank) {
      body += field("Start pump below level", "startLevel", l.startLevel ?? 1, { unit: u.len });
      body += field("Stop pump above level", "stopLevel", l.stopLevel ?? 4, { unit: u.len });
      if (!((l.startLevel ?? 1) < (l.stopLevel ?? 4))) body += `<p class="text-xs text-crit">The start level must be below the stop level.</p>`;
    } else if (tanks.length) body += `<p class="text-xs text-muted">A pump filling a tank normally needs level control, or it runs against a full tank and the simulation can become unbalanced.</p>`;
  } else {
    body += field("Valve type", "valveType", l.valveType, { options: VALVE_TYPES });
    body += field("Diameter", "diameter", l.diameter, { unit: u.diam });
    const settingUnit = { PRV: u.press, PSV: u.press, PBV: u.press, FCV: u.flow, TCV: "" }[l.valveType];
    body += field(l.valveType === "TCV" ? "Loss coefficient" : l.valveType === "FCV" ? "Flow setting" : "Pressure setting", "setting", l.setting, { unit: settingUnit });
    body += field("Minor loss coeff.", "minorLoss", l.minorLoss);
    body += field("Fixed status", "status", l.status, { options: { Active: "Active (uses setting)", Open: "Fully open", Closed: "Closed" } });
  }
  body += `<p id="insp-err" class="text-xs text-crit" hidden></p>`;
  let res = "";
  if (results) {
    const k = results.linkIdx.get(l.id), s = results.steps[timeIndex];
    const pairs = [["Flow", `${fmt(s.Q[k], 3)} ${u.flow}`], ["Velocity", `${fmt(s.V[k])} ${u.vel}`]];
    if (l.kind === "pipe") pairs.push(["Unit headloss", `${fmt(s.HL[k])} ${u.hlUnit}`]);
    else pairs.push(["Head change", `${fmt(s.HL[k])} ${u.head}`]);
    pairs.push(["Status", statusText(s.S[k])]);
    res = section(`Results at ${clock(s.t)}`, resultRows(pairs));
  }
  insp.innerHTML = header(KIND_LABEL[l.kind], l.id) + res + section("Properties", body);
  bindInspector(l, false);
  $("btn-reverse").onclick = () => { checkpoint(); [l.from, l.to] = [l.to, l.from]; changed(); };
}

function header(kind, id) {
  return `<div class="flex items-center gap-2 border-b border-line px-4 py-3">
    <div class="min-w-0"><div class="eyebrow">${esc(kind)}</div><div class="truncate font-mono text-base font-semibold">${esc(id)}</div></div>
    <button id="btn-delete" class="btn ml-auto text-crit" title="Delete (Del)">Delete</button>
  </div>`;
}

function bindInspector(el, isNode) {
  $("btn-delete").onclick = deleteSelection;
  insp.querySelectorAll("[data-goto-link]").forEach((b) => (b.onclick = () => { selection = { type: "link", id: b.dataset.gotoLink }; renderSelection(); }));
  insp.querySelectorAll("[data-k]").forEach((input) => {
    input.addEventListener("change", () => {
      const k = input.dataset.k;
      const err = $("insp-err");
      if (k === "id") {
        const msg = renameElement(el, isNode, input.value.trim());
        if (msg) { err.textContent = msg; err.hidden = false; input.value = el.id; }
        return;
      }
      let v;
      if (input.type === "checkbox") v = input.checked;
      else if (input.tagName === "SELECT") v = input.value;
      else {
        v = num(input.value);
        const mustBePositive = ["diameter", "length", "roughness", "pumpFlow", "pumpHead"].includes(k);
        if (Number.isNaN(v) || (mustBePositive && v <= 0) || v < 0 && !["elev", "head"].includes(k)) {
          err.textContent = mustBePositive ? "Enter a number greater than zero." : "Enter a valid number.";
          err.hidden = false;
          input.value = el[k];
          return;
        }
      }
      checkpoint();
      el[k] = v;
      if (k === "length") el.autoLength = false;
      if (k === "controlTank" && v) {
        const t = nodeById(v);
        if (el.startLevel == null) el.startLevel = round(t.minLevel + 0.3 * (t.maxLevel - t.minLevel), 2);
        if (el.stopLevel == null) el.stopLevel = round(t.maxLevel - 0.05 * (t.maxLevel - t.minLevel), 2);
      }
      if (el.kind === "tank" && el.minLevel > el.maxLevel) { err.textContent = "Minimum level is above maximum level."; err.hidden = false; }
      changed();
    });
  });
}

function renderNetworkPanel() {
  const o = model.options, u = U();
  const counts = { junction: 0, reservoir: 0, tank: 0, pipe: 0, pump: 0, valve: 0 };
  model.nodes.forEach((n) => counts[n.kind]++);
  model.links.forEach((l) => counts[l.kind]++);
  const totalDemand = model.nodes.filter((n) => n.kind === "junction").reduce((s, n) => s + (n.demand || 0), 0);
  const pipeLen = model.links.filter((l) => l.kind === "pipe").reduce((s, l) => s + (l.length || 0), 0);
  const summary = resultRows([
    ["Junctions", counts.junction], ["Reservoirs", counts.reservoir], ["Tanks", counts.tank],
    ["Pipes", counts.pipe], ["Pumps", counts.pump], ["Valves", counts.valve],
    ["Total base demand", `${fmt(totalDemand, 2)} ${u.flow}`],
    ["Total pipe length", `${fmt(pipeLen / (isSI(o) ? 1000 : 5280), 2)} ${isSI(o) ? "km" : "mi"}`],
  ]);
  const unitOpts = Object.fromEntries([...SI_FLOWS, ...US_FLOWS].map((k) => [k, `${FLOW_LABEL[k]}${SI_FLOWS.includes(k) ? " (SI, metres)" : " (US, feet)"}`]));
  let settings = field("Flow units", "units", o.units, { options: unitOpts });
  settings += field("Headloss formula", "headloss", o.headloss, { options: HEADLOSS });
  settings += field("Duration (0 = single snapshot)", "duration", o.duration, { unit: "h" });
  settings += field("Hydraulic time step", "hydStep", o.hydStep, { unit: "min" });
  settings += field("Pattern time step", "patStep", o.patStep, { unit: "min" });
  settings += field("Minimum pressure", "minPressure", o.minPressure, { unit: u.press });
  settings += `<p class="text-xs leading-relaxed text-muted">${isSI(o) ? "CPHEEO guidance for residual pressure: 7 m for single-storey, 12 m for two-storey and 17 m for three-storey buildings. " : ""}Junctions below this pressure are marked red. Changing units does not convert values already entered.</p>`;
  const pats = model.patterns.map((p, i) => `
    <div class="space-y-1.5 rounded-md border border-line p-2">
      <div class="flex items-center gap-2"><input class="inp font-mono" aria-label="Pattern ID" data-pat-id="${i}" value="${esc(p.id)}" maxlength="31" spellcheck="false"><button class="btn px-2 py-1 text-xs" data-pat-del="${i}">Remove</button></div>
      <textarea class="inp h-16 resize-y font-mono text-xs" aria-label="Multipliers for ${esc(p.id)}" data-pat-mult="${i}" spellcheck="false">${p.mult.join(", ")}</textarea>
      <p class="text-[11px] text-muted">${p.mult.length} multipliers, average ${fmt(p.mult.reduce((a, b) => a + b, 0) / p.mult.length, 2)}, one per ${o.patStep} min</p>
    </div>`).join("");
  insp.innerHTML = `
    <div class="border-b border-line px-4 py-3"><div class="eyebrow">Network</div><div class="truncate text-base font-semibold">${esc(model.title)}</div></div>
    ${section("Summary", summary)}
    ${section("Settings", settings + `<p id="insp-err" class="text-xs text-crit" hidden></p>`)}
    ${section("Demand patterns", (pats || `<p class="text-[13px] text-muted">No patterns. Demands stay constant through the run.</p>`) + `<button class="btn w-full justify-center" id="pat-add">Add 24-hour pattern</button>`)}
    ${section("Shortcuts", `<p class="text-xs leading-relaxed text-muted">S select · J junction · R reservoir · T tank · P pipe · M pump · V valve · Del delete · Esc cancel · Ctrl+Z undo · hold Alt to place without snapping.</p>`)}`;

  insp.querySelectorAll("[data-k]").forEach((input) => input.addEventListener("change", () => {
    const k = input.dataset.k;
    let v = input.tagName === "SELECT" ? input.value : num(input.value);
    if (typeof v === "number" && (Number.isNaN(v) || v < 0 || ((k === "hydStep" || k === "patStep") && v <= 0))) {
      const err = $("insp-err"); err.textContent = "Enter a valid positive number."; err.hidden = false; input.value = o[k]; return;
    }
    checkpoint();
    o[k] = v;
    changed({ keepResults: k === "minPressure" });
  }));
  insp.querySelectorAll("[data-pat-id]").forEach((input) => input.addEventListener("change", () => {
    const p = model.patterns[+input.dataset.patId];
    const id = input.value.trim();
    if (!validId(id) || model.patterns.some((q) => q !== p && q.id === id)) { input.value = p.id; return; }
    checkpoint();
    for (const n of model.nodes) if (n.pattern === p.id) n.pattern = id;
    p.id = id;
    changed();
  }));
  insp.querySelectorAll("[data-pat-mult]").forEach((ta) => ta.addEventListener("change", () => {
    const vals = ta.value.split(/[\s,;]+/).filter(Boolean).map(num);
    if (!vals.length || vals.some((v) => Number.isNaN(v) || v < 0)) { ta.value = model.patterns[+ta.dataset.patMult].mult.join(", "); return; }
    checkpoint();
    model.patterns[+ta.dataset.patMult].mult = vals;
    changed();
  }));
  insp.querySelectorAll("[data-pat-del]").forEach((b) => (b.onclick = () => {
    const p = model.patterns[+b.dataset.patDel];
    checkpoint();
    model.patterns.splice(+b.dataset.patDel, 1);
    for (const n of model.nodes) if (n.pattern === p.id) n.pattern = "";
    changed();
  }));
  $("pat-add").onclick = () => {
    checkpoint();
    let i = 1;
    while (model.patterns.some((p) => p.id === `PAT${i}`)) i++;
    model.patterns.push({ id: `PAT${i}`, mult: Array(24).fill(1) });
    changed();
  };
}

/* ----------------------------------------------------------- INP writer */

function validate(m) {
  const errs = [];
  if (!m.nodes.length) errs.push("The network is empty. Add a reservoir or tank, junctions and pipes.");
  if (!m.nodes.some((n) => n.kind !== "junction")) errs.push("Add at least one reservoir or tank to supply the network.");
  if (!m.nodes.some((n) => n.kind === "junction")) errs.push("Add at least one junction.");
  const linked = new Set(m.links.flatMap((l) => [l.from, l.to]));
  const loose = m.nodes.filter((n) => !linked.has(n.id)).map((n) => n.id);
  if (loose.length) errs.push(`Not connected to any pipe: ${loose.slice(0, 12).join(", ")}${loose.length > 12 ? ` and ${loose.length - 12} more` : ""}.`);
  for (const l of m.links) if (l.kind === "pump" && l.controlTank && !(l.startLevel < l.stopLevel)) errs.push(`Pump ${l.id}: the start level must be below the stop level.`);
  for (const n of m.nodes) if (n.kind === "tank" && !(n.minLevel <= n.initLevel && n.initLevel <= n.maxLevel)) errs.push(`Tank ${n.id}: the initial level must lie between the minimum and maximum levels.`);
  return errs;
}

function toInp(m) {
  const o = m.options;
  const L = [];
  const row = (...cols) => L.push(" " + cols.map((c) => String(c).padEnd(14)).join(" ").trimEnd());
  L.push("[TITLE]", m.title || "Network", "");
  L.push("[JUNCTIONS]", ";ID            Elev           Demand         Pattern");
  for (const n of m.nodes.filter((n) => n.kind === "junction")) row(n.id, inpNum(n.elev), inpNum(n.demand), n.pattern || "");
  L.push("", "[RESERVOIRS]", ";ID            Head           Pattern");
  for (const n of m.nodes.filter((n) => n.kind === "reservoir")) row(n.id, inpNum(n.head), n.pattern || "");
  L.push("", "[TANKS]", ";ID            Elevation      InitLevel      MinLevel       MaxLevel       Diameter       MinVol");
  for (const n of m.nodes.filter((n) => n.kind === "tank")) row(n.id, inpNum(n.elev), inpNum(n.initLevel), inpNum(n.minLevel), inpNum(n.maxLevel), inpNum(n.diameter), 0);
  L.push("", "[PIPES]", ";ID            Node1          Node2          Length         Diameter       Roughness      MinorLoss      Status");
  for (const l of m.links.filter((l) => l.kind === "pipe")) row(l.id, l.from, l.to, inpNum(l.length), inpNum(l.diameter), inpNum(l.roughness), inpNum(l.minorLoss), l.status || "Open");
  L.push("", "[PUMPS]", ";ID            Node1          Node2          Parameters");
  const pumps = m.links.filter((l) => l.kind === "pump");
  for (const l of pumps) row(l.id, l.from, l.to, "HEAD", `C_${l.id}`);
  L.push("", "[VALVES]", ";ID            Node1          Node2          Diameter       Type           Setting        MinorLoss");
  const valves = m.links.filter((l) => l.kind === "valve");
  for (const l of valves) row(l.id, l.from, l.to, inpNum(l.diameter), l.valveType, inpNum(l.setting), inpNum(l.minorLoss));
  L.push("", "[STATUS]");
  for (const l of pumps) if (l.status === "Closed") row(l.id, "Closed");
  for (const l of valves) if (l.status === "Open" || l.status === "Closed") row(l.id, l.status);
  L.push("", "[CONTROLS]");
  for (const l of pumps) {
    if (!l.controlTank || !m.nodes.some((n) => n.id === l.controlTank)) continue;
    L.push(` LINK ${l.id} OPEN IF NODE ${l.controlTank} BELOW ${inpNum(l.startLevel)}`);
    L.push(` LINK ${l.id} CLOSED IF NODE ${l.controlTank} ABOVE ${inpNum(l.stopLevel)}`);
  }
  L.push("", "[PATTERNS]");
  for (const p of m.patterns) for (let i = 0; i < p.mult.length; i += 6) row(p.id, ...p.mult.slice(i, i + 6).map(inpNum));
  L.push("", "[CURVES]", ";ID            Flow           Head");
  for (const l of pumps) row(`C_${l.id}`, inpNum(l.pumpFlow), inpNum(l.pumpHead));
  const hm = (min) => `${Math.floor(min / 60)}:${String(Math.round(min % 60)).padStart(2, "0")}`;
  L.push("", "[TIMES]", ` Duration           ${hm(o.duration * 60)}`, ` Hydraulic Timestep ${hm(o.hydStep)}`, ` Pattern Timestep   ${hm(o.patStep)}`, ` Report Timestep    ${hm(o.hydStep)}`);
  L.push("", "[REPORT]", " Status             No", " Summary            No");
  L.push("", "[OPTIONS]", ` Units              ${o.units}`, ` Headloss           ${o.headloss}`);
  L.push("", "[COORDINATES]", ";Node           X-Coord        Y-Coord");
  for (const n of m.nodes) row(n.id, inpNum(n.x), inpNum(n.y));
  L.push("", "[END]", "");
  return L.join("\n");
}

/* -------------------------------------------------------------- engine */

let workspace = null;
const engineReady = (async () => {
  try {
    const ws = new Workspace();
    await ws.loadModule();
    workspace = ws;
    const v = ws.version;
    log(`EPANET ${Math.floor(v / 10000)}.${Math.floor((v % 10000) / 100)}.${v % 100} engine loaded. Everything runs on this computer; no internet needed.`, "ok");
    setRunState();
  } catch (err) {
    log(`The EPANET engine could not start: ${err.message}. Try opening the page in a current version of Chrome, Edge or Firefox.`, "error");
    setRunState("Engine failed", "crit");
  }
})();

function reportErrors() {
  try {
    const rpt = workspace.readFile("model.rpt");
    return rpt.split("\n").map((s) => s.trim()).filter((s) => /^(Error|Warning|WARNING)/i.test(s) || /^\d+:/.test(s)).slice(0, 12);
  } catch { return []; }
}
const cleanErr = (err) => (err?.message || String(err)).replace(/^EPANET Error (\d+): Error \1: /, "EPANET error $1: ");

async function runSimulation() {
  await engineReady;
  if (!workspace) return;
  const errs = validate(model);
  if (errs.length) {
    showTab("log");
    log("Cannot run yet:", "error");
    errs.forEach((e) => log(`  • ${e}`, "error"));
    return;
  }
  const btn = $("btn-run");
  btn.disabled = true;
  showTab("log");
  log(`Running “${model.title}”: ${model.nodes.length} nodes, ${model.links.length} links, ${model.options.duration} h…`);
  await new Promise((r) => setTimeout(r, 0));
  const project = new Project(workspace);
  let opened = false, hyd = false;
  try {
    workspace.writeFile("model.inp", toInp(model));
    try { project.open("model.inp", "model.rpt", ""); }
    catch (err) {
      try { project.close(); } catch {}
      const lines = reportErrors();
      log(cleanErr(err), "error");
      lines.forEach((l) => log(`  ${l}`, "error"));
      return;
    }
    opened = true;
    const nodeIdx = new Map(), linkIdx = new Map();
    const nN = project.getCount(CountType.NodeCount), nL = project.getCount(CountType.LinkCount);
    for (let i = 1; i <= nN; i++) nodeIdx.set(project.getNodeId(i), i - 1);
    for (let i = 1; i <= nL; i++) linkIdx.set(project.getLinkId(i), i - 1);
    project.openH(); hyd = true;
    project.initH(InitHydOption.NoSave);
    const steps = [];
    let tstep = 0;
    do {
      const t = project.runH();
      const s = { t, P: new Float32Array(nN), H: new Float32Array(nN), D: new Float32Array(nN), Q: new Float32Array(nL), V: new Float32Array(nL), HL: new Float32Array(nL), S: new Uint8Array(nL) };
      for (let i = 1; i <= nN; i++) {
        s.P[i - 1] = project.getNodeValue(i, NodeProperty.Pressure);
        s.H[i - 1] = project.getNodeValue(i, NodeProperty.Head);
        s.D[i - 1] = project.getNodeValue(i, NodeProperty.Demand);
      }
      for (let i = 1; i <= nL; i++) {
        s.Q[i - 1] = project.getLinkValue(i, LinkProperty.Flow);
        s.V[i - 1] = project.getLinkValue(i, LinkProperty.Velocity);
        s.HL[i - 1] = project.getLinkValue(i, LinkProperty.Headloss);
        s.S[i - 1] = project.getLinkValue(i, LinkProperty.Status);
      }
      steps.push(s);
      tstep = project.nextH();
      if (steps.length % 12 === 0) { log(`  solved to ${clock(t)}`); await new Promise((r) => setTimeout(r, 0)); }
    } while (tstep > 0);
    project.closeH(); hyd = false;
    project.close(); opened = false; // flushes the report file
    results = { steps, nodeIdx, linkIdx, units: U() };
    resultsStale = false;
    timeIndex = 0;
    const warn = reportWarnings();
    const endT = steps.at(-1).t, duration = model.options.duration * 3600;
    if (endT < duration - 1) {
      log(`Simulation stopped early at ${clock(endT)} of ${clock(duration)}: EPANET could not balance the network. Results up to that time are shown.`, "error");
      log(`  Check pumps against full tanks (add level control), closed paths, or very small pipes.`, "error");
    } else log(`Simulation complete: ${steps.length} time step${steps.length > 1 ? "s" : ""}.`, "ok");
    warn.forEach((w) => log(`  ${w}`, "warn"));
    summariseRun();
    renderAll();
    showTab("nodes");
  } catch (err) {
    log(cleanErr(err), "error");
    reportErrors().forEach((l) => log(`  ${l}`, "error"));
  } finally {
    if (hyd) try { project.closeH(); } catch {}
    if (opened) try { project.close(); } catch {}
    btn.disabled = false;
  }
}
function reportWarnings() {
  try {
    const rpt = workspace.readFile("model.rpt");
    return [...new Set(rpt.split("\n").map((s) => s.trim()).filter((s) => /WARNING/i.test(s)).map((s) => s.replace(/^\d+:\d+:\d+:\s*/, "")))].slice(0, 8);
  } catch { return []; }
}
function summariseRun() {
  let worst = { p: Infinity, id: "", t: 0 };
  const junctions = model.nodes.filter((n) => n.kind === "junction");
  const lowSet = new Set();
  for (const s of results.steps) for (const n of junctions) {
    const p = s.P[results.nodeIdx.get(n.id)];
    if (p < worst.p) worst = { p, id: n.id, t: s.t };
    if (p < model.options.minPressure) lowSet.add(n.id);
  }
  const u = results.units.press;
  log(`  Lowest junction pressure: ${fmt(worst.p)} ${u} at ${worst.id}, time ${clock(worst.t)}.`);
  log(lowSet.size ? `  ${lowSet.size} junction${lowSet.size > 1 ? "s" : ""} fall below the ${fmt(model.options.minPressure, 0)} ${u} minimum at some time: ${[...lowSet].slice(0, 15).join(", ")}.` : `  All junctions stay at or above the ${fmt(model.options.minPressure, 0)} ${u} minimum.`, lowSet.size ? "warn" : "ok");
}
function statusText(s) {
  return s === 0 ? "Closed" : "Open";
}

/* --------------------------------------------------------------- import */

async function importInp(text, name) {
  await engineReady;
  if (!workspace) return;
  const project = new Project(workspace);
  const notes = [];
  try {
    workspace.writeFile("import.inp", text);
    try { project.open("import.inp", "import.rpt", ""); }
    catch (err) {
      try { project.close(); } catch {}
      log(`Could not read ${name}: ${cleanErr(err)}`, "error");
      try { workspace.readFile("import.rpt").split("\n").filter((s) => /Error/i.test(s)).slice(0, 8).forEach((s) => log(`  ${s.trim()}`, "error")); } catch {}
      return;
    }
    const m = emptyModel(FLOW_ENUM[project.getFlowUnits()] || "LPS");
    m.title = (project.getTitle?.().line1 || "").trim() || name.replace(/\.inp$/i, "");
    m.options.headloss = ["H-W", "D-W", "C-M"][project.getOption(7)] || "H-W";
    m.options.duration = round(project.getTimeParameter(TimeParameter.Duration) / 3600, 3);
    m.options.hydStep = round(project.getTimeParameter(TimeParameter.HydStep) / 60, 2);
    m.options.patStep = round(project.getTimeParameter(TimeParameter.PatternStep) / 60, 2);
    m.options.minPressure = defaults(m.options).minPressure;
    const nP = project.getCount(CountType.PatCount);
    const patIds = [""];
    for (let i = 1; i <= nP; i++) {
      const id = project.getPatternId(i);
      patIds.push(id);
      const len = project.getPatternLength(i);
      m.patterns.push({ id, mult: Array.from({ length: len }, (_, k) => round(project.getPatternValue(i, k + 1), 4)) });
    }
    const nN = project.getCount(CountType.NodeCount);
    let missingXY = 0;
    for (let i = 1; i <= nN; i++) {
      const id = project.getNodeId(i);
      const type = project.getNodeType(i);
      let x = 0, y = 0;
      try { ({ x, y } = project.getCoordinates(i)); } catch { missingXY++; const a = (i / nN) * 2 * Math.PI; x = round(500 * Math.cos(a), 1); y = round(500 * Math.sin(a), 1); }
      const elev = round(project.getNodeValue(i, NodeProperty.Elevation), 4);
      const pat = patIds[project.getNodeValue(i, NodeProperty.Pattern)] ?? "";
      if (type === NodeType.Junction) {
        const nd = project.getNumberOfDemands(i);
        let demand = 0, dpat = pat;
        for (let d = 1; d <= nd; d++) demand += project.getBaseDemand(i, d);
        if (nd >= 1) dpat = patIds[project.getDemandPattern(i, 1)] ?? "";
        if (nd > 1) notes.push(`${id}: ${nd} demand categories combined into one.`);
        m.nodes.push({ id, kind: "junction", x, y, elev, demand: round(demand, 6), pattern: dpat });
      } else if (type === NodeType.Reservoir) {
        m.nodes.push({ id, kind: "reservoir", x, y, head: elev, pattern: pat });
      } else {
        m.nodes.push({
          id, kind: "tank", x, y, elev,
          initLevel: round(project.getNodeValue(i, NodeProperty.TankLevel), 4),
          minLevel: round(project.getNodeValue(i, NodeProperty.MinLevel), 4),
          maxLevel: round(project.getNodeValue(i, NodeProperty.MaxLevel), 4),
          diameter: round(project.getNodeValue(i, NodeProperty.TankDiam), 4),
        });
        if (project.getNodeValue(i, NodeProperty.VolCurve) > 0) notes.push(`Tank ${id}: volume curve replaced by a cylinder of the same diameter.`);
      }
    }
    if (missingXY) notes.push(`${missingXY} node${missingXY > 1 ? "s had" : " had"} no coordinates and were placed on a circle.`);
    const nL = project.getCount(CountType.LinkCount);
    const vtypes = { [LinkType.PRV]: "PRV", [LinkType.PSV]: "PSV", [LinkType.PBV]: "PBV", [LinkType.FCV]: "FCV", [LinkType.TCV]: "TCV" };
    for (let i = 1; i <= nL; i++) {
      const id = project.getLinkId(i);
      const type = project.getLinkType(i);
      const { node1, node2 } = project.getLinkNodes(i);
      const from = project.getNodeId(node1), to = project.getNodeId(node2);
      const open = project.getLinkValue(i, LinkProperty.InitStatus) !== 0;
      if (type === LinkType.Pipe || type === LinkType.CVPipe) {
        m.links.push({
          id, kind: "pipe", from, to, autoLength: false,
          length: round(project.getLinkValue(i, LinkProperty.Length), 4),
          diameter: round(project.getLinkValue(i, LinkProperty.Diameter), 4),
          roughness: round(project.getLinkValue(i, LinkProperty.Roughness), 6),
          minorLoss: round(project.getLinkValue(i, LinkProperty.MinorLoss), 4),
          status: type === LinkType.CVPipe ? "CV" : open ? "Open" : "Closed",
        });
      } else if (type === LinkType.Pump) {
        const ci = project.getHeadCurveIndex(i);
        let flow = defaults(m.options).pumpFlow, head = defaults(m.options).pumpHead;
        if (ci > 0) {
          const n = project.getCurveLenth(ci);
          const pt = project.getCurveValue(ci, n === 3 ? 2 : 1);
          flow = round(pt.x, 4); head = round(pt.y, 4);
          if (n > 1) notes.push(`Pump ${id}: ${n}-point curve simplified to its design point (${flow}, ${head}).`);
        } else notes.push(`Pump ${id}: constant-power pump replaced by a default one-point curve. Check its flow and head.`);
        m.links.push({ id, kind: "pump", from, to, pumpFlow: flow, pumpHead: head, status: open ? "Open" : "Closed" });
      } else if (vtypes[type]) {
        m.links.push({
          id, kind: "valve", from, to, valveType: vtypes[type],
          diameter: round(project.getLinkValue(i, LinkProperty.Diameter), 4),
          setting: round(project.getLinkValue(i, LinkProperty.InitSetting), 4),
          minorLoss: round(project.getLinkValue(i, LinkProperty.MinorLoss), 4),
          status: "Active",
        });
      } else {
        notes.push(`${id}: general-purpose valve imported as an open pipe.`);
        m.links.push({ id, kind: "pipe", from, to, autoLength: false, length: 1, diameter: round(project.getLinkValue(i, LinkProperty.Diameter), 4), roughness: defaults(m.options).rough, minorLoss: 0, status: "Open" });
      }
    }
    // Map simple tank-level pump controls; other controls and rules are skipped.
    let skipped = project.getCount(CountType.RuleCount);
    const nC = project.getCount(CountType.ControlCount);
    for (let c = 1; c <= nC; c++) {
      const ctl = project.getControl(c);
      const pump = m.links.find((l) => l.id === project.getLinkId(ctl.linkIndex));
      const node = ctl.nodeIndex > 0 ? m.nodes.find((n) => n.id === project.getNodeId(ctl.nodeIndex)) : null;
      const ok = pump?.kind === "pump" && node?.kind === "tank" && (!pump.controlTank || pump.controlTank === node.id);
      if (ok && ctl.type === 0 && ctl.setting > 0) { pump.controlTank = node.id; pump.startLevel = round(ctl.level, 4); }
      else if (ok && ctl.type === 1 && ctl.setting === 0) { pump.controlTank = node.id; pump.stopLevel = round(ctl.level, 4); }
      else skipped++;
    }
    for (const l of m.links) if (l.controlTank && (l.startLevel == null || l.stopLevel == null)) {
      const t = m.nodes.find((n) => n.id === l.controlTank);
      l.startLevel ??= t.minLevel; l.stopLevel ??= t.maxLevel;
      notes.push(`Pump ${l.id}: only one of its start/stop levels was set in the file; the other uses the tank limit.`);
    }
    if (skipped) notes.push(`${skipped} control${skipped > 1 ? "s" : ""} or rule${skipped > 1 ? "s" : ""} not imported. Only pump start/stop on tank level is supported.`);
    replaceModel(m);
    log(`Imported ${name}: ${m.nodes.length} nodes, ${m.links.length} links.`, "ok");
    notes.slice(0, 12).forEach((n) => log(`  Note: ${n}`, "warn"));
    if (notes.length > 12) log(`  …and ${notes.length - 12} more notes.`, "warn");
  } catch (err) {
    log(`Could not import ${name}: ${cleanErr(err)}`, "error");
  } finally {
    try { project.close(); } catch {}
  }
}

/* -------------------------------------------------------- results dock */

function showTab(name) {
  document.querySelectorAll("#tabs .tab").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.tab === name)));
  document.querySelectorAll("[data-panel]").forEach((p) => (p.hidden = p.dataset.panel !== name));
  activeTab = name;
  renderDock();
}
let activeTab = "log";
document.querySelectorAll("#tabs .tab").forEach((t) => (t.onclick = () => showTab(t.dataset.tab)));

function setRunState(text, tone) {
  const el = $("run-state");
  if (text == null) {
    if (!workspace) { text = "Loading engine…"; tone = "muted"; }
    else if (results) { text = `Results · ${results.steps.length} step${results.steps.length > 1 ? "s" : ""}`; tone = "good"; }
    else if (resultsStale) { text = "Edited since last run"; tone = "warn"; }
    else { text = "Not run yet"; tone = "muted"; }
  }
  const tones = {
    muted: "background:var(--sunk);color:var(--muted)",
    good: "background:color-mix(in srgb, var(--good) 16%, transparent);color:var(--ink)",
    warn: "background:color-mix(in srgb, var(--select) 20%, transparent);color:var(--ink)",
    crit: "background:color-mix(in srgb, var(--crit) 18%, transparent);color:var(--ink)",
  };
  el.textContent = text;
  el.style.cssText = tones[tone];
}

function renderTime() {
  const ctl = $("time-ctl");
  if (!results || results.steps.length < 2) { ctl.hidden = !results; }
  else ctl.hidden = false;
  if (!results) return;
  const sel = $("time-select");
  if (sel.options.length !== results.steps.length || sel.dataset.sig !== String(results.steps.length) + results.steps.at(-1).t) {
    sel.innerHTML = results.steps.map((s, i) => `<option value="${i}">${clock(s.t)}</option>`).join("");
    sel.dataset.sig = String(results.steps.length) + results.steps.at(-1).t;
  }
  sel.value = String(timeIndex);
  const range = $("time-range");
  range.max = String(results.steps.length - 1);
  range.value = String(timeIndex);
}
function setTime(i) {
  timeIndex = Math.max(0, Math.min(i, results.steps.length - 1));
  drawCanvas();
  renderInspector();
  renderTime();
  renderDock();
}
$("time-select").onchange = (e) => setTime(+e.target.value);
$("time-range").oninput = (e) => setTime(+e.target.value);
let playTimer = null;
$("play").onclick = () => {
  if (playTimer) { clearInterval(playTimer); playTimer = null; $("play").textContent = "▶"; return; }
  if (!results) return;
  if (timeIndex >= results.steps.length - 1) setTime(0);
  $("play").textContent = "❚❚";
  playTimer = setInterval(() => {
    if (!results || timeIndex >= results.steps.length - 1) { clearInterval(playTimer); playTimer = null; $("play").textContent = "▶"; return; }
    setTime(timeIndex + 1);
  }, 450);
};

function renderDock() {
  if (activeTab === "nodes") renderNodeTable();
  else if (activeTab === "links") renderLinkTable();
  else if (activeTab === "graph") renderGraph();
}
const emptyPanel = (msg) => `<p class="px-4 py-6 text-[13px] text-muted">${msg}</p>`;

function renderNodeTable() {
  const panel = document.querySelector('[data-panel="nodes"]');
  if (!results) { panel.innerHTML = emptyPanel(resultsStale ? "The network changed since the last run. Run the simulation again to see node results." : "Run the simulation to see pressure, head and demand at every node."); return; }
  const u = results.units, s = results.steps[timeIndex], min = model.options.minPressure;
  const junc = model.nodes.filter((n) => n.kind === "junction");
  let lowest = null, below = 0;
  for (const n of junc) { const p = s.P[results.nodeIdx.get(n.id)]; if (!lowest || p < lowest.p) lowest = { id: n.id, p }; if (p < min) below++; }
  const head = `<div class="flex flex-wrap gap-x-6 gap-y-1 border-b border-line px-4 py-2 text-[13px]">
      <span>At <b class="tabular-nums">${clock(s.t)}</b></span>
      ${lowest ? `<span>Lowest pressure <b class="tabular-nums">${fmt(lowest.p)} ${u.press}</b> at <span class="font-mono">${esc(lowest.id)}</span></span>` : ""}
      <span>${below ? `<b class="text-crit">▲ ${below} below ${fmt(min, 0)} ${u.press}</b>` : `<span class="text-good">✓</span> All junctions at or above ${fmt(min, 0)} ${u.press}`}</span></div>`;
  const rows = model.nodes.map((n) => {
    const k = results.nodeIdx.get(n.id);
    const p = s.P[k];
    const low = n.kind === "junction" && p < min;
    const sel = selection?.type === "node" && selection.id === n.id;
    const level = n.kind === "tank" ? fmt(s.H[k] - n.elev) : "–";
    return `<tr data-row-node="${esc(n.id)}" aria-selected="${sel}">
      <td class="font-mono">${esc(n.id)}</td><td class="text-muted">${KIND_LABEL[n.kind]}</td>
      <td class="num">${n.kind === "reservoir" ? "–" : fmt(n.elev)}</td>
      <td class="num">${n.kind === "junction" ? fmt(s.D[k], 3) : fmt(-s.D[k], 3)}</td>
      <td class="num">${fmt(s.H[k])}</td>
      <td class="num">${n.kind === "junction" ? `<span class="${low ? "font-semibold text-crit" : ""}">${low ? "▲ " : ""}${fmt(p)}</span>` : "–"}</td>
      <td class="num">${level}</td></tr>`;
  }).join("");
  panel.innerHTML = head + `<table class="rtable"><thead><tr><th>Node</th><th>Type</th><th class="num">Elevation (${u.elev})</th><th class="num">Demand / supply (${esc(u.flow)})</th><th class="num">Head (${u.head})</th><th class="num">Pressure (${u.press})</th><th class="num">Tank level (${u.len})</th></tr></thead><tbody>${rows}</tbody></table>`;
  panel.querySelectorAll("[data-row-node]").forEach((r) => (r.onclick = () => { selection = { type: "node", id: r.dataset.rowNode }; renderSelection(); }));
}

function renderLinkTable() {
  const panel = document.querySelector('[data-panel="links"]');
  if (!results) { panel.innerHTML = emptyPanel(resultsStale ? "The network changed since the last run. Run the simulation again to see link results." : "Run the simulation to see flow, velocity and headloss in every pipe, pump and valve."); return; }
  const u = results.units, s = results.steps[timeIndex];
  const rows = model.links.map((l) => {
    const k = results.linkIdx.get(l.id);
    const sel = selection?.type === "link" && selection.id === l.id;
    return `<tr data-row-link="${esc(l.id)}" aria-selected="${sel}">
      <td class="font-mono">${esc(l.id)}</td><td class="text-muted">${KIND_LABEL[l.kind]}${l.kind === "valve" ? ` ${l.valveType}` : ""}</td>
      <td class="font-mono">${esc(l.from)}</td><td class="font-mono">${esc(l.to)}</td>
      <td class="num">${l.kind === "pump" ? "–" : fmt(l.diameter, 0)}</td>
      <td class="num">${fmt(s.Q[k], 3)}</td><td class="num">${fmt(s.V[k])}</td>
      <td class="num">${l.kind === "pipe" ? fmt(s.HL[k]) : "–"}</td>
      <td>${statusText(s.S[k])}</td></tr>`;
  }).join("");
  panel.innerHTML = `<table class="rtable"><thead><tr><th>Link</th><th>Type</th><th>From</th><th>To</th><th class="num">Diameter (${u.diam})</th><th class="num">Flow (${esc(u.flow)})</th><th class="num">Velocity (${u.vel})</th><th class="num">Headloss (${u.hlUnit})</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table>`;
  panel.querySelectorAll("[data-row-link]").forEach((r) => (r.onclick = () => { selection = { type: "link", id: r.dataset.rowLink }; renderSelection(); }));
}

function renderGraph() {
  const panel = document.querySelector('[data-panel="graph"]');
  if (!results) { panel.innerHTML = emptyPanel("Run the simulation, then select a junction, tank or pipe to chart it over time."); return; }
  if (results.steps.length < 2) { panel.innerHTML = emptyPanel("This was a single-snapshot run (duration 0 h). Set a duration in Network settings to see values over time."); return; }
  const u = results.units;
  // What to plot: the selection, else the junction with the lowest pressure.
  let target = selection;
  if (!target) {
    let worst = null;
    for (const n of model.nodes.filter((n) => n.kind === "junction")) {
      const k = results.nodeIdx.get(n.id);
      const m = Math.min(...results.steps.map((s) => s.P[k]));
      if (!worst || m < worst.m) worst = { id: n.id, m };
    }
    if (worst) target = { type: "node", id: worst.id, auto: true };
  }
  if (!target) { panel.innerHTML = emptyPanel("Select an item on the plan to chart it."); return; }
  let title, unit, series, showMin = false;
  if (target.type === "node") {
    const n = nodeById(target.id), k = results.nodeIdx.get(target.id);
    if (n.kind === "junction") { title = `Pressure at ${n.id}`; unit = u.press; series = results.steps.map((s) => s.P[k]); showMin = true; }
    else if (n.kind === "tank") { title = `Water level in ${n.id}`; unit = u.len; series = results.steps.map((s) => s.H[k] - n.elev); }
    else { title = `Outflow from ${n.id}`; unit = u.flow; series = results.steps.map((s) => -s.D[k]); }
  } else {
    const k = results.linkIdx.get(target.id);
    title = `Flow in ${target.id}`; unit = u.flow; series = results.steps.map((s) => s.Q[k]);
  }
  const times = results.steps.map((s) => s.t / 3600);
  const min = model.options.minPressure;
  const W = Math.max(panel.clientWidth - 24, 280), H = Math.max(panel.clientHeight - 48, 140);
  const m = { l: 48, r: 16, t: 10, b: 26 };
  let y0 = Math.min(...series, showMin ? min : Infinity), y1 = Math.max(...series, showMin ? min : -Infinity);
  if (y1 - y0 < 1e-6) { y0 -= 1; y1 += 1; }
  const yStep = niceStep((y1 - y0) / 4);
  y0 = Math.floor(y0 / yStep) * yStep; y1 = Math.ceil(y1 / yStep) * yStep;
  const x1 = times.at(-1) || 1;
  const X = (h) => m.l + (h / x1) * (W - m.l - m.r);
  const Y = (v) => m.t + (1 - (v - y0) / (y1 - y0)) * (H - m.t - m.b);
  const xStep = x1 <= 12 ? 1 : x1 <= 48 ? 3 : niceStep(x1 / 8);
  let g = "";
  for (let v = y0; v <= y1 + 1e-9; v += yStep) g += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line)"/><text x="${m.l - 6}" y="${Y(v) + 4}" text-anchor="end" fill="var(--muted)" font-size="11">${fmt(v, yStep < 1 ? 1 : 0)}</text>`;
  for (let h = 0; h <= x1 + 1e-9; h += xStep) g += `<text x="${X(h)}" y="${H - 8}" text-anchor="middle" fill="var(--muted)" font-size="11">${h}h</text>`;
  if (showMin) g += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(min)}" y2="${Y(min)}" stroke="var(--crit)" stroke-width="1.5" stroke-dasharray="5 4"/><text x="${W - m.r}" y="${Y(min) - 5}" text-anchor="end" fill="var(--ink)" font-size="11">Minimum ${fmt(min, 0)} ${esc(unit)}</text>`;
  const path = series.map((v, i) => `${i ? "L" : "M"}${X(times[i]).toFixed(1)} ${Y(v).toFixed(1)}`).join("");
  const area = `${path}L${X(times.at(-1))} ${Y(y0)}L${X(0)} ${Y(y0)}Z`;
  const cur = timeIndex;
  panel.innerHTML = `<div class="mb-1 flex items-baseline gap-2 text-[13px]"><b>${esc(title)}</b><span class="text-muted">(${esc(unit)})${target.auto ? " · lowest-pressure junction; select another item to change" : ""}</span></div>
    <div class="relative"><svg id="chart" width="${W}" height="${H}" class="block max-w-full" role="img" aria-label="${esc(title)} over time">
      ${g}
      <path d="${area}" fill="var(--seq-3)" opacity=".10"/>
      <path d="${path}" fill="none" stroke="var(--seq-3)" stroke-width="2" stroke-linejoin="round"/>
      <line id="ch-now" x1="${X(times[cur])}" x2="${X(times[cur])}" y1="${m.t}" y2="${H - m.b}" stroke="var(--muted)" stroke-dasharray="2 3"/>
      <circle cx="${X(times[cur])}" cy="${Y(series[cur])}" r="4.5" fill="var(--seq-3)" stroke="var(--panel)" stroke-width="2"/>
      <g id="ch-hover" visibility="hidden"><line id="ch-hl" y1="${m.t}" y2="${H - m.b}" stroke="var(--ink)" stroke-opacity=".35"/><circle id="ch-hc" r="4" fill="var(--panel)" stroke="var(--seq-3)" stroke-width="2"/></g>
      <rect x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${H - m.t - m.b}" fill="transparent" id="ch-hit"/>
    </svg><div id="ch-tip" hidden class="pointer-events-none absolute rounded-md bg-panel px-2 py-1 text-xs shadow ring-1 ring-line tabular-nums"></div></div>`;
  const hit = $("ch-hit"), tip = $("ch-tip");
  const nearest = (evt) => {
    const r = $("chart").getBoundingClientRect();
    const h = ((evt.clientX - r.left - m.l) / (W - m.l - m.r)) * x1;
    let best = 0;
    times.forEach((t, i) => { if (Math.abs(t - h) < Math.abs(times[best] - h)) best = i; });
    return best;
  };
  hit.onpointermove = (evt) => {
    const i = nearest(evt);
    $("ch-hover").setAttribute("visibility", "visible");
    $("ch-hl").setAttribute("x1", X(times[i])); $("ch-hl").setAttribute("x2", X(times[i]));
    $("ch-hc").setAttribute("cx", X(times[i])); $("ch-hc").setAttribute("cy", Y(series[i]));
    tip.innerHTML = `<span class="text-muted">${clock(results.steps[i].t)}</span> <b>${fmt(series[i])}</b> ${esc(unit)}`;
    tip.hidden = false;
    tip.style.left = `${Math.min(X(times[i]) + 10, W - 130)}px`;
    tip.style.top = `${Math.max(Y(series[i]) - 34, 0)}px`;
  };
  hit.onpointerleave = () => { $("ch-hover").setAttribute("visibility", "hidden"); tip.hidden = true; };
  hit.onclick = (evt) => setTime(nearest(evt));
}

/* ------------------------------------------------------ log & notices */

function log(msg, kind = "info") {
  const el = $("log");
  const color = { error: "var(--crit)", warn: "var(--ink)", ok: "var(--good)", info: "" }[kind];
  const line = document.createElement("div");
  const stamp = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  line.textContent = `${stamp}  ${msg}`;
  if (color) line.style.color = color;
  if (kind === "warn") line.style.fontWeight = "500";
  el.appendChild(line);
  el.parentElement.scrollTop = el.parentElement.scrollHeight;
}

function confirmBar(text, actionLabel, onConfirm) {
  const bar = $("notice");
  $("notice-text").textContent = text;
  const acts = $("notice-actions");
  acts.innerHTML = `<button class="btn-danger" id="nb-yes">${esc(actionLabel)}</button><button class="btn" id="nb-no">Cancel</button>`;
  bar.hidden = false;
  $("nb-yes").onclick = () => { bar.hidden = true; onConfirm(); };
  $("nb-no").onclick = () => { bar.hidden = true; };
  $("nb-no").focus();
}
const hasWork = () => model.nodes.length > 0;

$("btn-new").onclick = () => {
  const go = () => { replaceModel(emptyModel(model.options.units)); setTool("reservoir"); log("Started a new network. Place a reservoir or tank first, then junctions and pipes."); };
  hasWork() ? confirmBar("Start a new network? The current drawing will be cleared. You can undo this with Ctrl+Z.", "Clear and start new", go) : go();
};
$("btn-sample").onclick = () => {
  const go = () => { replaceModel(sampleModel()); setTool("select"); log("Loaded the sample network."); };
  hasWork() ? confirmBar("Replace the current drawing with the sample network? You can undo this with Ctrl+Z.", "Load sample", go) : go();
};
$("inp-import").onchange = async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  const text = await file.text();
  const go = () => importInp(text, file.name);
  hasWork() ? confirmBar(`Replace the current drawing with ${file.name}? You can undo this with Ctrl+Z.`, "Import", go) : go();
};
$("btn-run").onclick = runSimulation;

$("btn-export").onclick = () => {
  $("export-text").value = toInp(model);
  $("export-modal").hidden = false;
  $("export-copy").focus();
};
$("export-close").onclick = () => ($("export-modal").hidden = true);
$("export-modal").onclick = (e) => { if (e.target.id === "export-modal") $("export-modal").hidden = true; };
$("export-copy").onclick = async () => {
  const ta = $("export-text");
  try { await navigator.clipboard.writeText(ta.value); $("export-copy").textContent = "Copied"; }
  catch { ta.focus(); ta.select(); $("export-copy").textContent = "Text selected: press Ctrl+C"; }
  setTimeout(() => ($("export-copy").textContent = "Copy text"), 2500);
};
// Inside the claude.ai viewer, files go through its downloads capability
// (which does not accept .inp, so the file is offered as .inp.txt). Opened
// directly from disk, a normal browser download is used.
let viewerDownloads;
const inClaudeViewer = typeof window.claude?.use === "function";
if (inClaudeViewer) window.claude.use("downloads").then((d) => { viewerDownloads = d; }, () => { viewerDownloads = null; });
$("export-download").onclick = async () => {
  const text = $("export-text").value;
  const base = (model.title || "network").replace(/[^\w.-]+/g, "_").slice(0, 60);
  const btn = $("export-download");
  if (inClaudeViewer) {
    if (!viewerDownloads) { btn.textContent = "Not available here: use Copy text"; setTimeout(() => (btn.textContent = "Download .inp"), 3000); return; }
    try {
      await viewerDownloads.save({ filename: `${base}.inp.txt`, data: text });
      log(`Saved ${base}.inp.txt. Rename it to ${base}.inp to open it in EPANET.`, "ok");
    } catch (err) {
      if (err?.code !== "declined") log(`The file could not be saved (${err?.code || "error"}). Use Copy text instead.`, "error");
    }
    return;
  }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
  a.download = `${base}.inp`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
};

$("net-title").addEventListener("change", (e) => {
  checkpoint();
  model.title = e.target.value.trim() || "Untitled network";
  changed({ keepResults: true });
});

/* -------------------------------------------------------------- render */

function renderSelection() {
  drawCanvas();
  renderInspector();
  if (activeTab !== "log") renderDock();
}
function renderAll() {
  $("net-title").value = model.title;
  $("btn-undo").disabled = !undoStack.length;
  $("btn-redo").disabled = !redoStack.length;
  setRunState();
  drawCanvas();
  renderInspector();
  renderTime();
  renderDock();
}

/* ---------------------------------------------------------------- start */

const saved = loadSaved();
model = saved || sampleModel();
setTool("select");
renderAll();
fitView();
showTab("log");
log(saved ? `Restored your last drawing, “${model.title}”, from this browser.` : "Loaded a sample network so you can see how it works. Press Run simulation, or choose New network to start your own design.");
