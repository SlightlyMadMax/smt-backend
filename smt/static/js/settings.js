document.getElementById('settings-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const formData = new FormData(e.target);
    const settings = Object.fromEntries(formData.entries());

    // Convert numeric fields
    const numericFields = [
        'min_profit_threshold', 'min_profit_percentage', 'max_investment_per_item',
        'buy_percentile', 'sell_percentile', 'min_volume_24h', 'min_volume_7d',
        'min_volatility_threshold', 'max_volatility_threshold', 'max_daily_loss'
    ];

    numericFields.forEach(field => {
        if (settings[field]) {
            settings[field] = parseFloat(settings[field]);
        }
    });

    // Convert boolean
    settings.emergency_stop = formData.has('emergency_stop');

    try {
        const response = await fetch('/api/v1/settings/', {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });

        if (response.ok) {
            showStatus('Settings saved successfully!', 'success');
        } else {
            const error = await response.text();
            showStatus(`Error: ${error}`, 'error');
        }
    } catch (error) {
        showStatus(`Network error: ${error.message}`, 'error');
    }
});

document.getElementById('reset-btn').addEventListener('click', async () => {
    if (!confirm('Reset all settings to defaults? This cannot be undone.')) return;

    try {
        const response = await fetch('/api/v1/settings/reset', { method: 'POST' });
        if (response.ok) {
            location.reload();
        }
    } catch (error) {
        showStatus(`Error resetting settings: ${error.message}`, 'error');
    }
});

function showStatus(message, type) {
    const statusEl = document.getElementById('settings-status');
    statusEl.textContent = message;
    statusEl.className = `status-message ${type}`;
    statusEl.style.display = 'block';

    setTimeout(() => {
        statusEl.style.display = 'none';
    }, 5000);
}