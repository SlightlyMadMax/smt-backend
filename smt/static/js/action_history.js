const REFRESH_INTERVAL = 15000;

const body = document.getElementById('action-body');
const levelFilter = document.getElementById('level-filter');
const entryCount = document.getElementById('entry-count');
const clearButton = document.getElementById('clear-history');

const PAGE_SIZE = 50;

const paging = SMT.pager(document.getElementById('actions-pager'), {
  pageSize: PAGE_SIZE,
  onChange: () => load(),
});

const sorting = SMT.sortControl(document.querySelector('.action-table'), {
  key: 'occurred_at',
  onChange: () => {
    paging.reset();
    load();
  },
});

function escapeHtml(value) {
  const div = document.createElement('div');
  div.textContent = value == null ? '' : value;
  return div.innerHTML;
}

function formatDatetime(value) {
  const d = new Date(value);
  const pad = n => String(n).padStart(2, '0');
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
    `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}

function renderRow(entry) {
  const item = entry.market_hash_name
    ? escapeHtml(entry.market_hash_name)
    : '<span class="filter-hint">—</span>';

  return `<tr class="level-${escapeHtml(entry.level)}">
    <td class="when">${formatDatetime(entry.occurred_at)}</td>
    <td class="event"><span class="event-chip">${escapeHtml(entry.kind.replace(/_/g, ' '))}</span></td>
    <td>${item}</td>
    <td>${escapeHtml(entry.message)}</td>
  </tr>`;
}

function renderEmpty(message) {
  body.innerHTML = `<tr><td colspan="4" class="empty">${escapeHtml(message)}</td></tr>`;
}

async function load() {
  const level = levelFilter.value;
  const query = new URLSearchParams({
    limit: PAGE_SIZE,
    offset: paging.offset,
    sort: sorting.key,
    order: sorting.direction === 'ascending' ? 'asc' : 'desc',
  });
  if (level) query.set('level', level);

  try {
    const page = await SMT.get(`/api/v1/actions/?${query}`);
    const entries = page.items;
    paging.update(page.total);

    if (entries.length === 0) {
      renderEmpty(level
        ? 'Nothing of that kind has happened yet.'
        : 'The bot has not done anything yet. It records an entry whenever it places, fills or closes an order.');
      entryCount.textContent = '';
      return;
    }
    body.innerHTML = entries.map(renderRow).join('');
    entryCount.textContent = countLabel(page.total);
  } catch (e) {
    renderEmpty(`Could not load the history: ${e.message}`);
  }
}

function countLabel(n) {
  return `${n} entr${n === 1 ? 'y' : 'ies'}`;
}

async function clearHistory() {
  if (!SMT.confirmAction('Delete every entry in the action history? This cannot be undone.')) return;

  clearButton.disabled = true;
  try {
    const result = await SMT.remove('/api/v1/actions/');
    SMT.notify(result.removed === 0 ? 'There was nothing to delete.' : `Deleted ${countLabel(result.removed)}.`);
    await load();
  } catch (e) {
    SMT.notify(`Could not clear the history: ${e.message}`, 'error');
  } finally {
    clearButton.disabled = false;
  }
}

levelFilter.addEventListener('change', () => {
  paging.reset();
  load();
});
clearButton.addEventListener('click', clearHistory);

load();
setInterval(load, REFRESH_INTERVAL);
