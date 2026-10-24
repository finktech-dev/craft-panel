(() => {
  const $ = (selector) => document.querySelector(selector);
  const esc = (value) => Panel.escapeHtml(value);
  const STEPS = ['java', 'server', 'connection', 'ready'];
  // Lets someone continue without a friends list on purpose, without looping back to step 3.
  const FRIENDS_SKIPPED_KEY = 'craft-onboarding-friends-skipped';

  let state = null;
  const chosenVersion = {};

  const say = (selector, message) => { const node = $(selector); if (node) node.textContent = message; };
  const showError = (message) => { const node = $('#onboarding-error'); node.textContent = message; node.classList.remove('hidden'); };
  const selectedFlavor = () => document.querySelector('input[name="flavor"]:checked')?.value || 'vanilla';
  const friendsSkipped = () => { try { return sessionStorage.getItem(FRIENDS_SKIPPED_KEY) === '1'; } catch { return false; } };
  const rememberFriendsSkipped = () => { try { sessionStorage.setItem(FRIENDS_SKIPPED_KEY, '1'); } catch { /* private mode */ } };
  const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));

  const showStep = (name) => {
    document.querySelectorAll('.onboarding-step').forEach((node) => node.classList.toggle('hidden', node.dataset.step !== name));
    const current = STEPS.indexOf(name);
    document.querySelectorAll('[data-step-indicator]').forEach((node) => {
      const index = STEPS.indexOf(node.dataset.stepIndicator);
      node.dataset.state = index < current ? 'done' : index === current ? 'current' : 'pending';
      node.querySelector('.step-mark').textContent = index < current ? '✓' : String(index + 1);
      if (index === current) node.setAttribute('aria-current', 'step'); else node.removeAttribute('aria-current');
    });
  };

  const internetReady = () => !state?.playit_enabled || state?.playit_connected;
  const effectiveStep = () => {
    if (state.first_step === 'connection' && internetReady() && friendsSkipped()) return 'ready';
    return state.first_step;
  };

  const fillVersions = () => {
    const flavor = selectedFlavor();
    const select = $('#minecraft-version');
    const versions = state?.recommended_versions?.[flavor] || [];
    select.replaceChildren(...versions.map((value) => new Option(value, value, false, value === chosenVersion[flavor])));
    $('#install-new-server')?.classList.toggle('hidden', flavor === 'import');
    $('#import-existing-server')?.classList.toggle('hidden', flavor !== 'import');
  };

  const renderFriends = async () => {
    let whitelist = { enabled: false, players: [] };
    try { whitelist = await Panel.api('/api/whitelist'); } catch { /* the server folder may not exist yet */ }
    $('#friends-list').innerHTML = whitelist.players.map((player) => `
      <li class="friend-chip">${esc(player.name)}<button type="button" data-remove-friend="${esc(player.name)}" aria-label="Quitar a ${esc(player.name)}">×</button></li>
    `).join('');
    return whitelist;
  };

  const renderInternet = () => {
    const done = internetReady();
    $('#playit-done')?.classList.toggle('hidden', !done);
    $('#playit-steps')?.classList.toggle('hidden', done);
    if (state && !state.playit_enabled) say('#playit-done', 'Elegiste jugar solo en esta casa. Lo podés cambiar después en Ajustes.');
  };

  const refresh = async () => {
    try {
      state = await Panel.api('/api/onboarding/status');
      $('#onboarding-loading').classList.add('hidden');
      say('#java-message', state.java_ready ? '' : state.java_message);
      fillVersions();
      renderInternet();
      await renderFriends();

      const launch = await Panel.api('/api/runtime/launch-settings');
      const ram = $('#onboarding-ram');
      ram.replaceChildren(...Array.from({ length: launch.maximum_recommended_ram_gb }, (_, index) => {
        const value = index + 1;
        return new Option(`${value} GB`, String(value), false, value === launch.allocated_ram_gb);
      }));
      say('#onboarding-ram-hint', `Tu computadora tiene ${launch.total_ram_gb} GB. Recomendamos hasta ${launch.maximum_recommended_ram_gb} GB para que el resto siga andando bien.`);
      showStep(effectiveStep());
    } catch (error) { showError(error.message); }
  };

  const waitForPublicAddress = async () => {
    say('#ready-feedback', 'Buscando la dirección para tus amigos.');
    for (let attempt = 0; attempt < 30; attempt += 1) {
      await sleep(1000);
      const tunnel = await Panel.api('/api/tunnel/status');
      if (tunnel.public_address) return tunnel.public_address;
      if (tunnel.last_error) throw new Error(tunnel.last_error);
    }
    return null;
  };

  const withButton = async (button, pendingLabel, task) => {
    const original = button.textContent;
    button.disabled = true;
    if (pendingLabel) button.textContent = pendingLabel;
    try { await task(); } finally { button.disabled = false; button.textContent = original; }
  };

  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-refresh]').forEach((button) => button.addEventListener('click', refresh));
    document.querySelectorAll('input[name="flavor"]').forEach((input) => input.addEventListener('change', fillVersions));
    $('#minecraft-version')?.addEventListener('change', (event) => { chosenVersion[selectedFlavor()] = event.target.value; });

    // Downloads and installs run as jobs; their progress shows right under the button.
    $('#download-java')?.addEventListener('click', async ({ currentTarget }) => {
      const version = $('#minecraft-version')?.value || state?.recommended_versions?.vanilla?.[0];
      say('#java-feedback', '');
      try {
        const body = version ? { minecraft_version: version } : {};
        const job = await PanelJobs.start('/api/onboarding/java', { mount: '#java-progress', button: currentTarget, body });
        if (job.status === 'succeeded') await refresh();
      } catch (error) { say('#java-feedback', error.message); }
    });

    $('#check-imported-server')?.addEventListener('click', async () => {
      say('#install-feedback', 'Revisando la carpeta…');
      try {
        const status = await Panel.api('/api/onboarding/status');
        if (!status.server_ready) throw new Error('Todavía no encontramos el archivo de inicio (run.bat) dentro de la carpeta server.');
        say('#install-feedback', 'Encontramos tu servidor. No tocamos nada.');
        await refresh();
      } catch (error) { say('#install-feedback', error.message); }
    });

    $('#install-server')?.addEventListener('click', async ({ currentTarget }) => {
      if (!$('#accept-eula').checked) { say('#install-feedback', 'Para seguir tenés que aceptar las reglas de uso de Minecraft.'); return; }
      say('#install-feedback', 'Con mods puede tardar varios minutos. Si cerrás esta ventana, la instalación sigue.');
      try {
        const job = await PanelJobs.start('/api/onboarding/install', {
          mount: '#install-progress',
          button: currentTarget,
          body: { flavor: selectedFlavor(), minecraft_version: $('#minecraft-version').value, accept_eula: true },
        });
        say('#install-feedback', '');
        if (job.status === 'succeeded') await refresh();
      } catch (error) { say('#install-feedback', error.message); }
    });

    // Friends list: the first name added turns the list on, so only listed people can join.
    $('#friends-form')?.addEventListener('submit', async (event) => {
      event.preventDefault();
      const input = $('#friend-name');
      const username = input.value.trim();
      if (!/^[A-Za-z0-9_]{3,16}$/.test(username)) {
        say('#friends-feedback', 'Los nombres de Minecraft tienen entre 3 y 16 letras, números o guiones bajos.');
        return;
      }
      say('#friends-feedback', `Agregando a ${username}…`);
      try {
        await Panel.api('/api/whitelist/add', { method: 'POST', body: { username } });
        const whitelist = await renderFriends();
        if (!whitelist.enabled) await Panel.api('/api/whitelist/toggle', { method: 'POST', body: { enabled: true } });
        say('#friends-feedback', `${username} ya puede entrar.`);
        input.value = '';
        input.focus();
        state = await Panel.api('/api/onboarding/status');
      } catch (error) { say('#friends-feedback', error.message); }
    });
    $('#friends-list')?.addEventListener('click', async (event) => {
      const button = event.target.closest('[data-remove-friend]');
      if (!button) return;
      try {
        await Panel.api('/api/whitelist/remove', { method: 'POST', body: { username: button.dataset.removeFriend } });
        await renderFriends();
      } catch (error) { say('#friends-feedback', error.message); }
    });

    const showPlayitClaim = (claimUrl) => {
      const link = $('#playit-claim-link');
      if (!claimUrl || !link) return false;
      link.href = claimUrl;
      link.textContent = 'Abrir Playit para aprobar esta computadora';
      $('#playit-claim').classList.remove('hidden');
      return true;
    };
    $('#begin-playit-onboarding')?.addEventListener('click', ({ currentTarget }) => withButton(currentTarget, 'Preparando…', async () => {
      try {
        let tunnel = await Panel.api('/api/tunnel/begin-claim', { method: 'POST' });
        for (let attempt = 0; !tunnel.claim_url && attempt < 20; attempt += 1) {
          await sleep(500);
          tunnel = await Panel.api('/api/tunnel/status');
        }
        if (!showPlayitClaim(tunnel.claim_url)) throw new Error('Playit no respondió. Revisá tu conexión a Internet e intentá de nuevo.');
        say('#connection-feedback', 'Aprobá esta computadora en Playit y después volvé acá.');
      } catch (error) { say('#connection-feedback', error.message); }
    }));
    $('#complete-playit-claim')?.addEventListener('click', async () => {
      try {
        await Panel.api('/api/tunnel/complete-claim', { method: 'POST' });
        say('#connection-feedback', '');
        await refresh();
      } catch (error) { say('#connection-feedback', error.message); }
    });
    $('#show-manual-playit')?.addEventListener('click', () => {
      $('#manual-playit-secret')?.classList.remove('hidden');
      $('#show-manual-playit')?.classList.add('hidden');
      $('#onboarding-playit-secret')?.focus();
    });
    $('#connect-playit-onboarding')?.addEventListener('click', async () => {
      try {
        await Panel.api('/api/tunnel/setup', { method: 'POST', body: { agent_secret: $('#onboarding-playit-secret').value } });
        await refresh();
      } catch (error) { say('#connection-feedback', error.message); }
    });
    $('#local-only-onboarding')?.addEventListener('click', async () => {
      try {
        const current = await Panel.api('/api/runtime/launch-settings');
        await Panel.api('/api/runtime/launch-settings', { method: 'PUT', body: { allocated_ram_gb: current.allocated_ram_gb, playit_enabled: false } });
        await refresh();
      } catch (error) { say('#connection-feedback', error.message); }
    });

    $('#friends-continue')?.addEventListener('click', async () => {
      state = await Panel.api('/api/onboarding/status');
      if (!internetReady()) {
        say('#connection-feedback', 'Conectá Playit o elegí "Jugar solo en esta casa" en Otras opciones.');
        return;
      }
      if (!state.whitelist_enabled) {
        const ok = window.confirm('¿Seguir sin lista de amigos? Cualquiera que consiga la dirección va a poder entrar.');
        if (!ok) { $('#friend-name')?.focus(); return; }
        rememberFriendsSkipped();
      }
      showStep('ready');
    });

    // Once the start job ends, tell the host what to do next in one sentence.
    const afterStart = async (job, playitEnabled) => {
      if (!job || job.status !== 'succeeded') { say('#ready-feedback', ''); return; }
      let address = null;
      if (playitEnabled) {
        try { address = await waitForPublicAddress(); } catch (error) { say('#ready-feedback', error.message); }
      }
      say('#ready-feedback', address
        ? `¡Listo! Pasales esta dirección a tus amigos: ${address}`
        : 'Tu servidor está encendido. En el inicio vas a ver la dirección para compartir.');
      $('#onboarding-done')?.classList.remove('hidden');
    };

    $('#start-from-onboarding')?.addEventListener('click', ({ currentTarget }) => withButton(currentTarget, null, async () => {
      say('#ready-feedback', '');
      try {
        const current = await Panel.api('/api/runtime/launch-settings');
        await Panel.api('/api/runtime/launch-settings', { method: 'PUT', body: { allocated_ram_gb: Number($('#onboarding-ram').value), playit_enabled: current.playit_enabled } });
        const job = await PanelJobs.start('/api/server/start', { mount: '#start-progress', button: currentTarget });
        await afterStart(job, current.playit_enabled);
      } catch (error) { say('#ready-feedback', error.message); }
    }));

    // After a reload, show the install, Java download or first start that is still running.
    PanelJobs.resume({ kinds: ['install_java'], mount: '#java-progress', button: '#download-java' })
      .then((job) => { if (job?.status === 'succeeded') refresh(); });
    PanelJobs.resume({ kinds: ['install_server'], mount: '#install-progress', button: '#install-server' })
      .then((job) => { if (job?.status === 'succeeded') refresh(); });
    PanelJobs.resume({ kinds: ['start'], mount: '#start-progress', button: '#start-from-onboarding' })
      .then((job) => afterStart(job, Boolean(state?.playit_enabled)));

    refresh();
  });
})();
