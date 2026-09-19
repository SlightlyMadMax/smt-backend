const HISTORY_DAYS = 7;

function buildChart(records, buyTarget, sellTarget) {
  return SMT.priceChart(records, buyTarget, sellTarget, HISTORY_DAYS);
}

function buildDepth(book, status) {
  if (!book) {
    const ask = status.current_lowest_price;
    const bid = status.current_highest_buy_order;
    const stored = (ask != null || bid != null)
      ? SMT.statsList([['Cheapest listing', ask], ['Top buy order', bid]])
      : '';
    return '<p class="details-empty">Steam did not answer, so the depth is missing. ' +
      'These are the prices from the last refresh.</p>' + stored;
  }
  return SMT.depthLists(book);
}

function buildStats(status) {
  const rows = [
    ['Top buy order', status.current_highest_buy_order],
    ['Volume, 24h', status.current_volume24h],
    ['Volume, 7d', status.current_volume7d],
    ['Volatility', status.volatility],
    ['Computed buy', status.optimal_buy_price],
    ['Computed sell', status.optimal_sell_price],
    ['Asking percentile chosen', status.sell_percentile_used],
    ['Listings ahead of ours', status.queue_ahead],
    ['Time to clear that queue', SMT.duration(status.days_to_clear)],
    ['Round trips in the history', status.round_trips],
    ['Trips the queue allows', status.feasible_round_trips],
    ['Median hold, h', status.median_hold_hours],
    ['Return, % / 30d', status.return_on_capital_30d],
    ['Traded by the bot', status.use_for_trading ? 'yes' : 'no'],
  ];
  return SMT.statsList(rows);
}

function buildForm(status) {
  const val = v => (v == null ? '' : SMT.escapeHtml(v));
  return '<form class="details-form">' +
    '<div class="form-group"><label>Manual buy price</label>' +
    '<input type="number" step="0.01" min="0" name="manual_buy_price" value="' +
    val(status.manual_buy_price) + '" placeholder="' + val(status.optimal_buy_price) + '">' +
    '<small>Overrides the computed price. Empty means use the computed one.</small></div>' +
    '<div class="form-group"><label>Manual sell price</label>' +
    '<input type="number" step="0.01" min="0" name="manual_sell_price" value="' +
    val(status.manual_sell_price) + '" placeholder="' + val(status.optimal_sell_price) + '">' +
    '<small>Overrides the computed price. Empty means use the computed one.</small></div>' +
    '<div class="form-group"><label>Max listed</label>' +
    '<input type="number" step="1" min="1" name="max_listed" value="' +
    (val(status.max_listed) || '1') + '">' +
    '<small>How many positions may be open at once.</small></div>' +
    '<div class="form-actions"><button type="submit" class="btn small">Save</button></div></form>';
}

async function loadDetails(hash, panel) {
  panel.innerHTML = '<p class="details-empty">Loading...</p>';

  const since = new Date(Date.now() - HISTORY_DAYS * 86400000).toISOString();
  const results = await Promise.all([
    SMT.get('/api/v1/pool/status?market_hash_names=' + encodeURIComponent(hash)),
    SMT.get('/api/v1/price_records/' + encodeURIComponent(hash) +
      '?since=' + encodeURIComponent(since)).catch(() => []),
    SMT.get('/api/v1/pool/' + encodeURIComponent(hash) + '/order-book').catch(() => null),
  ]);

  const status = results[0][0] || {};
  const history = results[1];
  const book = results[2];

  panel.innerHTML = '<div class="details-grid">' +
    '<section><h4>Price, last ' + HISTORY_DAYS + ' days</h4>' +
    buildChart(history, status.optimal_buy_price, status.optimal_sell_price) +
    buildStats(status) + '</section>' +
    '<section><h4>Order book</h4>' + buildDepth(book, status) + '</section>' +
    '<section><h4>Manual overrides</h4>' + buildForm(status) + '</section>' +
    '</div>';

  panel.querySelector('.details-form').addEventListener('submit', async ev => {
    ev.preventDefault();
    const data = new FormData(ev.target);
    const payload = {};
    ['manual_buy_price', 'manual_sell_price', 'max_listed'].forEach(field => {
      const raw = data.get(field);
      payload[field] = raw === '' ? null : Number(raw);
    });

    try {
      await SMT.patch('/api/v1/pool/' + encodeURIComponent(hash), payload);
      SMT.notify('Saved.');
      await loadDetails(hash, panel);

      const fresh = await SMT.get('/api/v1/pool/status?market_hash_names=' + encodeURIComponent(hash));
      if (fresh[0]) applyStatus(fresh[0]);
    } catch (e) {
      SMT.notify('Could not save: ' + e.message, 'error');
    }
  });
}

async function toggleRow(row) {
  const hash = row.dataset.hash;
  const detailsRow = document.querySelector('.details-row[data-details-for="' + CSS.escape(hash) + '"]');
  const panel = detailsRow.querySelector('.details-panel');
  const expanded = row.getAttribute('aria-expanded') === 'true';

  row.setAttribute('aria-expanded', String(!expanded));
  detailsRow.hidden = expanded;

  if (expanded) return;

  try {
    await loadDetails(hash, panel);
  } catch (e) {
    panel.innerHTML = '<p class="details-empty">Could not load details: ' +
      SMT.escapeHtml(e.message) + '</p>';
  }
}

document.querySelectorAll('.pool-row').forEach(row => {
  row.addEventListener('click', ev => {
    if (ev.target.closest('a, input, label, button, select')) return;
    toggleRow(row);
  });

  row.addEventListener('keydown', ev => {
    if (ev.key !== 'Enter' && ev.key !== ' ') return;
    if (ev.target !== row) return;
    ev.preventDefault();
    toggleRow(row);
  });
});
