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
let selectedParent = null;    // { symbol, half_life_s }
let selectedDaughter = null;  // { symbol, half_life_s, branching_ratio }
let searchDebounce = null;

// ── DOM refs ───────────────────────────────────────────────────────────────
const presetSelect    = document.getElementById('preset-select');
const presetSection   = document.getElementById('preset-section');
const presetMeta      = document.getElementById('preset-meta');
const customSection   = document.getElementById('custom-section');
const customMeta      = document.getElementById('custom-meta');
const parentSearch    = document.getElementById('parent-search');
const parentResults   = document.getElementById('parent-results');
const daughterSelect  = document.getElementById('daughter-select');
const calcBtn         = document.getElementById('calculate-btn');
const errorMsg        = document.getElementById('error-msg');
const inferredInfo    = document.getElementById('inferred-info');
const chartDiv        = document.getElementById('chart');
const chartPlaceholder = document.getElementById('chart-placeholder');
const tableContainer  = document.getElementById('table-container');
const tableBody       = document.querySelector('#milking-table tbody');

// ── Init ───────────────────────────────────────────────────────────────────
async function initPage() {
  const presets = await API.presets();
  presets.forEach(p => {
    const opt = document.createElement('option');
    opt.value = JSON.stringify(p);
    opt.textContent = p.display_name;
    presetSelect.appendChild(opt);
  });
  if (presets.length) onPresetChange();

  document.querySelectorAll('input[name="mode"]').forEach(r =>
    r.addEventListener('change', onModeChange)
  );
  presetSelect.addEventListener('change', onPresetChange);
  parentSearch.addEventListener('input', onParentInput);
  daughterSelect.addEventListener('change', onDaughterChange);
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
  }
}

// ── Preset ─────────────────────────────────────────────────────────────────
function onPresetChange() {
  const p = JSON.parse(presetSelect.value);
  selectedParent   = { symbol: p.parent_symbol,   half_life_s: p.parent_half_life_s };
  selectedDaughter = { symbol: p.daughter_symbol, half_life_s: p.daughter_half_life_s, branching_ratio: 1 };
  presetMeta.innerHTML = formatMeta(p.parent_symbol, p.parent_half_life_s, p.daughter_symbol, p.daughter_half_life_s);
  presetMeta.classList.remove('hidden');
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

async function selectParent(item) {
  parentSearch.value = item.symbol;
  selectedParent = { symbol: item.symbol, half_life_s: item.half_life_s };
  hideResults();

  daughterSelect.innerHTML = '<option value="">Loading…</option>';
  daughterSelect.disabled = true;
  customMeta.classList.add('hidden');
  selectedDaughter = null;

  const daughters = await API.daughters(item.symbol);
  daughterSelect.innerHTML = '';
  if (!daughters.length) {
    daughterSelect.innerHTML = '<option value="">No decay daughters found</option>';
    return;
  }
  daughters.forEach(d => {
    const opt = document.createElement('option');
    opt.value = JSON.stringify(d);
    opt.textContent = `${d.daughter_symbol} (${(d.branching_ratio * 100).toFixed(1)}% — ${d.mode})`;
    daughterSelect.appendChild(opt);
  });
  daughterSelect.disabled = false;
  if (daughters.length === 1) {
    daughterSelect.selectedIndex = 0;
    onDaughterChange();
  } else {
    const blank = document.createElement('option');
    blank.value = '';
    blank.textContent = '— select daughter —';
    daughterSelect.prepend(blank);
    daughterSelect.selectedIndex = 0;
  }
}

function onDaughterChange() {
  if (!daughterSelect.value) { selectedDaughter = null; customMeta.classList.add('hidden'); return; }
  const d = JSON.parse(daughterSelect.value);
  selectedDaughter = { symbol: d.daughter_symbol, half_life_s: d.daughter_half_life_s, branching_ratio: d.branching_ratio };
  customMeta.innerHTML = formatMeta(
    selectedParent.symbol, selectedParent.half_life_s,
    d.daughter_symbol, d.daughter_half_life_s,
    d.branching_ratio, d.mode
  );
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
  const interval = parseFloat(document.getElementById('milking-interval').value);
  const durationRaw = document.getElementById('duration').value.trim();
  const minYieldRaw = document.getElementById('min-yield').value.trim();
  const duration = durationRaw !== '' ? parseFloat(durationRaw) : null;
  const minYield = minYieldRaw !== '' ? parseFloat(minYieldRaw) : null;

  if (!initAct || initAct <= 0) { showError('Initial activity must be > 0.'); return; }
  if (!interval || interval <= 0) { showError('Milking interval must be > 0.'); return; }
  if (duration === null && !minYield) {
    showError('Provide duration, min yield threshold, or both.'); return;
  }

  calcBtn.disabled = true;
  calcBtn.textContent = 'Calculating…';

  const body = {
    parent_symbol: selectedParent.symbol,
    daughter_symbol: selectedDaughter.symbol,
    initial_activity_MBq: initAct,
    milking_interval_h: interval,
  };
  if (duration !== null) body.duration_h = duration;
  if (minYield !== null) body.min_yield_MBq = minYield;

  const data = await API.calculate(body);

  calcBtn.disabled = false;
  calcBtn.textContent = 'Calculate';

  if (data.error) { showError(data.error); return; }

  if (data.inferred_duration_h !== null) {
    inferredInfo.textContent = `Inferred duration: ${data.inferred_duration_h.toFixed(1)} h — yield drops below threshold at this point.`;
    inferredInfo.classList.remove('hidden');
  }

  renderChart(data);
  renderTable(data.milking_events, data.min_yield_MBq);
}

// ── Chart ─────────────────────────────────────────────────────────────────
function renderChart(data) {
  chartPlaceholder.classList.add('hidden');
  chartDiv.classList.remove('hidden');

  // Build daughter trace with explicit drops to 0 at milking times
  const tDaughter = [];
  const aDaughter = [];
  const milkTimes = new Set(data.milking_events.map(e => e.time_h));

  data.time_points_h.forEach((t, i) => {
    tDaughter.push(t);
    aDaughter.push(data.daughter_activity_MBq[i]);
    if (milkTimes.has(t) && i < data.time_points_h.length - 1) {
      tDaughter.push(t);
      aDaughter.push(0);
    }
  });

  const traces = [
    {
      x: data.time_points_h,
      y: data.parent_activity_MBq,
      name: `${data.metadata.parent_symbol} (parent)`,
      mode: 'lines',
      line: { color: '#2a5cbf', width: 2 },
      yaxis: 'y1',
      hovertemplate: '<b>%{x:.2f} h</b><br>%{y:.1f} MBq<extra>' + data.metadata.parent_symbol + '</extra>',
    },
    {
      x: tDaughter,
      y: aDaughter,
      name: `${data.metadata.daughter_symbol} (daughter)`,
      mode: 'lines',
      line: { color: '#e67e22', width: 2 },
      yaxis: 'y2',
      hovertemplate: '<b>%{x:.2f} h</b><br>%{y:.1f} MBq<extra>' + data.metadata.daughter_symbol + '</extra>',
    },
  ];

  const shapes = data.milking_events.map(e => ({
    type: 'line', xref: 'x', yref: 'paper',
    x0: e.time_h, x1: e.time_h, y0: 0, y1: 1,
    line: { color: '#aab0c0', width: 1, dash: 'dot' },
  }));

  if (data.min_yield_MBq > 0) {
    traces.push({
      x: [data.time_points_h[0], data.time_points_h[data.time_points_h.length - 1]],
      y: [data.min_yield_MBq, data.min_yield_MBq],
      name: 'Min yield threshold',
      mode: 'lines',
      line: { color: '#c0392b', width: 1.5, dash: 'dash' },
      yaxis: 'y2',
      hoverinfo: 'skip',
    });
  }

  const layout = {
    margin: { t: 20, r: 80, b: 50, l: 80 },
    xaxis: { title: 'Time (h)', gridcolor: '#eef0f4' },
    yaxis: {
      title: `${data.metadata.parent_symbol} activity (MBq)`,
      titlefont: { color: '#2a5cbf' },
      tickfont: { color: '#2a5cbf' },
      gridcolor: '#eef0f4',
    },
    yaxis2: {
      title: `${data.metadata.daughter_symbol} activity (MBq)`,
      titlefont: { color: '#e67e22' },
      tickfont: { color: '#e67e22' },
      overlaying: 'y',
      side: 'right',
      gridcolor: 'transparent',
    },
    legend: { x: 0.01, y: 0.99, bgcolor: 'rgba(255,255,255,0.8)', bordercolor: '#dde1e9', borderwidth: 1 },
    plot_bgcolor: '#fff',
    paper_bgcolor: '#fff',
    shapes,
  };

  Plotly.newPlot('chart', traces, layout, { responsive: true, displayModeBar: false });
}

// ── Table ──────────────────────────────────────────────────────────────────
function renderTable(events, minYield) {
  tableBody.innerHTML = '';
  events.forEach(e => {
    const tr = document.createElement('tr');
    let vsCell;
    if (minYield > 0) {
      vsCell = e.yield_MBq >= minYield
        ? '<td class="above">✓ Above</td>'
        : '<td class="below">✗ Below</td>';
    } else {
      vsCell = '<td class="no-threshold">—</td>';
    }
    tr.innerHTML = `
      <td>${e.time_h.toFixed(1)}</td>
      <td>${e.yield_MBq.toLocaleString(undefined, {maximumFractionDigits: 1})}</td>
      ${vsCell}
    `;
    tableBody.appendChild(tr);
  });
  tableContainer.classList.remove('hidden');
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
