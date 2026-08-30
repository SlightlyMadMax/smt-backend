const HISTORY_DAYS = 7;
const CHART_W = 620;
const CHART_H = 170;
const CHART_PAD = 28;

function escapeHtml(value) {
  const div = document.createElement('div');
  div.textContent = value == null ? '' : value;
  return div.innerHTML;
}

const OUTLIER_FACTOR = 5;

function withoutOutliers(records) {
  if (records.length === 0) return records;
  const sorted = records.map(r => Number(r.price)).sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)];
  if (!(median > 0)) return records;
  return records.filter(r => {
    const price = Number(r.price);
    return price >= median / OUTLIER_FACTOR && price <= median * OUTLIER_FACTOR;
  });
}

function buildChart(allRecords, buyTarget, sellTarget) {
  const records = withoutOutliers(allRecords);
  const hidden = allRecords.length - records.length;

  if (records.length < 2) {
    return '<p class="details-empty">Not enough price history yet.</p>';
  }

  const prices = records.map(r => Number(r.price));
  const times = records.map(r => new Date(r.recorded_at).getTime());
  const levels = [buyTarget, sellTarget].filter(v => v != null).map(Number);
  const min = Math.min(...prices, ...levels);
  const max = Math.max(...prices, ...levels);
  const span = max - min || 1;
  const tMin = times[0];
  const tSpan = times[times.length - 1] - tMin || 1;

  const x = t => CHART_PAD + ((t - tMin) / tSpan) * (CHART_W - CHART_PAD * 2);
  const y = p => CHART_H - CHART_PAD - ((p - min) / span) * (CHART_H - CHART_PAD * 2);
  const line = records.map((r, i) => x(times[i]).toFixed(1) + ',' + y(prices[i]).toFixed(1)).join(' ');

  const level = (value, cls, label) => {
    if (value == null) return '';
    const yy = y(Number(value)).toFixed(1);
    return '<line class="chart-level ' + cls + '" x1="' + CHART_PAD + '" x2="' + (CHART_W - CHART_PAD) +
      '" y1="' + yy + '" y2="' + yy + '"/>' +
      '<text class="chart-label ' + cls + '" x="' + (CHART_W - CHART_PAD + 3) + '" y="' + yy +
      '" dy="4">' + label + '</text>';
  };

  return '<svg class="price-chart" viewBox="0 0 ' + CHART_W + ' ' + CHART_H + '" role="img" ' +
    'aria-label="Price over the last ' + HISTORY_DAYS + ' days">' +
    '<text class="chart-axis" x="2" y="' + y(max).toFixed(1) + '" dy="4">' + max.toFixed(2) + '</text>' +
    '<text class="chart-axis" x="2" y="' + y(min).toFixed(1) + '" dy="4">' + min.toFixed(2) + '</text>' +
    level(buyTarget, 'chart-buy', 'buy') +
    level(sellTarget, 'chart-sell', 'sell') +
    '<polyline class="chart-line" points="' + line + '"/></svg>' +
    (hidden > 0
      ? '<p class="chart-note">' + hidden + ' sale(s) far outside the usual range are not drawn. ' +
        'They are typically money moved between accounts rather than trading.</p>'
      : '');
}

function buildDepth(book) {
  if (!book) {
    return '<p class="details-empty">The order book is unavailable right now.</p>';
  }

  const sells = (book.sell_levels || []).slice(0, 6);
  const buys = (book.buy_levels || []).slice(0, 6);
  const peak = Math.max(1, ...sells.map(l => l.quantity), ...buys.map(l => l.quantity));

  const side = (levels, cls) => levels.map(l =>
    '<li><span class="depth-price">' + escapeHtml(l.price) + '</span>' +
    '<span class="depth-bar"><i class="' + cls + '" style="width:' +
    (l.quantity / peak * 100).toFixed(1) + '%"></i></span>' +
    '<span class="depth-qty">' + l.quantity + '</span></li>').join('');

  const total = value => (value == null ? '-' : value);

  return '<div class="depth">' +
    '<div><h4>Sell orders <small>' + total(book.sell_order_count) + ' total</small></h4>' +
    '<ul class="depth-list">' + side(sells, 'depth-sell') + '</ul></div>' +
    '<div><h4>Buy orders <small>' + total(book.buy_order_count) + ' total</small></h4>' +
    '<ul class="depth-list">' + side(buys, 'depth-buy') + '</ul></div></div>';
}

function buildStats(status) {
  const rows = [
    ['Top buy order', status.current_highest_buy_order],
    ['Volume, 24h', status.current_volume24h],
    ['Volatility', status.volatility],
    ['Computed buy', status.optimal_buy_price],
    ['Computed sell', status.optimal_sell_price],
    ['Traded by the bot', status.use_for_trading ? 'yes' : 'no'],
  ];
  return '<dl class="details-stats">' + rows.map(pair =>
    '<div><dt>' + pair[0] + '</dt><dd>' +
    (pair[1] == null ? '-' : escapeHtml(pair[1])) + '</dd></div>').join('') + '</dl>';
}

function buildForm(status) {
  const val = v => (v == null ? '' : escapeHtml(v));
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
    '<section><h4>Order book</h4>' + buildDepth(book) + '</section>' +
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

      // the polling loop only touches cells it is waiting on, so the row above
      // would keep showing the previous prices until a reload
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
      escapeHtml(e.message) + '</p>';
  }
}

document.querySelectorAll('.pool-row').forEach(row => {
  // the checkbox and the item link keep their own behaviour
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
