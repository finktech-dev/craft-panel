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
    const colors = { RUNNING: 'bg-emerald-400', STOPPED: 'bg-rose-400', CRASHED: 'bg-rose-400', STARTING: 'bg-amber-400' };
    const labels = { RUNNING: 'ONLINE', STOPPED: 'STOPPED', CRASHED: 'CRASHED', STARTING: 'STARTING' };
    target.querySelector('span').className = `h-2.5 w-2.5 rounded-full ${colors[normalized] || 'bg-zinc-500'}`;
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
    document.querySelector('#logout-button')?.addEventListener('click', async () => { try { await api('/api/auth/logout', { method: 'POST' }); } finally { window.location.assign('/'); } });
    if (document.querySelector('#server-status')) {
      const refreshHeaderStatus = async () => {
        try {
          const metrics = await api('/api/server/metrics');
          setStatus(metrics.state);
          const navDev = document.querySelector('#nav-dev-badge');
          if (navDev) {
            if (metrics.dev_mode) {
              navDev.classList.remove('hidden');
              navDev.classList.add('flex');
            } else {
              navDev.classList.add('hidden');
              navDev.classList.remove('flex');
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
})();

document.addEventListener('DOMContentLoaded', () => {
  const toggle = document.querySelector('#topnav-toggle');
  const menu = document.querySelector('#mobile-nav');
  if (!toggle || !menu) return;
  const close = () => { menu.classList.add('hidden'); toggle.setAttribute('aria-expanded', 'false'); toggle.setAttribute('aria-label', 'Abrir navegación'); };
  toggle.addEventListener('click', () => {
    const opening = menu.classList.contains('hidden');
    menu.classList.toggle('hidden', !opening);
    toggle.setAttribute('aria-expanded', String(opening));
    toggle.setAttribute('aria-label', opening ? 'Cerrar navegación' : 'Abrir navegación');
    if (opening) menu.querySelector('a')?.focus();
  });
  menu.querySelectorAll('a').forEach((link) => link.addEventListener('click', close));
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !menu.classList.contains('hidden')) { close(); toggle.focus(); } });
});