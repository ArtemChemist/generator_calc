'use strict';

const API = {
  presets: () => fetch('/api/presets').then(r => r.json()),
  search: q => fetch(`/api/isotopes/search?q=${encodeURIComponent(q)}`).then(r => r.json()),
  daughters: sym => fetch(`/api/isotopes/${encodeURIComponent(sym)}/daughters`).then(r => r.json()),
  calculate: body => fetch('/api/calculate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(r => r.json()),
};

// ── State ──────────────────────────────────────────────────────────────────
let selectedParent = null;        // { symbol, half_life_s }
let selectedDaughter = null;      // { symbol, half_life_s }
let selectedIntermediates = [];   // [{ symbol, half_life_s }, ...]
let chainSelections = [];         // parallel to chain-step divs; each is null or { symbol, half_life_s }
let searchDebounce = null;
let currentUnit = 'MBq';
let currentTimeUnit  = { label: 'h', secs: 3600 };  // graph x-axis + duration input (parent timescale)
let milkingTimeUnit  = { label: 'h', secs: 3600 };  // milking interval input (daughter timescale)
let lastResult = null;

// ── Time-unit helpers ──────────────────────────────────────────────────────
const TIME_UNITS = [
  { label: 's',         secs: 1 },
  { label: 'min',       secs: 60 },
  { label: 'h',         secs: 3600 },
  { label: 'd',         secs: 86400 },
  { label: 'months',    secs: 30.4375 * 86400 },   // covers ~30–365 d half-lives
  { label: 'y',         secs: 365.25 * 86400 },
  { label: 'decades',   secs: 10 * 365.25 * 86400 },
  { label: 'centuries', secs: 100 * 365.25 * 86400 },
];

// Pick the unit where the half-life is expressed in 1–99 (single or double digits)
function pickTimeUnit(halfLifeS) {
  for (const u of TIME_UNITS) {
    const hl = halfLifeS / u.secs;
    if (hl >= 1 && hl < 100) return u;
  }
  return TIME_UNITS[TIME_UNITS.length - 1];
}

function hToUnit(hours, u) { return hours * 3600 / u.secs; }

function getParentHalfLifeS(data) {
  if (data.metadata.chain_half_lives_h) return data.metadata.chain_half_lives_h[0] * 3600;
  return (data.metadata.parent_half_life_h || 1) * 3600;
}

function getDaughterHalfLifeS(data) {
  if (data.metadata.chain_half_lives_h) {
    const hls = data.metadata.chain_half_lives_h;
    return hls[hls.length - 1] * 3600;
  }
  return (data.metadata.daughter_half_life_h || 1) * 3600;
}

function updateInputTimeUnit(parentHalfLifeS, daughterHalfLifeS) {
  const nextGraph = pickTimeUnit(parentHalfLifeS);
  const nextMilk  = pickTimeUnit(daughterHalfLifeS);

  if (currentTimeUnit.secs !== nextGraph.secs) {
    const el = document.getElementById('duration');
    if (el.value) {
      const hours = parseFloat(el.value) * currentTimeUnit.secs / 3600;
      el.value = parseFloat((hours * 3600 / nextGraph.secs).toPrecision(4));
    }
    currentTimeUnit = nextGraph;
    document.getElementById('duration-unit-lbl').textContent = nextGraph.label;
  }

  if (milkingTimeUnit.secs !== nextMilk.secs) {
    const el = document.getElementById('milking-interval');
    if (el.value) {
      const hours = parseFloat(el.value) * milkingTimeUnit.secs / 3600;
      el.value = parseFloat((hours * 3600 / nextMilk.secs).toPrecision(4));
    }
    milkingTimeUnit = nextMilk;
    document.getElementById('interval-unit-lbl').textContent = nextMilk.label;
  }
}

const MBQ_PER_MCI = 37;

function toMBq(v)   { return currentUnit === 'mCi' ? v * MBQ_PER_MCI : v; }
function fromMBq(v) { return currentUnit === 'mCi' ? v / MBQ_PER_MCI : v; }
function unitLabel() { return currentUnit; }

// ── DOM refs ───────────────────────────────────────────────────────────────
const presetSelect    = document.getElementById('preset-select');
const presetSection   = document.getElementById('preset-section');
const presetMeta      = document.getElementById('preset-meta');
const customSection   = document.getElementById('custom-section');
const customMeta      = document.getElementById('custom-meta');
const parentSearch    = document.getElementById('parent-search');
const parentResults   = document.getElementById('parent-results');
const chainStepsEl    = document.getElementById('chain-steps');
const addStepBtn      = document.getElementById('add-step-btn');
const calcBtn             = document.getElementById('calculate-btn');
const errorMsg            = document.getElementById('error-msg');
const inferredInfo        = document.getElementById('inferred-info');
const chartDiv            = document.getElementById('chart');
const chartPlaceholder    = document.getElementById('chart-placeholder');
const cumulativeDiv       = document.getElementById('cumulative-chart');
const cumulativePlaceholder = document.getElementById('cumulative-placeholder');
const tableContainer      = document.getElementById('table-container');
const tableBody           = document.querySelector('#milking-table tbody');

// ── Init ───────────────────────────────────────────────────────────────────
async function initPage() {
  currentUnit = document.querySelector('input[name="unit"]:checked')?.value || 'MBq';
  document.querySelectorAll('.unit-lbl').forEach(el => el.textContent = currentUnit);

  const presets = await API.presets();
  presets.forEach(p => {
    const opt = document.createElement('option');
    opt.value = JSON.stringify(p);
    opt.textContent = p.display_name;
    presetSelect.appendChild(opt);
  });
  if (presets.length) onPresetChange();

  document.querySelectorAll('.tab-btn').forEach(b =>
    b.addEventListener('click', () => switchTab(b.dataset.tab))
  );
  document.querySelectorAll('input[name="mode"]').forEach(r =>
    r.addEventListener('change', onModeChange)
  );
  document.querySelectorAll('input[name="unit"]').forEach(r =>
    r.addEventListener('change', onUnitChange)
  );
  presetSelect.addEventListener('change', onPresetChange);
  parentSearch.addEventListener('input', onParentInput);
  addStepBtn.addEventListener('click', onAddStep);
  calcBtn.addEventListener('click', onCalculate);
  document.addEventListener('click', e => {
    if (!e.target.closest('#parent-search-wrapper')) hideResults();
  });
}

// ── Mode toggle ────────────────────────────────────────────────────────────
function onModeChange() {
  const mode = document.querySelector('input[name="mode"]:checked').value;
  if (mode === 'preset') {
    presetSection.classList.remove('hidden');
    customSection.classList.add('hidden');
    onPresetChange();
  } else {
    presetSection.classList.add('hidden');
    customSection.classList.remove('hidden');
    selectedParent = null;
    selectedDaughter = null;
    selectedIntermediates = [];
    chainSelections = [];
    chainStepsEl.innerHTML = '';
    addStepBtn.classList.add('hidden');
    customMeta.classList.add('hidden');
    parentSearch.value = '';
  }
}

// ── Tab switching ──────────────────────────────────────────────────────────
function switchTab(tabId) {
  document.querySelectorAll('.tab-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.tab === tabId)
  );
  document.querySelectorAll('.tab-panel').forEach(p =>
    p.classList.toggle('hidden', p.id !== `tab-${tabId}`)
  );
  if (tabId === 'events' && lastResult) {
    renderCumulativeChart(lastResult.milking_events, lastResult._minYieldDisplay, lastResult._genYield);
  }
  if (tabId === 'chart' && lastResult) {
    Plotly.Plots.resize('chart');
  }
}

// ── Unit toggle ────────────────────────────────────────────────────────────
function onUnitChange() {
  currentUnit = document.querySelector('input[name="unit"]:checked').value;
  document.querySelectorAll('.unit-lbl').forEach(el => el.textContent = currentUnit);
  if (lastResult) {
    renderChart(lastResult);
    renderTable(lastResult.milking_events, lastResult._minYieldDisplay, lastResult._genYield);
    renderCumulativeChart(lastResult.milking_events, lastResult._minYieldDisplay, lastResult._genYield);
  }
}

// ── Preset ─────────────────────────────────────────────────────────────────
function onPresetChange() {
  const p = JSON.parse(presetSelect.value);
  selectedParent        = { symbol: p.parent_symbol,   half_life_s: p.parent_half_life_s };
  selectedDaughter      = { symbol: p.daughter_symbol, half_life_s: p.daughter_half_life_s, branching_ratio: 1 };
  selectedIntermediates = (p.intermediate_symbols || []).map((sym, i) => ({
    symbol: sym,
    half_life_s: (p.intermediate_half_lives_s || [])[i] ?? null,
  }));

  let metaHtml = formatMeta(p.parent_symbol, p.parent_half_life_s, p.daughter_symbol, p.daughter_half_life_s);
  if (selectedIntermediates.length) {
    const viaLabels = selectedIntermediates.map(m =>
      `<strong>${m.symbol}</strong> t<sub>½</sub> = ${formatHalfLife(m.half_life_s)}`
    ).join(', ');
    metaHtml += `<br><span class="chain-via">via ${viaLabels}</span>`;
  }
  presetMeta.innerHTML = metaHtml;
  presetMeta.classList.remove('hidden');
  updateInputTimeUnit(p.parent_half_life_s, p.daughter_half_life_s);
}

// ── Custom parent search ───────────────────────────────────────────────────
function onParentInput() {
  clearTimeout(searchDebounce);
  const q = parentSearch.value.trim();
  if (q.length < 1) { hideResults(); return; }
  searchDebounce = setTimeout(async () => {
    const results = await API.search(q);
    showResults(results);
  }, 300);
}

function showResults(items) {
  parentResults.innerHTML = '';
  if (!items.length) { hideResults(); return; }
  items.forEach(item => {
    const li = document.createElement('li');
    li.textContent = `${item.symbol} — ${formatHalfLife(item.half_life_s)}`;
    li.dataset.symbol = item.symbol;
    li.dataset.hl = item.half_life_s;
    li.addEventListener('click', () => selectParent(item));
    parentResults.appendChild(li);
  });
  parentResults.classList.remove('hidden');
}

function hideResults() {
  parentResults.classList.add('hidden');
}

function selectParent(item) {
  parentSearch.value = item.symbol;
  selectedParent = { symbol: item.symbol, half_life_s: item.half_life_s };
  hideResults();
  selectedDaughter = null;
  selectedIntermediates = [];
  chainSelections = [];
  addStepBtn.classList.add('hidden');
  customMeta.classList.add('hidden');
  buildStep(0, item.symbol);

  // Update duration unit immediately based on parent's timescale;
  // milking unit will be updated once a daughter is selected.
  const nextGraph = pickTimeUnit(item.half_life_s);
  if (currentTimeUnit.secs !== nextGraph.secs) {
    const el = document.getElementById('duration');
    if (el.value) {
      const hours = parseFloat(el.value) * currentTimeUnit.secs / 3600;
      el.value = parseFloat((hours * 3600 / nextGraph.secs).toPrecision(4));
    }
    currentTimeUnit = nextGraph;
    document.getElementById('duration-unit-lbl').textContent = nextGraph.label;
  }
}

// ── Chain builder ──────────────────────────────────────────────────────────
function buildStep(stepIndex, parentSym) {
  // Remove any steps at or after this index
  const existing = chainStepsEl.querySelectorAll('.chain-step');
  existing.forEach((el, i) => { if (i >= stepIndex) el.remove(); });
  chainSelections = chainSelections.slice(0, stepIndex);

  const stepDiv = document.createElement('div');
  stepDiv.className = 'chain-step';

  const header = document.createElement('div');
  header.className = 'chain-step-header';

  const lbl = document.createElement('label');
  lbl.textContent = `Daughter of ${parentSym}`;
  lbl.htmlFor = `step-select-${stepIndex}`;
  header.appendChild(lbl);

  if (stepIndex > 0) {
    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'chain-remove-btn';
    removeBtn.textContent = '✕ Remove';
    removeBtn.addEventListener('click', () => removeStepsFrom(stepIndex));
    header.appendChild(removeBtn);
  }

  stepDiv.appendChild(header);

  const sel = document.createElement('select');
  sel.id = `step-select-${stepIndex}`;
  sel.disabled = true;
  sel.innerHTML = '<option value="">Loading…</option>';
  sel.addEventListener('change', () => onStepChange(stepIndex, sel));
  stepDiv.appendChild(sel);

  chainStepsEl.appendChild(stepDiv);
  addStepBtn.classList.add('hidden');

  API.daughters(parentSym).then(daughters => {
    sel.innerHTML = '';
    if (!daughters.length) {
      sel.innerHTML = '<option value="">No daughters found</option>';
      return;
    }
    const blank = document.createElement('option');
    blank.value = '';
    blank.textContent = '— select daughter —';
    sel.appendChild(blank);
    daughters.forEach(d => {
      const opt = document.createElement('option');
      opt.value = JSON.stringify(d);
      opt.textContent = `${d.daughter_symbol} (${(d.branching_ratio * 100).toFixed(1)}% — ${d.mode})`;
      sel.appendChild(opt);
    });
    sel.disabled = false;
  });
}

function onStepChange(stepIndex, sel) {
  removeStepsFrom(stepIndex + 1);

  if (!sel.value) {
    chainSelections[stepIndex] = null;
    updateChainState();
    return;
  }

  const d = JSON.parse(sel.value);
  chainSelections[stepIndex] = { symbol: d.daughter_symbol, half_life_s: d.daughter_half_life_s };
  updateChainState();
}

function removeStepsFrom(fromIndex) {
  const steps = chainStepsEl.querySelectorAll('.chain-step');
  steps.forEach((el, i) => { if (i >= fromIndex) el.remove(); });
  chainSelections = chainSelections.slice(0, fromIndex);
  updateChainState();
}

function updateChainState() {
  const valid = chainSelections.filter(Boolean);
  if (valid.length === 0) {
    selectedDaughter = null;
    selectedIntermediates = [];
  } else {
    selectedDaughter = valid[valid.length - 1];
    selectedIntermediates = valid.slice(0, -1);
    if (selectedParent && selectedDaughter.half_life_s)
      updateInputTimeUnit(selectedParent.half_life_s, selectedDaughter.half_life_s);
  }
  // Show "Add step" only when the last step has a valid selection
  const lastValid = chainSelections.length > 0 && chainSelections[chainSelections.length - 1] != null;
  addStepBtn.classList.toggle('hidden', !lastValid);
  updateChainMeta();
}

function onAddStep() {
  if (!selectedDaughter) return;
  const nextIndex = chainSelections.length;
  buildStep(nextIndex, selectedDaughter.symbol);
}

function updateChainMeta() {
  if (!selectedParent || !selectedDaughter) {
    customMeta.classList.add('hidden');
    return;
  }
  const chain = [selectedParent, ...selectedIntermediates, selectedDaughter];
  const html = chain.map((item, i) => {
    const role = i === 0 ? 'parent' : i === chain.length - 1 ? 'daughter' : 'intermediate';
    return `<strong>${item.symbol}</strong> t<sub>½</sub> = ${formatHalfLife(item.half_life_s)} <span class="chain-role">(${role})</span>`;
  }).join('<span class="chain-arrow">↓</span>');
  customMeta.innerHTML = html;
  customMeta.classList.remove('hidden');
}

// ── Calculate ─────────────────────────────────────────────────────────────
async function onCalculate() {
  clearError();
  inferredInfo.classList.add('hidden');
  if (!selectedParent || !selectedDaughter) {
    showError('Please select a generator pair.'); return;
  }
  const initAct  = parseFloat(document.getElementById('initial-activity').value);
  const intervalRaw = parseFloat(document.getElementById('milking-interval').value);
  const durationRaw = document.getElementById('duration').value.trim();
  const minYieldRaw = document.getElementById('min-yield').value.trim();
  const durationParsed = durationRaw !== '' ? parseFloat(durationRaw) : null;
  const minYield = minYieldRaw !== '' ? parseFloat(minYieldRaw) : null;
  const genYieldPct = parseFloat(document.getElementById('gen-yield').value) || 100;
  const genYield = Math.min(Math.max(genYieldPct, 0), 100) / 100;

  // Milking interval is in daughter's timescale; duration is in parent's timescale
  const interval_h = intervalRaw * milkingTimeUnit.secs / 3600;
  const duration_h = durationParsed !== null ? durationParsed * currentTimeUnit.secs / 3600 : null;

  if (!initAct || initAct <= 0) { showError('Initial activity must be > 0.'); return; }
  if (!intervalRaw || intervalRaw <= 0) { showError(`Milking interval must be > 0 ${milkingTimeUnit.label}.`); return; }
  if (genYield <= 0) { showError('Generator yield must be > 0%.'); return; }
  if (duration_h === null && !minYield) {
    showError('Provide duration, min yield threshold, or both.'); return;
  }

  calcBtn.disabled = true;
  calcBtn.textContent = 'Calculating…';

  const body = {
    parent_symbol: selectedParent.symbol,
    daughter_symbol: selectedDaughter.symbol,
    intermediate_symbols: selectedIntermediates.map(m => m.symbol),
    initial_activity_MBq: toMBq(initAct),
    milking_interval_h: interval_h,
  };
  if (duration_h !== null) body.duration_h = duration_h;
  // Send threshold as theoretical equivalent so backend infers duration on practical yield
  if (minYield !== null) body.min_yield_MBq = toMBq(minYield) / genYield;

  const data = await API.calculate(body);

  calcBtn.disabled = false;
  calcBtn.textContent = 'Calculate';

  if (data.error) { showError(data.error); return; }

  lastResult = data;
  lastResult._genYield = genYield;
  lastResult._minYieldDisplay = minYield ? toMBq(minYield) : 0; // practical threshold in MBq

  // Confirm time units from API response (should match selection-time units)
  currentTimeUnit = pickTimeUnit(getParentHalfLifeS(data));
  milkingTimeUnit  = pickTimeUnit(getDaughterHalfLifeS(data));
  document.getElementById('duration-unit-lbl').textContent = currentTimeUnit.label;
  document.getElementById('interval-unit-lbl').textContent = milkingTimeUnit.label;

  if (data.inferred_duration_h !== null) {
    const t = hToUnit(data.inferred_duration_h, currentTimeUnit);
    inferredInfo.textContent = `Inferred duration: ${t.toFixed(2)} ${currentTimeUnit.label} — yield drops below threshold at this point.`;
    inferredInfo.classList.remove('hidden');
  }

  renderChart(data);
  renderTable(data.milking_events, data._minYieldDisplay, genYield);
  renderCumulativeChart(data.milking_events, data._minYieldDisplay, genYield);
}

// ── Chart ─────────────────────────────────────────────────────────────────
function renderChart(data) {
  chartPlaceholder.classList.add('hidden');
  chartDiv.classList.remove('hidden');

  const tu = currentTimeUnit;
  const tlabel = tu.label;

  // Build daughter trace with explicit drops to 0 at milking times
  const tDaughter = [];
  const aDaughter = [];
  const milkTimesConverted = new Set(data.milking_events.map(e => hToUnit(e.time_h, tu)));

  data.time_points_h.forEach((h, i) => {
    const t = hToUnit(h, tu);
    tDaughter.push(t);
    aDaughter.push(data.daughter_activity_MBq[i]);
    if (milkTimesConverted.has(t) && i < data.time_points_h.length - 1) {
      tDaughter.push(t);
      aDaughter.push(0);
    }
  });

  const timeArr = data.time_points_h.map(h => hToUnit(h, tu));

  const ul = unitLabel();
  const parentY = data.parent_activity_MBq.map(fromMBq);
  const daughterY = aDaughter.map(fromMBq);

  const intermediateColors = ['#8e44ad', '#6c3483', '#5b2c6f'];
  const chainSymbols = data.metadata.chain_symbols || [data.metadata.parent_symbol, data.metadata.daughter_symbol];

  const traces = [
    {
      x: timeArr,
      y: parentY,
      name: `${chainSymbols[0]} (parent)`,
      mode: 'lines',
      line: { color: '#2a5cbf', width: 2 },
      hovertemplate: `<b>%{x:.2f} ${tlabel}</b><br>%{y:.2f} ${ul}<extra>${chainSymbols[0]}</extra>`,
    },
  ];

  // Intermediate traces — no drops at milking (intermediates stay in column)
  if (data.intermediate_activities_MBq) {
    data.intermediate_activities_MBq.forEach((actArr, i) => {
      const sym = chainSymbols[1 + i] || `Intermediate ${i + 1}`;
      traces.push({
        x: timeArr,
        y: actArr.map(fromMBq),
        name: `${sym} (intermediate)`,
        mode: 'lines',
        line: { color: intermediateColors[i % intermediateColors.length], width: 2 },
        hovertemplate: `<b>%{x:.2f} ${tlabel}</b><br>%{y:.2f} ${ul}<extra>${sym}</extra>`,
      });
    });
  }

  traces.push({
    x: tDaughter,
    y: daughterY,
    name: `${chainSymbols[chainSymbols.length - 1]} (daughter)`,
    mode: 'lines',
    line: { color: '#e67e22', width: 2 },
    hovertemplate: `<b>%{x:.2f} ${tlabel}</b><br>%{y:.2f} ${ul}<extra>${chainSymbols[chainSymbols.length - 1]}</extra>`,
  });

  const shapes = data.milking_events.map(e => ({
    type: 'line', xref: 'x', yref: 'paper',
    x0: hToUnit(e.time_h, tu), x1: hToUnit(e.time_h, tu), y0: 0, y1: 1,
    line: { color: '#aab0c0', width: 1, dash: 'dot' },
  }));

  if (data.min_yield_MBq > 0) {
    const thresholdVal = fromMBq(data.min_yield_MBq);
    traces.push({
      x: [timeArr[0], timeArr[timeArr.length - 1]],
      y: [thresholdVal, thresholdVal],
      name: 'Min yield threshold',
      mode: 'lines',
      line: { color: '#c0392b', width: 1.5, dash: 'dash' },
      hoverinfo: 'skip',
    });
  }

  const layout = {
    margin: { t: 20, r: 40, b: 50, l: 80 },
    xaxis: { title: `Time (${tlabel})`, gridcolor: '#eef0f4' },
    yaxis: {
      title: `Activity (${ul})`,
      gridcolor: '#eef0f4',
    },
    legend: { x: 0.01, y: 0.99, bgcolor: 'rgba(255,255,255,0.8)', bordercolor: '#dde1e9', borderwidth: 1 },
    plot_bgcolor: '#fff',
    paper_bgcolor: '#fff',
    shapes,
  };

  Plotly.newPlot('chart', traces, layout, { responsive: true, displayModeBar: false });
}

// ── Table ──────────────────────────────────────────────────────────────────
function renderTable(events, minYieldMBq, genYield = 1) {
  const tu = currentTimeUnit;
  document.getElementById('time-col-header').textContent = `Time (${tu.label})`;
  tableBody.innerHTML = '';
  let runningMBq = 0;
  events.forEach(e => {
    const practicalMBq = e.yield_MBq * genYield;
    runningMBq += practicalMBq;
    const timeDisplay       = hToUnit(e.time_h, tu).toLocaleString(undefined, { maximumFractionDigits: 2 });
    const yieldDisplay      = fromMBq(practicalMBq).toLocaleString(undefined, { maximumFractionDigits: 2 });
    const cumulativeDisplay = fromMBq(runningMBq).toLocaleString(undefined,   { maximumFractionDigits: 2 });
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${timeDisplay}</td>
      <td>${yieldDisplay}</td>
      <td>${cumulativeDisplay}</td>
    `;
    tableBody.appendChild(tr);
  });
  tableContainer.classList.remove('hidden');
}

// ── Cumulative chart ───────────────────────────────────────────────────────
function renderCumulativeChart(events, minYieldMBq, genYield = 1) {
  if (!events.length) return;
  cumulativePlaceholder.classList.add('hidden');
  cumulativeDiv.classList.remove('hidden');

  const ul = unitLabel();
  const tu = currentTimeUnit;
  const x = [];
  const y = [];
  let running = 0;
  events.forEach(e => {
    running += fromMBq(e.yield_MBq * genYield);
    x.push(hToUnit(e.time_h, tu));
    y.push(running);
  });

  const traces = [{
    x,
    y,
    type: 'bar',
    marker: { color: '#27ae60', opacity: 0.85 },
    name: `Cumulative yield (${ul})`,
    hovertemplate: `<b>%{x:.2f} ${tu.label}</b><br>%{y:.2f} ${ul}<extra></extra>`,
  }];

  const layout = {
    margin: { t: 20, r: 40, b: 50, l: 80 },
    xaxis: { title: `Time (${tu.label})`, gridcolor: '#eef0f4' },
    yaxis: { title: `Cumulative yield (${ul})`, gridcolor: '#eef0f4' },
    plot_bgcolor: '#fff',
    paper_bgcolor: '#fff',
    showlegend: false,
  };

  Plotly.newPlot('cumulative-chart', traces, layout, { responsive: true, displayModeBar: false });
}

// ── Helpers ────────────────────────────────────────────────────────────────
function formatHalfLife(s) {
  if (s >= 1e29) return 'stable';
  if (s >= 86400 * 365) return `${(s / 86400 / 365.25).toFixed(1)} y`;
  if (s >= 86400) return `${(s / 86400).toFixed(2)} d`;
  if (s >= 3600) return `${(s / 3600).toFixed(2)} h`;
  if (s >= 60) return `${(s / 60).toFixed(2)} min`;
  return `${s.toFixed(2)} s`;
}

function formatMeta(pSym, pHl, dSym, dHl, br, mode) {
  let html = `<strong>${pSym}</strong> t<sub>½</sub> = ${formatHalfLife(pHl)}<br>`;
  html += `<strong>${dSym}</strong> t<sub>½</sub> = ${formatHalfLife(dHl)}`;
  if (br !== undefined) html += `<br>Branching: ${(br * 100).toFixed(1)}% (${mode})`;
  return html;
}

function showError(msg) {
  errorMsg.textContent = msg;
  errorMsg.classList.remove('hidden');
}

function clearError() {
  errorMsg.classList.add('hidden');
}

// ── Boot ───────────────────────────────────────────────────────────────────
initPage();
