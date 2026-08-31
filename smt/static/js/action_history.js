const REFRESH_INTERVAL = 15000;

const body = document.getElementById('action-body');
const levelFilter = document.getElementById('level-filter');
const entryCount = document.getElementById('entry-count');

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
  const url = level ? `/api/v1/actions/?level=${encodeURIComponent(level)}` : '/api/v1/actions/';

  try {
    const entries = await SMT.get(url);
    if (entries.length === 0) {
      renderEmpty(level
        ? 'Nothing of that kind has happened yet.'
        : 'The bot has not done anything yet. It records an entry whenever it places, fills or closes an order.');
      entryCount.textContent = '';
      return;
    }
    body.innerHTML = entries.map(renderRow).join('');
    entryCount.textContent = `${entries.length} entr${entries.length === 1 ? 'y' : 'ies'}`;
  } catch (e) {
    renderEmpty(`Could not load the history: ${e.message}`);
  }
}

levelFilter.addEventListener('change', load);

load();
setInterval(load, REFRESH_INTERVAL);
