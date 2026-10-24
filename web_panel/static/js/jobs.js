// Long operations (copies, restores, installs, restarts) run as jobs on the panel.
// This file starts them, follows them over the console WebSocket (with polling as a
// fallback) and draws the shared progress element where the action was started.
(() => {
  const ACTIVE = new Set(['queued', 'running']);
  const FAILED_VISIBLE_MS = 15 * 60 * 1000;
  const POLL_MS = 3000;
  const RECONNECT_MS = 4000;

  const jobs = new Map();
  const listeners = new Set();
  const waiters = new Map();
  let socket = null;
  let reconnectTimer = null;
  let pollTimer = null;

  const isActive = (job) => Boolean(job) && ACTIVE.has(job.status);
  const resolveNode = (target) => (typeof target === 'string' ? document.querySelector(target) : target);
  const wanted = () => listeners.size > 0 || waiters.size > 0;

  // A finished job never goes back to running because of a late or stale message.
  const remember = (job) => {
    if (!job || !job.id) return;
    const known = jobs.get(job.id);
    if (known && !isActive(known) && isActive(job)) return;
    jobs.set(job.id, job);
    listeners.forEach((listener) => { try { listener(job); } catch { /* one view must not break the others */ } });
    if (!isActive(job) && waiters.has(job.id)) {
      waiters.get(job.id).forEach((resolve) => resolve(job));
      waiters.delete(job.id);
    }
  };

  const fetchJob = async (id) => { try { remember(await Panel.api(`/api/jobs/${encodeURIComponent(id)}`)); } catch { /* try again on the next tick */ } };
  const list = async () => {
    const recent = await Panel.api('/api/jobs?limit=20');
    recent.slice().reverse().forEach(remember);
    return recent;
  };

  const schedulePoll = () => {
    if (pollTimer || !waiters.size) return;
    pollTimer = window.setTimeout(async () => {
      pollTimer = null;
      if (!socket || socket.readyState !== WebSocket.OPEN) await Promise.all([...waiters.keys()].map(fetchJob));
      schedulePoll();
    }, POLL_MS);
  };

  const connect = () => {
    if (socket || !wanted() || typeof WebSocket === 'undefined') return;
    try { socket = new WebSocket(Panel.websocketUrl('/ws/terminal')); } catch { socket = null; return; }
    socket.addEventListener('open', () => { list().catch(() => {}); });
    socket.addEventListener('message', (event) => {
      let payload = null;
      try { payload = JSON.parse(event.data); } catch { return; }
      if (payload && payload.type === 'job') remember(payload.job);
    });
    socket.addEventListener('close', () => {
      socket = null;
      if (!wanted() || reconnectTimer) return;
      reconnectTimer = window.setTimeout(() => { reconnectTimer = null; connect(); }, RECONNECT_MS);
    });
  };

  const waitFor = (job) => {
    if (!isActive(job)) return Promise.resolve(job);
    const promise = new Promise((resolve) => {
      if (!waiters.has(job.id)) waiters.set(job.id, []);
      waiters.get(job.id).push(resolve);
    });
    connect();
    schedulePoll();
    return promise;
  };

  const VIEW = `
    <div class="h-1.5 overflow-hidden rounded-full bg-zinc-800" role="progressbar" aria-valuemin="0" aria-valuemax="100" data-job-track>
      <div class="h-full rounded-full bg-emerald-400 transition duration-300" data-job-bar></div>
    </div>
    <p class="mt-2 leading-relaxed text-zinc-200" data-job-sentence></p>
    <p class="mt-0.5 text-sm text-zinc-500" data-job-meta></p>
    <p class="mt-1 hidden text-sm leading-relaxed text-zinc-400" data-job-hint></p>`;

  const overallPercent = (job) => {
    if (job.status === 'succeeded') return 100;
    const total = job.steps.length || 1;
    const finished = job.steps.filter((step) => step.state === 'done' || step.state === 'skipped').length;
    const inStep = isActive(job) ? (Number(job.percent) || 0) / 100 : 0;
    return Math.max(isActive(job) ? 3 : 0, Math.min(100, ((finished + inStep) / total) * 100));
  };

  // The reusable progress element: thin bar, what is happening now, and "Paso 2 de 4".
  const render = (target, job) => {
    const node = resolveNode(target);
    if (!node || !job) return;
    if (node.dataset.jobView !== '1') { node.innerHTML = VIEW; node.dataset.jobView = '1'; }
    node.classList.remove('hidden');
    node.dataset.jobId = job.id;
    const track = node.querySelector('[data-job-track]');
    const bar = node.querySelector('[data-job-bar]');
    const sentence = node.querySelector('[data-job-sentence]');
    const meta = node.querySelector('[data-job-meta]');
    const hint = node.querySelector('[data-job-hint]');
    const total = job.steps.length;
    const index = Number.isInteger(job.current_step) ? job.current_step : 0;
    const step = job.steps[index];
    const percent = Math.round(overallPercent(job));
    const failed = job.status === 'failed' || job.status === 'cancelled';

    bar.style.width = `${percent}%`;
    bar.classList.toggle('bg-emerald-400', !failed);
    bar.classList.toggle('bg-[#ec7a6a]', failed);
    track.setAttribute('aria-valuenow', String(percent));
    track.setAttribute('aria-label', job.title);
    sentence.classList.toggle('text-[#f3a79b]', failed);
    sentence.classList.toggle('text-zinc-200', !failed);
    sentence.textContent = failed ? (job.error || job.message) : job.message;

    if (isActive(job)) {
      const label = step && step.label !== job.message ? ` · ${step.label}` : '';
      meta.textContent = total ? `Paso ${index + 1} de ${total}${label}` : '';
    } else if (failed && total && step) {
      meta.textContent = `Se frenó en el paso ${index + 1} de ${total}: ${step.label}.`;
    } else {
      meta.textContent = '';
    }
    meta.hidden = !meta.textContent;
    hint.textContent = failed ? (job.next_step || '') : '';
    hint.classList.toggle('hidden', !hint.textContent);
  };

  const setBusy = (button, busy) => {
    const node = resolveNode(button);
    if (node) node.disabled = busy;
  };

  // Follow a job until it ends, keeping its progress element and button in sync.
  const track = async (job, { mount, button } = {}) => {
    const node = resolveNode(mount);
    const update = (latest) => { if (latest.id === job.id && node) render(node, latest); };
    listeners.add(update);
    update(jobs.get(job.id) || job);
    setBusy(button, true);
    try {
      return await waitFor(jobs.get(job.id) || job);
    } finally {
      listeners.delete(update);
      setBusy(button, false);
    }
  };

  // POST to an endpoint that answers 202 {job_id, job}; errors before the job starts throw.
  // ``onAccepted`` runs once the job exists (e.g. to close a confirmation dialog).
  const start = async (path, { mount, button, body, onAccepted } = {}) => {
    setBusy(button, true);
    let accepted;
    try {
      accepted = await Panel.api(path, body ? { method: 'POST', body } : { method: 'POST' });
    } catch (error) {
      setBusy(button, false);
      throw error;
    }
    remember(accepted.job);
    if (onAccepted) onAccepted(accepted.job);
    return track(accepted.job, { mount, button });
  };

  // After a reload: pick up a running job of these kinds, or show a recent failure.
  const resume = async ({ kinds, mount, button } = {}) => {
    let recent = [];
    try { recent = await list(); } catch { return null; }
    const latest = recent.find((job) => kinds.includes(job.kind));
    if (!latest) return null;
    if (isActive(latest)) return track(latest, { mount, button });
    const finishedAt = Date.parse(latest.finished_at || '');
    if (latest.status === 'failed' && Number.isFinite(finishedAt) && Date.now() - finishedAt < FAILED_VISIBLE_MS) {
      render(mount, latest);
    }
    return null;
  };

  const subscribe = (listener) => {
    listeners.add(listener);
    connect();
    return () => listeners.delete(listener);
  };

  const active = () => [...jobs.values()].filter(isActive);

  window.PanelJobs = { active, isActive, list, render, resume, start, subscribe, track };
})();
