const POLL_INTERVAL = 3000;
const MAX_ATTEMPTS = 10;
const LOADING_MARKUP = '<em>Loading…</em>';
const LOADING_TEXT = 'Loading…';

const POLL_FIELDS = [
  ['.poll-buy-price', 'effective_buy_price'],
  ['.poll-sell-price', 'effective_sell_price'],
  ['.poll-current-price', 'current_lowest_price'],
  ['.poll-profit', 'potential_profit'],
];

const applyBtn = document.querySelector('.bulk-actions button');
const bulkForm = document.getElementById('bulk-action-form');
const actionSelect = document.getElementById('bulk-action-select');
const selectAll = document.getElementById('select-all');
const checkboxes = Array.from(document.querySelectorAll('.row-checkbox'));

const refreshingBaseline = {};
let attemptCount = 0;
let pollHandle;

// ── selection ────────────────────────────────────────────────────────────
function selectedHashes() {
  return checkboxes.filter(cb => cb.checked).map(cb => cb.value);
}

function updateApplyState() {
  applyBtn.disabled = selectedHashes().length === 0;
}

checkboxes.forEach(cb => cb.addEventListener('change', updateApplyState));

selectAll.addEventListener('change', ev => {
  checkboxes.forEach(cb => (cb.checked = ev.target.checked));
  updateApplyState();
});

function clearSelection() {
  selectAll.checked = false;
  checkboxes.forEach(cb => (cb.checked = false));
  updateApplyState();
}

updateApplyState();

// ── bulk actions ─────────────────────────────────────────────────────────
async function removeItems(hashes) {
  const confirmed = SMT.confirmAction(
    `Remove ${hashes.length} item(s) from the pool? Their price history will be deleted too.`
  );
  if (!confirmed) return;

  try {
    const result = await SMT.remove('/api/v1/pool/', {market_hash_names: hashes});
    hashes.forEach(h => document.querySelector(`tr[data-hash="${CSS.escape(h)}"]`)?.remove());
    clearSelection();
    SMT.notify(result.message);
    refreshSummary();
  } catch (e) {
    SMT.notify(`Could not remove items: ${e.message}`, 'error');
  }
}

function markPending(hashes) {
  hashes.forEach(h => {
    const timeEl = document.querySelector(`.poll-updated-at[data-hash="${CSS.escape(h)}"]`);
    refreshingBaseline[h] = timeEl ? timeEl.textContent : null;

    const selectors = [...POLL_FIELDS.map(([sel]) => sel), '.poll-updated-at']
      .map(sel => `${sel}[data-hash="${CSS.escape(h)}"]`)
      .join(',');
    document.querySelectorAll(selectors).forEach(el => (el.innerHTML = LOADING_MARKUP));
  });
}

async function refreshItems(hashes) {
  markPending(hashes);
  attemptCount = 0;
  if (pollHandle) clearInterval(pollHandle);
  pollHandle = setInterval(pollUpdates, POLL_INTERVAL);
  pollUpdates();

  try {
    await SMT.post('/api/v1/pool/refresh-many', {market_hash_names: hashes});
  } catch (e) {
    SMT.notify(`Could not queue the refresh: ${e.message}`, 'error');
  }
  clearSelection();
}

bulkForm.addEventListener('submit', async ev => {
  ev.preventDefault();
  const hashes = selectedHashes();
  if (!actionSelect.value || hashes.length === 0) return;

  if (actionSelect.value === 'remove') await removeItems(hashes);
  else if (actionSelect.value === 'refresh') await refreshItems(hashes);
});

// ── polling ──────────────────────────────────────────────────────────────
function formatDatetime(value) {
  const d = new Date(value);
  const pad = n => String(n).padStart(2, '0');
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
    `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}

function pendingElements() {
  const selectors = [...POLL_FIELDS.map(([sel]) => sel), '.poll-updated-at'].join(',');
  return Array.from(document.querySelectorAll(selectors))
    .filter(el => el.textContent.trim() === LOADING_TEXT);
}

function giveUpOnPending() {
  pendingElements().forEach(el => (el.textContent = '–'));
  SMT.notify('The refresh did not finish in time. Check that the worker is running.', 'error');
}

function applyStatus(item) {
  const name = item.market_hash_name;
  const baseline = refreshingBaseline[name];

  if (baseline !== undefined) {
    if (baseline && item.updated_at && item.updated_at.slice(0, 16) === baseline.trim().replace(' ', 'T')) {
      return;
    }
    delete refreshingBaseline[name];
  }

  POLL_FIELDS.forEach(([selector, field]) => {
    if (item[field] == null) return;
    const el = document.querySelector(`${selector}[data-hash="${CSS.escape(name)}"]`);
    if (el) el.textContent = item[field];
  });

  if (item.updated_at) {
    const el = document.querySelector(`.poll-updated-at[data-hash="${CSS.escape(name)}"]`);
    if (el) el.textContent = formatDatetime(item.updated_at);
  }

  const row = document.querySelector(`tr[data-hash="${CSS.escape(name)}"]`);
  if (row) {
    row.classList.toggle('state-positive', item.use_for_trading === true);
    row.classList.toggle('state-negative', item.use_for_trading !== true);
  }
}

async function pollUpdates() {
  attemptCount++;
  const pending = pendingElements();

  if (pending.length === 0 || attemptCount > MAX_ATTEMPTS) {
    clearInterval(pollHandle);
    if (attemptCount > MAX_ATTEMPTS) giveUpOnPending();
    return;
  }

  const hashes = Array.from(new Set(pending.map(el => el.dataset.hash)));
  try {
    const statuses = await SMT.get(
      `/api/v1/pool/status?market_hash_names=${hashes.map(encodeURIComponent).join(',')}`
    );
    statuses.forEach(applyStatus);
  } catch (e) {
    console.error('Status poll failed', e);
  }
}

pollHandle = setInterval(pollUpdates, POLL_INTERVAL);
pollUpdates();

const SUMMARY_INTERVAL = 20000;

const tradingToggle = document.getElementById('trading-toggle');
const tradingState = document.getElementById('trading-state');

function applySummary(summary) {
  document.querySelectorAll('[data-summary]').forEach(el => {
    el.textContent = summary[el.dataset.summary];
  });
  tradingToggle.checked = summary.trading_enabled;
  tradingState.textContent = summary.trading_enabled ? 'on' : 'off';
}

tradingToggle.addEventListener('change', async () => {
  const enabled = tradingToggle.checked;

  if (enabled && !SMT.confirmAction(
    'Enable trading? The bot will place real buy orders and spend the money in your Steam wallet.')) {
    tradingToggle.checked = false;
    return;
  }

  try {
    applySummary(await SMT.patch('/api/v1/pool/trading', {enabled: enabled}));
    SMT.notify(enabled ? 'Trading enabled.' : 'Trading disabled.');
  } catch (e) {
    tradingToggle.checked = !enabled;
    SMT.notify('Could not change the trading state: ' + e.message, 'error');
  }
});

async function refreshSummary() {
  try {
    applySummary(await SMT.get('/api/v1/pool/summary'));
  } catch (e) {
    console.error('Could not refresh the summary', e);
  }
}

setInterval(refreshSummary, SUMMARY_INTERVAL);

// ── sorting ──────────────────────────────────────────────────────────────
const SORT_SELECTORS = {
  name: '.item-link',
  buy_price: '.poll-buy-price',
  sell_price: '.poll-sell-price',
  current_price: '.poll-current-price',
  profit: '.poll-profit',
  updated_at: '.poll-updated-at',
};

const poolTable = document.querySelector('.pool-table');
const poolBody = poolTable && poolTable.querySelector('tbody');

function cellValue(row, key) {
  const cell = row.querySelector(SORT_SELECTORS[key]);
  if (!cell) return '';
  const text = cell.textContent.trim();
  return text === LOADING_TEXT ? '' : text;
}

function reorderRows(key, direction) {
  const rows = Array.from(poolBody.querySelectorAll('.pool-row'));
  rows.sort(SMT.comparator(direction, row => cellValue(row, key)));

  rows.forEach(row => {
    const details = poolBody.querySelector(`.details-row[data-details-for="${CSS.escape(row.dataset.hash)}"]`);
    poolBody.appendChild(row);
    if (details) poolBody.appendChild(details);
  });
}

if (poolBody && poolBody.querySelector('.pool-row')) {
  SMT.sortControl(poolTable, {key: null, onChange: reorderRows});
}
