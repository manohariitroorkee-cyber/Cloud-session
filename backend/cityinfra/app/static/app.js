/* City Infrastructure Designer – the page logic.
 *
 * One plain script, no build step and no outside libraries.  The drawing is kept as a
 * list of objects in project coordinates (metres, EPSG:32643) and sent to the local
 * server, which runs the engineering checks.  Every button and field carries a
 * data-help text: it shows as a tooltip, in the status line, and in the Help guide.
 */
'use strict';
(() => {
const EPSG = 32643, E0 = 704000, N0 = 3193000;
const SVGNS = 'http://www.w3.org/2000/svg';

// ------------------------------------------------------------------ small helpers
const $ = (s, r = document) => r.querySelector(s);
function h(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'text') e.textContent = v;
    else if (k === 'html') e.innerHTML = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (k === 'class') e.className = v;
    else e.setAttribute(k, v === true ? '' : v);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined && k !== false) e.append(k);
  return e;
}
function s(tag, attrs = {}) {
  const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) e.setAttribute(k, v);
  return e;
}
const uid = () => (crypto.randomUUID ? crypto.randomUUID()
  : 'id-' + Date.now().toString(36) + Math.random().toString(36).slice(2));
const clone = o => JSON.parse(JSON.stringify(o));
const pretty = v => String(v).replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());
const fmt = v => (typeof v === 'number' ? (Math.abs(v) >= 100 ? v.toFixed(1).replace(/\.0$/, '') : String(+v.toFixed(3))) : String(v));
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
const esc = t => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const empty = v => v === undefined || v === null || v === '' || (typeof v === 'number' && isNaN(v));
const store = {
  get(k) { try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage may be off */ } },
};

// ------------------------------------------------------------------ plain words for choices
const WORDS = {
  plastic: 'Plastic (general)', hdpe: 'HDPE plastic', upvc: 'uPVC plastic', di_unlined: 'Ductile iron',
  ci_unlined: 'Cast iron', rcc: 'Concrete (RCC)', stoneware: 'Stoneware (clay)', brick: 'Brick', grass: 'Grass-lined channel',
  residential: 'Homes', commercial: 'Shops and offices', arterial_road: 'Main road', underpass: 'Underpass',
  critical_infrastructure: 'Hospital, power station or other critical site', institutional: 'School, hospital or office',
  streetlight: 'Street lights', pumping: 'Water pump', ev_charging: 'Electric vehicle charging',
  plain: 'Flat land', rolling: 'Gently hilly land', mountainous: 'Hills', steep: 'Very steep hills',
  car: 'Cars only', bus: 'Buses', truck: 'Trucks', semi_trailer: 'Long trailer trucks',
  circular: 'Round pipe', rectangular: 'Box drain (rectangular)', trapezoidal: 'Open channel with sloping sides',
};
const word = v => WORDS[v] || pretty(v);

// road cross-section types: per side of the centre line (the model mirrors them)
const ROAD_TYPES = {
  lane2: { label: 'Two-lane street (7 m road, footpaths)',
    template: { strips: [{ type: 'carriageway', width: 3.5, crossfall_pct: -2.5 },
      { type: 'footpath', width: 2.0, crossfall_pct: 2.0, step_m: 0.15 }] } },
  lane4: { label: 'Four-lane divided road (with median)',
    template: { median: { width: 1.2, raised_m: 0.15 }, strips: [{ type: 'carriageway', width: 7.0, crossfall_pct: -2.5 },
      { type: 'footpath', width: 2.0, crossfall_pct: 2.0, step_m: 0.15 }, { type: 'drain', width: 1.0, crossfall_pct: 0 }] } },
  lane6: { label: 'Six-lane divided road (with cycle track)',
    template: { median: { width: 1.5, raised_m: 0.15 }, strips: [{ type: 'carriageway', width: 10.5, crossfall_pct: -2.5 },
      { type: 'cycle_track', width: 2.0, crossfall_pct: -2.0, step_m: 0.15 },
      { type: 'footpath', width: 2.5, crossfall_pct: 2.0, step_m: 0.1 }, { type: 'drain', width: 1.0, crossfall_pct: 0 }] } },
};
const SPEEDS = [20, 30, 40, 50, 60, 65, 80, 100];
const roadWidth = t => t ? 2 * (t.strips || []).reduce((a, x) => a + (+x.width || 0), 0) + (t.median ? +t.median.width || 0 : 0) : 7;

// catchment surface mixes (fractions of the area)
const SURFACE_MIX = {
  built: { label: 'Mostly roofs and paving', surfaces: { roof: 0.5, paved: 0.4, lawn_clay: 0.1 } },
  houses: { label: 'Houses with small gardens', surfaces: { roof: 0.35, paved: 0.4, lawn_clay: 0.25 } },
  park: { label: 'Parks and open land', surfaces: { lawn_clay: 0.7, open_ground: 0.2, paved: 0.1 } },
};
const mixOf = srf => {
  for (const [k, m] of Object.entries(SURFACE_MIX))
    if (srf && Object.keys(m.surfaces).length === Object.keys(srf).length
        && Object.entries(m.surfaces).every(([a, b]) => Math.abs((srf[a] || 0) - b) < 1e-6)) return k;
  return srf ? 'file' : '';
};

// junction layouts
const LAYOUTS = {
  cross: { label: 'Crossroad (4 roads)', type: 'intersection', arms: [[ 'N', 0, 'major'], ['E', 90], ['S', 180, 'major'], ['W', 270]] },
  tee: { label: 'T-junction (3 roads)', type: 'intersection', arms: [['E', 90, 'major'], ['S', 180], ['W', 270, 'major']] },
  wye: { label: 'Y-junction (3 roads)', type: 'intersection', arms: [['N', 0, 'major'], ['SE', 135], ['SW', 225, 'major']] },
  round: { label: 'Roundabout (4 roads)', type: 'roundabout', arms: [['N', 0], ['E', 90], ['S', 180], ['W', 270]] },
};
const CONTROLS = [['uncontrolled', 'No signs or signals'], ['priority', 'Stop / give-way signs on the side roads'],
  ['signal', 'Traffic signals']];

// ------------------------------------------------------------------ what can be drawn
// geometry: point | link (joins two points) | line (road) | area
const KINDS = {};
function kind(id, def) { KINDS[id] = Object.assign({ id, fields: [] }, def); }
const num = (key, label, help, unit, more = {}) => Object.assign({ key, label, help, unit, type: 'number' }, more);
const sel = (key, label, help, options, more = {}) => Object.assign({ key, label, help, type: 'select', options }, more);
const levelHelp = 'Height above sea level in metres, from the survey drawing (for example 216.4).';

kind('manhole', { label: 'Manhole', geom: 'point', prefix: 'MH', colour: '#8a5a2b', shape: 'ring',
  fields: [num('ground_level', 'Ground level', levelHelp, 'm', { req: true }),
    num('population', 'People whose sewage enters here', 'How many people live in the houses that connect to the sewer at this manhole (in the future, when the area is fully built).', 'people', { req: true, show: () => S.module === 'sewer' }),
    num('present_population', 'People living there today (optional)', 'Fewer people may live there now; this checks the pipe still stays clean in the early years. Leave empty if not known.', 'people', { show: () => S.module === 'sewer' })] });
kind('sewer_outfall', { label: 'Sewer outfall', geom: 'point', prefix: 'OUT', colour: '#8a5a2b', shape: 'tri',
  fields: [num('ground_level', 'Ground level', levelHelp, 'm', { req: true }),
    num('invert_level', 'Pipe bottom level where it leaves', 'Level of the inside bottom of the pipe at the treatment plant or main sewer it joins.', 'm', { req: true })] });
kind('sewer_pipe', { label: 'Sewer pipe', geom: 'link', prefix: 'S', colour: '#8a5a2b', from: ['manhole'], to: ['manhole', 'sewer_outfall'],
  fields: [sel('diameter_mm', 'Pipe size', 'Inside diameter of the pipe. The check tells you if it is too small.', () => OPT.sewer_diameters_mm.map(d => [d, d + ' mm']), { req: true, num: true }),
    sel('material', 'Pipe material', 'What the pipe is made of. It changes how easily water flows.', () => OPT.sewer_materials.map(m => [m, word(m)]), { req: true }),
    num('us_invert', 'Pipe bottom level at the start', 'Inside bottom of the pipe at the upper manhole. Use "Fill in pipe levels for me" if you are not sure.', 'm', { req: true }),
    num('ds_invert', 'Pipe bottom level at the end', 'Inside bottom of the pipe at the lower manhole. It must be lower than the start so sewage flows.', 'm', { req: true })] });

kind('reservoir', { label: 'Water tank', geom: 'point', prefix: 'TANK', colour: '#1f6fd1', shape: 'square',
  fields: [num('head', 'Water level in the tank', 'Height of the water surface in the tank above sea level, in metres. A higher tank gives more pressure.', 'm', { req: true })] });
kind('water_junction', { label: 'Supply point', geom: 'point', prefix: 'J', colour: '#1f6fd1', shape: 'dot',
  fields: [num('elevation', 'Ground level', levelHelp, 'm', { req: true }),
    num('people', 'People who get water here', 'How many people take water from the pipes near this point.', 'people'),
    num('demand_lps', 'Or: water used here', 'Only if you know the flow directly (litres per second). Leave empty to work it out from the number of people.', 'L/s', { advanced: true })] });
kind('water_pipe', { label: 'Water pipe', geom: 'link', prefix: 'W', colour: '#1f6fd1', from: ['reservoir', 'water_junction'], to: ['water_junction'],
  fields: [num('diameter_mm', 'Pipe size', 'Inside diameter of the pipe in millimetres.', 'mm', { req: true }),
    num('roughness', 'Pipe smoothness (C value)', 'Hazen-Williams C: about 140 for new plastic, 130 for new ductile iron, 100 for old pipes.', '', { req: true })] });

kind('drain_node', { label: 'Drain point', geom: 'point', prefix: 'DN', colour: '#12857a', shape: 'square',
  fields: [num('ground_level', 'Ground level', levelHelp, 'm', { req: true })] });
kind('drain_outfall', { label: 'Drain outfall', geom: 'point', prefix: 'OF', colour: '#12857a', shape: 'tri',
  fields: [num('ground_level', 'Ground level', levelHelp, 'm', { req: true }),
    num('invert_level', 'Drain bottom level where it leaves', 'Level of the bottom of the drain where it empties into the river, nala or bigger drain.', 'm', { req: true })] });
kind('storm_drain', { label: 'Drain', geom: 'link', prefix: 'D', colour: '#12857a', from: ['drain_node'], to: ['drain_node', 'drain_outfall'],
  fields: [sel('shape', 'Type of drain', 'A round pipe, a box drain, or an open channel with sloping sides.', () => ['circular', 'rectangular', 'trapezoidal'].map(v => [v, word(v)]), { req: true }),
    sel('diameter_mm', 'Pipe size', 'Inside diameter of the round pipe.', () => OPT.drain_diameters_mm.map(d => [d, d + ' mm']), { req: true, num: true, show: f => (f.a.shape || 'circular') === 'circular' }),
    num('width_m', 'Width at the bottom', 'Inside width of the drain at its bottom.', 'm', { req: true, show: f => ['rectangular', 'trapezoidal'].includes(f.a.shape) }),
    num('height_m', 'Depth', 'Inside depth of the drain.', 'm', { req: true, show: f => ['rectangular', 'trapezoidal'].includes(f.a.shape) }),
    num('side_slope', 'Side slope (across : up)', 'How much the side leans: 1 means 1 m across for every 1 m up.', '', { req: true, show: f => f.a.shape === 'trapezoidal' }),
    sel('lining', 'Drain material', 'What the drain is made of or lined with.', () => OPT.drain_linings.map(m => [m, word(m)]), { req: true }),
    num('us_invert', 'Bottom level at the start', 'Level of the inside bottom at the upper end. Use "Fill in drain levels for me" if you are not sure.', 'm', { req: true }),
    num('ds_invert', 'Bottom level at the end', 'Level of the inside bottom at the lower end. It must be lower than the start.', 'm', { req: true })] });
kind('catchment', { label: 'Rain area', geom: 'area', prefix: 'C', colour: '#12857a',
  fields: [sel('ui_mix', 'What covers this area', 'Roofs and paving send most rain into the drains; gardens and parks soak up more.',
      f => [...Object.entries(SURFACE_MIX).map(([k, m]) => [k, m.label]), ...(mixOf(f.a.surfaces) === 'file' ? [['file', 'Mix given in the file']] : [])],
      { req: true, get: f => mixOf(f.a.surfaces), set: (f, v) => { if (SURFACE_MIX[v]) { f.a.surfaces = clone(SURFACE_MIX[v].surfaces);
        f.a.impervious_pct = Math.round(100 * ((f.a.surfaces.roof || 0) + (f.a.surfaces.paved || 0))); } }, sugKey: 'surfaces' }),
    num('flow_length_m', 'Longest path rain travels to the drain', 'From the farthest corner of the area to the drain point, in metres.', 'm', { req: true }),
    num('overland_slope', 'Ground slope', 'How steeply the ground falls towards the drain, in percent (1 % = 1 m fall in 100 m).', '%', { req: true, scale: 100 }),
    sel('drains_to', 'Rain from here goes to', 'The drain point that collects the rain from this area.',
      () => feats().filter(f => f.kind === 'drain_node').map(f => [f.name, f.name]), { req: true })] });

kind('road_alignment', { label: 'Road', geom: 'line', prefix: 'R', colour: '#4f5b66', custom: 'road' });
kind('road_junction', { label: 'Junction', geom: 'point', prefix: 'JN', colour: '#4f5b66', shape: 'junction', custom: 'junction' });
kind('plot', { label: 'Building or wall', geom: 'area', prefix: 'B', colour: '#7b6f61', fields: [] });
kind('terrain_point', { label: 'Ground level point', geom: 'point', prefix: 'TP', colour: '#9aa5ad', shape: 'tiny', passive: true });

kind('substation', { label: 'Substation', geom: 'point', prefix: 'SS', colour: '#7a3fb5', shape: 'bolt',
  fields: [num('voltage_kv', 'Supply voltage', 'High-tension voltage the substation sends out, usually 11 kV.', 'kV', { req: true })] });
kind('transformer', { label: 'Transformer', geom: 'point', prefix: 'TX', colour: '#7a3fb5', shape: 'ring',
  fields: [sel('rating_kva', 'Size', 'How much power the transformer can supply.', () => OPT.transformer_ratings_kva.map(v => [v, v + ' kVA']), { req: true, num: true }),
    num('hv_kv', 'Input voltage', 'Voltage coming in from the substation.', 'kV', { req: true }),
    num('lv_v', 'Output voltage (no load)', 'Voltage going out to buildings when nothing is switched on, usually 433 V.', 'V', { req: true })] });
kind('feeder_pillar', { label: 'Feeder pillar', geom: 'point', prefix: 'FP', colour: '#7a3fb5', shape: 'square', fields: [] });
kind('electrical_load', { label: 'Building', geom: 'point', prefix: 'BLD', colour: '#7a3fb5', shape: 'house',
  fields: [num('connected_load_kw', 'Total power of everything connected', 'Add up the power of all lights, fans, pumps and machines in the building.', 'kW', { req: true }),
    sel('category', 'Type of building', 'Homes, shops and pumps use power differently through the day.', () => OPT.load_categories.map(v => [v, word(v)]), { req: true }),
    num('power_factor', 'Power factor', 'Usually 0.8 to 0.95. Leave the suggested value if you do not know.', '', { req: true })] });
kind('electrical_cable', { label: 'Cable', geom: 'link', prefix: 'K', colour: '#7a3fb5', from: ['substation', 'transformer', 'feeder_pillar'], to: ['transformer', 'feeder_pillar', 'electrical_load'],
  fields: [sel('cable_type', 'Cable', 'The cable from the cable list. Cables marked 11 kV go from the substation to transformers; 1.1 kV cables go to buildings.', () => OPT.cables.map(c => [c.value, c.label]), { req: true }),
    num('runs', 'Number of cables side by side', 'Two cables side by side carry twice the current.', '', { req: true })] });

const KIND_HELP = {
  manhole: 'Place a manhole: click on the sheet where pipes meet, turn or change slope.',
  sewer_outfall: 'Place the outfall: the point where the sewage leaves your area (treatment plant or main sewer).',
  sewer_pipe: 'Draw a pipe: click the upper manhole first, then the lower one. The arrow shows the flow.',
  reservoir: 'Place the water tank or other source of water.',
  water_junction: 'Place a point where water is taken or where pipes meet.',
  water_pipe: 'Draw a pipe: click one point, then the next one.',
  drain_node: 'Place a drain point: where drains meet, turn, or collect rain from an area.',
  drain_outfall: 'Place the outfall: where the drain empties into a river, nala or bigger drain.',
  storm_drain: 'Draw a drain: click the upper drain point first, then the lower one. The arrow shows the flow.',
  catchment: 'Draw a rain area: click around its edge, double-click to finish, then click the drain point it flows to.',
  road_alignment: 'Draw a road: click at the start, at each bend and at the end; double-click to finish. Or hold the mouse button and draw it freehand.',
  road_junction: 'Place a junction: click where the roads meet. You can then choose crossroad, T, Y or roundabout.',
  plot: 'Draw a building, wall or anything that may block drivers’ view at a junction: click around its edge, double-click to finish.',
  substation: 'Place the substation where the high-tension supply comes from.',
  transformer: 'Place a transformer: it turns the 11 kV supply into the 415 V used by buildings.',
  feeder_pillar: 'Place a feeder pillar: a street box that splits one cable into several.',
  electrical_load: 'Place a building that uses electricity.',
  electrical_cable: 'Draw a cable: click where the power comes from, then where it goes to.',
};
const TOOLS = {
  sewer: ['manhole', 'sewer_outfall', 'sewer_pipe'],
  water: ['reservoir', 'water_junction', 'water_pipe'],
  drainage: ['drain_node', 'drain_outfall', 'storm_drain', 'catchment'],
  road: ['road_alignment', 'manhole'],
  junction: ['road_junction', 'plot'],
  electrical: ['substation', 'transformer', 'feeder_pillar', 'electrical_load', 'electrical_cable'],
};
const TOOL_SUB = {
  manhole: 'Where pipes meet', sewer_outfall: 'Where sewage leaves', sewer_pipe: 'Join two manholes',
  reservoir: 'Source of water', water_junction: 'Where water is used', water_pipe: 'Join two points',
  drain_node: 'Where drains meet', drain_outfall: 'Where rain water leaves', storm_drain: 'Join two drain points',
  catchment: 'Area whose rain drains here', road_alignment: 'Click along its path', road_junction: 'Where roads meet',
  plot: 'Can block the view', substation: 'Power comes from here', transformer: '11 kV to 415 V',
  feeder_pillar: 'Street box', electrical_load: 'Uses power', electrical_cable: 'Join supply to user',
};

// ------------------------------------------------------------------ state
const S = {
  modules: [], mod: null, module: null, name: 'My design', feats: [], settings: {},
  sel: null, tool: 'select', draft: null, mouse: null,
  view: { s: 1, ox: E0 - 400, oy: N0 + 250 }, results: null, stale: false, undo: [], redo: [],
};
let OPT = {};
const feats = () => S.feats;
const byId = id => S.feats.find(f => f.id === id);
const byName = n => S.feats.find(f => f.name === n);

// ------------------------------------------------------------------ status line, tooltips, help
const statusLine = $('#status-line'), tip = $('#tip');
let sayTimer = 0;
function say(msg, keep) {
  statusLine.textContent = msg;
  clearTimeout(sayTimer);
  if (!keep) sayTimer = setTimeout(() => { statusLine.textContent = ''; }, 9000);
}
let tipTimer = 0, tipFor = null;
function helpOf(e) { return e && e.closest && e.closest('[data-help]'); }
function showTip(t) {
  const r = t.getBoundingClientRect();
  tip.textContent = t.dataset.help;
  tip.classList.add('on');
  const tw = tip.offsetWidth, th = tip.offsetHeight;
  let x = Math.min(window.innerWidth - tw - 8, Math.max(8, r.left + r.width / 2 - tw / 2));
  let y = r.bottom + 8;
  if (y + th > window.innerHeight - 8) y = Math.max(8, r.top - th - 8);
  tip.style.left = x + 'px'; tip.style.top = y + 'px';
}
document.addEventListener('mouseover', e => {
  const t = helpOf(e.target);
  if (t === tipFor) return;
  tipFor = t; clearTimeout(tipTimer); tip.classList.remove('on');
  if (!t || t.id === 'canvas') { if (t) statusLine.textContent = t.dataset.help; return; }
  statusLine.textContent = t.dataset.help;
  tipTimer = setTimeout(() => showTip(t), 450);
});
document.addEventListener('focusin', e => {
  const t = helpOf(e.target);
  if (t && t.id !== 'canvas') statusLine.textContent = t.dataset.help;
});
document.addEventListener('pointerdown', e => {
  clearTimeout(tipTimer); tip.classList.remove('on');
  if (e.pointerType === 'touch') {                       // long-press shows the explanation on touch screens
    const t = helpOf(e.target);
    if (t && t.id !== 'canvas') tipTimer = setTimeout(() => { showTip(t); statusLine.textContent = t.dataset.help; }, 550);
  }
}, true);
document.addEventListener('pointerup', e => { if (e.pointerType === 'touch') clearTimeout(tipTimer); }, true);

function controlName(e) {
  if (e.getAttribute('aria-label')) return e.getAttribute('aria-label');
  if (e.classList.contains('field')) return (e.querySelector('span') || e).firstChild.textContent.trim();
  if (e.classList.contains('tool')) return (e.querySelector('b') || e).textContent.trim();
  if (e.matches('input,select')) return (e.closest('label') || e).textContent.trim().slice(0, 40) || e.name || 'Field';
  return e.textContent.trim().replace(/\s+/g, ' ').slice(0, 48) || e.id;
}
function openGuide() {
  closeGuide();
  const groups = [['Top of the screen', '.top, .disclaimer'], ['Drawing tools (left)', '#tools'], ['Drawing sheet', '.sheet'],
    ['Panel on the right', '#side'], ['Check results', '#results']];
  const sections = [];
  for (const [title, sel] of groups) {
    const rows = [], seen = new Set();
    document.querySelectorAll(sel).forEach(root => {
      if (root.closest('[hidden]')) return;
      const all = [...(root.matches('[data-help]') ? [root] : []), ...root.querySelectorAll('[data-help]')];
      for (const e of all) {
        if (e.closest('[hidden]') || e.closest('.field') && !e.classList.contains('field')) continue;
        const n = controlName(e);
        if (seen.has(n + e.dataset.help)) continue;
        seen.add(n + e.dataset.help);
        rows.push(h('tr', {}, h('td', { text: n }), h('td', { text: e.dataset.help })));
      }
    });
    if (rows.length) sections.push(h('h3', { text: title }), h('table', {}, rows));
  }
  const how = S.mod
    ? [h('h3', { text: `How to design ${S.mod.title.toLowerCase()}` }), h('ol', {}, S.mod.steps.map(t => h('li', { text: t })))]
    : [h('h3', { text: 'Getting started' }), h('p', { text: 'Pick what you want to design. Each one opens a drawing sheet with tools on the left and a guide on the right.' })];
  const bg = h('div', { class: 'guide-bg', id: 'guide', onclick: e => { if (e.target === bg) closeGuide(); } },
    h('section', { class: 'guide', role: 'dialog', 'aria-label': 'Help guide' },
      h('button', { class: 'btn', style: 'float:right', onclick: closeGuide, 'data-help': 'Close this guide (or press Esc).' }, 'Close'),
      h('h2', { text: 'Help' }),
      h('p', { text: 'Point at any button or box to see what it does. The same explanation appears in the line at the bottom of the screen.' }),
      ...how,
      h('h3', { text: 'What the colours mean' }),
      h('table', {}, [['Green', 'OK – meets the rule.'], ['Amber', 'Check this – may be acceptable, an engineer should look.'],
        ['Red', 'Problem – needs changing. The advice says what to try.'], ['Grey', 'Not checked – some information was missing.']]
        .map(([a, b]) => h('tr', {}, h('td', { text: a }), h('td', { text: b })))),
      h('h3', { text: 'Handy keys' }),
      h('table', {}, [['Esc', 'Stop drawing / close'], ['Enter', 'Finish a road or area'], ['Delete', 'Delete the selected item'],
        ['Ctrl + Z', 'Undo'], ['Ctrl + Y', 'Redo'], ['F1', 'This guide'], ['Mouse wheel', 'Zoom'], ['Drag empty space', 'Move around']]
        .map(([a, b]) => h('tr', {}, h('td', { text: a }), h('td', { text: b })))),
      ...sections,
      h('h3', { text: 'Important' }),
      h('p', { text: 'The results are calculations to help an engineer. A qualified engineer must review and approve the design. Values marked "Suggested – check this" were filled in for you and must be confirmed.' })));
  document.body.append(bg);
  bg.querySelector('button').focus();
}
function closeGuide() { const g = $('#guide'); if (g) g.remove(); }

// ------------------------------------------------------------------ server
async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const ct = r.headers.get('Content-Type') || '';
  const data = ct.includes('json') ? await r.json() : await r.text();
  if (!r.ok) throw new Error((data && data.error) || `The program answered with error ${r.status}.`);
  return data;
}

// ------------------------------------------------------------------ drawing <-> GeoJSON
function toFC(forCheck) {
  return {
    type: 'FeatureCollection', name: S.name,
    crs: { type: 'name', properties: { name: `urn:ogc:def:crs:EPSG::${EPSG}` } },
    ...(forCheck ? {} : { cityinfra: { module: S.module, settings: S.settings, app: 'City Infrastructure Designer' } }),
    features: S.feats.map(f => {
      const p = { id: f.id, kind: f.kind, name: f.name, status: f.a.status || 'proposed' };
      for (const [k, v] of Object.entries(f.a)) if (k !== 'status' && !(forCheck && k.startsWith('ui_'))) p[k] = v;
      if (!forCheck && Object.keys(f.sug).length) p.ui_suggested = Object.keys(f.sug);
      return { type: 'Feature', geometry: f.g, properties: p };
    }),
  };
}
function fromFC(fc) {
  const out = [];
  for (const ft of fc.features || []) {
    const p = Object.assign({}, ft.properties || {});
    const f = { id: p.id || uid(), kind: p.kind, name: p.name || null, g: ft.geometry, a: {}, sug: {} };
    for (const s2 of p.ui_suggested || []) f.sug[s2] = 1;
    for (const [k, v] of Object.entries(p)) if (!['id', 'kind', 'name', 'ui_suggested'].includes(k)) f.a[k] = v;
    if (f.a.status === 'proposed') delete f.a.status;
    if (p.attributes && typeof p.attributes === 'object') { Object.assign(f.a, p.attributes); delete f.a.attributes; }
    out.push(f);
  }
  return out;
}
function nextName(k) {
  const pre = (KINDS[k] || { prefix: 'X' }).prefix;
  let n = 1;
  for (const f of S.feats) {
    const m = f.name && f.name.startsWith(pre) && /^\d+$/.test(f.name.slice(pre.length)) && +f.name.slice(pre.length);
    if (m && m >= n) n = m + 1;
  }
  return pre + n;
}

// ------------------------------------------------------------------ undo / save
function snap() { return JSON.stringify({ feats: S.feats, settings: S.settings, name: S.name }); }
function restore(t) { const o = JSON.parse(t); S.feats = o.feats; S.settings = o.settings; S.name = o.name; if (S.sel && !byId(S.sel)) S.sel = null; }
function pushUndo() { S.undo.push(snap()); if (S.undo.length > 80) S.undo.shift(); S.redo = []; }
function afterChange() { if (S.results) S.stale = true; persist(); draw(); sideSoon(); renderResults(); renderTools(); hint(); }
function edit(fn) { pushUndo(); fn(); afterChange(); }
function undo() { if (!S.undo.length) return say('Nothing to undo.'); S.redo.push(snap()); restore(S.undo.pop()); S.draft = null; afterChange(); say('Undone.'); }
function redo() { if (!S.redo.length) return say('Nothing to redo.'); S.undo.push(snap()); restore(S.redo.pop()); afterChange(); say('Redone.'); }
function persist() { if (S.module) store.set('cityinfra.v1.' + S.module, { fc: toFC(false), settings: S.settings, name: S.name }); }

// ------------------------------------------------------------------ defaults for new objects
function sug(f, key, val) { f.a[key] = val; f.sug[key] = 1; }
function suggestRadius(v) { return Math.ceil(v * v / (127 * 0.22) * 1.3 / 10) * 10; }
function suggestEasing(v, R) { return Math.max(15, Math.ceil(2.7 * v * v / R / 5) * 5); }
function lineLength(c) { let L = 0; for (let i = 1; i < c.length; i++) L += dist(c[i - 1], c[i]); return L; }
function suggestBends(f) {
  // a comfortable radius for the speed, made smaller where the drawn straights are too short for it
  const v = +f.a.design_speed_kmh || 50, cs = f.g.coordinates, n = cs.length - 2, cur = f.a.curves || {}, out = {};
  const seg = k => dist(cs[k], cs[k + 1]);
  for (let i = 1; i <= n; i++) {
    if (cur[i] && !f.sug.curves) { out[i] = cur[i]; continue; }
    const b1 = Math.atan2(cs[i][0] - cs[i - 1][0], cs[i][1] - cs[i - 1][1]), b2 = Math.atan2(cs[i + 1][0] - cs[i][0], cs[i + 1][1] - cs[i][1]);
    let defl = Math.abs(b2 - b1); if (defl > Math.PI) defl = 2 * Math.PI - defl;
    const room = 0.9 * Math.min(i === 1 ? seg(0) : seg(i - 1) / 2, i === n ? seg(n) : seg(i) / 2);
    let R = suggestRadius(v), Ls = suggestEasing(v, R);
    const T = (r, l) => (r + l * l / (24 * r)) * Math.tan(defl / 2) + l / 2;
    while (R > 10 && T(R, Ls) > room) { R -= 5; Ls = Math.min(suggestEasing(v, R), Math.max(0, Math.floor(R * defl / 2 / 5) * 5)); }
    out[i] = [R, Ls];
  }
  f.a.curves = out;
}
function newObject(k, geom) {
  const f = { id: uid(), kind: k, name: nextName(k), g: geom, a: {}, sug: {} };
  const D = (key, v) => sug(f, key, v);
  switch (k) {
    case 'manhole': if (S.module === 'sewer') D('population', 0); break;
    case 'sewer_pipe': D('diameter_mm', 200); D('material', OPT.sewer_materials.includes('upvc') ? 'upvc' : OPT.sewer_materials[0]); break;
    case 'water_pipe': D('diameter_mm', 150); D('roughness', 130); break;
    case 'storm_drain': D('shape', 'circular'); D('diameter_mm', 600); D('lining', 'rcc'); break;
    case 'catchment': {
      f.a.surfaces = clone(SURFACE_MIX.houses.surfaces); f.a.impervious_pct = 75; f.sug.surfaces = 1;
      const c = geom.coordinates[0]; const xs = c.map(p => p[0]), ys = c.map(p => p[1]);
      D('flow_length_m', Math.round(Math.hypot(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys))));
      D('overland_slope', 0.01); break;
    }
    case 'road_alignment': {
      D('design_speed_kmh', 50); D('terrain', 'plain'); D('kerbed', true); D('ui_road_type', 'lane2');
      f.a.template = clone(ROAD_TYPES.lane2.template); f.sug.curves = 1;
      const L = lineLength(geom.coordinates);
      f.a.profile = [[0, 100, 0], ['end', +(100 - 0.005 * L).toFixed(2), 0]]; f.sug.ui_start = 1; f.sug.ui_end = 1;
      if (f.a.horizontal_mode !== 'fit') suggestBends(f);
      break;
    }
    case 'road_junction': applyLayout(f, 'cross'); D('design_vehicle', 'bus'); D('control', 'uncontrolled'); break;
    case 'substation': D('voltage_kv', 11); break;
    case 'transformer': D('rating_kva', OPT.transformer_ratings_kva.includes(400) ? 400 : OPT.transformer_ratings_kva[0]); D('hv_kv', 11); D('lv_v', 433); break;
    case 'electrical_load': D('category', 'residential'); D('power_factor', 0.9); break;
    case 'electrical_cable': D('runs', 1); break;
    case 'plot': f.a.sight_obstruction = true; break;
  }
  return f;
}
function applyLayout(f, key) {
  const L = LAYOUTS[key];
  f.a.type = L.type; f.a.ui_layout = key;
  const wide = 3.5;
  f.a.arms = L.arms.map(([name, b, pr]) => Object.assign({ name, bearing_deg: b, width_left: pr ? 7.0 : wide, width_right: pr ? 7.0 : wide,
    speed_kmh: pr ? 50 : 40 }, pr ? { priority: 'major' } : {}));
  f.sug.arms = 1;
  if (L.type === 'roundabout') {
    f.a.roundabout = Object.assign({ central_island_radius_m: 38, circulatory_width_m: 8, entry_radius_m: 20, exit_radius_m: 25, setting: 'urban' },
      (f.a.roundabout && f.a.roundabout.flows_pcu_h) ? { flows_pcu_h: f.a.roundabout.flows_pcu_h } : {});
    f.sug.roundabout = 1;
  }
}

// ------------------------------------------------------------------ pipe / drain levels helper
function fillLevels(linkKind, cover, slope1in) {
  const links = S.feats.filter(f => f.kind === linkKind);
  const node = n => byName(n);
  let done = 0, skipped = [];
  const ready = new Set(), out = {};
  // upstream first: a link is ready when every link entering its start node is done
  for (let guard = 0; guard < links.length + 2; guard++) {
    for (const l of links) {
      if (ready.has(l.id)) continue;
      const incoming = links.filter(x => x.a.to === l.a.from);
      if (!incoming.every(x => ready.has(x.id))) continue;
      const A = node(l.a.from), B = node(l.a.to);
      const gA = A && +A.a.ground_level;
      if (!A || !B || empty(A.a.ground_level)) { skipped.push(l.name); ready.add(l.id); continue; }
      const D = l.a.shape && l.a.shape !== 'circular' ? +l.a.height_m || 0 : (+l.a.diameter_mm || 0) / 1000;
      let us = gA - cover - D;
      for (const x of incoming) if (out[x.id] !== undefined) us = Math.min(us, out[x.id]);
      const L = lineLength(l.g.coordinates);
      const ds = us - L / slope1in;
      const user = k => !empty(l.a[k]) && !l.sug[k];
      if (!user('us_invert')) sug(l, 'us_invert', +us.toFixed(3));
      if (!user('ds_invert')) sug(l, 'ds_invert', +ds.toFixed(3));
      out[l.id] = +l.a.ds_invert;
      ready.add(l.id); done++;
    }
  }
  return { done, skipped, loop: links.length - ready.size };
}

// ------------------------------------------------------------------ what is still missing
function fieldsOf(f) { return (KINDS[f.kind] || {}).fields || []; }
function getVal(f, d) { return d.get ? d.get(f) : f.a[d.key]; }
function missing() {
  const out = [];
  const add = (f, what) => out.push({ f, what });
  for (const f of S.feats) {
    const K = KINDS[f.kind]; if (!K || K.passive) continue;
    for (const d of fieldsOf(f)) if (d.req && (!d.show || d.show(f)) && empty(getVal(f, d))) add(f, d.label);
    if (K.geom === 'link') {
      if (!byName(f.a.from) || !byName(f.a.to)) add(f, 'Both ends must be joined to points');
    }
    if (f.kind === 'water_junction' && empty(f.a.people) && empty(f.a.demand_lps)) add(f, 'People who get water here');
    if (f.kind === 'road_alignment') {
      if (f.g.coordinates.length < 2) add(f, 'The road needs at least two points');
      if (f.a.horizontal_mode !== 'fit') for (const [i, rl] of Object.entries(f.a.curves || {}))
        if (empty(rl[0])) add(f, `Radius of bend ${i}`);
    }
  }
  if (S.module === 'water' && empty(S.settings.litres_per_person_per_day) && S.feats.some(f => f.kind === 'water_junction' && !empty(f.a.people)))
    out.push({ f: null, what: 'Water used per person per day (in the panel on the right)' });
  return out;
}

// ------------------------------------------------------------------ canvas
const svg = $('#canvas');
const sx = E => (E - S.view.ox) * S.view.s, sy = N => (S.view.oy - N) * S.view.s;
const P = c => [sx(c[0]), sy(c[1])];
const toWorld = (x, y) => [x / S.view.s + S.view.ox, S.view.oy - y / S.view.s];
const ptsAttr = cs => cs.map(c => P(c).map(v => v.toFixed(1)).join(',')).join(' ');
function evPoint(e) { const r = svg.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; }
function lineCoords(f) { return f.g.type === 'LineString' ? f.g.coordinates : f.g.type === 'Polygon' ? f.g.coordinates[0] : [f.g.coordinates]; }

function allCoords(includeOverlays) {
  const c = [];
  for (const f of S.feats) {
    if (f.kind === 'terrain_point' && S.feats.length > 40) continue;
    if (f.g.type === 'Point') c.push(f.g.coordinates); else c.push(...lineCoords(f));
    if (f.kind === 'road_junction') c.push([f.g.coordinates[0] - 60, f.g.coordinates[1] - 60], [f.g.coordinates[0] + 60, f.g.coordinates[1] + 60]);
  }
  if (includeOverlays && S.results) for (const o of S.results.overlays || []) if (o.geometry.type === 'LineString') c.push(...o.geometry.coordinates);
  return c;
}
function fit() {
  const r = svg.getBoundingClientRect(), c = allCoords(false);
  if (!c.length || !r.width) { S.view = { s: 1, ox: E0 - r.width / 2, oy: N0 + r.height / 2 }; draw(); return; }
  const xs = c.map(p => p[0]), ys = c.map(p => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const s2 = Math.min(50, Math.max(0.02, Math.min((r.width - 120) / Math.max(x1 - x0, 20), (r.height - 150) / Math.max(y1 - y0, 20))));
  S.view = { s: s2, ox: (x0 + x1) / 2 - r.width / 2 / s2, oy: (y0 + y1) / 2 + (r.height - 60) / 2 / s2 + 60 / s2 };
  draw();
}
function zoom(k, at) {
  const r = svg.getBoundingClientRect();
  const p = at || [r.width / 2, r.height / 2], w = toWorld(...p);
  S.view.s = Math.min(80, Math.max(0.01, S.view.s * k));
  S.view.ox = w[0] - p[0] / S.view.s; S.view.oy = w[1] + p[1] / S.view.s;
  draw();
}

function symbol(K, x, y, cls) {
  const g = s('g', { class: cls });
  const c = K.colour, R = 7;
  const add = e => g.append(e);
  switch (K.shape) {
    case 'ring': add(s('circle', { cx: x, cy: y, r: R, fill: 'var(--panel)', stroke: c, 'stroke-width': 3 })); add(s('circle', { cx: x, cy: y, r: 2.5, fill: c })); break;
    case 'tri': add(s('path', { d: `M${x} ${y - 9}L${x + 9} ${y + 7}L${x - 9} ${y + 7}Z`, fill: c, stroke: 'var(--panel)', 'stroke-width': 1.5 })); break;
    case 'square': add(s('rect', { x: x - 7, y: y - 7, width: 14, height: 14, rx: 2, fill: c, stroke: 'var(--panel)', 'stroke-width': 1.5 })); break;
    case 'dot': add(s('circle', { cx: x, cy: y, r: 6, fill: c, stroke: 'var(--panel)', 'stroke-width': 2 })); break;
    case 'tiny': add(s('circle', { cx: x, cy: y, r: 1.6, fill: c })); break;
    case 'bolt': add(s('rect', { x: x - 9, y: y - 9, width: 18, height: 18, rx: 3, fill: c }));
      add(s('path', { d: `M${x + 1} ${y - 7}L${x - 4} ${y + 1}H${x}L${x - 1} ${y + 7}L${x + 4} ${y - 1}H${x}Z`, fill: '#fff' })); break;
    case 'house': add(s('path', { d: `M${x - 8} ${y + 7}V${y - 1}L${x} ${y - 8}L${x + 8} ${y - 1}V${y + 7}Z`, fill: c, stroke: 'var(--panel)', 'stroke-width': 1.5 })); break;
    case 'junction': add(s('circle', { cx: x, cy: y, r: 9, fill: 'var(--panel)', stroke: c, 'stroke-width': 3 }));
      add(s('path', { d: `M${x - 5} ${y}H${x + 5}M${x} ${y - 5}V${y + 5}`, stroke: c, 'stroke-width': 2.5 })); break;
    default: add(s('circle', { cx: x, cy: y, r: 6, fill: c }));
  }
  return g;
}
function label(x, y, text, anchor = 'start') { const t = s('text', { x, y, class: 'lbl', 'text-anchor': anchor }); t.textContent = text; return t; }

function draw() {
  const r = svg.getBoundingClientRect();
  svg.replaceChildren();
  const st = (S.results && S.results.object_status) || {};
  const layers = { area: s('g'), road: s('g'), link: s('g'), over: s('g'), point: s('g'), label: s('g'), top: s('g') };
  // grid
  const grid = s('g', { opacity: 0.5 });
  const step = niceStep(80 / S.view.s);
  const [wx0, wy1] = toWorld(0, 0), [wx1, wy0] = toWorld(r.width, r.height);
  if ((wx1 - wx0) / step < 200) {
    for (let x = Math.ceil(wx0 / step) * step; x < wx1; x += step) grid.append(s('line', { x1: sx(x), x2: sx(x), y1: 0, y2: r.height, stroke: 'var(--line)', 'stroke-width': 1 }));
    for (let y = Math.ceil(wy0 / step) * step; y < wy1; y += step) grid.append(s('line', { y1: sy(y), y2: sy(y), x1: 0, x2: r.width, stroke: 'var(--line)', 'stroke-width': 1 }));
  }
  svg.append(grid);
  const halo = (id, make) => { if (st[id] && !(st[id] === 'pass' && false)) { const e = make(); e.classList.add('halo-' + st[id]); return e; } return null; };

  for (const f of S.feats) {
    const K = KINDS[f.kind] || { colour: '#888', geom: f.g.type === 'Point' ? 'point' : f.g.type === 'Polygon' ? 'area' : 'line', label: pretty(f.kind) };
    const selected = f.id === S.sel;
    const op = S.stale ? 0.5 : 0.55;
    if (f.g.type === 'Polygon') {
      const pts = ptsAttr(f.g.coordinates[0]);
      const hh = halo(f.id, () => s('polygon', { points: pts, fill: 'none', 'stroke-width': 9, opacity: op }));
      if (hh) layers.area.append(hh);
      const poly = s('polygon', { points: pts, 'data-id': f.id, class: 'obj', fill: K.colour, 'fill-opacity': f.kind === 'plot' ? 0.35 : 0.13,
        stroke: selected ? 'var(--sign)' : K.colour, 'stroke-width': selected ? 3 : 1.6, 'stroke-dasharray': f.kind === 'catchment' ? '6 4' : null });
      layers.area.append(poly);
      const c = centroid(f.g.coordinates[0]);
      layers.label.append(label(sx(c[0]), sy(c[1]), f.name || '', 'middle'));
      if (f.kind === 'catchment' && f.a.drains_to && byName(f.a.drains_to)) {
        const t = byName(f.a.drains_to).g.coordinates;
        layers.area.append(s('line', { x1: sx(c[0]), y1: sy(c[1]), x2: sx(t[0]), y2: sy(t[1]), stroke: K.colour, 'stroke-width': 1.5, 'stroke-dasharray': '2 4', 'marker-end': 'url(#arrow)' }));
      }
    } else if (f.g.type === 'LineString') {
      const cs = f.g.coordinates, pts = ptsAttr(cs);
      if (f.kind === 'road_alignment') {
        const w = Math.max(5, roadWidth(f.a.template) * S.view.s);
        const hh = halo(f.id, () => s('polyline', { points: pts, fill: 'none', 'stroke-width': w + 12, opacity: op, 'stroke-linejoin': 'round' }));
        if (hh) layers.road.append(hh);
        layers.road.append(s('polyline', { points: pts, fill: 'none', stroke: '#9aa5ad', 'stroke-opacity': 0.55, 'stroke-width': w, 'stroke-linejoin': 'round', 'stroke-linecap': 'round', class: 'obj', 'data-id': f.id }));
        layers.road.append(s('polyline', { points: pts, fill: 'none', stroke: selected ? 'var(--sign)' : '#4f5b66', 'stroke-width': selected ? 2.5 : 1.5, 'stroke-dasharray': '10 6', 'pointer-events': 'none' }));
        if (f.a.horizontal_mode !== 'fit') cs.slice(1, -1).forEach((c, i) => layers.label.append(label(sx(c[0]) + 8, sy(c[1]) - 8, `bend ${i + 1}`)));
        const m = cs[Math.floor(cs.length / 2)];
        layers.label.append(label(sx(cs[0][0]) - 6, sy(cs[0][1]) - 10, (f.name || '') + ' start', 'end'));
      } else {
        const hh = halo(f.id, () => s('polyline', { points: pts, fill: 'none', 'stroke-width': 11, opacity: op }));
        if (hh) layers.link.append(hh);
        layers.link.append(s('polyline', { points: pts, fill: 'none', stroke: 'transparent', 'stroke-width': 14, class: 'obj', 'data-id': f.id }));
        layers.link.append(s('polyline', { points: pts, fill: 'none', stroke: selected ? 'var(--sign)' : K.colour, 'stroke-width': selected ? 4.5 : 3, 'pointer-events': 'none' }));
        const a = P(cs[0]), b = P(cs[cs.length - 1]);
        const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2, ang = Math.atan2(b[1] - a[1], b[0] - a[0]) * 180 / Math.PI;
        if (dist(a, b) > 30) layers.link.append(s('path', { d: 'M-6 -5L5 0L-6 5Z', fill: selected ? 'var(--sign)' : K.colour, transform: `translate(${mx},${my}) rotate(${ang})`, 'pointer-events': 'none' }));
        if (dist(a, b) > 45) layers.label.append(label(mx + 6, my - 7, f.name || ''));
      }
    } else if (f.g.type === 'Point') {
      const [x, y] = P(f.g.coordinates);
      if (x < -50 || y < -50 || x > r.width + 50 || y > r.height + 50) continue;
      if (f.kind === 'road_junction') drawJunction(f, layers.road);
      const hh = halo(f.id, () => s('circle', { cx: x, cy: y, r: 14, fill: 'none', 'stroke-width': 6, opacity: 0.75 }));
      if (hh) layers.point.append(hh);
      const g = symbol(K, x, y, K.passive ? '' : 'obj');
      if (!K.passive) g.setAttribute('data-id', f.id);
      if (selected) layers.point.append(s('circle', { cx: x, cy: y, r: 15, fill: 'none', stroke: 'var(--sign)', 'stroke-width': 2.5, 'stroke-dasharray': '4 3' }));
      layers.point.append(g);
      if (!K.passive) layers.label.append(label(x + 12, y - 9, f.name || ''));
    }
  }
  // results overlays
  if (S.results && !S.stale) for (const o of S.results.overlays || []) drawOverlay(o, layers.over, layers.label);
  // vertex handles of the selected road / area
  const sf = S.sel && byId(S.sel);
  if (sf && S.tool === 'select' && ((sf.kind === 'road_alignment' && sf.a.horizontal_mode !== 'fit') || sf.g.type === 'Polygon')) {
    const cs = lineCoords(sf), n = sf.g.type === 'Polygon' ? cs.length - 1 : cs.length;
    for (let i = 0; i < n; i++) layers.top.append(s('circle', { cx: sx(cs[i][0]), cy: sy(cs[i][1]), r: 6.5, fill: 'var(--panel)', stroke: 'var(--sign)', 'stroke-width': 2.5,
      'data-handle': i, 'data-fid': sf.id, style: 'cursor:move' }));
  }
  // drawing in progress
  const d = S.draft;
  if (d && (d.type === 'road' || d.type === 'area') && d.pts.length) {
    const cs = d.pts.concat(S.mouse ? [S.mouse] : []);
    layers.top.append(s(d.type === 'area' && cs.length > 2 ? 'polygon' : 'polyline', { points: ptsAttr(cs), fill: d.type === 'area' ? 'var(--sign)' : 'none', 'fill-opacity': 0.08, stroke: 'var(--sign)', 'stroke-width': 2.5, 'stroke-dasharray': '6 4', 'pointer-events': 'none' }));
    for (const c of d.pts) layers.top.append(s('circle', { cx: sx(c[0]), cy: sy(c[1]), r: 4, fill: 'var(--sign)', 'pointer-events': 'none' }));
  }
  if (d && d.type === 'link' && S.mouse) {
    const a = byId(d.from); if (a) layers.top.append(s('line', { x1: sx(a.g.coordinates[0]), y1: sy(a.g.coordinates[1]), x2: sx(S.mouse[0]), y2: sy(S.mouse[1]), stroke: 'var(--sign)', 'stroke-width': 2.5, 'stroke-dasharray': '6 4', 'pointer-events': 'none' }));
  }
  const defs = s('defs');
  const mk = s('marker', { id: 'arrow', viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse' });
  mk.append(s('path', { d: 'M0 0L10 5L0 10Z', fill: '#12857a' })); defs.append(mk);
  svg.append(defs, layers.area, layers.road, layers.link, layers.over, layers.point, layers.label, layers.top);
  drawScale(r.width);
}
function niceStep(x) { const p = Math.pow(10, Math.floor(Math.log10(x))); for (const m of [1, 2, 5, 10]) if (m * p >= x) return m * p; return 10 * p; }
function drawScale() {
  const L = niceStep(100 / S.view.s), px = L * S.view.s;
  $('#scale').innerHTML = `${L >= 1000 ? L / 1000 + ' km' : L + ' m'}<i style="width:${px.toFixed(0)}px"></i>`;
}
function centroid(ring) { const n = ring.length - (dist(ring[0], ring[ring.length - 1]) < 1e-9 ? 1 : 0); let x = 0, y = 0; for (let i = 0; i < n; i++) { x += ring[i][0]; y += ring[i][1]; } return [x / n, y / n]; }
function drawJunction(f, layer) {
  const [cx, cy] = f.g.coordinates, A = 45;
  for (const arm of f.a.arms || []) {
    if (arm.road) continue;
    const b = (+arm.bearing_deg || 0) * Math.PI / 180, w = ((+arm.width_left || 0) + (+arm.width_right || 0)) * S.view.s;
    const ex = cx + A * Math.sin(b), ey = cy + A * Math.cos(b);
    layer.append(s('line', { x1: sx(cx), y1: sy(cy), x2: sx(ex), y2: sy(ey), stroke: '#9aa5ad', 'stroke-opacity': 0.55, 'stroke-width': Math.max(4, w), 'stroke-linecap': 'butt', 'pointer-events': 'none' }));
    layer.append(label(sx(cx + (A + 6) * Math.sin(b)), sy(cy + (A + 6) * Math.cos(b)), arm.name || '', 'middle'));
  }
  if (f.a.type === 'roundabout' && f.a.roundabout) {
    const R = +f.a.roundabout.central_island_radius_m || 0, W = +f.a.roundabout.circulatory_width_m || 0;
    layer.append(s('circle', { cx: sx(cx), cy: sy(cy), r: (R + W) * S.view.s, fill: 'var(--paper)', stroke: '#9aa5ad', 'stroke-width': 2, 'pointer-events': 'none' }));
    layer.append(s('circle', { cx: sx(cx), cy: sy(cy), r: R * S.view.s, fill: '#17824a', 'fill-opacity': 0.25, stroke: '#17824a', 'pointer-events': 'none' }));
  }
}
function drawOverlay(o, layer, labels) {
  const g = o.geometry, k = (o.properties || {}).kind || '';
  const colour = { designed_centreline: '#1f4e9c', kerb_return: '#1d2b36', sight_triangle: '#d99a00', entry_kerb: '#1f4e9c', exit_kerb: '#1f4e9c' }[k] || '#1f4e9c';
  if (g.type === 'LineString') layer.append(s('polyline', { points: ptsAttr(g.coordinates), fill: 'none', stroke: colour, 'stroke-width': k === 'designed_centreline' ? 3 : 2, 'pointer-events': 'none' }));
  else if (g.type === 'Polygon') layer.append(s('polygon', { points: ptsAttr(g.coordinates[0]), fill: colour, 'fill-opacity': 0.12, stroke: colour, 'stroke-dasharray': '5 4', 'pointer-events': 'none' }));
  else if (g.type === 'Point') {
    const [x, y] = P(g.coordinates);
    if (o.properties.radius_m && /island|circle/.test(k)) layer.append(s('circle', { cx: x, cy: y, r: o.properties.radius_m * S.view.s, fill: 'none', stroke: colour, 'stroke-width': 2, 'pointer-events': 'none' }));
    if (o.properties.text) { const t = label(x + 8, y + 16, o.properties.text); t.setAttribute('style', 'fill:#1f4e9c;font-weight:600'); labels.append(t); }
  }
}

// ------------------------------------------------------------------ pointer handling
let drag = null;
svg.addEventListener('contextmenu', e => e.preventDefault());
svg.addEventListener('pointerdown', e => {
  svg.setPointerCapture(e.pointerId);
  const p = evPoint(e), w = toWorld(...p);
  const t = e.target.closest('[data-id],[data-handle]');
  drag = { start: p, last: p, moved: false, target: t, mode: 'pan', undo: false };
  if (e.button === 1 || e.button === 2) return;
  if (S.tool === 'road_alignment' && !(S.draft && S.draft.pts && S.draft.pts.length)) { drag.mode = 'freehand'; drag.pts = [w]; return; }
  if (S.tool !== 'select') return;
  if (t && t.dataset.handle !== undefined) { drag.mode = 'vertex'; drag.fid = t.dataset.fid; drag.idx = +t.dataset.handle; return; }
  if (t && t.dataset.id) {
    select(t.dataset.id, true);
    const f = byId(t.dataset.id);
    if (f && f.g.type === 'Point') { drag.mode = 'move'; drag.fid = f.id; }
  }
});
svg.addEventListener('pointermove', e => {
  const p = evPoint(e), w = toWorld(...p);
  S.mouse = w;
  if (!drag) { if (S.draft) draw(); return; }
  if (!drag.moved && dist(p, drag.start) < 4) return;
  drag.moved = true;
  const dx = p[0] - drag.last[0], dy = p[1] - drag.last[1];
  drag.last = p;
  if (drag.mode === 'pan') { S.view.ox -= dx / S.view.s; S.view.oy += dy / S.view.s; draw(); return; }
  if (drag.mode === 'freehand') { if (dist(P(drag.pts[drag.pts.length - 1]), p) > 7) drag.pts.push(w); S.draft = { type: 'road', pts: drag.pts }; S.mouse = null; draw(); return; }
  const f = byId(drag.fid); if (!f) return;
  if (!drag.undo) { pushUndo(); drag.undo = true; }
  if (drag.mode === 'move') { f.g.coordinates = [w[0], w[1], ...f.g.coordinates.slice(2)]; moveLinks(f); }
  if (drag.mode === 'vertex') {
    if (f.g.type === 'Polygon') { const ring = f.g.coordinates[0]; ring[drag.idx] = w; if (drag.idx === 0) ring[ring.length - 1] = w; }
    else f.g.coordinates[drag.idx] = w;
  }
  draw();
});
svg.addEventListener('pointerup', e => {
  const d = drag; drag = null;
  if (!d) return;
  if (d.mode === 'freehand' && d.moved) {
    S.draft = null;
    if (d.pts.length >= 4) finishRoad(d.pts, true); else { say('That line was too short. Click along the road, or hold the button down and draw.'); draw(); }
    return;
  }
  if (d.moved) { if (d.undo) afterChange(); return; }
  click(d.start, toWorld(...d.start), d.target, e);
});
svg.addEventListener('dblclick', e => {
  const p = evPoint(e);
  if (S.draft && S.draft.type === 'road') return finishRoad(dedupe(S.draft.pts), false);
  if (S.draft && S.draft.type === 'area') return finishArea(dedupe(S.draft.pts));
  const t = e.target.closest('[data-id]');
  const f = t && byId(t.dataset.id);
  if (S.tool === 'select' && f && f.kind === 'road_alignment') insertVertex(f, toWorld(...p));
});
svg.addEventListener('wheel', e => { e.preventDefault(); zoom(e.deltaY < 0 ? 1.18 : 1 / 1.18, evPoint(e)); }, { passive: false });
svg.addEventListener('pointerleave', () => { S.mouse = null; if (S.draft) draw(); });

function dedupe(pts) { const out = []; for (const p of pts) if (!out.length || dist(P(out[out.length - 1]), P(p)) > 4) out.push(p); return out; }
function moveLinks(n) {
  for (const l of S.feats) {
    if (!KINDS[l.kind] || KINDS[l.kind].geom !== 'link') continue;
    if (l.a.from === n.name) l.g.coordinates[0] = n.g.coordinates.slice(0, 2);
    if (l.a.to === n.name) l.g.coordinates[l.g.coordinates.length - 1] = n.g.coordinates.slice(0, 2);
  }
}
function insertVertex(f, w) {
  const cs = f.g.coordinates; let best = 1, bd = Infinity;
  for (let i = 1; i < cs.length; i++) { const d2 = segDist(w, cs[i - 1], cs[i]); if (d2 < bd) { bd = d2; best = i; } }
  edit(() => {
    cs.splice(best, 0, w);
    if (f.a.horizontal_mode !== 'fit') {
      const old = f.a.curves || {}, nc = {};
      for (const [k, v] of Object.entries(old)) nc[+k >= best ? +k + 1 : +k] = v;
      const v = +f.a.design_speed_kmh || 50, R = suggestRadius(v);
      nc[best] = [R, suggestEasing(v, R)]; f.a.curves = nc; f.sug.curves = 1;
    }
  });
  say(`Bend ${best} added. Drag the round handle to move it; set its radius in the panel.`);
}
function segDist(p, a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1], L = dx * dx + dy * dy;
  const t = L ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L)) : 0;
  return dist(p, [a[0] + t * dx, a[1] + t * dy]);
}

function click(p, w, t, e) {
  const tool = S.tool, K = KINDS[tool];
  const hit = t && t.dataset.id ? byId(t.dataset.id) : null;
  if (S.draft && S.draft.type === 'pick') {
    const c = byId(S.draft.for);
    if (hit && hit.kind === 'drain_node' && c) { edit(() => { c.a.drains_to = hit.name; delete c.sug.drains_to; }); S.draft = null; select(c.id); say(`${c.name} drains to ${hit.name}.`); }
    else say('Click a drain point (square) to say where this area’s rain goes, or press Esc to choose later.');
    hint(); return;
  }
  if (tool === 'select') { if (!hit) select(null); return; }
  if (!K) return;
  if (K.geom === 'point') {
    const f = newObject(tool, { type: 'Point', coordinates: w });
    edit(() => S.feats.push(f)); S.sel = f.id; sideSoon();
    say(`${K.label} ${f.name} placed. Fill in its details on the right, or click again to place another.`);
    return;
  }
  if (K.geom === 'link') {
    if (!S.draft) {
      if (hit && K.from.includes(hit.kind)) { S.draft = { type: 'link', kind: tool, from: hit.id }; hint(); draw(); }
      else say(`Start the ${K.label.toLowerCase()} on a ${K.from.map(k => KINDS[k].label.toLowerCase()).join(' or ')}.`);
      return;
    }
    const a = byId(S.draft.from);
    if (hit && hit.id !== a.id && K.to.includes(hit.kind)) {
      if (S.feats.some(l => l.kind === tool && ((l.a.from === a.name && l.a.to === hit.name) || (l.a.from === hit.name && l.a.to === a.name))))
        return say(`${a.name} and ${hit.name} are already joined.`);
      const f = newObject(tool, { type: 'LineString', coordinates: [a.g.coordinates.slice(0, 2), hit.g.coordinates.slice(0, 2)] });
      f.a.from = a.name; f.a.to = hit.name;
      if (tool === 'electrical_cable') {
        const ht = a.kind === 'substation';
        const c = OPT.cables.find(c2 => (ht ? c2.grade_kv > 2 : c2.grade_kv < 2) && /95|185/.test(c2.value)) || OPT.cables[0];
        sug(f, 'cable_type', c.value);
      }
      edit(() => S.feats.push(f));
      say(`${K.label} ${f.name} added from ${a.name} to ${hit.name}. Click the next point to continue, or press Esc to stop.`);
      S.draft = K.from.includes(hit.kind) ? { type: 'link', kind: tool, from: hit.id } : null;
      S.sel = f.id; sideSoon(); hint(); draw();
    } else if (hit && hit.id === a.id) { S.draft = null; hint(); draw(); }
    else say(`End the ${K.label.toLowerCase()} on a ${K.to.map(k => KINDS[k].label.toLowerCase()).join(' or ')}.`);
    return;
  }
  if (K.geom === 'line' || K.geom === 'area') {
    if (!S.draft) S.draft = { type: K.geom === 'line' ? 'road' : 'area', kind: tool, pts: [] };
    S.draft.pts.push(w); hint(); draw();
  }
}
function finishRoad(pts, freehand) {
  pts = dedupe(pts);
  S.draft = null;
  if (pts.length < 2) { hint(); draw(); return say('A road needs at least two points.'); }
  const f = newObject('road_alignment', { type: 'LineString', coordinates: pts.map(p => [p[0], p[1]]) });
  if (freehand) { f.a.horizontal_mode = 'fit'; delete f.a.curves; delete f.sug.curves; }
  edit(() => S.feats.push(f));
  S.sel = f.id; S.tool = 'select'; renderTools(); sideSoon(); hint();
  say(freehand ? `Road ${f.name} drawn freehand. Its curves will be fitted to your drawing when you press Check my design.`
    : `Road ${f.name} drawn with ${pts.length - 2} bend(s). Set its speed and the bends’ radius on the right.`);
}
function finishArea(pts) {
  const tool = S.draft.kind; S.draft = null;
  if (pts.length < 3) { hint(); draw(); return say('An area needs at least three corners.'); }
  const ring = pts.map(p => [p[0], p[1]]); ring.push(ring[0].slice());
  const f = newObject(tool, { type: 'Polygon', coordinates: [ring] });
  edit(() => S.feats.push(f)); S.sel = f.id; sideSoon();
  if (tool === 'catchment') {
    const nodes = S.feats.filter(x => x.kind === 'drain_node');
    if (nodes.length === 1) { f.a.drains_to = nodes[0].name; say(`Rain area ${f.name} drawn; its rain goes to ${nodes[0].name}.`); }
    else if (nodes.length) { S.draft = { type: 'pick', for: f.id }; say(`Rain area ${f.name} drawn. Now click the drain point its rain flows to.`, true); }
    else say(`Rain area ${f.name} drawn. Place a drain point, then choose it on the right under "Rain from here goes to".`);
  } else say(`${KINDS[tool].label} ${f.name} drawn.`);
  hint(); draw();
}

// ------------------------------------------------------------------ selection / deletion
function select(id, fromCanvas) {
  S.sel = id; draw(); renderSide();
  if (id && !fromCanvas) centreOn(byId(id));
}
function centreOn(f) {
  if (!f) return;
  const r = svg.getBoundingClientRect(), cs = f.g.type === 'Point' ? [f.g.coordinates] : lineCoords(f);
  const c = cs.length === 1 ? cs[0] : centroid(cs.concat([cs[0]]));
  S.view.ox = c[0] - r.width / 2 / S.view.s; S.view.oy = c[1] + r.height / 2 / S.view.s; draw();
}
function removeSelected() {
  const f = S.sel && byId(S.sel);
  if (!f) return say('Click an item first, then press Delete.');
  const joined = S.feats.filter(l => KINDS[l.kind] && KINDS[l.kind].geom === 'link' && (l.a.from === f.name || l.a.to === f.name));
  edit(() => {
    S.feats = S.feats.filter(x => x !== f && !joined.includes(x));
    for (const c of S.feats) if (c.a.drains_to === f.name) delete c.a.drains_to;
    S.sel = null;
  });
  say(`Deleted ${f.name || KINDS[f.kind].label}${joined.length ? ` and ${joined.length} line(s) joined to it` : ''}. Undo brings it back.`);
}
function rename(f, n) {
  n = (n || '').trim();
  if (!n) return say('A name cannot be empty.');
  if (n !== f.name && byName(n)) return say(`The name ${n} is already used. Choose another.`);
  const old = f.name;
  edit(() => {
    f.name = n;
    for (const x of S.feats) {
      if (x.a.from === old) x.a.from = n;
      if (x.a.to === old) x.a.to = n;
      if (x.a.drains_to === old) x.a.drains_to = n;
      for (const arm of x.a.arms || []) if (arm.road === old) arm.road = n;
    }
  });
}

// ------------------------------------------------------------------ hint over the sheet
function hint() {
  const el = $('#hint'); el.replaceChildren();
  const d = S.draft, K = KINDS[S.tool];
  let msg = '', btns = [];
  if (d && d.type === 'pick') msg = 'Now click the drain point where this area’s rain goes.';
  else if (d && d.type === 'link') msg = `Now click where the ${KINDS[d.kind].label.toLowerCase()} goes to. Esc stops.`;
  else if (d && d.type === 'road') { msg = `${d.pts.length} point(s). Click to add bends; double-click or press Finish when done.`;
    btns = [h('button', { class: 'btn primary', onclick: () => finishRoad(S.draft.pts, false), 'data-help': 'Finish the road at the last point you clicked (same as double-click or Enter).' }, 'Finish road')]; }
  else if (d && d.type === 'area') { msg = `${d.pts.length} corner(s). Click around the edge; double-click or press Finish when done.`;
    btns = [h('button', { class: 'btn primary', onclick: () => finishArea(dedupe(S.draft.pts)), 'data-help': 'Close the area using the corners you clicked (same as double-click or Enter).' }, 'Finish area')]; }
  else if (K) msg = KIND_HELP[S.tool];
  else if (!S.feats.length) msg = 'The sheet is empty. Choose a tool and click on the sheet – or press Load example at the top to see a finished one.';
  else if (S.results && !S.stale) msg = 'Rings show the result: red = problem, amber = check this, green = OK. Click an item to see why.';
  else msg = 'Click an item to see or change its details. Drag empty space to move around; use the mouse wheel to zoom.';
  if (d) btns.push(h('button', { class: 'btn', onclick: cancelDraft, 'data-help': 'Stop what you are drawing (same as Esc).' }, 'Cancel'));
  el.append(h('span', { text: msg }), ...btns);
}
function cancelDraft() { S.draft = null; hint(); draw(); say('Stopped.'); }

// ------------------------------------------------------------------ tool bar
const ICON = {
  select: '<path d="M7 4l14 9-6 1.5 3.5 7-2.5 1.2-3.5-7L8 20z" fill="var(--ink)"/>',
};
function toolIcon(k) {
  if (ICON[k]) return `<svg viewBox="0 0 28 28">${ICON[k]}</svg>`;
  const K = KINDS[k];
  if (K.geom === 'link') return `<svg viewBox="0 0 28 28"><circle cx="5" cy="22" r="3.5" fill="${K.colour}"/><circle cx="23" cy="6" r="3.5" fill="${K.colour}"/><path d="M5 22L23 6" stroke="${K.colour}" stroke-width="3"/></svg>`;
  if (K.geom === 'area') return `<svg viewBox="0 0 28 28"><path d="M4 9l10-5 10 7-3 12H7z" fill="${K.colour}" fill-opacity=".25" stroke="${K.colour}" stroke-width="2" stroke-dasharray="${k === 'plot' ? '' : '4 2'}"/></svg>`;
  if (K.geom === 'line') return `<svg viewBox="0 0 28 28"><path d="M3 24C8 16 10 8 25 5" stroke="#9aa5ad" stroke-width="7" fill="none" stroke-linecap="round"/><path d="M3 24C8 16 10 8 25 5" stroke="#4f5b66" stroke-width="1.5" stroke-dasharray="4 3" fill="none"/></svg>`;
  const g = symbol(K, 14, 14, ''); const w = document.createElementNS(SVGNS, 'svg'); w.setAttribute('viewBox', '0 0 28 28'); w.append(g); return w.outerHTML;
}
function renderTools() {
  const box = $('#tools'); if (!S.module) return;
  box.replaceChildren(h('h4', { text: 'Tools' }));
  const ids = ['select', ...TOOLS[S.module]];
  for (const k of ids) {
    const isSel = k === 'select';
    const b = h('button', { class: 'tool', 'aria-pressed': String(S.tool === k), 'data-tool': k,
      'data-help': isSel ? 'Choose and move things: click an item to see its details, drag a point to move it, double-click a road to add a bend.' : KIND_HELP[k],
      onclick: () => setTool(k) });
    b.innerHTML = toolIcon(k);
    b.append(h('span', {}, h('b', { text: isSel ? 'Choose / move' : KINDS[k].label }), h('small', { text: isSel ? 'Click or drag items' : TOOL_SUB[k] })));
    box.append(b);
  }
  box.append(h('h4', { text: 'Change' }),
    h('div', { class: 'row' },
      h('button', { class: 'btn', onclick: undo, disabled: !S.undo.length, 'data-help': 'Take back the last change (Ctrl+Z).' }, 'Undo'),
      h('button', { class: 'btn', onclick: redo, disabled: !S.redo.length, 'data-help': 'Put back a change you undid (Ctrl+Y).' }, 'Redo')),
    h('button', { class: 'btn danger', onclick: removeSelected, disabled: !S.sel, 'data-help': 'Delete the selected item (Delete key). Pipes joined to a deleted point are deleted too. Undo brings them back.' }, 'Delete selected'));
}
function setTool(k) {
  S.tool = k; S.draft = null;
  renderTools(); hint(); draw();
  if (k !== 'select') say(KIND_HELP[k], true);
}

// ------------------------------------------------------------------ side panel
let sideTimer = 0;
function sideSoon() { clearTimeout(sideTimer); sideTimer = setTimeout(renderSide, 0); }
function renderSide() {
  const box = $('#side'); if (!S.module) return;
  const active = document.activeElement, key = active && active.dataset ? active.dataset.key : null;
  const scroll = box.scrollTop;
  box.replaceChildren();
  const f = S.sel && byId(S.sel);
  if (f) objectPanel(box, f); else overviewPanel(box);
  if (key) { const again = box.querySelector(`[data-key="${CSS.escape(key)}"]`); if (again) again.focus(); }
  box.scrollTop = scroll;
}
function stepsDone() {
  const n = k => S.feats.filter(f => f.kind === k).length, has = k => n(k) > 0, every = (k, fn) => S.feats.filter(f => f.kind === k).every(fn);
  const checked = !!S.results && !S.stale;
  switch (S.module) {
    case 'sewer': return [has('manhole'), has('sewer_outfall'), has('sewer_pipe'), has('manhole') && every('manhole', f => +f.a.population > 0), checked];
    case 'water': return [has('reservoir'), has('water_junction'), has('water_pipe'), has('water_junction') && every('water_junction', f => !empty(f.a.people) || !empty(f.a.demand_lps)), checked];
    case 'drainage': return [has('drain_node') && has('drain_outfall'), has('storm_drain'), has('catchment'), !!S.settings.ui_storm_set, checked];
    case 'road': return [has('road_alignment'), has('road_alignment'), has('road_alignment') && every('road_alignment', f => !f.sug.design_speed_kmh), checked];
    case 'junction': return [has('road_junction'), has('road_junction') && every('road_junction', f => !f.sug.arms || f.a.ui_layout !== 'cross' || !!f.a.ui_layout_chosen), has('road_junction'), checked];
    case 'electrical': return [has('substation') && has('transformer') && has('electrical_load'), has('electrical_cable'), has('electrical_load') && every('electrical_load', f => !empty(f.a.connected_load_kw)), checked];
  }
  return [];
}
function overviewPanel(box) {
  const done = stepsDone();
  box.append(h('h2', { text: S.mod.title }), h('p', { class: 'note', text: S.mod.what }),
    h('label', { class: 'field', 'data-help': 'A name for this design. It appears on the report and in the saved file name.' },
      h('span', { text: 'Name of this design' }),
      h('input', { value: S.name, 'data-key': 'design-name', onchange: e => edit(() => { S.name = e.target.value.trim() || 'My design'; }) })),
    h('h3', { text: 'Steps' }),
    h('ol', { class: 'steps', 'data-help': 'The steps to follow. Each one gets a tick when it is done.' }, S.mod.steps.map((t, i) => h('li', { class: done[i] ? 'done' : '', text: t }))));
  settingsPanel(box);
  const counts = {};
  for (const f of S.feats) if (KINDS[f.kind] && !KINDS[f.kind].passive) counts[f.kind] = (counts[f.kind] || 0) + 1;
  const tp = S.feats.filter(f => f.kind === 'terrain_point').length;
  box.append(h('h3', { text: 'On your drawing' }));
  if (!Object.keys(counts).length) box.append(h('p', { class: 'note', text: 'Nothing yet. Choose a tool to start, or press Load example.' }));
  else box.append(h('dl', { class: 'values' }, Object.entries(counts).flatMap(([k, c]) => [h('dt', { text: KINDS[k].label }), h('dd', { text: String(c) })]),
    tp ? [h('dt', { text: 'Ground level points' }), h('dd', { text: String(tp) })] : []));
  const miss = missing();
  if (miss.length) box.append(h('h3', { text: 'Still to fill in' }), missingList(miss.slice(0, 12)), miss.length > 12 ? h('p', { class: 'note', text: `…and ${miss.length - 12} more.` }) : '');
}
function missingList(miss) {
  return h('ul', { class: 'res-list' }, miss.map(m => h('li', { class: 'res-item warning' },
    m.f ? h('button', { class: 'btn goto', onclick: () => select(m.f.id), 'data-help': 'Select this item on the drawing so you can fill it in.' }, 'Show') : '',
    h('span', { class: 't', text: m.f ? `${m.f.name || KINDS[m.f.kind].label}: ` : '' }), m.what)));
}
function setting(key, labelText, help, input) {
  input.dataset.key = 'set-' + key;
  return h('label', { class: 'field', 'data-help': help }, h('span', { text: labelText }), input, h('small', { class: 'help', text: help }));
}
function settingsPanel(box) {
  const st = S.settings, m = S.module;
  const levelsHelper = (linkKind, word2) => {
    const cover = h('input', { type: 'number', step: '0.1', min: '0.3', value: st.ui_cover ?? 1.0 });
    const slope = h('input', { type: 'number', step: '10', min: '20', value: st.ui_slope ?? (linkKind === 'sewer_pipe' ? 200 : 300) });
    cover.onchange = () => edit(() => { st.ui_cover = +cover.value; });
    slope.onchange = () => edit(() => { st.ui_slope = +slope.value; });
    box.append(h('h3', { text: `${word2} levels` }),
      h('p', { class: 'note', text: `If you do not know the ${word2.toLowerCase()} levels, this fills them in from the ground levels: starting at the depth below and falling at the slope below. Levels you typed yourself are kept.` }),
      setting('cover', 'Soil above the pipe at the top end', 'How much soil covers the top of the pipe where it starts, in metres. About 1 m is usual under streets.', cover),
      setting('slope', 'Fall: 1 metre in every …', 'How steeply it falls. 200 means 1 m down for every 200 m along (0.5 %). Smaller numbers are steeper.', slope),
      h('button', { class: 'btn', 'data-help': `Work out the ${word2.toLowerCase()} bottom levels for you, from the ground levels, the depth and the fall above. They are marked "Suggested – check this".`,
        onclick: () => {
          let r; edit(() => { r = fillLevels(linkKind, +cover.value || 1, +slope.value || 200); });
          say(`Levels filled in for ${r.done} ${word2.toLowerCase()}(s)` + (r.skipped.length ? `; ${r.skipped.join(', ')} skipped because a ground level is missing.` : '.') + (r.loop ? ' Some form a loop and were skipped.' : ''));
        } }, `Fill in ${word2.toLowerCase()} levels for me`));
  };
  if (m === 'sewer') levelsHelper('sewer_pipe', 'Pipe');
  if (m === 'water') {
    const i = h('input', { type: 'number', min: '1', step: '5', value: st.litres_per_person_per_day ?? '' });
    i.onchange = () => edit(() => { st.litres_per_person_per_day = i.value === '' ? undefined : +i.value; delete st.ui_sug_lpcd; });
    const lab = setting('lpcd', 'Water used per person per day (litres)', 'Litres each person uses in a day. Your design standard gives this (for example 135 litres for towns with sewers). Check the figure that applies to your project.', i);
    if (st.ui_sug_lpcd) { lab.classList.add('suggested'); lab.querySelector('span').append(h('span', { class: 'chip', text: 'Suggested – check this' })); }
    box.append(h('h3', { text: 'Water use' }), lab);
  }
  if (m === 'drainage') {
    const example = (st.ui_rain_mode || 'example') === 'example';
    const rps = example ? [2, 5, 10] : [1, 2, 5, 10, 25, 50, 100];
    const rp = h('select', {}, rps.map(v => h('option', { value: v, selected: +st.return_period === v, text: `Once in ${v} year${v > 1 ? 's' : ''}` })));
    rp.onchange = () => edit(() => { st.return_period = +rp.value; st.ui_storm_set = true; });
    const at = h('select', {}, OPT.area_types.map(v => h('option', { value: v, selected: st.area_type === v, text: word(v) })));
    at.onchange = () => edit(() => { st.area_type = at.value; st.ui_storm_set = true; });
    const mode = h('select', {}, h('option', { value: 'example', selected: example, text: 'Example rainfall – only for trying out' }),
      h('option', { value: 'table', selected: !example, text: 'My rainfall figures' }));
    mode.onchange = () => edit(() => { st.ui_rain_mode = mode.value; st.ui_storm_set = true; if (mode.value === 'example' && ![2, 5, 10].includes(+st.return_period)) st.return_period = 5; });
    box.append(h('h3', { text: 'Storm to design for' }),
      setting('rp', 'How rare a storm should the drains carry?', 'Drains are sized for a heavy storm that comes about once in so many years. Rarer storms are heavier and need bigger drains.', rp),
      setting('area', 'What kind of area is it?', 'Busier or more important areas are designed for rarer, heavier storms. The check tells you if your choice is lower than recommended.', at),
      setting('rain', 'Rainfall figures', 'The example figures are invented, only for trying the program. For a real design enter the figures from the weather office (IMD) or the hydrology report.', mode));
    if (!example) {
      const tab = st.ui_rain_table || (st.ui_rain_table = [null, null, null, null, null, null]);
      const durs = [5, 10, 15, 30, 60, 120];
      box.append(h('p', { class: 'note', text: 'Rain intensity (mm per hour) for a storm of the chosen rarity that lasts…' }),
        h('table', { class: 'arms' }, h('tr', {}, durs.map(d => h('th', { text: d + ' min' }))),
          h('tr', {}, durs.map((d, i) => h('td', {}, h('input', { type: 'number', min: '0', value: tab[i] ?? '', 'aria-label': `Rain intensity for ${d} minutes (mm/h)`, 'data-key': 'rain' + i,
            'data-help': `Average rain intensity, in millimetres per hour, during a ${d}-minute storm.`, onchange: e => edit(() => { tab[i] = e.target.value === '' ? null : +e.target.value; }) }))))));
      const src = h('input', { value: st.ui_rain_source || '' });
      src.onchange = () => edit(() => { st.ui_rain_source = src.value; });
      box.append(setting('src', 'Where the figures come from', 'For example "IMD Delhi (Safdarjung) 1990–2020". It is printed on the report.', src));
    }
    levelsHelper('storm_drain', 'Drain');
  }
}
function fieldEl(f, d) {
  const v = getVal(f, d), sugKey = d.sugKey || d.key, suggested = !!f.sug[sugKey];
  let input;
  const shown = v === undefined || v === null ? '' : d.scale ? +(v * d.scale).toFixed(6) : v;
  if (d.type === 'select') {
    const opts = d.options(f);
    input = h('select', {}, h('option', { value: '', text: '– choose –' }), opts.map(([val, t]) => h('option', { value: val, selected: String(val) === String(shown), text: t })));
    if (!empty(shown) && !opts.some(([val]) => String(val) === String(shown))) input.append(h('option', { value: shown, selected: true, text: `${shown} (from file)` }));
  } else if (d.type === 'check') input = h('input', { type: 'checkbox', checked: !!v });
  else input = h('input', { type: d.type === 'number' ? 'number' : 'text', step: 'any', value: shown, inputmode: d.type === 'number' ? 'decimal' : null });
  input.dataset.key = f.id + ':' + d.key;
  input.onchange = () => {
    let val = d.type === 'check' ? input.checked : input.value;
    if (d.type === 'number' || d.num) val = val === '' ? undefined : +val;
    if (d.scale && val !== undefined) val = val / d.scale;
    edit(() => {
      if (d.set) d.set(f, val); else if (val === undefined || val === '') delete f.a[d.key]; else f.a[d.key] = val;
      delete f.sug[sugKey];
    });
  };
  const missingNow = d.req && empty(v);
  const head = h('span', {}, h('span', {}, d.label, d.unit ? h('span', { class: 'unit', text: ` (${d.unit})` }) : ''),
    suggested ? h('span', { class: 'chip', text: 'Suggested – check this' }) : missingNow ? h('span', { class: 'chip', style: 'background:color-mix(in srgb,var(--stop) 18%,var(--panel))', text: 'Needed' }) : '');
  return h('label', { class: 'field' + (suggested ? ' suggested' : ''), 'data-help': d.help }, head, input, h('small', { class: 'help', text: d.help }));
}
function objectPanel(box, f) {
  const K = KINDS[f.kind] || { label: pretty(f.kind), fields: [] };
  box.append(h('button', { class: 'btn ghost', onclick: () => select(null), 'data-help': 'Go back to the steps and settings for the whole design.' }, '← Back to steps'),
    h('h2', { text: `${K.label} ${f.name || ''}` }));
  // results for this object
  if (S.results && !S.stale) {
    const its = S.results.items.filter(i => i.object_id === f.id);
    const vals = S.results.values[f.id];
    if (its.length) box.append(h('ul', { class: 'res-list' }, its.filter(i => i.status !== 'pass').map(i => resultItem(i, true)),
      its.some(i => i.status === 'pass') ? h('li', { class: 'note', text: `${its.filter(i => i.status === 'pass').length} check(s) OK.` }) : ''));
    if (vals) box.append(h('h3', { text: 'Calculated' }), h('dl', { class: 'values', 'data-help': 'Figures worked out by the last check.' },
      Object.entries(vals).flatMap(([k, v]) => [h('dt', { text: k }), h('dd', { text: fmt(v) })])));
  } else if (S.results && S.stale) box.append(h('p', { class: 'note', text: 'The drawing changed after the last check. Press Check my design to update the results.' }));
  box.append(h('h3', { text: 'Details' }));
  if (!K.passive) {
    const nm = h('input', { value: f.name || '', 'data-key': f.id + ':name' });
    nm.onchange = () => rename(f, nm.value);
    box.append(h('label', { class: 'field', 'data-help': 'A short name for this item. Pipes and cables refer to points by their names.' }, h('span', { text: 'Name' }), nm));
  }
  if (K.geom === 'link') {
    box.append(h('p', { class: 'note', text: `Goes from ${f.a.from || '?'} to ${f.a.to || '?'} – ${lineLength(f.g.coordinates).toFixed(1)} m long.` }),
      h('button', { class: 'btn', 'data-help': 'Swap the two ends, if you drew it the wrong way round. Sewage and rain water flow in the direction of the arrow.',
        onclick: () => edit(() => { [f.a.from, f.a.to] = [f.a.to, f.a.from]; f.g.coordinates.reverse(); [f.a.us_invert, f.a.ds_invert] = [f.a.ds_invert, f.a.us_invert]; }) }, 'Reverse direction'));
  }
  if (K.custom === 'road') roadPanel(box, f);
  else if (K.custom === 'junction') junctionPanel(box, f);
  else {
    const fl = fieldsOf(f);
    const basic = fl.filter(d => !d.advanced && (!d.show || d.show(f))), adv = fl.filter(d => d.advanced && (!d.show || d.show(f)));
    basic.forEach(d => box.append(fieldEl(f, d)));
    if (adv.length) box.append(h('details', {}, h('summary', { text: 'More options', 'data-help': 'Extra details most people do not need.' }), adv.map(d => fieldEl(f, d))));
    if (f.kind === 'plot') box.append(h('p', { class: 'note', text: 'Buildings and walls near a junction are checked to see whether they block drivers’ view.' }));
    if (f.kind === 'catchment') box.append(h('p', { class: 'note', text: `Area: ${(polyArea(f.g.coordinates[0]) / 10000).toFixed(3)} hectares. Drag the round handles to change its shape.` }));
  }
  if (!K.passive) box.append(h('p', {}, h('button', { class: 'btn danger', onclick: removeSelected, 'data-help': 'Delete this item. Undo brings it back.' }, 'Delete this ' + K.label.toLowerCase())));
}
function polyArea(r) { let a = 0; for (let i = 0, n = r.length; i < n; i++) { const p = r[i], q = r[(i + 1) % n]; a += p[0] * q[1] - q[0] * p[1]; } return Math.abs(a / 2); }

function roadPanel(box, f) {
  const set = (key, fn) => edit(() => { fn(); delete f.sug[key]; });
  const L = lineLength(f.g.coordinates);
  const prof = f.a.profile || (f.a.profile = [[0, null, 0], ['end', null, 0]]);
  const rt = f.a.ui_road_type || (f.a.template ? 'file' : '');
  const fd = (key, labelText, help, input, unit) => {
    input.dataset.key = f.id + ':' + key;
    const sgd = !!f.sug[key];
    return h('label', { class: 'field' + (sgd ? ' suggested' : ''), 'data-help': help },
      h('span', {}, h('span', {}, labelText, unit ? h('span', { class: 'unit', text: ` (${unit})` }) : ''), sgd ? h('span', { class: 'chip', text: 'Suggested – check this' }) : ''),
      input, h('small', { class: 'help', text: help }));
  };
  const selectOf = (opts, cur) => h('select', {}, opts.map(([v, t]) => h('option', { value: v, selected: String(v) === String(cur), text: t })));
  box.append(h('p', { class: 'note', text: f.a.horizontal_mode === 'fit' ? `${L.toFixed(1)} m long, drawn freehand.`
    : `${L.toFixed(1)} m long, ${Math.max(0, f.g.coordinates.length - 2)} bend point(s). Drag the round handles to reshape it; double-click the road to add a bend.` }));
  const t = selectOf([...Object.entries(ROAD_TYPES).map(([k, v]) => [k, v.label]), ...(rt === 'file' ? [['file', 'As given in the file']] : [])], rt);
  t.onchange = () => set('ui_road_type', () => { if (ROAD_TYPES[t.value]) { f.a.ui_road_type = t.value; f.a.template = clone(ROAD_TYPES[t.value].template); } });
  const sp = selectOf(SPEEDS.map(v => [v, v + ' km/h']), f.a.design_speed_kmh);
  sp.onchange = () => set('design_speed_kmh', () => { f.a.design_speed_kmh = +sp.value; if (f.sug.curves && f.a.horizontal_mode !== 'fit') suggestBends(f); });
  const tr = selectOf(OPT.terrains.map(v => [v, word(v)]), f.a.terrain);
  tr.onchange = () => set('terrain', () => { f.a.terrain = tr.value; });
  const kb = h('input', { type: 'checkbox', checked: !!f.a.kerbed });
  kb.onchange = () => set('kerbed', () => { f.a.kerbed = kb.checked; });
  const mode = selectOf([['pi', 'I give each bend a radius (recommended)'], ['fit', 'Fit curves to the shape I drew']], f.a.horizontal_mode || 'pi');
  mode.onchange = () => {
    if (mode.value === 'pi' && f.g.coordinates.length > 12) { mode.value = 'fit'; return say('This road was drawn freehand with many points. To give each bend a radius, draw it again by clicking at each bend.', true); }
    set('horizontal_mode', () => { f.a.horizontal_mode = mode.value; if (mode.value === 'pi') { f.sug.curves = 1; suggestBends(f); } });
  };
  const z0 = h('input', { type: 'number', step: 'any', value: prof[0][1] ?? '' });
  z0.onchange = () => set('ui_start', () => { prof[0][1] = z0.value === '' ? null : +z0.value; });
  const z1 = h('input', { type: 'number', step: 'any', value: prof[prof.length - 1][1] ?? '' });
  z1.onchange = () => set('ui_end', () => { prof[prof.length - 1][1] = z1.value === '' ? null : +z1.value; });
  box.append(
    fd('ui_road_type', 'Type of road', 'How wide the road is and what it has on each side. It sets the lanes, footpaths and median.', t),
    fd('design_speed_kmh', 'Design speed', 'The speed the road is made safe for. Higher speeds need gentler bends and longer easing curves.', sp, 'km/h'),
    fd('terrain', 'Land', 'How hilly the land is. It changes how long the easing curves at bends must be.', tr),
    h('label', { class: 'field' + (f.sug.kerbed ? ' suggested' : ''), 'data-help': 'Tick if the road has raised kerbs at its edges. Kerbed roads need a little slope so rain runs to the drains.' },
      h('span', {}, h('span', {}, kb, 'Has kerbs (raised edges)'), f.sug.kerbed ? h('span', { class: 'chip', text: 'Suggested – check this' }) : '')),
    fd('ui_start', 'Road level at the start', 'Height of the finished road surface where the road starts (above sea level).', z0, 'm'),
    fd('ui_end', 'Road level at the end', 'Height of the finished road surface where the road ends.', z1, 'm'));
  if (prof.length > 2) box.append(h('p', { class: 'note', text: `This road also has ${prof.length - 2} level point(s) in between, from the file. They are kept.` }));
  box.append(fd('horizontal_mode', 'How bends are made', 'Choose "radius" to type a curve radius at each corner you clicked. Choose "fit" to let the program find curves that follow a shape you drew freehand.', mode));
  if ((f.a.horizontal_mode || 'pi') === 'pi') {
    const n = f.g.coordinates.length - 2;
    if (n <= 0) box.append(h('p', { class: 'note', text: 'This road is straight. Double-click on it to add a bend.' }));
    else {
      const cur = f.a.curves || (f.a.curves = {});
      const row = i => {
        const v = cur[i] || [null, 0];
        const R = h('input', { type: 'number', min: '1', value: v[0] ?? '', 'aria-label': `Radius of bend ${i} (m)`, 'data-key': `${f.id}:R${i}`, 'data-help': 'Radius of the curve at this bend, in metres. Bigger is gentler and safer.' });
        const Ls = h('input', { type: 'number', min: '0', value: v[1] ?? 0, 'aria-label': `Easing curve length at bend ${i} (m)`, 'data-key': `${f.id}:L${i}`, 'data-help': 'Length of the gradual easing curve into and out of the bend (a spiral), in metres. 0 means none.' });
        const upd = () => set('curves', () => { cur[i] = [R.value === '' ? null : +R.value, Ls.value === '' ? 0 : +Ls.value]; });
        R.onchange = upd; Ls.onchange = upd;
        return h('tr', {}, h('td', { text: String(i) }), h('td', {}, R), h('td', {}, Ls));
      };
      box.append(h('h3', {}, 'Bends ', f.sug.curves ? h('span', { class: 'chip', text: 'Suggested – check this' }) : ''),
        h('table', { class: 'arms', 'data-help': 'One row for each bend point, counted from the start of the road.' },
          h('tr', {}, h('th', { text: 'Bend' }), h('th', { text: 'Radius (m)' }), h('th', { text: 'Easing curve (m)' })),
          Array.from({ length: n }, (_, k) => row(k + 1))));
    }
  } else box.append(h('p', { class: 'note', text: 'The curves will be fitted to the shape you drew when you press Check my design. The fitted road is drawn in blue. To change the shape, delete this road and draw it again.' }));
}

function junctionPanel(box, f) {
  const selectOf = (opts, cur) => h('select', {}, opts.map(([v, t]) => h('option', { value: v, selected: String(v) === String(cur), text: t })));
  const fd = (key, labelText, help, input, unit, sugKey) => {
    input.dataset.key = f.id + ':' + key;
    const sgd = !!f.sug[sugKey || key];
    return h('label', { class: 'field' + (sgd ? ' suggested' : ''), 'data-help': help },
      h('span', {}, h('span', {}, labelText, unit ? h('span', { class: 'unit', text: ` (${unit})` }) : ''), sgd ? h('span', { class: 'chip', text: 'Suggested – check this' }) : ''),
      input, h('small', { class: 'help', text: help }));
  };
  const lay = selectOf([...Object.entries(LAYOUTS).map(([k, v]) => [k, v.label]), ...(f.a.ui_layout ? [] : [['', 'As given in the file']])], f.a.ui_layout || '');
  lay.onchange = () => { if (LAYOUTS[lay.value]) edit(() => { applyLayout(f, lay.value); f.a.ui_layout_chosen = true; }); };
  box.append(fd('layout', 'Kind of junction', 'Choosing a kind sets up the roads for you (you can then change their directions and widths below).', lay, '', 'arms'));
  if (f.a.type !== 'roundabout') {
    const ctl = selectOf(CONTROLS, f.a.control || 'uncontrolled');
    ctl.onchange = () => edit(() => { f.a.control = ctl.value; delete f.sug.control; });
    box.append(fd('control', 'How traffic is controlled', 'Who gives way. This decides how far drivers must be able to see at the corners.', ctl));
    const veh = selectOf(OPT.design_vehicles.map(v => [v, word(v)]), f.a.design_vehicle);
    veh.onchange = () => edit(() => { f.a.design_vehicle = veh.value; delete f.sug.design_vehicle; });
    box.append(fd('design_vehicle', 'Biggest vehicle that must turn here', 'Corners are made wide enough for this vehicle to turn without climbing the kerb.', veh));
    const c = f.a.corner || {};
    const ct = selectOf([['simple', 'Simple curve'], ['three_centred', 'Three-part curve (better for big vehicles)']], c.type || 'simple');
    ct.onchange = () => edit(() => { f.a.corner = Object.assign({}, f.a.corner, { type: ct.value }, ct.value === 'three_centred' ? { ratio: 2, end_deflection_deg: 15 } : {}); });
    const cr = h('input', { type: 'number', min: '1', value: c.R ?? '', placeholder: 'from the rules' });
    cr.onchange = () => edit(() => { f.a.corner = Object.assign({}, f.a.corner || { type: 'simple' }); if (cr.value === '') delete f.a.corner.R; else f.a.corner.R = +cr.value; });
    box.append(fd('corner_type', 'Shape of the kerb at the corners', 'A three-part curve fits the path of long vehicles better than a single curve.', ct),
      fd('corner_R', 'Corner radius (optional)', 'Leave empty to use the smallest radius the rules allow for the vehicle chosen above.', cr, 'm'));
  } else {
    const rb = f.a.roundabout || (f.a.roundabout = {});
    const rnum = (key, labelText, help) => {
      const i = h('input', { type: 'number', min: '0', step: 'any', value: rb[key] ?? '' });
      i.onchange = () => edit(() => { if (i.value === '') delete rb[key]; else rb[key] = +i.value; delete f.sug.roundabout; });
      return fd('rb_' + key, labelText, help, i, 'm', 'roundabout');
    };
    const setg = selectOf([['urban', 'In town'], ['rural', 'Outside town']], rb.setting || 'urban');
    setg.onchange = () => edit(() => { rb.setting = setg.value; });
    box.append(rnum('central_island_radius_m', 'Centre island radius', 'Radius of the raised island in the middle.'),
      rnum('circulatory_width_m', 'Width of the ring road', 'Width of the road going round the island.'),
      rnum('entry_radius_m', 'Entry curve radius', 'Radius of the kerb where vehicles come into the roundabout.'),
      rnum('exit_radius_m', 'Exit curve radius', 'Radius of the kerb where vehicles leave the roundabout.'),
      fd('rb_setting', 'Location', 'Recommended entry curves differ in town and outside town.', setg));
    if (!rb.flows_pcu_h) box.append(h('p', { class: 'note', text: 'Traffic counts were not given, so the roundabout’s traffic capacity is not checked. An engineer can add them in the saved file.' }));
  }
  // arms table
  const arms = f.a.arms || (f.a.arms = []);
  const upd = fn => edit(() => { fn(); delete f.sug.arms; });
  const rows = arms.map((a, i) => {
    if (a.road) return h('tr', {}, h('td', { colspan: 6, text: `Follows road ${a.road} (its width and speed come from the road)` }),
      h('td', {}, h('button', { class: 'btn', 'aria-label': `Remove ${a.road}`, 'data-help': 'Remove this road from the junction.', onclick: () => upd(() => arms.splice(i, 1)) }, '×')));
    const inp = (key, w, help, attrs = {}) => {
      const e = h('input', Object.assign({ type: key === 'name' ? 'text' : 'number', value: a[key] ?? '', 'data-key': `${f.id}:arm${i}:${key}`, 'aria-label': `${help.split('.')[0]} – road ${a.name || i + 1}`, 'data-help': help, style: `width:${w}` }, attrs));
      e.onchange = () => upd(() => { a[key] = key === 'name' ? e.value : e.value === '' ? undefined : +e.value; });
      return h('td', {}, e);
    };
    const maj = h('input', { type: 'checkbox', checked: a.priority === 'major', 'aria-label': `Main road – ${a.name}`, 'data-help': 'Tick for the main road, which has priority.' });
    maj.onchange = () => upd(() => { if (maj.checked) a.priority = 'major'; else delete a.priority; });
    return h('tr', {}, inp('name', '3.2em', 'Name of this road.'), inp('bearing_deg', '3.6em', 'Direction of this road from the junction, in degrees: 0 is north (up), 90 east, 180 south, 270 west.', { min: 0, max: 359 }),
      inp('width_left', '3.2em', 'Road width on the left side of its centre line, looking out from the junction (m).', { min: 0, step: 'any' }),
      inp('width_right', '3.2em', 'Road width on the right side of its centre line, looking out from the junction (m).', { min: 0, step: 'any' }),
      inp('speed_kmh', '3.2em', 'Speed of traffic on this road (km/h).', { min: 5 }), h('td', {}, maj),
      h('td', {}, h('button', { class: 'btn', 'aria-label': `Remove road ${a.name}`, 'data-help': 'Remove this road from the junction.', onclick: () => upd(() => arms.splice(i, 1)) }, '×')));
  });
  box.append(h('h3', {}, 'Roads meeting here ', f.sug.arms ? h('span', { class: 'chip', text: 'Suggested – check this' }) : ''),
    h('table', { class: 'arms', 'data-help': 'One row for each road that meets at the junction.' },
      h('tr', {}, ['Name', 'Direction °', 'Left m', 'Right m', 'km/h', 'Main', ''].map(t2 => h('th', { text: t2 }))), rows),
    h('p', {}, h('button', { class: 'btn', 'data-help': 'Add another road to this junction.', onclick: () => upd(() => arms.push({ name: String.fromCharCode(65 + arms.length), bearing_deg: 45, width_left: 3.5, width_right: 3.5, speed_kmh: 40 })) }, '+ Add a road')));
}

// ------------------------------------------------------------------ check
function payloadSettings() {
  const st = S.settings, out = {};
  for (const [k, v] of Object.entries(st)) if (!k.startsWith('ui_')) out[k] = v;
  if (S.module === 'drainage') {
    out.return_period = +st.return_period || 5; out.area_type = st.area_type || 'residential';
    if ((st.ui_rain_mode || 'example') === 'table')
      out.idf = { form: 'table', source: st.ui_rain_source || 'Rainfall figures entered by the user (source not stated)', durations_min: [5, 10, 15, 30, 60, 120],
        return_periods: { [String(out.return_period)]: st.ui_rain_table } };
    else out.idf = 'example';
  }
  return out;
}
async function runCheck() {
  if (!S.feats.some(f => KINDS[f.kind] && !KINDS[f.kind].passive)) return say('Draw something first – choose a tool on the left, or press Load example.');
  S.draft = null;
  const miss = missing();
  if (S.module === 'drainage' && (S.settings.ui_rain_mode === 'table') && (S.settings.ui_rain_table || []).some(empty))
    miss.push({ f: null, what: 'All six rainfall figures (in the panel on the right, with nothing selected)' });
  if (miss.length) {
    S.results = null; S.stale = false;
    renderResults(miss); draw(); renderSide();
    return say(`${miss.length} detail(s) still need filling in before the check can run.`);
  }
  const b = $('#btn-check'); b.disabled = true; b.textContent = 'Checking…';
  say('Checking your design…', true);
  try {
    const r = await api('/api/check/' + S.module, { features: toFC(true), settings: payloadSettings(), name: S.name });
    S.results = r; S.stale = false; S.showMissing = false;
    renderResults(); draw(); renderSide(); hint();
    say(r.headline);
    $('#results').scrollTop = 0;
  } catch (e) { say('The check could not run: ' + e.message, true); }
  finally { b.disabled = false; b.textContent = 'Check my design'; }
}
function resultItem(i, inPanel) {
  const fix = i.fix ? h('div', { class: 'fix' }, h('b', { text: 'What to do: ' }), i.fix) : '';
  const tech = [i.detail, i.source && `Rule: ${i.source}`, i.verification && i.verification !== 'verified' && `Rule status: ${i.verification === 'requires_verification' ? 'needs confirming by your office' : i.verification.replace(/_/g, ' ')}`].filter(Boolean);
  return h('li', { class: 'res-item ' + i.status },
    byId(i.object_id) && inPanel !== true ? h('button', { class: 'btn goto', onclick: () => select(i.object_id), 'data-help': 'Show this item on the drawing and open its details.' }, 'Show') : '',
    h('div', { class: 't' }, `${i.status_word}: ${i.title} `, h('span', { class: 'who', text: i.object ? `– ${i.object}` : '' })),
    i.why ? h('div', { class: 'why', text: i.why }) : '', fix,
    tech.length ? h('details', {}, h('summary', { text: 'Technical details', 'data-help': 'The figures and the rule behind this result, for the engineer.' }), tech.map(t => h('div', { text: t }))) : '');
}
let showOk = false;
function renderResults(miss) {
  const box = $('#results');
  if (miss) S.showMissing = true;
  if (!miss && !S.results && S.showMissing) {
    miss = missing();
    if (!miss.length) {
      box.hidden = false;
      box.replaceChildren(h('div', { class: 'res-head' }, signal('pass'), h('h2', { text: 'All details are filled in. Press Check my design.' }), h('span', { class: 'spacer' }),
        h('button', { class: 'btn primary', onclick: runCheck, 'data-help': 'Run the check now.' }, 'Check my design'),
        h('button', { class: 'btn', onclick: closeResults, 'data-help': 'Hide the results panel.' }, 'Close')));
      return;
    }
  }
  if (miss) {
    box.hidden = false;
    box.replaceChildren(h('div', { class: 'res-head' }, signal('fail'), h('h2', { text: 'Some details are still missing' }), h('span', { class: 'spacer' }),
      h('button', { class: 'btn', onclick: closeResults, 'data-help': 'Hide the results panel.' }, 'Close')),
      h('div', { class: 'errors' }, h('h3', { text: 'Fill these in first' }), missingList(miss)));
    return;
  }
  const r = S.results;
  if (!r) { box.hidden = true; return; }
  box.hidden = false;
  const items = r.items.filter(i => i.status !== 'pass'), ok = r.items.filter(i => i.status === 'pass');
  const c = r.counts;
  box.replaceChildren(
    h('div', { class: 'res-head' }, signal(r.tone),
      h('div', {}, h('h2', { text: r.headline }), h('div', { class: 'counts', text: `${c.fail} problem(s) · ${c.warning} to check · ${c.pass} OK` + (c.not_evaluated ? ` · ${c.not_evaluated} not checked` : '') })),
      h('span', { class: 'spacer' }),
      r.report_markdown ? h('button', { class: 'btn', onclick: openReport, 'data-help': 'Open the full report for the engineer in a new tab. You can print it or save it as PDF from there.' }, 'Open the report') : '',
      h('button', { class: 'btn', onclick: closeResults, 'data-help': 'Hide the results panel. The colours stay on the drawing.' }, 'Close')),
    S.stale ? h('p', { class: 'note', text: 'You changed the drawing after this check. Press Check my design again to update.' }) : '',
    r.errors.length ? h('div', { class: 'errors' }, h('h3', { text: 'Fix these first' }), h('ul', {}, r.errors.map(e => h('li', { text: e })))) : '',
    r.notes.length || r.unverified_rules ? h('div', { class: 'notes' }, r.notes.map(n => h('p', { class: 'note', text: n })),
      r.unverified_rules ? h('p', { class: 'note', text: `${r.unverified_rules} of the rules used still need confirming by your office. The report marks them.` }) : '') : '',
    h('ul', { class: 'res-list' }, items.map(i => resultItem(i))),
    ok.length ? h('button', { class: 'btn toggle-ok', onclick: () => { showOk = !showOk; renderResults(); }, 'data-help': 'Show or hide the checks that passed.' },
      showOk ? 'Hide the things that are OK' : `Show the ${ok.length} thing(s) that are OK`) : '',
    showOk ? h('ul', { class: 'res-list' }, ok.map(i => resultItem(i))) : '',
    h('p', { class: 'note', text: r.disclaimer }));
}
function signal(tone) {
  const on = { fail: 'r', error: 'r', warning: 'a', pass: 'g' }[tone];
  return h('div', { class: 'signal', 'aria-label': { r: 'Red', a: 'Amber', g: 'Green' }[on] + ' light', role: 'img' },
    ...['r', 'a', 'g'].map(k => h('i', { class: k + (k === on ? ' on' : '') })));
}
function closeResults() { S.showMissing = false; $('#results').hidden = true; }
async function openReport() {
  const w = window.open('', '_blank');
  try {
    const html = await api('/api/report', { markdown: S.results.report_markdown, title: `${S.name} – ${S.mod.title} check` });
    if (w) { w.document.open(); w.document.write(html); w.document.close(); }
    else download(new Blob([html], { type: 'text/html' }), fileBase() + '-report.html');
  } catch (e) { if (w) w.close(); say('The report could not be made: ' + e.message); }
}

// ------------------------------------------------------------------ files
function fileBase() { return (S.name || 'design').replace(/[^\w\- ]+/g, '').trim().replace(/\s+/g, '-').toLowerCase() || 'design'; }
function download(blob, name) {
  const a = h('a', { href: URL.createObjectURL(blob), download: name }); document.body.append(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}
function saveFile() {
  download(new Blob([JSON.stringify(toFC(false), null, 1)], { type: 'application/geo+json' }), `${fileBase()}-${S.module}.geojson`);
  say('Saved to your Downloads folder. Use Open saved work to continue later.');
}
function openFile(file) {
  const rd = new FileReader();
  rd.onload = () => {
    try {
      const fc = JSON.parse(rd.result);
      if (!fc || !Array.isArray(fc.features)) throw new Error('this is not a drawing file (GeoJSON).');
      const crs = (((fc.crs || {}).properties) || {}).name || '';
      if (!crs.endsWith(':' + EPSG) && !crs.endsWith('::' + EPSG)) throw new Error(`the file must be in the project coordinates EPSG:${EPSG} (UTM 43N, metres). It says "${crs || 'none'}".`);
      const meta = fc.cityinfra || {};
      const m = meta.module && S.modules.some(x => x.id === meta.module) ? meta.module : S.module;
      if (m !== S.module) openModule(m, true);
      edit(() => { S.feats = fromFC(fc); S.settings = meta.settings || S.settings; S.name = fc.name || S.name; S.sel = null; S.results = null; });
      S.stale = false; renderResults(); fit();
      say(`Opened ${file.name}: ${S.feats.length} item(s).`);
    } catch (e) { say('Could not open the file: ' + e.message, true); }
  };
  rd.readAsText(file);
}

// ------------------------------------------------------------------ pages
function homeTileIcon(k) {
  const I = {
    sewer: '<circle cx="24" cy="24" r="16" fill="none" stroke="#8a5a2b" stroke-width="4"/><circle cx="24" cy="24" r="5" fill="#8a5a2b"/>',
    water: '<path d="M24 6C24 6 11 21 11 29a13 13 0 0026 0C37 21 24 6 24 6z" fill="#1f6fd1"/>',
    rain: '<path d="M10 22a9 9 0 0117-4 7 7 0 0111 6H10z" fill="#12857a"/><path d="M14 30l-3 7M24 30l-3 7M34 30l-3 7" stroke="#12857a" stroke-width="3" stroke-linecap="round"/>',
    road: '<path d="M16 42L22 6h4l6 36z" fill="#9aa5ad"/><path d="M24 10v6M24 22v6M24 34v6" stroke="#fff" stroke-width="2.5"/>',
    junction: '<path d="M19 4h10v15h15v10H29v15H19V29H4V19h15z" fill="#9aa5ad"/>',
    power: '<path d="M27 4L12 27h10l-3 17 17-25H25z" fill="#7a3fb5"/>',
  };
  return `<svg viewBox="0 0 48 48" aria-hidden="true">${I[k] || ''}</svg>`;
}
function renderHome() {
  const box = $('#tiles'); box.replaceChildren();
  for (const m of S.modules) {
    const b = h('button', { class: 'tile', onclick: () => openModule(m.id), 'data-help': `Design ${m.title.toLowerCase()}: ${m.what}` });
    b.innerHTML = homeTileIcon(m.icon);
    b.append(h('h3', { text: m.title }), h('p', { text: m.what }), h('span', { class: 'go', text: 'Start' }));
    box.append(b);
  }
}
function showHome() {
  S.module = null; S.mod = null; S.draft = null;
  $('#home').hidden = false; $('#work').hidden = true; $('#results').hidden = true; $('#top-actions').hidden = true;
  $('#top-module').replaceChildren();
  say('Choose what you want to design.');
}
function openModule(id, quiet) {
  S.module = id; S.mod = S.modules.find(m => m.id === id); S.showMissing = false;
  S.tool = 'select'; S.draft = null; S.sel = null; S.results = null; S.stale = false; S.undo = []; S.redo = [];
  const saved = store.get('cityinfra.v1.' + id);
  if (saved && saved.fc) { S.feats = fromFC(saved.fc); S.settings = saved.settings || {}; S.name = saved.name || 'My design'; }
  else { S.feats = []; S.settings = defaultSettings(id); S.name = 'My design'; }
  $('#home').hidden = true; $('#work').hidden = false; $('#top-actions').hidden = false; $('#results').hidden = true;
  $('#top-module').replaceChildren(h('b', { text: S.mod.title }));
  renderTools(); renderSide(); hint();
  requestAnimationFrame(() => { fit(); });
  if (!store.get('cityinfra.v1.seen-guide')) { store.set('cityinfra.v1.seen-guide', true); setTimeout(openGuide, 50); }
  if (!quiet) say(saved && saved.fc && S.feats.length ? 'Your last drawing was brought back. Press Start fresh for an empty sheet.' : 'Choose a tool and click on the sheet – or press Load example to see a finished one.', true);
}
function defaultSettings(id) {
  if (id === 'water') return { litres_per_person_per_day: 135, ui_sug_lpcd: true };
  if (id === 'drainage') return { return_period: 5, area_type: 'residential', ui_rain_mode: 'example' };
  return {};
}
async function loadExample() {
  try {
    const ex = await api('/api/example/' + S.module);
    edit(() => {
      S.feats = fromFC(ex.features); S.name = ex.name;
      S.settings = Object.assign(defaultSettings(S.module), ex.settings, { ui_storm_set: true });
      delete S.settings.ui_sug_lpcd;
      if (ex.settings.idf === 'example') S.settings.ui_rain_mode = 'example';
      S.sel = null; S.results = null;
    });
    S.stale = false; S.tool = 'select'; renderTools(); renderResults(); fit(); hint();
    say('Example loaded. Press Check my design to see the results. Undo brings back your own drawing.', true);
  } catch (e) { say('The example could not be loaded: ' + e.message, true); }
}
function startFresh() {
  edit(() => { S.feats = []; S.settings = defaultSettings(S.module); S.name = 'My design'; S.sel = null; S.results = null; });
  S.stale = false; renderResults(); fit(); hint();
  say('Empty sheet. Undo brings back what was there.');
}

// ------------------------------------------------------------------ keys and buttons
document.addEventListener('keydown', e => {
  const typing = e.target.matches && e.target.matches('input, select, textarea');
  if (e.key === 'F1') { e.preventDefault(); return openGuide(); }
  if (e.key === 'Escape') {
    if ($('#guide')) return closeGuide();
    if (S.draft) return cancelDraft();
    if (S.tool !== 'select') return setTool('select');
    if (S.sel) return select(null);
    return;
  }
  if (!S.module || typing) return;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); return e.shiftKey ? redo() : undo(); }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') { e.preventDefault(); return redo(); }
  if (e.key === 'Enter' && S.draft && S.draft.type === 'road') return finishRoad(S.draft.pts, false);
  if (e.key === 'Enter' && S.draft && S.draft.type === 'area') return finishArea(dedupe(S.draft.pts));
  if (e.key === 'Backspace' && S.draft && S.draft.pts && S.draft.pts.length) { S.draft.pts.pop(); hint(); return draw(); }
  if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); return removeSelected(); }
});
$('#go-home').onclick = showHome;
$('#btn-help').onclick = openGuide;
$('#btn-example').onclick = loadExample;
$('#btn-clear').onclick = startFresh;
$('#btn-save').onclick = saveFile;
$('#btn-open').onclick = () => $('#file-open').click();
$('#file-open').onchange = e => { const f = e.target.files[0]; if (f) openFile(f); e.target.value = ''; };
$('#btn-check').onclick = runCheck;
$('#zoom-in').onclick = () => zoom(1.4);
$('#zoom-out').onclick = () => zoom(1 / 1.4);
$('#zoom-fit').onclick = fit;
// keep the middle of the drawing in the middle when the sheet changes size (window, results panel)
let lastSize = null;
new ResizeObserver(() => {
  const r = svg.getBoundingClientRect();
  if (lastSize && r.width && lastSize.width) {
    S.view.ox += (lastSize.width - r.width) / 2 / S.view.s;
    S.view.oy -= (lastSize.height - r.height) / 2 / S.view.s;
  }
  lastSize = { width: r.width, height: r.height };
  if (S.module && r.width) draw();
}).observe(svg);

// ------------------------------------------------------------------ start
(async function start() {
  try {
    [S.modules, OPT] = await Promise.all([api('/api/modules'), api('/api/options')]);
  } catch (e) {
    $('#tiles').replaceChildren(h('p', { class: 'errors', text: 'The program’s calculation part is not running. Start it again with the start-app file, then reload this page.' }));
    return;
  }
  renderHome(); showHome();
  window.cityinfra = { S, KINDS, missing, toFC, select };    // for automated tests
})();
})();
