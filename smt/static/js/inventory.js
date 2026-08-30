document.addEventListener('DOMContentLoaded', () => {
  const refreshBtn = document.getElementById('refresh-btn');
  const addSelectedBtn = document.getElementById('add-selected-btn');
  const grid = document.querySelector('.inventory-grid');

  const selectedIds = () =>
    Array.from(grid.querySelectorAll('input[name="asset_ids"]:checked')).map(cb => cb.value);

  refreshBtn.addEventListener('click', async () => {
    const game = new URLSearchParams(location.search).get('game');
    refreshBtn.disabled = true;
    try {
      await SMT.request(`/api/v1/inventory/refresh?game=${encodeURIComponent(game)}`, {method: 'PUT'});
      location.reload();
    } catch (e) {
      SMT.notify(`Could not refresh the inventory: ${e.message}`, 'error');
      refreshBtn.disabled = false;
    }
  });

  grid.addEventListener('change', () => {
    addSelectedBtn.disabled = selectedIds().length === 0;
  });

  addSelectedBtn.addEventListener('click', async () => {
    const asset_ids = selectedIds();
    if (asset_ids.length === 0) return;

    addSelectedBtn.disabled = true;
    try {
      const result = await SMT.post('/api/v1/pool/add-multiple', {asset_ids});
      SMT.notify(`Added ${result.count} item(s) to the pool.`);
      window.location.href = '/pool';
    } catch (e) {
      SMT.notify(`Could not add items: ${e.message}`, 'error');
      addSelectedBtn.disabled = false;
    }
  });
});
