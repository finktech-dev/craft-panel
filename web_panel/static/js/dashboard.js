(() => {
  const $ = (selector) => document.querySelector(selector);
  const text = (selector, value) => { const node = $(selector); if (node) node.textContent = value; };
  const esc = (value) => Panel.escapeHtml(value);

  const since = (seconds) => {
    const total = Math.max(0, Number(seconds) || 0);
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    if (hours >= 1) return `${hours} h ${minutes} min`;
    return `${Math.max(minutes, 1)} min`;
  };
  const formatDate = (value) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'en una fecha desconocida';
    const today = new Date();
    const time = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (date.toDateString() === today.toDateString()) return `hoy a las ${time}`;
    return `el ${date.toLocaleDateString([], { day: 'numeric', month: 'long' })} a las ${time}`;
  };

  let serverRunning = false;
  let externalPid = null;
  let lastMetrics = null;

  // Start, restart and graceful restart share the hero button and its progress element.
  const LIFECYCLE = ['start', 'restart', 'graceful_restart'];
  const lifecycleBusy = () => PanelJobs.active().some((job) => LIFECYCLE.includes(job.kind));

  // One sentence and one obvious action for each server state.
  const HERO = {
    RUNNING: { mark: 'state-on', kicker: 'Encendido', title: 'Tu servidor está encendido', summary: 'Tus amigos ya pueden entrar con la dirección de abajo.', action: 'Reiniciar' },
    STARTING: { mark: 'state-busy', kicker: 'Encendiendo', title: 'Tu servidor se está encendiendo', summary: 'Con muchos mods puede tardar unos minutos. No hace falta que hagas nada.', action: null },
    CRASHED: { mark: 'state-error', kicker: 'Se cerró solo', title: 'Tu servidor se cerró solo', summary: 'Mirá abajo qué pasó antes de volver a encenderlo.', action: 'Volver a encender' },
    STOPPED: { mark: '', kicker: 'Apagado', title: 'Tu servidor está apagado', summary: 'Encendelo cuando quieras jugar.', action: 'Encender' },
  };
  const setHero = (metrics) => {
    lastMetrics = metrics;
    const state = String(metrics?.state || 'STOPPED').toUpperCase();
    const hero = HERO[state] || HERO.STOPPED;
    serverRunning = Boolean(metrics?.is_running);
    const holder = $('#hero-state');
    holder?.classList.remove('state-on', 'state-busy', 'state-error');
    if (hero.mark) holder?.classList.add(hero.mark);
    text('#hero-kicker', hero.kicker);
    text('#dashboard-title', hero.title);
    text('#dashboard-summary', externalPid ? 'Hay otra ventana con el servidor abierto. Cerrala para manejarlo desde acá.' : hero.summary);
    text('#hero-meta', serverRunning
      ? `Encendido hace ${since(metrics.uptime_seconds)} · usa ${(Number(metrics.ram_used_mb || 0) / 1024).toFixed(1).replace('.', ',')} GB de memoria`
      : '');
    const button = $('#hero-action');
    if (!button) return;
    button.hidden = !hero.action;
    button.textContent = hero.action || '';
    button.disabled = !hero.action || Boolean(externalPid) || lifecycleBusy();
    // The side panel only offers what makes sense right now.
    const busy = lifecycleBusy() || Boolean(externalPid);
    const starting = state === 'STARTING';
    const setEnabled = (selector, enabled) => { const node = $(selector); if (node) node.disabled = !enabled; };
    setEnabled('#graceful-restart', serverRunning && !busy);
    setEnabled('[data-server-action="stop"]', (serverRunning || starting) && !externalPid);
    setEnabled('[data-server-action="start-silent"]', !serverRunning && !starting && !busy);
    setEnabled('[data-server-action="kill"]', (serverRunning || starting) && !externalPid);
  };

  // One short line while anything is running, so a reload never hides ongoing work.
  const setJobsNow = () => {
    const running = PanelJobs.active();
    $('#jobs-now')?.classList.toggle('hidden', running.length === 0);
    text('#jobs-now-text', running.map((job) => {
      const total = job.steps.length;
      const step = Number.isInteger(job.current_step) ? job.current_step + 1 : 1;
      return total ? `${job.title} (paso ${step} de ${total}).` : `${job.title}.`;
    }).join(' '));
  };

  const setConnection = (connection, tunnel) => {
    text('#connection-address', connection?.public_address || 'Todavía no hay dirección');
    text('#connection-message', connection?.message || 'No encontramos una dirección para compartir.');
    text('#connection-next-step', connection?.next_step || '');
    const button = $('#copy-connection');
    if (button) button.disabled = !connection?.can_share_with_friends;
    // No address yet: offer to read it from the official Playit app, or to paste it.
    const official = Boolean(tunnel?.external_agent && tunnel.external_agent !== 'not_installed');
    $('#connection-fix')?.classList.toggle('hidden', connection?.source !== 'local_only');
    $('#use-playit-address')?.classList.toggle('hidden', !official);
  };

  const setBackup = (backups) => {
    const latest = Array.isArray(backups) && backups.length
      ? [...backups].sort((a, b) => new Date(b.created_at) - new Date(a.created_at))[0]
      : null;
    text('#backup-status', latest
      ? `La última copia se hizo ${formatDate(latest.created_at)}. Si algo sale mal, podés volver a ese momento.`
      : 'Todavía no hay copias. Hacé una antes de instalar mods o cambiar cosas grandes.');
  };

  // Hidden warnings live in this browser. A warning comes back if it gets worse (warn -> danger)
  // or once it was fixed and shows up again later.
  const DISMISSED_KEY = 'cp.dismissedChecks';
  const readDismissed = () => {
    try { return new Set(JSON.parse(window.localStorage.getItem(DISMISSED_KEY) || '[]')); } catch { return new Set(); }
  };
  const writeDismissed = (set) => {
    try { window.localStorage.setItem(DISMISSED_KEY, JSON.stringify([...set])); } catch { /* private mode: hiding lasts until reload */ }
  };
  let dismissed = readDismissed();
  let lastSummary = null;
  const checkId = (item) => `${item.key}|${item.level}`;

  // Only what needs attention is listed; when everything is fine, one calm sentence.
  const setChecks = (summary) => {
    lastSummary = summary;
    const list = $('#safety-list');
    if (!list) return;
    if (!summary) {
      text('#safety-headline', 'No pudimos revisar el estado ahora. Probá recargar la página.');
      list.innerHTML = '';
      return;
    }
    // Forget hidden warnings that are fixed now, so they show again if they come back.
    const fixed = new Set(summary.items.filter((item) => item.level === 'ok').map((item) => item.key));
    const kept = new Set([...dismissed].filter((id) => !fixed.has(id.split('|')[0])));
    if (kept.size !== dismissed.size) { dismissed = kept; writeDismissed(dismissed); }

    const attention = summary.items.filter((item) => item.level === 'warn' || item.level === 'danger');
    const pending = attention.filter((item) => !dismissed.has(checkId(item)));
    const hiddenCount = attention.length - pending.length;
    text('#safety-count', pending.length ? `(${pending.length})` : '');
    // The section title already says "Cosas para revisar"; only speak up when there is nothing to show.
    const headline = $('#safety-headline');
    if (headline) {
      headline.hidden = pending.length > 0;
      headline.textContent = attention.length ? 'No hay nada nuevo para revisar.' : 'Todo en orden. No hay nada que revisar.';
    }
    const restore = $('#safety-restore');
    if (restore) {
      restore.classList.toggle('hidden', hiddenCount === 0);
      restore.textContent = hiddenCount === 1 ? 'Mostrar 1 aviso oculto' : `Mostrar ${hiddenCount} avisos ocultos`;
    }
    list.innerHTML = pending.map((item) => `
      <div class="check-row check-${esc(item.level)}">
        <span class="check-icon" aria-hidden="true">!</span>
        <div>
          <h3 class="font-semibold text-zinc-50">${esc(item.title)}</h3>
          <p class="mt-1 leading-relaxed text-zinc-400">${esc(item.detail)}</p>
          <div class="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-sm">
            ${item.action_href ? `<a href="${esc(item.action_href)}" class="link">${esc(item.action_label || 'Revisar')}</a>` : ''}
            <button type="button" class="text-zinc-500 hover:text-zinc-300" data-dismiss-check="${esc(checkId(item))}">Ocultar este aviso</button>
          </div>
        </div>
      </div>`).join('');
  };

  const EXTERNAL_TITLES = {
    is_our_server: 'El servidor ya está abierto en otra ventana',
    other_java_server: 'Hay otro servidor de Minecraft abierto',
    other_program_on_port: 'Otro programa está usando el puerto del servidor',
  };
  const setExternal = (external) => {
    externalPid = external?.detected ? external.pid : null;
    $('#external-server')?.classList.toggle('hidden', !externalPid);
    if (externalPid) {
      text('#external-title', EXTERNAL_TITLES[external.kind] || EXTERNAL_TITLES.is_our_server);
      text('#external-message', external.message);
    }
    // Why the panel thinks so, as a short list built with textContent only.
    const reasons = externalPid && Array.isArray(external.reasons) ? external.reasons : [];
    const list = $('#external-reasons');
    if (list) list.replaceChildren(...reasons.map((reason) => Object.assign(document.createElement('li'), { textContent: reason })));
    $('#external-reasons-title')?.classList.toggle('hidden', reasons.length === 0);
    // Only a Minecraft (Java) process can be closed from here; anything else just holds the port.
    const terminate = $('#external-terminate');
    if (terminate) terminate.hidden = !external?.can_terminate;
  };

  const query = async (path) => { try { return await Panel.api(path); } catch { return null; } };
  const refresh = async () => {
    const [metrics, connection, backups, safety, external, tunnel] = await Promise.all([
      query('/api/server/metrics'),
      query('/api/server/connection-info'),
      query('/api/backups'),
      query('/api/server/safety-summary'),
      query('/api/server/external'),
      query('/api/tunnel/status'),
    ]);
    setExternal(external);
    setHero(metrics);
    setConnection(connection, tunnel);
    setBackup(backups);
    setChecks(safety);
    text('#dashboard-updated', `Actualizado a las ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`);
  };

  const setOperationFeedback = (value) => text('#operation-feedback', value);
  const withBusy = async (button, pendingLabel, task) => {
    const original = button.textContent;
    button.disabled = true;
    if (pendingLabel) button.textContent = pendingLabel;
    try { await task(); } finally { button.disabled = false; button.textContent = original; }
  };
  const reportResult = (result, fallback) => { Panel.toast(result?.message || fallback); setOperationFeedback(result?.message || fallback); };
  const reportError = (error) => { Panel.toast(error.message, 'error'); setOperationFeedback(error.message); };

  // Long operations run as jobs: the progress element shows each step, and the
  // final sentence (or the error and what to do next) stays where it was started.
  // Success fades after a moment so an old "listo" never contradicts the current state;
  // failures stay until the next attempt.
  const reportJob = (job, mount) => {
    if (!job) return;
    if (job.status === 'succeeded') {
      Panel.toast(job.message);
      window.setTimeout(() => { if ($(mount)?.dataset.jobId === job.id) $(mount).classList.add('hidden'); }, 8000);
    } else {
      Panel.toast(job.error || job.message, 'error');
    }
  };
  const runJob = async (path, mount, button) => {
    setOperationFeedback('');
    try {
      reportJob(await PanelJobs.start(path, { mount, button }), mount);
    } catch (error) { reportError(error); }
    await refresh();
  };

  const closeActions = () => $('#server-actions')?.close();
  const runServerAction = async (button, action = button.dataset.serverAction) => {
    if (action === 'start') { await runJob('/api/server/start', '#hero-progress', button); return; }
    // Same start, without the Discord announcement; progress shows under the main button.
    if (action === 'start-silent') { closeActions(); await runJob('/api/server/start?dev_mode=true', '#hero-progress', $('#hero-action')); return; }
    const prompts = {
      stop: '¿Apagar el servidor? Quienes estén jugando se van a desconectar.',
      kill: '¿Forzar el cierre? Lo que no se haya guardado en los últimos minutos se pierde. Usalo solo si apagar no funciona.',
    };
    if (prompts[action] && !window.confirm(prompts[action])) return;
    closeActions();
    setOperationFeedback('');
    await withBusy(button, null, async () => {
      try {
        const result = await Panel.api(`/api/server/${action}`, { method: 'POST' });
        reportResult(result, 'Listo.');
      } catch (error) { reportError(error); }
    });
    await refresh();
  };
  const createBackup = async (button) => {
    if (!window.confirm('¿Hacer una copia de tu mundo ahora? Se puede seguir jugando mientras tanto.')) return;
    await runJob('/api/backups', '#backup-progress', button);
  };
  const gracefulRestart = async (button) => {
    if (!window.confirm('¿Reiniciar? Se avisa en el chat y se reinicia en 10 segundos.')) return;
    closeActions();
    await runJob('/api/server/graceful-restart?countdown=10', '#hero-progress', button);
  };
  const terminateExternal = async (button) => {
    if (!externalPid) return;
    if (!window.confirm('¿Cerrar el servidor que está abierto aparte? Primero le pedimos que guarde el mundo y se cierre, como si apretaras Ctrl+C en su ventana; puede tardar hasta un minuto. Si no responde, lo cerramos a la fuerza.')) return;
    await withBusy(button, 'Guardando y cerrando…', async () => {
      try {
        const result = await Panel.api('/api/server/external/terminate', { method: 'POST', body: { pid: externalPid, confirm: true } });
        reportResult(result, 'Listo, se cerró.');
      } catch (error) { reportError(error); }
    });
    await refresh();
  };

  document.addEventListener('DOMContentLoaded', () => {
    $('#copy-connection')?.addEventListener('click', async () => {
      const value = $('#connection-address')?.textContent || '';
      try { await navigator.clipboard.writeText(value); Panel.toast('Dirección copiada. Pegala en el chat con tus amigos.'); }
      catch { Panel.toast('No se pudo copiar. Seleccioná la dirección y copiala a mano.', 'error'); }
    });
    $('#use-playit-address')?.addEventListener('click', ({ currentTarget }) => withBusy(currentTarget, 'Buscando…', async () => {
      try { reportResult(await Panel.api('/api/tunnel/external/address', { method: 'POST' }), 'Listo.'); } catch (error) { reportError(error); }
      await refresh();
    }));
    $('#connection-address-form')?.addEventListener('submit', async (event) => {
      event.preventDefault();
      const input = $('#connection-address-input');
      if (!input?.value.trim()) { setOperationFeedback('Pegá la dirección que te muestra Playit.'); return; }
      try {
        reportResult(await Panel.api('/api/tunnel/address', { method: 'POST', body: { public_address: input.value } }), 'Listo.');
        input.value = '';
      } catch (error) { reportError(error); }
      await refresh();
    });
    $('#hero-action')?.addEventListener('click', ({ currentTarget }) => (
      serverRunning ? gracefulRestart(currentTarget) : runServerAction(currentTarget, 'start')
    ));
    document.querySelectorAll('[data-server-action]').forEach((button) => button.addEventListener('click', () => runServerAction(button)));
    $('#create-backup')?.addEventListener('click', ({ currentTarget }) => createBackup(currentTarget));
    $('#graceful-restart')?.addEventListener('click', ({ currentTarget }) => gracefulRestart(currentTarget));
    $('#external-terminate')?.addEventListener('click', ({ currentTarget }) => terminateExternal(currentTarget));
    $('#open-server-actions')?.addEventListener('click', () => $('#server-actions')?.showModal());
    $('#safety-list')?.addEventListener('click', (event) => {
      const button = event.target.closest('[data-dismiss-check]');
      if (!button) return;
      dismissed.add(button.dataset.dismissCheck);
      writeDismissed(dismissed);
      setChecks(lastSummary);
    });
    $('#safety-restore')?.addEventListener('click', () => {
      dismissed = new Set();
      writeDismissed(dismissed);
      setChecks(lastSummary);
    });
    // Whether "Cosas para revisar" is open is remembered in this browser.
    const safetySection = $('#safety-section');
    if (safetySection) {
      try { if (window.localStorage.getItem('cp.safetyOpen') === 'false') safetySection.open = false; } catch { /* keep it open */ }
      safetySection.addEventListener('toggle', () => {
        try { window.localStorage.setItem('cp.safetyOpen', String(safetySection.open)); } catch { /* not remembered */ }
      });
    }
    PanelJobs.subscribe((job) => {
      setJobsNow();
      if (LIFECYCLE.includes(job.kind) && lastMetrics) setHero(lastMetrics);
    });
    // After a reload, put running (or recently failed) work back where it was started.
    const resumed = (mount) => (job) => { if (job) { reportJob(job, mount); refresh(); } };
    PanelJobs.resume({ kinds: LIFECYCLE, mount: '#hero-progress' }).then(resumed('#hero-progress'));
    PanelJobs.resume({ kinds: ['backup'], mount: '#backup-progress', button: '#create-backup' }).then(resumed('#backup-progress'));
    refresh();
    window.setInterval(refresh, 15_000);
  });
})();
