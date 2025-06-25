const POLL_INTERVAL = 3000;
const MAX_ATTEMPTS = 10;
const refreshingBaseline = {};

const applyBtn = document.querySelector('.bulk-actions button');
const checkboxes = Array.from(document.querySelectorAll('.row-checkbox'));
const bulkForm = document.getElementById('bulk-action-form');
const selectAll = document.getElementById('select-all');
const actionSelect = document.getElementById('bulk-action-select');

let attemptCount = 0;
let pollHandle;

// ── ENABLE/DISABLE APPLY BUTTON ─────────────────────────────────────────
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

// ── PER‐ROW MAX_LISTED UPDATE ────────────────────────────────
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

// ── BULK‐ACTION SUBMIT HANDLER ───────────────────────────────────────────
bulkForm.addEventListener('submit', async ev => {
  ev.preventDefault();

  const action = actionSelect.value;
  const hashes = checkboxes.filter(cb => cb.checked).map(cb => cb.value);
  if (!action || hashes.length === 0) return;

  if (action === 'remove') {
    const res = await fetch('/api/v1/pool', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ market_hash_names: hashes })
    });

    if (res.ok) {
      hashes.forEach(h => {
        const row = document.querySelector(`tr[data-hash="${h}"]`);
        if (row) row.remove();
      });
      selectAll.checked = false;
      updateApplyState();
    } else {
      console.error('Bulk remove failed:', await res.text());
    }

  } else if (action === 'refresh') {
    hashes.forEach(h => {
      const timeEl = document.querySelector(`.poll-updated-at[data-hash="${h}"]`);
      refreshingBaseline[h] = timeEl?.textContent || null;
    });
    hashes.forEach(h => {
      const selector = `
        .poll-current-price[data-hash="${h}"],
        .poll-buy-price[data-hash="${h}"],
        .poll-sell-price[data-hash="${h}"],
        .poll-volume[data-hash="${h}"],
        .poll-volatility[data-hash="${h}"],
        .poll-profit[data-hash="${h}"],
        .poll-updated-at[data-hash="${h}"]
      `;
      document.querySelectorAll(selector).forEach(el => el.innerHTML = '<em>Loading</em>');
    });

    attemptCount = 0;
    if (pollHandle) clearInterval(pollHandle);
    pollHandle = setInterval(pollUpdates, POLL_INTERVAL);
    pollUpdates();

    fetch('/api/v1/pool/refresh-many', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ market_hash_names: hashes })
    })
    .then(res => {
      if (!res.ok) console.error('Bulk refresh failed:', res.status, res.statusText);
    });

    selectAll.checked = false;
    checkboxes.forEach(cb => cb.checked = false);
    updateApplyState();
  }
});

// ── POLLING LOGIC ────────────────────────────────────────────────────────
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

    if (refreshingBaseline.hasOwnProperty(name)) {
      const baselineRaw = refreshingBaseline[name].trim();
      const baselineNorm = baselineRaw.replace(' ', 'T');
      const tsNorm = ts.slice(0, 16);

      if (tsNorm === baselineNorm) {
        return;
      }
      delete refreshingBaseline[name];
    }

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
