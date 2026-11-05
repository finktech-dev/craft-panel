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
  let lastState = 'STOPPED';
  let stoppingSince = null;
  let opInFlight = false;
  let metricFailures = 0;

  // Start, restart and graceful restart share the hero button and its progress element.
  const LIFECYCLE = ['start', 'restart', 'graceful_restart'];
  const lifecycleBusy = () => PanelJobs.active().some((job) => LIFECYCLE.includes(job.kind));

  // One sentence and one obvious action for each server state.
  const HERO = {
    RUNNING: { mark: 'state-on', kicker: 'Encendido', title: 'Tu servidor está encendido', summary: 'Tus amigos ya pueden entrar con la dirección de abajo.', action: 'Reiniciar' },
    STARTING: { mark: 'state-busy', kicker: 'Encendiendo', title: 'Tu servidor se está encendiendo', summary: 'Con muchos mods puede tardar unos minutos. No hace falta que hagas nada.', action: null },
    STOPPING: { mark: 'state-busy', kicker: 'Apagando', title: 'Tu servidor se está apagando', summary: 'Apagando… guardando el mundo. No lo vuelvas a encender hasta que termine.', action: 'Apagando…', locked: true },
    CRASHED: { mark: 'state-error', kicker: 'Se cerró solo', title: 'Tu servidor se cerró solo', summary: 'Mirá abajo qué pasó antes de volver a encenderlo.', action: 'Volver a encender' },
    START_FAILED: { mark: 'state-error', kicker: 'No llegó a encender', title: 'Tu servidor no llegó a encender', summary: 'Algo falló mientras se encendía. Mirá abajo qué pasó y probá de nuevo.', action: 'Probar de nuevo' },
    STOPPED: { mark: '', kicker: 'Apagado', title: 'Tu servidor está apagado', summary: 'Encendelo cuando quieras jugar.', action: 'Encender' },
  };
  const setHero = (metrics) => {
    lastMetrics = metrics;
    const state = String(metrics?.state || 'STOPPED').toUpperCase();
    const hero = HERO[state] || HERO.STOPPED;
    lastState = state;
    if (state === 'STOPPING') { if (stoppingSince === null) stoppingSince = Date.now(); } else { stoppingSince = null; }
    setProblem(state);
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
    button.disabled = !hero.action || hero.locked || Boolean(externalPid) || lifecycleBusy();
    // The side panel only offers what makes sense right now.
    const stopping = state === 'STOPPING';
    const busy = lifecycleBusy() || Boolean(externalPid) || stopping;
    const starting = state === 'STARTING';
    const setEnabled = (selector, enabled) => { const node = $(selector); if (node) node.disabled = !enabled; };
    setEnabled('#graceful-restart', serverRunning && !busy);
    setEnabled('[data-server-action="stop"]', (serverRunning || starting) && !stopping && !externalPid);
    // "Apagar" sits next to the main button only while there is something to shut down.
    const stopButton = $('#hero-stop');
    if (stopButton) stopButton.hidden = !(serverRunning || starting) || stopping;
    setEnabled('[data-server-action="start-silent"]', !serverRunning && !starting && !busy);
    setEnabled('[data-server-action="kill"]', (serverRunning || starting || stopping) && !externalPid);
    updateSlowStop();
  };

  // Shutdown normally takes seconds; past 30 s offer the existing force-close.
  const SLOW_STOP_MS = 30_000;
  const updateSlowStop = () => {
    $('#stop-slow')?.classList.toggle('hidden', !(stoppingSince !== null && Date.now() - stoppingSince > SLOW_STOP_MS));
  };

  // Plain-words notice when the server closed on its own or never finished turning on.
  const REPORT_MAX_AGE_MS = 2 * 60 * 60 * 1000;
  let problemFor = null;
  const setProblem = async (state) => {
    const box = $('#server-problem');
    if (!box) return;
    if (state !== 'CRASHED' && state !== 'START_FAILED') { problemFor = null; box.classList.add('hidden'); return; }
    if (problemFor === state) return;
    problemFor = state;
    text('#server-problem-title', state === 'START_FAILED' ? 'El servidor no llegó a encender' : 'El servidor se cerró solo');
    text('#server-problem-message', 'Buscando el motivo…');
    box.classList.remove('hidden');
    let message = 'No encontramos un motivo claro. Abrí la consola para ver los últimos mensajes.';
    let link = '/console';
    try {
      const report = await Panel.api('/api/server/crash-report');
      const age = Date.now() - new Date(report.timestamp).getTime();
      if (report?.cause && age < REPORT_MAX_AGE_MS) {
        message = `Motivo: ${report.cause}${report.suggestion ? ` ${report.suggestion}` : ''}`;
        link = '/crashes';
      }
    } catch { /* no report: keep the generic text */ }
    if (problemFor !== state) return;
    text('#server-problem-message', message);
    $('#server-problem-link')?.setAttribute('href', link);
  };

  // The panel does not answer: say so instead of pretending the server is off.
  const setOffline = () => {
    lastState = 'OFFLINE';
    const holder = $('#hero-state');
    holder?.classList.remove('state-on', 'state-error');
    holder?.classList.add('state-busy');
    text('#hero-kicker', 'Sin conexión');
    text('#dashboard-title', 'No podemos hablar con el panel');
    text('#dashboard-summary', 'Sin conexión, reintentando… Si el panel se cerró, abrilo de nuevo.');
    text('#hero-meta', '');
    const button = $('#hero-action');
    if (button) button.disabled = true;
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
    // Friends on the owner's VPN can also use its address, even when Playit gives the main one.
    const otherVpns = (connection?.vpn_addresses || []).filter((item) => item.address !== connection?.public_address);
    text('#connection-vpn', otherVpns.map((item) => `También por ${item.name}: ${item.address}`).join(' · '));
    $('#connection-vpn')?.classList.toggle('hidden', otherVpns.length === 0);
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
    // Some locales already end the time with a period ("8:20 a. m.").
    const when = formatDate(latest?.created_at).replace(/\.$/, '');
    text('#backup-status', latest
      ? `La última copia se hizo ${when}. Si algo sale mal, podés volver a ese momento.`
      : 'Todavía no hay copias. Hacé una antes de instalar mods o cambiar cosas grandes.');
  };

  // Who is in the game right now; the whole section only shows while the server runs.
  const setPlayers = (online) => {
    const players = online?.is_running && Array.isArray(online.players) ? online.players : [];
    $('#players-section')?.classList.toggle('hidden', !online?.is_running);
    text('#players-count', online?.is_running ? `(${players.length} de ${online.max_players})` : '');
    $('#players-empty')?.classList.toggle('hidden', players.length > 0);
    const list = $('#players-list');
    if (!list) return;
    list.innerHTML = players.map((player) => `
      <li class="flex items-center gap-2 rounded-full border border-zinc-800 py-1.5 pl-2 pr-3 text-sm text-zinc-200">
        <img src="${esc(player.avatar_url)}" alt="" class="h-5 w-5 rounded-sm" loading="lazy">
        <span>${esc(player.username)}</span>
      </li>`).join('');
  };

  // A newer panel release, once per page load. "Ahora no" hides that version in this browser only.
  const UPDATE_KEY = 'cp.updateDismissed';
  const showUpdate = async () => {
    const update = await query('/api/updates');
    if (!update?.available) return;
    let hidden = null;
    try { hidden = window.localStorage.getItem(UPDATE_KEY); } catch { /* private mode */ }
    if (hidden === update.latest) return;
    text('#update-latest', update.latest);
    text('#update-current', update.current);
    if (update.url) $('#update-link')?.setAttribute('href', update.url);
    $('#update-notice')?.classList.remove('hidden');
    $('#update-dismiss')?.addEventListener('click', () => {
      try { window.localStorage.setItem(UPDATE_KEY, update.latest); } catch { /* hidden until reload */ }
      $('#update-notice')?.classList.add('hidden');
    }, { once: true });
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
    const [metrics, connection, backups, safety, external, tunnel, online] = await Promise.all([
      query('/api/server/metrics'),
      query('/api/server/connection-info'),
      query('/api/backups'),
      query('/api/server/safety-summary'),
      query('/api/server/external'),
      query('/api/tunnel/status'),
      query('/api/server/online-players'),
    ]);
    if (metrics) {
      metricFailures = 0;
      setExternal(external);
      setHero(metrics);
    } else {
      // A failed query says nothing about the server: keep the buttons as they were.
      metricFailures += 1;
      if (metricFailures >= 2) setOffline();
    }
    setPlayers(online);
    setConnection(connection, tunnel);
    setBackup(backups);
    setChecks(safety);
    text('#dashboard-updated', `Actualizado a las ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`);
  };

  // Poll faster while something is in progress so the page never lags behind the server.
  let pollTimer = null;
  const schedule = (delay) => {
    window.clearTimeout(pollTimer);
    const fast = opInFlight || lifecycleBusy() || ['STARTING', 'STOPPING', 'OFFLINE'].includes(lastState);
    pollTimer = window.setTimeout(async () => { await refresh(); schedule(); }, delay ?? (fast ? 2500 : 15_000));
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

  // Own confirmation dialog: the safe answer is first and focused, the risky one is red.
  // Escape, the backdrop and the safe button all mean "no".
  const confirmDialog = ({ title, message, yes, no, danger = true }) => new Promise((resolve) => {
    const dialog = $('#confirm-dialog');
    if (!dialog || typeof dialog.showModal !== 'function') { resolve(window.confirm(`${title} ${message}`)); return; }
    const yesButton = $('#confirm-yes');
    const noButton = $('#confirm-no');
    text('#confirm-title', title);
    text('#confirm-message', message);
    yesButton.textContent = yes;
    noButton.textContent = no;
    yesButton.classList.toggle('btn-danger', danger);
    yesButton.classList.toggle('btn-primary', !danger);
    noButton.classList.toggle('btn-primary', danger);
    noButton.classList.toggle('btn-quiet', !danger);
    let answer = false;
    const onYes = () => { answer = true; dialog.close(); };
    const onNo = () => dialog.close();
    const onBackdrop = (event) => { if (event.target === dialog) dialog.close(); };
    dialog.addEventListener('close', () => {
      yesButton.removeEventListener('click', onYes);
      noButton.removeEventListener('click', onNo);
      dialog.removeEventListener('click', onBackdrop);
      resolve(answer);
    }, { once: true });
    yesButton.addEventListener('click', onYes);
    noButton.addEventListener('click', onNo);
    dialog.addEventListener('click', onBackdrop);
    dialog.showModal();
    noButton.focus();
  });

  const closeActions = () => $('#server-actions')?.close();
  const runServerAction = async (button, action = button.dataset.serverAction) => {
    if (action === 'start') { await runJob('/api/server/start', '#hero-progress', button); return; }
    // Same start, without the Discord announcement; progress shows under the main button.
    if (action === 'start-silent') { closeActions(); await runJob('/api/server/start?dev_mode=true', '#hero-progress', $('#hero-action')); return; }
    const prompts = {
      stop: { title: '¿Apagar el servidor?', message: 'Quienes estén jugando se van a desconectar.', yes: 'Sí, apagar', no: 'No, seguir jugando' },
      kill: { title: '¿Forzar el cierre?', message: 'Lo que no se haya guardado en los últimos minutos se pierde. Usalo solo si apagar no funciona.', yes: 'Sí, forzar el cierre', no: 'No, esperar' },
    };
    if (prompts[action] && !await confirmDialog(prompts[action])) return;
    closeActions();
    setOperationFeedback(action === 'stop' ? 'Apagando… guardando el mundo.' : '');
    // The dialog is closed, so progress shows in the hero through fast polling.
    opInFlight = true;
    schedule(0);
    try {
      reportResult(await Panel.api(`/api/server/${action}`, { method: 'POST' }), 'Listo.');
    } catch (error) { reportError(error); }
    opInFlight = false;
    await refresh();
    schedule();
  };
  const createBackup = async (button) => {
    if (!await confirmDialog({ title: '¿Hacer una copia de tu mundo ahora?', message: 'Se puede seguir jugando mientras tanto.', yes: 'Sí, hacer la copia', no: 'Ahora no', danger: false })) return;
    await runJob('/api/backups', '#backup-progress', button);
  };
  const gracefulRestart = async (button) => {
    if (!await confirmDialog({ title: '¿Reiniciar el servidor?', message: 'Se avisa en el chat y se reinicia en 10 segundos. Quienes estén jugando se van a desconectar un momento.', yes: 'Sí, reiniciar', no: 'No, seguir jugando' })) return;
    closeActions();
    await runJob('/api/server/graceful-restart?countdown=10', '#hero-progress', button);
  };
  const terminateExternal = async (button) => {
    if (!externalPid) return;
    if (!await confirmDialog({ title: '¿Cerrar el servidor que quedó abierto en otra ventana?', message: 'Primero le pedimos que guarde el mundo y se apague solo; puede tardar hasta un minuto. Si no responde, lo cerramos a la fuerza.', yes: 'Sí, cerrarlo', no: 'No, dejarlo' })) return;
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
    $('#force-stop')?.addEventListener('click', () => {
      const kill = $('[data-server-action="kill"]');
      if (kill) runServerAction(kill);
    });
    refresh().then(() => schedule());
    showUpdate();
  });
})();
