const PAGE_SIZE = 25;
const POLL_INTERVAL = 3000;

const form = document.getElementById('scan-form');
const startButton = document.getElementById('scan-start');
const statusBox = document.getElementById('scan-status');
const errorBox = document.getElementById('scan-error');
const rowsBody = document.getElementById('scan-rows');
const table = document.getElementById('scan-table');
const selectAll = document.getElementById('select-all');
const onlyTradable = document.getElementById('only-tradable');
const bulkForm = document.getElementById('scan-bulk-form');
const addButton = document.getElementById('add-selected');

let scanId = null;
let scanParams = {};
let candidates = [];
let pollTimer = null;
const selected = new Set();

const sorter = SMT.sortControl(table, {key: 'return_on_capital_pct', direction: 'descending', onChange: render});
const pages = SMT.pager(document.getElementById('scan-pager'), {pageSize: PAGE_SIZE, onChange: render});

function numeric(row, key) {
  const value = row[key];
  return value == null || value === '' ? null : Number(value);
}

function sortValue(row) {
  if (sorter.key === 'name') return row.name;
  return numeric(row, sorter.key);
}

function visible() {
  return onlyTradable.checked ? candidates.filter(c => c.tradable) : candidates;
}

function listingUrl(row) {
  return 'https://steamcommunity.com/market/listings/' + row.app_id + '/' + encodeURIComponent(row.market_hash_name);
}

function money(value) {
  return value == null || value === '' ? '-' : SMT.escapeHtml(value);
}

function buildRow(row, index) {
  const hash = row.market_hash_name;
  const checked = selected.has(hash) ? ' checked' : '';
  const state = row.tradable ? 'state-positive' : 'state-negative';
  const note = row.note ? ' title="' + SMT.escapeHtml(row.note) + '"' : '';

  return (
    '<tr class="pool-row ' + state + '" data-hash="' + SMT.escapeHtml(hash) + '"' + note +
    ' tabindex="0" role="button" aria-expanded="false" aria-controls="scan-details-' + index + '">' +
    '<td><label class="checkbox-label"><input type="checkbox" class="row-checkbox" value="' +
    SMT.escapeHtml(hash) + '"' + checked + '/><span class="checkbox-custom"></span></label></td>' +
    '<td>' + (row.icon_url ? '<img src="' + SMT.escapeHtml(row.icon_url) + '" alt="" width="32">' : '') + '</td>' +
    '<td><a href="' + listingUrl(row) + '" target="_blank" rel="noopener" class="item-link">' +
    SMT.escapeHtml(row.name) + '</a></td>' +
    '<td>' + money(row.current_price) + '</td>' +
    '<td>' + money(row.buy_target) + '</td>' +
    '<td>' + money(row.sell_target) + '</td>' +
    '<td>' + money(row.profit_per_trade) + '</td>' +
    '<td>' + row.round_trips + '</td>' +
    '<td>' + (row.queue_ahead == null ? '-' : row.queue_ahead) + '</td>' +
    '<td>' + money(row.days_to_clear) + '</td>' +
    '<td>' + row.feasible_round_trips + '</td>' +
    '<td>' + money(row.median_hold_hours) + '</td>' +
    '<td>' + money(row.return_on_capital_pct) + '</td>' +
    '<td>' + row.volume_30d + '</td>' +
    '<td class="chevron-cell" title="Show price history and order book">' +
    '<span class="row-chevron" aria-hidden="true"></span></td></tr>' +
    '<tr class="details-row" id="scan-details-' + index + '" data-details-for="' + SMT.escapeHtml(hash) +
    '" hidden><td colspan="15"><div class="details-panel"></div></td></tr>'
  );
}

function render() {
  const shown = visible();
  pages.update(shown.length);
  const ordered = sorter.sort(shown, sortValue);
  const page = ordered.slice(pages.offset, pages.offset + pages.pageSize);

  if (page.length === 0) {
    rowsBody.innerHTML = '<tr><td colspan="15" class="empty">' +
      (candidates.length === 0 ? 'No scan yet. Set the band above and start one.'
        : 'Nothing here. Untick the filter to see the items that were measured and rejected.') +
      '</td></tr>';
  } else {
    rowsBody.innerHTML = page.map(buildRow).join('');
  }

  selectAll.checked = page.length > 0 && page.every(row => selected.has(row.market_hash_name));
  addButton.disabled = selected.size === 0;
  addButton.textContent = selected.size ? 'Add ' + selected.size + ' to pool' : 'Add selected to pool';
}

function applyState(state) {
  scanId = state.id;
  scanParams = state.params || {};
  candidates = state.candidates || [];

  statusBox.hidden = false;
  document.getElementById('scan-state').textContent = state.status;
  document.getElementById('scan-collected').textContent = state.collected;
  document.getElementById('scan-measured').textContent = state.measured;
  document.getElementById('scan-tradable').textContent = candidates.filter(c => c.tradable).length;
  document.getElementById('scan-when').textContent = state.finished_at
    ? 'Finished ' + new Date(state.finished_at).toLocaleString()
    : '';

  errorBox.hidden = !state.error;
  errorBox.textContent = state.error || '';

  const running = state.status === 'running';
  startButton.disabled = running;
  startButton.textContent = running ? 'Scanning…' : 'Start scan';

  render();
  return running;
}

async function poll() {
  try {
    const state = await SMT.get('/api/v1/scan/latest');
    if (applyState(state)) return;
  } catch (e) {
    if (!String(e.message).includes('No scan')) SMT.notify('Could not read the scan: ' + e.message, 'error');
  }
  clearInterval(pollTimer);
  pollTimer = null;
}

function watch() {
  if (pollTimer) return;
  pollTimer = setInterval(poll, POLL_INTERVAL);
}

form.addEventListener('submit', async ev => {
  ev.preventDefault();
  const data = new FormData(form);
  const payload = {};
  data.forEach((value, key) => {
    payload[key] = value;
  });

  selected.clear();
  pages.reset();

  try {
    startButton.disabled = true;
    await SMT.post('/api/v1/scan/', payload);
    SMT.notify('Scan started. It reads one item at a time, so give it a few minutes.');
    await poll();
    watch();
  } catch (e) {
    startButton.disabled = false;
    SMT.notify('Could not start the scan: ' + e.message, 'error');
  }
});

onlyTradable.addEventListener('change', () => {
  pages.reset();
  render();
});

rowsBody.addEventListener('change', ev => {
  const box = ev.target.closest('.row-checkbox');
  if (!box) return;
  if (box.checked) selected.add(box.value);
  else selected.delete(box.value);
  addButton.disabled = selected.size === 0;
  addButton.textContent = selected.size ? 'Add ' + selected.size + ' to pool' : 'Add selected to pool';
});

selectAll.addEventListener('change', () => {
  const shown = sorter.sort(visible(), sortValue).slice(pages.offset, pages.offset + pages.pageSize);
  shown.forEach(row => {
    if (selectAll.checked) selected.add(row.market_hash_name);
    else selected.delete(row.market_hash_name);
  });
  render();
});

bulkForm.addEventListener('submit', async ev => {
  ev.preventDefault();
  const chosen = candidates.filter(c => selected.has(c.market_hash_name));
  if (chosen.length === 0) return;

  const items = chosen.map(c => ({
    market_hash_name: c.market_hash_name,
    name: c.name,
    app_id: c.app_id,
    context_id: c.context_id,
    icon_url: c.icon_url,
  }));

  try {
    addButton.disabled = true;
    const result = await SMT.post('/api/v1/pool/add-scanned', {items: items});
    const skipped = items.length - result.count;
    SMT.notify(
      'Added ' + result.count + ' item(s) to the pool' +
      (skipped > 0 ? '; ' + skipped + ' were already there.' : '.'),
    );
    selected.clear();
    render();
  } catch (e) {
    addButton.disabled = false;
    SMT.notify('Could not add to the pool: ' + e.message, 'error');
  }
});

function detailStats(row) {
  return SMT.statsList([
    ['Cheapest listing', row.current_price],
    ['Median price', row.median_price],
    ['Drift vs today', row.price_drift],
    ['Listings', row.listings],
    ['Volume over window', row.volume_30d],
    ['Buy target', row.buy_target],
    ['Sell target', row.sell_target],
    ['Spread, %', row.spread_pct],
    ['Needed to break even, %', row.required_pct],
    ['Profit per trip', row.profit_per_trade],
    ['Round trips in the history', row.round_trips],
    ['Listings ahead of ours', row.queue_ahead],
    ['Days to clear that queue', row.days_to_clear],
    ['Trips the queue allows', row.feasible_round_trips],
    ['Median hold, h', row.median_hold_hours],
    ['Return, % / window', row.return_on_capital_pct],
    ['Verdict', row.note || (row.tradable ? 'clears the fee hurdle' : 'the fee eats the spread')],
  ]);
}

async function loadDetails(hash, panel) {
  const row = candidates.find(c => c.market_hash_name === hash);
  panel.innerHTML = '<p class="details-empty">Loading…</p>';

  const details = await SMT.get('/api/v1/scan/' + scanId + '/candidate/' + encodeURIComponent(hash));
  const days = Number(scanParams.days) || 30;

  panel.innerHTML =
    '<div class="details-grid">' +
    '<section><h4>Price, last ' + days + ' days</h4>' +
    SMT.priceChart(details.history, row.buy_target, row.sell_target, days) +
    detailStats(row) + '</section>' +
    '<section><h4>Order book</h4>' +
    (details.order_book
      ? SMT.depthLists(details.order_book)
      : '<p class="details-empty">Steam did not answer, so the depth is missing.</p>') +
    '</section></div>';
}

async function toggleRow(row) {
  const hash = row.dataset.hash;
  const detailsRow = row.nextElementSibling;
  const panel = detailsRow.querySelector('.details-panel');
  const expanded = row.getAttribute('aria-expanded') === 'true';

  row.setAttribute('aria-expanded', String(!expanded));
  detailsRow.hidden = expanded;
  if (expanded) return;

  try {
    await loadDetails(hash, panel);
  } catch (e) {
    panel.innerHTML = '<p class="details-empty">Could not load details: ' + SMT.escapeHtml(e.message) + '</p>';
  }
}

rowsBody.addEventListener('click', ev => {
  if (ev.target.closest('a, input, label, button, select')) return;
  const row = ev.target.closest('.pool-row');
  if (row) toggleRow(row);
});

rowsBody.addEventListener('keydown', ev => {
  if (ev.key !== 'Enter' && ev.key !== ' ') return;
  const row = ev.target.closest('.pool-row');
  if (!row || ev.target !== row) return;
  ev.preventDefault();
  toggleRow(row);
});

poll().then(() => {
  if (document.getElementById('scan-state').textContent === 'running') watch();
});
