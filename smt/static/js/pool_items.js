const POLL_INTERVAL = 3000;
const MAX_ATTEMPTS = 10;
const applyBtn = document.querySelector('.bulk-actions button');
const checkboxes = Array.from(document.querySelectorAll('.row-checkbox'));
const selectAll = document.getElementById('select-all');
let attemptCount = 0;
let pollHandle;

function updateApplyState() {
  applyBtn.disabled = !checkboxes.some(cb => cb.checked);
}

checkboxes.forEach(cb => cb.addEventListener('change', updateApplyState));

selectAll.addEventListener('change', ev => {
  const checked = ev.target.checked;
  checkboxes.forEach(cb => cb.checked = checked);
  updateApplyState();
});

updateApplyState();

document.querySelectorAll('.update-form').forEach(form => {
  form.addEventListener('submit', async ev => {
    ev.preventDefault();
    const field = form.querySelector('input[name="max_listed"]');
    const payload = { max_listed: Number(field.value) };
    const res = await fetch(form.action, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      location.reload();
    } else {
      console.error('Failed to update max_listed', await res.text());
    }
  });
});

async function fetchStatuses(hashes) {
  const qs = hashes.map(encodeURIComponent).join(',');
  const res = await fetch(`/api/v1/pool/status?market_hash_names=${qs}`);
  if (!res.ok) {
    console.error('Status fetch failed', res.status);
    return null;
  }
  return res.json();
}

function formatDatetime(dateString) {
  const d = new Date(dateString);
  return d.getUTCFullYear() + "-" +
    String(d.getUTCMonth() + 1).padStart(2,'0') + "-" +
    String(d.getUTCDate()).padStart(2,'0') + " " +
    String(d.getUTCHours()).padStart(2,'0') + ":" +
    String(d.getUTCMinutes()).padStart(2,'0');
}

async function pollUpdates() {
  attemptCount++;

  const selectors = [
    '.poll-current-price',
    '.poll-buy-price',
    '.poll-sell-price',
    '.poll-volume',
    '.poll-volatility',
    '.poll-profit',
    '.poll-updated-at'
  ];
  const pendingEls = selectors
    .flatMap(sel => Array.from(document.querySelectorAll(sel)))
    .filter(el => el.textContent.trim() === 'Loading…');

  if (pendingEls.length === 0 || attemptCount > MAX_ATTEMPTS) {
    clearInterval(pollHandle);

    if (attemptCount > MAX_ATTEMPTS) {
      selectors.forEach(sel =>
        document.querySelectorAll(sel)
          .forEach(el => {
            if (el.textContent.trim() === 'Loading…') {
              el.textContent = '–';
            }
          })
      );
    }
    return;
  }

  const hashes = Array.from(new Set(pendingEls.map(el => el.dataset.hash)));
  const statuses = await fetchStatuses(hashes);
  if (!statuses) return;

  statuses.forEach(item => {
    const {
      market_hash_name: name,
      current_lowest_price: curr,
      current_volume24h: vol,
      updated_at: ts,
      optimal_buy_price: buy,
      optimal_sell_price: sell,
      volatility: sigma,
      potential_profit: prof,
      use_for_trading: flag
    } = item;

    function maybeSet(sel, attr, value) {
      if (value == null) return;
      const el = document.querySelector(`${sel}[${attr}="${name}"]`);
      if (el) el.textContent = value;
    }

    maybeSet('.poll-current-price', 'data-hash', curr);
    maybeSet('.poll-buy-price', 'data-hash', buy);
    maybeSet('.poll-sell-price', 'data-hash', sell);
    maybeSet('.poll-volume', 'data-hash', vol);
    maybeSet('.poll-volatility', 'data-hash', sigma);
    maybeSet('.poll-profit', 'data-hash', prof);

    if (ts) {
      const timeEl = document.querySelector(`.poll-updated-at[data-hash="${name}"]`);
      if (timeEl) timeEl.textContent = formatDatetime(ts);
    }

    if (flag === true) {
      const row = document.querySelector(`tr[data-hash="${name}"]`);
      if (row) {
        row.classList.replace('not-ready', 'ready');
      }
    }
  });
}

pollHandle = setInterval(pollUpdates, POLL_INTERVAL);
pollUpdates();
