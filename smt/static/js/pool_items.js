const POLL_INTERVAL = 3000;
const MAX_ATTEMPTS = 10;
let attemptCount = 0;
let pollHandle;

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
    '.poll-status',
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

  const hashes = Array.from(new Set(
    pendingEls.map(el =>
      el.dataset.hash
      || el.dataset.hashBuy
      || el.dataset.hashSell
      || el.dataset.hashVolatility
      || el.dataset.hashProfit
      || el.dataset.hashStatus
    )
  ));
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
    maybeSet('.poll-buy-price', 'data-hash-buy', buy);
    maybeSet('.poll-sell-price', 'data-hash-sell', sell);
    maybeSet('.poll-volume', 'data-hash', vol);
    maybeSet('.poll-volatility', 'data-hash-volatility', sigma);
    maybeSet('.poll-profit', 'data-hash-profit', prof);

    if (flag != null) {
      const statEl = document.querySelector(`.poll-status[data-hash-status="${name}"]`);
      if (statEl) {
        statEl.innerHTML = flag
          ? '<span class="badge success">Ready</span>'
          : '<span class="badge muted">—</span>';
      }
    }

    if (ts) {
      const timeEl = document.querySelector(`.poll-updated-at[data-hash="${name}"]`);
      if (timeEl) timeEl.textContent = formatDatetime(ts);
    }
  });
}

pollHandle = setInterval(pollUpdates, POLL_INTERVAL);
pollUpdates();
