// Change the version of a server that already exists, from Ajustes > Tu servidor.
(() => {
  const byId = (id) => document.getElementById(id);
  const current = byId('change-version-current');
  const openBtn = byId('change-version-open');
  const dialog = byId('change-version-dialog');
  if (!current || !openBtn || !dialog) return;

  const note = byId('change-version-note');
  const select = byId('change-version-select');
  const unavailable = byId('change-version-unavailable');
  const retry = byId('change-version-retry');
  const backup = byId('change-version-backup');
  const fresh = byId('change-version-fresh');
  const confirmBtn = byId('change-version-confirm');
  const cancelBtn = byId('change-version-cancel');
  const fromText = byId('change-version-from');
  const PROGRESS = '#change-version-progress';
  const SUPPORTED = { vanilla: 'vanilla', neoforge: 'neoforge', fabric: 'fabric' };

  let env = null;       // { loader, minecraft_version, label }
  let running = false;

  const isBusyState = (state) => ['RUNNING', 'STARTING', 'STOPPING'].includes(state);

  const render = () => {
    if (!env || !env.loader) {
      current.textContent = 'Todavía no hay un servidor instalado.';
      openBtn.hidden = true;
      return;
    }
    current.textContent = 'Ahora: ' + (env.label || 'Minecraft');
    if (!SUPPORTED[env.loader]) {
      openBtn.hidden = true;
      if (note) {
        note.hidden = false;
        note.textContent = 'Por ahora solo se puede cambiar la versión de servidores Vanilla, NeoForge o Fabric.';
      }
      return;
    }
    openBtn.hidden = false;
    openBtn.disabled = running;
    if (note) {
      note.hidden = !running;
      note.textContent = 'Apagá el servidor para poder cambiar la versión.';
    }
  };

  const loadState = async () => {
    try { env = await Panel.api('/api/mods/environment'); } catch { env = null; }
    try {
      const metrics = await Panel.api('/api/server/metrics');
      running = !!(metrics && (metrics.is_running || isBusyState(metrics.state)));
    } catch { running = false; }
    render();
  };

  const fillVersions = async () => {
    select.innerHTML = '';
    if (unavailable) unavailable.classList.add('hidden');
    confirmBtn.disabled = true;
    try {
      const flavor = SUPPORTED[env.loader];
      const data = await Panel.api('/api/onboarding/versions?flavor=' + encodeURIComponent(flavor));
      const versions = (data && data.versions) || [];
      if (!versions.length) throw new Error('empty');
      for (const version of versions) {
        const label = version.minecraft_version + (version.stable ? '' : ' (versión de prueba)')
          + (version.minecraft_version === env.minecraft_version ? ' — la de ahora' : '');
        select.add(new Option(label, version.minecraft_version));
      }
      confirmBtn.disabled = false;
    } catch {
      if (unavailable) unavailable.classList.remove('hidden');
    }
  };

  const open = async () => {
    if (running || !env || !SUPPORTED[env.loader]) { render(); return; }
    if (fromText) fromText.textContent = 'Ahora tenés ' + (env.label || 'Minecraft') + '. Elegí a qué versión pasar.';
    if (backup) backup.checked = true;
    if (fresh) fresh.checked = false;
    if (typeof dialog.showModal === 'function') dialog.showModal(); else dialog.setAttribute('open', '');
    await fillVersions();
  };

  const close = () => { if (dialog.open) dialog.close(); };

  const confirmChange = async () => {
    const minecraftVersion = select.value;
    if (!minecraftVersion) return;
    const deleteWorld = Boolean(fresh && fresh.checked);
    if (deleteWorld && !window.confirm('Vas a BORRAR el mundo actual para empezar de cero. Esto no se puede deshacer. ¿Seguro?')) return;
    const body = { minecraft_version: minecraftVersion, make_backup: Boolean(backup && backup.checked), delete_world: deleteWorld };
    try {
      await PanelJobs.start('/api/server/change-version', {
        mount: PROGRESS,
        button: openBtn,
        body,
        onAccepted: () => close(),
      });
      await loadState();
    } catch (error) {
      Panel.toast((error && error.message) || 'No pudimos cambiar la versión. Probá de nuevo en un momento.');
    }
  };

  openBtn.addEventListener('click', open);
  if (cancelBtn) cancelBtn.addEventListener('click', close);
  confirmBtn.addEventListener('click', confirmChange);
  if (retry) retry.addEventListener('click', fillVersions);

  loadState();
  if (window.PanelJobs && PanelJobs.resume) {
    PanelJobs.resume({ kinds: ['change_version'], mount: PROGRESS, button: openBtn });
  }
})();
