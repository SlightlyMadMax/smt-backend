(function (global) {
  'use strict';

  async function errorMessage(response) {
    try {
      const body = await response.json();
      if (typeof body.detail === 'string') return body.detail;
      if (Array.isArray(body.detail)) return body.detail.map(d => d.msg || d).join('; ');
      return JSON.stringify(body);
    } catch (e) {
      return response.statusText || `HTTP ${response.status}`;
    }
  }

  async function request(url, {method = 'GET', body} = {}) {
    const options = {method, headers: {}};
    if (body !== undefined) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }

    let response;
    try {
      response = await fetch(url, options);
    } catch (e) {
      throw new Error(`Network error: ${e.message}`);
    }

    if (!response.ok) {
      throw new Error(await errorMessage(response));
    }
    if (response.status === 204) return null;

    const type = response.headers.get('content-type') || '';
    return type.includes('application/json') ? response.json() : response.text();
  }

  function toastContainer() {
    let el = document.getElementById('toast-container');
    if (!el) {
      el = document.createElement('div');
      el.id = 'toast-container';
      el.className = 'toast-container';
      document.body.appendChild(el);
    }
    return el;
  }

  function notify(message, type = 'success', timeout = 5000) {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.setAttribute('role', type === 'error' ? 'alert' : 'status');
    toast.textContent = message;
    toastContainer().appendChild(toast);
    setTimeout(() => toast.remove(), timeout);
  }

  function confirmAction(message) {
    return global.confirm(message);
  }

  function comparator(direction, valueOf) {
    const sign = direction === 'ascending' ? 1 : -1;
    return (a, b) => {
      const left = valueOf(a);
      const right = valueOf(b);
      const leftMissing = left == null || left === '';
      const rightMissing = right == null || right === '';

      if (leftMissing && rightMissing) return 0;
      if (leftMissing) return 1;
      if (rightMissing) return -1;

      const leftNumber = Number(left);
      const rightNumber = Number(right);
      if (!Number.isNaN(leftNumber) && !Number.isNaN(rightNumber)) return sign * (leftNumber - rightNumber);
      return sign * String(left).localeCompare(String(right));
    };
  }

  function sortControl(table, {key = null, direction = 'descending', onChange}) {
    const headers = Array.from(table.querySelectorAll('th[data-sort]'));
    let current = {key, direction};

    function paint() {
      headers.forEach(th => {
        const arrow = th.querySelector('.sort-arrow');
        if (arrow) arrow.remove();

        if (th.dataset.sort !== current.key) {
          th.removeAttribute('aria-sort');
          return;
        }
        th.setAttribute('aria-sort', current.direction);
        th.insertAdjacentHTML(
          'beforeend',
          `<span class="sort-arrow" aria-hidden="true">${current.direction === 'ascending' ? '▲' : '▼'}</span>`,
        );
      });
    }

    function pick(next, fallback) {
      if (next === current.key) {
        current = {key: next, direction: current.direction === 'ascending' ? 'descending' : 'ascending'};
      } else {
        current = {key: next, direction: fallback || 'descending'};
      }
      paint();
      onChange(current.key, current.direction);
    }

    headers.forEach(th => {
      th.tabIndex = 0;
      th.setAttribute('role', 'button');
      th.addEventListener('click', () => pick(th.dataset.sort, th.dataset.sortDefault));
      th.addEventListener('keydown', ev => {
        if (ev.key !== 'Enter' && ev.key !== ' ') return;
        ev.preventDefault();
        pick(th.dataset.sort, th.dataset.sortDefault);
      });
    });

    paint();

    return {
      get key() {
        return current.key;
      },
      get direction() {
        return current.direction;
      },
      sort(rows, valueOf) {
        if (!current.key) return rows.slice();
        return rows.slice().sort(comparator(current.direction, valueOf || (row => row[current.key])));
      },
    };
  }

  function pager(container, {pageSize, onChange}) {
    let offset = 0;
    let total = 0;

    container.classList.add('pager');
    container.innerHTML =
      '<span class="pager-range"></span>' +
      '<button type="button" class="btn small" data-page="previous">Previous</button>' +
      '<button type="button" class="btn small" data-page="next">Next</button>';

    const range = container.querySelector('.pager-range');
    const previous = container.querySelector('[data-page="previous"]');
    const next = container.querySelector('[data-page="next"]');

    function render() {
      container.hidden = total <= pageSize;
      if (container.hidden) return;

      range.textContent = `${offset + 1}–${Math.min(offset + pageSize, total)} of ${total}`;
      previous.disabled = offset === 0;
      next.disabled = offset + pageSize >= total;
    }

    function move(by) {
      const wanted = offset + by * pageSize;
      if (wanted < 0 || wanted >= total) return;
      offset = wanted;
      render();
      onChange();
    }

    previous.addEventListener('click', () => move(-1));
    next.addEventListener('click', () => move(1));

    return {
      pageSize,
      get offset() {
        return offset;
      },
      update(newTotal) {
        total = newTotal;
        if (offset >= total) offset = Math.max(0, Math.floor(Math.max(total - 1, 0) / pageSize) * pageSize);
        render();
      },
      reset() {
        offset = 0;
      },
    };
  }


  const OUTLIER_FACTOR = 3;
  const CHART_W = 620;
  const CHART_H = 170;
  const CHART_PAD = 28;

  function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = value == null ? '' : value;
    return div.innerHTML;
  }

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

  function priceChart(allRecords, buyTarget, sellTarget, days) {
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
      'aria-label="Price over the last ' + days + ' days">' +
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

  function depthLists(book) {
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

  function statsList(rows) {
    return '<dl class="details-stats">' + rows.map(pair =>
      '<div><dt>' + pair[0] + '</dt><dd>' +
      (pair[1] == null || pair[1] === '' ? '-' : escapeHtml(pair[1])) + '</dd></div>').join('') + '</dl>';
  }

  global.SMT = {
    request,
    get: (url) => request(url),
    post: (url, body) => request(url, {method: 'POST', body}),
    patch: (url, body) => request(url, {method: 'PATCH', body}),
    remove: (url, body) => request(url, {method: 'DELETE', body}),
    notify,
    confirmAction,
    comparator,
    sortControl,
    pager,
    escapeHtml,
    priceChart,
    depthLists,
    statsList,
  };
})(window);

document.addEventListener('DOMContentLoaded', async () => {
  const el = document.getElementById('wallet-balance');
  if (!el) return;

  try {
    const wallet = await SMT.get('/api/v1/steam/wallet');
    el.textContent = wallet.balance == null ? 'unavailable' : wallet.balance;
    el.closest('.wallet').classList.toggle('wallet-stale', wallet.stale);
    if (wallet.stale) {
      el.closest('.wallet').title = 'Steam did not answer; this is the last known balance';
    }
  } catch (e) {
    el.textContent = 'unavailable';
    el.closest('.wallet').classList.add('wallet-stale');
  }
});
