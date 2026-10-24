(() => {
  const toastRegion = () => document.querySelector('#toast-region');
  const csrfToken = () => document.querySelector('meta[name="csrf-token"]')?.content || '';
  const nativeFetch = window.fetch.bind(window);

  window.fetch = (input, init = {}) => {
    const method = String(init.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
    const destination = typeof input === 'string' ? input : input.url;
    const isSameOrigin = new URL(destination, window.location.origin).origin === window.location.origin;
    if (!isSameOrigin || !['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) return nativeFetch(input, init);
    const token = csrfToken();
    if (!token) return nativeFetch(input, init);
    const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
    headers.set('X-CSRF-Token', token);
    return nativeFetch(input, { ...init, headers });
  };

  const messageFor = async (response) => {
    const fallback = `La operación falló (${response.status}).`;
    try {
      const data = await response.json();
      if (Array.isArray(data.detail)) {
        return data.detail.map((issue) => issue.msg || 'Dato inválido.').join(' ');
      }
      if (typeof data.detail === 'object' && data.detail !== null) {
        return data.detail.message || fallback;
      }
      return data.detail || data.message || fallback;
    } catch {
      return fallback;
    }
  };

  const readResponse = async (response) => {
    if (response.status === 401) {
      window.location.assign('/');
      throw Object.assign(new Error('La sesión expiró. Volvé a ingresar el PIN.'), { status: 401 });
    }
    if (!response.ok) {
      throw Object.assign(new Error(await messageFor(response)), { status: response.status });
    }
    if (response.status === 204) return null;
    return response.json();
  };

  const api = async (path, options = {}) => {
    const headers = new Headers(options.headers || {});
    const fetchOptions = { ...options, headers, credentials: 'same-origin' };
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(String(options.method || 'GET').toUpperCase())) {
      const token = csrfToken();
      if (token) headers.set('X-CSRF-Token', token);
    }
    if (options.body && !(options.body instanceof FormData) && typeof options.body !== 'string') {
      headers.set('Content-Type', 'application/json');
      fetchOptions.body = JSON.stringify(options.body);
    }
    return readResponse(await fetch(path, fetchOptions));
  };

  const toast = (message, type = 'success') => {
    const region = toastRegion();
    if (!region) return;
    const node = document.createElement('div');
    const colors = type === 'error' ? 'border-rose-400/40 bg-rose-950 text-rose-100' : 'border-emerald-400/40 bg-emerald-950 text-emerald-100';
    node.className = `pointer-events-auto rounded-lg border px-4 py-3 text-sm shadow-lg ${colors}`;
    node.textContent = message;
    region.append(node);
    window.setTimeout(() => node.remove(), 4500);
  };

  const setStatus = (state) => {
    const target = document.querySelector('#server-status');
    if (!target) return;
    const normalized = String(state || 'STOPPED').toUpperCase();
    const states = { RUNNING: 'state-on', STOPPED: '', CRASHED: 'state-error', STARTING: 'state-busy' };
    const labels = { RUNNING: 'Encendido', STOPPED: 'Apagado', CRASHED: 'Se cerró solo', STARTING: 'Encendiendo…' };
    target.classList.remove('state-on', 'state-busy', 'state-error');
    if (states[normalized]) target.classList.add(states[normalized]);
    target.querySelector('span:last-child').textContent = labels[normalized] || normalized;
  };

  const websocketUrl = (path) => {
    const token = csrfToken();
    const query = token ? `${path.includes('?') ? '&' : '?'}csrf=${encodeURIComponent(token)}` : '';
    return `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}${path}${query}`;
  };

  const sendConsoleCommand = (command) => new Promise((resolve, reject) => {
    const socket = new WebSocket(websocketUrl('/ws/terminal'));
    const timeout = window.setTimeout(() => { socket.close(); reject(new Error('La consola no respondió a tiempo.')); }, 7000);
    socket.addEventListener('open', () => socket.send(JSON.stringify({ type: 'command', command })));
    socket.addEventListener('message', (event) => {
      const payload = JSON.parse(event.data);
      if (payload.type === 'command_accepted') { window.clearTimeout(timeout); socket.close(); resolve(payload); }
      if (payload.type === 'error') { window.clearTimeout(timeout); socket.close(); reject(new Error(payload.message)); }
    });
    socket.addEventListener('error', () => { window.clearTimeout(timeout); reject(new Error('No se pudo conectar con la consola.')); });
  });

  const formatDuration = (seconds) => {
    const value = Math.max(0, Number(seconds) || 0);
    const hours = Math.floor(value / 3600);
    const minutes = Math.floor((value % 3600) / 60);
    const remainingSeconds = Math.floor(value % 60);
    return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(remainingSeconds).padStart(2, '0')}`;
  };

  const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[character]);

  document.addEventListener('DOMContentLoaded', () => {
    const logout = async () => { try { await api('/api/auth/logout', { method: 'POST' }); } finally { window.location.assign('/'); } };
    document.querySelectorAll('#logout-button, [data-logout]').forEach((button) => button.addEventListener('click', logout));
    if (document.querySelector('#server-status')) {
      const refreshHeaderStatus = async () => {
        try {
          const metrics = await api('/api/server/metrics');
          setStatus(metrics.state);
          const navDev = document.querySelector('#nav-dev-badge');
          if (navDev) {
            if (metrics.dev_mode) {
              navDev.classList.remove('hidden');
              navDev.classList.add('inline-flex');
            } else {
              navDev.classList.add('hidden');
              navDev.classList.remove('inline-flex');
            }
          }
        } catch { /* La página conserva su último estado visible. */ }
      };
      refreshHeaderStatus();
      window.setInterval(refreshHeaderStatus, 5000);
    }
    const publicAddress = document.querySelector('#public-address');
    const copyAddress = document.querySelector('#copy-address');
    if (publicAddress) {
      const refreshTunnel = async () => {
        try {
          const tunnel = await api('/api/tunnel/status');
          if (tunnel.public_address) {
            publicAddress.textContent = tunnel.public_address;
            copyAddress?.classList.remove('hidden');
          }
        } catch { /* Playit puede no estar configurado todavía. */ }
      };
      refreshTunnel();
      window.setInterval(refreshTunnel, 10000);
    }
    copyAddress?.addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(publicAddress.textContent); toast('Dirección copiada.', 'success'); }
      catch { toast('No se pudo copiar la dirección.', 'error'); }
    });
  });

  window.Panel = { api, escapeHtml, formatDuration, readResponse, sendConsoleCommand, setStatus, toast, websocketUrl };

  // Replacement for inline `onerror` handlers (blocked by the strict CSP):
  // images with data-fallback-src swap to that URL once when they fail to load.
  const useFallbackImage = (image) => {
    const fallback = image.dataset.fallbackSrc;
    if (!fallback || image.src === new URL(fallback, window.location.href).href) return;
    image.src = fallback;
  };
  // Load errors do not bubble, so listen in the capture phase.
  document.addEventListener('error', (event) => {
    if (event.target instanceof HTMLImageElement) useFallbackImage(event.target);
  }, true);
  // Images that already failed before this deferred script ran.
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('img[data-fallback-src]').forEach((image) => {
      if (image.complete && image.naturalWidth === 0 && image.getAttribute('src')) useFallbackImage(image);
    });
  });
})();

// "Jugadores" and "Mundo" share /worlds; highlight the one matching the open tab.
document.addEventListener('DOMContentLoaded', () => {
  if (document.body.dataset.page !== 'worlds') return;
  const sync = () => {
    const players = window.location.hash === '#whitelist';
    document.querySelectorAll('.topbar a[href="/worlds"], .topbar a[href="/worlds#whitelist"]').forEach((link) => {
      const isPlayers = link.getAttribute('href') === '/worlds#whitelist';
      if (isPlayers === players) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
    });
  };
  window.addEventListener('hashchange', sync);
  sync();
});

// Search boxes for long lists: <input data-list-filter="#list-id"> hides the rows of that list
// that do not match. Rows re-rendered by a page script are filtered again automatically.
document.addEventListener('DOMContentLoaded', () => {
  const fold = (text) => String(text || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  document.querySelectorAll('input[data-list-filter]').forEach((input) => {
    const list = document.querySelector(input.dataset.listFilter);
    if (!list) return;
    const apply = () => {
      const query = fold(input.value.trim());
      [...list.children].forEach((row) => { row.hidden = Boolean(query) && !fold(row.textContent).includes(query); });
    };
    input.addEventListener('input', apply);
    new MutationObserver(apply).observe(list, { childList: true });
  });
});

// Simple page sections shown one at a time: a [data-page-tabs] row of [data-page-tab="key"]
// buttons and matching [data-page-panel="key"] panels. The open one is kept in the hash (#key),
// so reloads and links land on it; the first one is the default.
document.addEventListener('DOMContentLoaded', () => {
  const bar = document.querySelector('[data-page-tabs]');
  if (!bar) return;
  const buttons = [...bar.querySelectorAll('[data-page-tab]')];
  const keys = buttons.map((button) => button.dataset.pageTab);
  const open = (key, remember = true) => {
    const target = keys.includes(key) ? key : keys[0];
    buttons.forEach((button) => button.setAttribute('aria-selected', button.dataset.pageTab === target ? 'true' : 'false'));
    document.querySelectorAll('[data-page-panel]').forEach((panel) => { panel.hidden = panel.dataset.pagePanel !== target; });
    if (remember) {
      const hash = target === keys[0] ? window.location.pathname : `#${target}`;
      try { history.replaceState(null, '', hash); } catch { /* the panel still switches */ }
    }
  };
  bar.addEventListener('click', (event) => {
    const button = event.target.closest('[data-page-tab]');
    if (button) open(button.dataset.pageTab);
  });
  bar.addEventListener('keydown', (event) => {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
    const index = buttons.indexOf(event.target);
    if (index < 0) return;
    const next = buttons[(index + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length];
    next.focus();
    open(next.dataset.pageTab);
  });
  const fromHash = () => open(window.location.hash.slice(1), false);
  window.addEventListener('hashchange', fromHash);
  fromHash();
  window.Panel.openPageTab = open;
});

// Header menus are <details> elements: close them on outside click or Escape.
document.addEventListener('DOMContentLoaded', () => {
  const menus = [...document.querySelectorAll('details[data-menu]')];
  document.addEventListener('click', (event) => {
    menus.forEach((menu) => { if (menu.open && !menu.contains(event.target)) menu.open = false; });
  });
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    menus.forEach((menu) => { if (menu.open) { menu.open = false; menu.querySelector('summary')?.focus(); } });
  });
});