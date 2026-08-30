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

  global.SMT = {
    request,
    get: (url) => request(url),
    post: (url, body) => request(url, {method: 'POST', body}),
    patch: (url, body) => request(url, {method: 'PATCH', body}),
    remove: (url, body) => request(url, {method: 'DELETE', body}),
    notify,
    confirmAction,
  };
})(window);
