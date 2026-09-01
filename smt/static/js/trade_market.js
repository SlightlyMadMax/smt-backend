const REFRESH_INTERVAL = 15000;

const body = document.getElementById('positions-body');
const statusFilter = document.getElementById('status-filter');
const rowCount = document.getElementById('row-count');

const PAGE_SIZE = 50;

const paging = SMT.pager(document.getElementById('positions-pager'), {
  pageSize: PAGE_SIZE,
  onChange: () => loadPositions(),
});

const sorting = SMT.sortControl(document.querySelector('.positions-table'), {
  key: 'created_at',
  onChange: () => {
    paging.reset();
    loadPositions();
  },
});

function formatDatetime(value) {
  if (!value) return '–';
  const d = new Date(value);
  const pad = n => String(n).padStart(2, '0');
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
    `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}

function money(value) {
  return value == null ? '–' : value;
}

function profitCell(value) {
  if (value == null) return '<td>–</td>';
  const cls = Number(value) >= 0 ? 'profit-positive' : 'profit-negative';
  return `<td class="${cls}">${value}</td>`;
}

function renderRow(p) {
  const icon = p.icon_url
    ? `<img src="${p.icon_url}" alt="">`
    : '';
  const name = p.listing_url
    ? `<a class="item-link" href="${p.listing_url}" target="_blank" rel="noopener">${p.name}</a>`
    : p.name;

  return `<tr>
    <td><span class="item-cell">${icon}${name}</span></td>
    <td>${p.status.replace('_', ' ')}</td>
    <td>${money(p.buy_price)}</td>
    <td>${money(p.sell_price)}</td>
    <td>${money(p.net_proceeds)}</td>
    ${profitCell(p.realized_profit)}
    <td>${formatDatetime(p.created_at)}</td>
    <td>${formatDatetime(p.bought_at)}</td>
    <td>${formatDatetime(p.listed_at)}</td>
    <td>${formatDatetime(p.sold_at)}</td>
  </tr>`;
}

function renderEmpty(message) {
  body.innerHTML = `<tr><td colspan="10" class="empty">${message}</td></tr>`;
}

async function loadPositions() {
  const status = statusFilter.value;
  const query = new URLSearchParams({
    limit: PAGE_SIZE,
    offset: paging.offset,
    sort: sorting.key,
    order: sorting.direction === 'ascending' ? 'asc' : 'desc',
  });
  if (status) query.set('status', status);

  try {
    const page = await SMT.get(`/api/v1/positions/?${query}`);
    paging.update(page.total);

    if (page.items.length === 0) {
      renderEmpty(status ? 'No positions with this status.' : 'No positions yet.');
      rowCount.textContent = '';
      return;
    }
    body.innerHTML = page.items.map(renderRow).join('');
    rowCount.textContent = `${page.total} position${page.total === 1 ? '' : 's'}`;
  } catch (e) {
    renderEmpty(`Could not load positions: ${e.message}`);
  }
}

async function loadSummary() {
  try {
    const summary = await SMT.get('/api/v1/positions/summary');
    document.querySelectorAll('[data-summary]').forEach(el => {
      el.textContent = summary[el.dataset.summary];
    });
    document.querySelectorAll('[data-status-count]').forEach(el => {
      const strong = el.querySelector('strong');
      if (strong) strong.textContent = summary.counts[el.dataset.statusCount] ?? 0;
    });
  } catch (e) {
    console.error('Could not load the summary', e);
  }
}

statusFilter.addEventListener('change', () => {
  paging.reset();
  loadPositions();
});

async function refresh() {
  await Promise.all([loadPositions(), loadSummary()]);
}

refresh();
setInterval(refresh, REFRESH_INTERVAL);
