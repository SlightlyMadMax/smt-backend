const ITEM_LIMIT = 50;
const HISTORY_DAYS = 30;
const CHART_W = 900;
const CHART_H = 180;
const CHART_PAD_X = 44;
const CHART_PAD_Y = 18;

const funnelEl = document.getElementById('funnel');
const itemsBody = document.getElementById('items-body');
const dailyEl = document.getElementById('daily-profit');

const sorting = SMT.sortControl(document.querySelector('.stats-table'), {
  key: 'profit',
  onChange: () => sortAndRender(),
});

let currentItems = [];

function escapeHtml(value) {
  const div = document.createElement('div');
  div.textContent = value == null ? '' : value;
  return div.innerHTML;
}

function num(value) {
  return value == null ? '—' : escapeHtml(value);
}

function signed(value) {
  if (value == null) return '<span class="forecast">—</span>';
  const cls = Number(value) < 0 ? 'negative' : 'positive';
  return `<span class="${cls}">${escapeHtml(value)}</span>`;
}

function step(label, value, note) {
  return `<div class="funnel-step">
    <span class="funnel-label">${escapeHtml(label)}</span>
    <span class="funnel-value">${escapeHtml(value)}</span>
    ${note ? `<span class="funnel-note">${escapeHtml(note)}</span>` : ''}
  </div>`;
}

function renderFunnel(funnel) {
  if (funnel.opened === 0) {
    funnelEl.innerHTML = '<p class="empty">No positions yet. The bot records one for every buy order it places.</p>';
    return;
  }

  funnelEl.innerHTML =
    step(
      'Buy orders that filled',
      funnel.fill_rate == null ? '—' : `${funnel.fill_rate}%`,
      `${funnel.bought} of ${funnel.opened}; the rest never got to the front of the queue`,
    ) +
    step(
      'Filled positions that sold',
      funnel.sell_through == null ? '—' : `${funnel.sell_through}%`,
      `${funnel.sold} of ${funnel.bought}`,
    );
}

function returnHint(item) {
  const days = escapeHtml(item.observed_days == null ? 0 : item.observed_days);
  if (item.actual_return_30d != null) {
    return ` title="Measured over ${days} days, then scaled to 30."`;
  }
  const trades = `${item.trades} trade${item.trades === 1 ? '' : 's'}`;
  return ` title="Too early to scale to 30 days: only ${trades} over ${days} days."`;
}

function renderItems(items) {
  if (items.length === 0) {
    itemsBody.innerHTML = '<tr><td colspan="12" class="empty">Nothing has been sold yet.</td></tr>';
    return;
  }

  itemsBody.innerHTML = items.map(item => `<tr>
    <td><span class="item-cell">
      ${item.icon_url ? `<img src="${escapeHtml(item.icon_url)}" alt="">` : ''}
      ${escapeHtml(item.name)}
    </span></td>
    <td>${item.trades}</td>
    <td>${signed(item.profit)}</td>
    <td class="group-start">${num(item.avg_profit)}</td>
    <td class="forecast">${num(item.forecast_profit)}</td>
    <td class="group-start">${num(item.median_hold_hours)}</td>
    <td class="forecast">${num(item.forecast_hold_hours)}</td>
    <td class="group-start">${num(item.sell_wait_hours)}</td>
    <td class="forecast">${num(item.forecast_sell_wait_hours)}</td>
    <td class="group-start">${num(item.buy_wait_hours)}</td>
    <td class="group-start"${returnHint(item)}>${signed(item.actual_return_30d)}</td>
    <td class="forecast">${num(item.forecast_return_30d)}</td>
  </tr>`).join('');
}

function sortAndRender() {
  renderItems(sorting.sort(currentItems));
}

function renderDailyProfit(days) {
  if (days.length === 0) {
    dailyEl.innerHTML = `<p class="empty">Nothing closed in the last ${HISTORY_DAYS} days.</p>`;
    return;
  }

  const values = days.map(d => Number(d.profit));
  const max = Math.max(0, ...values);
  const min = Math.min(0, ...values);
  const span = (max - min) || 1;

  const plotH = CHART_H - CHART_PAD_Y * 2;
  const plotW = CHART_W - CHART_PAD_X * 2;
  const slot = plotW / days.length;
  const barW = Math.max(2, slot * 0.7);
  const y = v => CHART_PAD_Y + ((max - v) / span) * plotH;
  const zero = y(0);

  const bars = days.map((day, i) => {
    const value = Number(day.profit);
    const top = value >= 0 ? y(value) : zero;
    const height = Math.max(1, Math.abs(y(value) - zero));
    const x = CHART_PAD_X + i * slot + (slot - barW) / 2;
    const cls = value < 0 ? 'bar-negative' : 'bar-positive';
    return `<rect class="${cls}" x="${x.toFixed(1)}" y="${top.toFixed(1)}" ` +
      `width="${barW.toFixed(1)}" height="${height.toFixed(1)}"><title>${escapeHtml(day.day)}: ` +
      `${escapeHtml(day.profit)}</title></rect>`;
  }).join('');

  dailyEl.innerHTML = `<svg class="profit-chart" viewBox="0 0 ${CHART_W} ${CHART_H}" role="img"
      aria-label="Realised profit per day over the last ${HISTORY_DAYS} days">
    <text class="chart-axis" x="2" y="${y(max).toFixed(1)}" dy="4">${max.toFixed(2)}</text>
    <text class="chart-axis" x="2" y="${y(min).toFixed(1)}" dy="4">${min.toFixed(2)}</text>
    <line class="zero-line" x1="${CHART_PAD_X}" x2="${CHART_W - CHART_PAD_X}"
      y1="${zero.toFixed(1)}" y2="${zero.toFixed(1)}"/>
    ${bars}
  </svg>
  <p class="funnel-note">${days.length} day${days.length === 1 ? '' : 's'} with a closed position. Hover a bar for the date.</p>`;
}

async function load() {
  try {
    const data = await SMT.get(`/api/v1/statistics/?top=${ITEM_LIMIT}&days=${HISTORY_DAYS}`);
    currentItems = data.items;
    renderFunnel(data.funnel);
    sortAndRender();
    renderDailyProfit(data.daily_profit);
  } catch (e) {
    funnelEl.innerHTML = `<p class="empty">Could not load the statistics: ${escapeHtml(e.message)}</p>`;
  }
}

load();
