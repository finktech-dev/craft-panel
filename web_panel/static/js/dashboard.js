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
    const restartButton = $('#graceful-restart');
    if (restartButton) restartButton.disabled = lifecycleBusy();
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

  const setConnection = (connection) => {
    text('#connection-address', connection?.public_address || 'Todavía no hay dirección');
    text('#connection-message', connection?.message || 'No encontramos una dirección para compartir.');
    text('#connection-next-step', connection?.next_step || '');
    const button = $('#copy-connection');
    if (button) button.disabled = !connection?.can_share_with_friends;
  };

  const setBackup = (backups) => {
    const latest = Array.isArray(backups) && backups.length
      ? [...backups].sort((a, b) => new Date(b.created_at) - new Date(a.created_at))[0]
      : null;
    text('#backup-status', latest
      ? `La última copia se hizo ${formatDate(latest.created_at)}. Si algo sale mal, podés volver a ese momento.`
      : 'Todavía no hay copias. Hacé una antes de instalar mods o cambiar cosas grandes.');
  };

  // Only what needs attention is listed; when everything is fine, one calm sentence.
  const setChecks = (summary) => {
    const list = $('#safety-list');
    if (!list) return;
    if (!summary) {
      text('#safety-headline', 'No pudimos revisar el estado ahora. Probá recargar la página.');
      list.innerHTML = '';
      return;
    }
    const pending = summary.items.filter((item) => item.level === 'warn' || item.level === 'danger');
    // The section title already says "Cosas para revisar"; only speak up when there is nothing to show.
    const headline = $('#safety-headline');
    if (headline) {
      headline.hidden = pending.length > 0;
      headline.textContent = 'Todo en orden. No hay nada que revisar.';
    }
    list.innerHTML = pending.map((item) => `
      <div class="check-row check-${esc(item.level)}">
        <span class="check-icon" aria-hidden="true">!</span>
        <div>
          <h3 class="font-semibold text-zinc-50">${esc(item.title)}</h3>
          <p class="mt-1 leading-relaxed text-zinc-400">${esc(item.detail)}</p>
          ${item.action_href ? `<a href="${esc(item.action_href)}" class="link mt-2 inline-block text-sm">${esc(item.action_label || 'Revisar')}</a>` : ''}
        </div>
      </div>`).join('');
  };

  const setExternal = (external) => {
    externalPid = external?.detected ? external.pid : null;
    $('#external-server')?.classList.toggle('hidden', !externalPid);
    if (externalPid) text('#external-message', external.message);
  };

  const query = async (path) => { try { return await Panel.api(path); } catch { return null; } };
  const refresh = async () => {
    const [metrics, connection, backups, safety, external] = await Promise.all([
      query('/api/server/metrics'),
      query('/api/server/connection-info'),
      query('/api/backups'),
      query('/api/server/safety-summary'),
      query('/api/server/external'),
    ]);
    setExternal(external);
    setHero(metrics);
    setConnection(connection);
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

  const runServerAction = async (button, action = button.dataset.serverAction) => {
    if (action === 'start') { await runJob('/api/server/start', '#hero-progress', button); return; }
    const prompts = {
      stop: '¿Apagar el servidor? Quienes estén jugando se van a desconectar.',
      kill: '¿Forzar el cierre? Lo que no se haya guardado en los últimos minutos se pierde. Usalo solo si apagar no funciona.',
    };
    if (prompts[action] && !window.confirm(prompts[action])) return;
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
    await runJob('/api/server/graceful-restart?countdown=10', '#hero-progress', button);
  };
  const terminateExternal = async (button) => {
    if (!externalPid) return;
    if (!window.confirm('¿Cerrar el servidor que está abierto en la otra ventana? Lo que no se haya guardado se pierde. Si podés, mejor cerralo desde esa ventana.')) return;
    await withBusy(button, 'Cerrando…', async () => {
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
    $('#hero-action')?.addEventListener('click', ({ currentTarget }) => (
      serverRunning ? gracefulRestart(currentTarget) : runServerAction(currentTarget, 'start')
    ));
    document.querySelectorAll('[data-server-action]').forEach((button) => button.addEventListener('click', () => runServerAction(button)));
    $('#create-backup')?.addEventListener('click', ({ currentTarget }) => createBackup(currentTarget));
    $('#graceful-restart')?.addEventListener('click', ({ currentTarget }) => gracefulRestart(currentTarget));
    $('#external-terminate')?.addEventListener('click', ({ currentTarget }) => terminateExternal(currentTarget));
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
