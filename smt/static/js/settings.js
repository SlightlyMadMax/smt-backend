const NUMERIC_FIELDS = [
  'min_profit_threshold', 'min_profit_percentage', 'max_investment_per_item',
  'buy_percentile', 'sell_percentile', 'min_volume_24h', 'min_volume_7d',
  'min_volatility_threshold', 'max_volatility_threshold', 'max_daily_loss',
  'max_hold_hours', 'min_return_on_capital_30d',
  'price_refresh_interval_minutes', 'stats_refresh_interval_minutes', 'cooldown_after_loss_hours',
  'max_concurrent_trades', 'price_history_days', 'analysis_window_days',
];

const BOOLEAN_FIELDS = ['emergency_stop', 'cancel_untracked_orders'];

function collectSettings(form) {
  const formData = new FormData(form);
  const settings = Object.fromEntries(formData.entries());

  NUMERIC_FIELDS.forEach(field => {
    if (settings[field] !== undefined && settings[field] !== '') {
      settings[field] = parseFloat(settings[field]);
    }
  });
  BOOLEAN_FIELDS.forEach(field => {
    settings[field] = formData.has(field);
  });

  return settings;
}

document.getElementById('settings-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    await SMT.patch('/api/v1/settings/', collectSettings(e.target));
    SMT.notify('Settings saved.');
  } catch (error) {
    SMT.notify(`Could not save settings: ${error.message}`, 'error');
  }
});

document.getElementById('reset-btn').addEventListener('click', async () => {
  if (!SMT.confirmAction('Reset all settings to defaults? This cannot be undone.')) return;
  try {
    await SMT.post('/api/v1/settings/reset');
    location.reload();
  } catch (error) {
    SMT.notify(`Could not reset settings: ${error.message}`, 'error');
  }
});
