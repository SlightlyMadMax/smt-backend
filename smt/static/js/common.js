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
