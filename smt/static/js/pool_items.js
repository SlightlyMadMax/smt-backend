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
    const res = await fetch(`/api/v1/pool/status?market_name_hashes=${qs}`);
    if (!res.ok) {
      console.error('Status fetch failed', res.status);
      return null;
    }
    return res.json();
}

function formatDatetime(dateString) {
    const date = new Date(dateString);
    return date.getUTCFullYear() + "-"
        + String(date.getUTCMonth() + 1).padStart(2, '0') + "-"
        + String(date.getUTCDate()).padStart(2, '0') + " "
        + String(date.getUTCHours()).padStart(2, '0') + ":"
        + String(date.getUTCMinutes()).padStart(2, '0');
}

async function pollUpdates() {
    attemptCount++;

    const pendingEls = [...document.querySelectorAll('.poll-current-price')]
      .filter(el => el.textContent.trim() === 'Loading…');
    if (pendingEls.length === 0 || attemptCount > MAX_ATTEMPTS) {
      clearInterval(pollHandle);

      if (attemptCount > MAX_ATTEMPTS) {
        document.querySelectorAll('.poll-current-price')
                .forEach(el => { if (el.textContent.trim()==='Loading…') el.textContent='–'; });
        document.querySelectorAll('.poll-volume')
                .forEach(el => { if (el.textContent.trim()==='Loading…') el.textContent='–'; });
        document.querySelectorAll('.poll-updated-at')
                .forEach(el => { if (el.textContent.trim()==='Loading…') el.textContent='–'; });
      }
      return;
    }

    const hashes = pendingEls.map(el => el.dataset.hash);
    const statuses = await fetchStatuses(hashes);
    if (!statuses) return;

    statuses.forEach(({
        market_hash_name,
        current_lowest_price,
        current_volume24h,
        updated_at,
        volatility,
        potential_profit,
        use_for_trading
    }) => {
      const priceEl = document.querySelector(`.poll-current-price[data-hash="${market_hash_name}"]`);
      const volEl   = document.querySelector(`.poll-volume[data-hash="${market_hash_name}"]`);
      const timeEl  = document.querySelector(`.poll-updated-at[data-hash="${market_hash_name}"]`);
      const volatEl = document.querySelector(`td[data-hash-volatility="${market_hash_name}"]`);
      const profitEl= document.querySelector(`td[data-hash-profit="${market_hash_name}"]`);
      const statusEl= document.querySelector(`td[data-hash-status="${market_hash_name}"]`);

      if (priceEl && current_lowest_price != null) priceEl.textContent = current_lowest_price;
      if (volEl   && current_volume24h  != null) volEl.textContent   = current_volume24h;
      if (timeEl  && updated_at) timeEl.textContent = formatDatetime(updated_at);

      if (volatEl)  volatEl.textContent  = volatility ?? '–';
      if (profitEl) profitEl.textContent = potential_profit ?? '–';
      if (statusEl) {
        statusEl.innerHTML = use_for_trading
          ? '<span class="badge success">Ready</span>'
          : '<span class="badge muted">—</span>';
      }
    });
}

pollHandle = setInterval(pollUpdates, POLL_INTERVAL);
pollUpdates();
