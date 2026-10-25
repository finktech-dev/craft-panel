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

  const show = (selector, visible) => $(selector)?.classList.toggle('hidden', !visible);

  // One block per Playit situation: running, installed but off, broken, or not installed.
  const renderInternet = () => {
    if (!state) return;
    const enabled = state.playit_enabled;
    const playit = state.playit_state || 'not_installed';
    const broken = playit === 'stopped' && !state.playit_connected;
    const ownAgent = playit === 'not_installed' && state.playit_connected;
    show('#playit-done', !enabled || ownAgent);
    say('#playit-done', enabled ? 'Listo, Playit ya está conectado.' : 'Elegiste jugar solo en esta casa. Lo podés cambiar después en Ajustes.');
    show('#playit-running', enabled && playit === 'running');
    show('#playit-stopped', enabled && playit === 'stopped' && !broken);
    show('#playit-autostart-help', state.playit_autostart === false);
    show('#playit-broken', enabled && broken);
    show('#playit-missing', enabled && playit === 'not_installed' && !ownAgent);
    show('#friend-address', enabled && (playit === 'running' || (playit === 'stopped' && !broken)));
    say('#friend-address-current', state.friend_address
      ? `Tus amigos entran con: ${state.friend_address}`
      : 'Todavía no tenemos la dirección para tus amigos. Tocá el botón y la buscamos en Playit.');
  };

  const relativeTime = (iso) => {
    const seconds = (new Date(iso).getTime() - Date.now()) / 1000;
    const format = new Intl.RelativeTimeFormat('es', { numeric: 'auto' });
    const units = [['year', 31536000], ['month', 2592000], ['day', 86400], ['hour', 3600], ['minute', 60]];
    for (const [unit, size] of units) {
      if (Math.abs(seconds) >= size) return format.format(Math.round(seconds / size), unit);
    }
    return 'hace un momento';
  };

  // "Tu mundo «world» ya se jugó: entraron 4 jugadores, la última vez hace 2 días."
  const historyText = () => {
    if (state.history_phase !== 'played') return '';
    const players = state.known_players;
    const who = players === 0 ? 'todavía no entró nadie más' : players === 1 ? 'entró 1 jugador' : `entraron ${players} jugadores`;
    const when = state.last_played_at ? `, la última vez ${relativeTime(state.last_played_at)}` : '';
    return `Tu mundo «${state.world_name}» ya se jugó: ${who}${when}.`;
  };

  // A server that is on, or already played, needs other words than a first install.
  // Ajustes > Acceso por Internet links here with ?review=access to go straight to that step.
  let reviewingAccess = new URLSearchParams(window.location.search).get('review') === 'access';
  const applyHistory = () => {
    const played = state.history_phase === 'played';
    const running = state.server_running || state.external_server;
    say('#onboarding-title', running ? 'Tu servidor' : played ? 'Revisemos tu servidor' : 'Vamos a armar tu servidor');
    say('#onboarding-lead', played || running
      ? 'Ya lo usaste antes: solo revisamos lo que falta. No borramos nada.'
      : 'Son cuatro pasos cortos. No borramos nada que ya tengas.');
    document.querySelectorAll('.onboarding-history').forEach((node) => {
      node.textContent = historyText();
      node.classList.toggle('hidden', !node.textContent);
    });
    show('#ready-first-time', !played);

    const showRunning = running && !reviewingAccess;
    show('#onboarding-running', showRunning);
    show('#onboarding-steps', !showRunning);
    say('#onboarding-running-title', state.server_running ? 'Tu servidor ya está encendido' : 'Hay un servidor abierto fuera del panel');
    say('#onboarding-running-text', state.server_running
      ? 'No hace falta seguir estos pasos. Si querés, revisá cómo entran tus amigos.'
      : 'Lo abriste desde otra ventana. Desde el Inicio podés cerrarlo o seguir usándolo así.');
    return showRunning;
  };

  const refresh = async () => {
    try {
      state = await Panel.api('/api/onboarding/status');
      $('#onboarding-loading').classList.add('hidden');
      if (applyHistory()) {
        document.querySelectorAll('.onboarding-step').forEach((node) => node.classList.add('hidden'));
        return;
      }
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
      showStep(reviewingAccess ? 'connection' : effectiveStep());
    } catch (error) { showError(error.message); }
  };

  // After starting, wait for an address friends can use. With the official Playit app it is
  // asked from the app's local status (never its key) until one shows up.
  const waitForFriendAddress = async () => {
    say('#ready-feedback', 'Buscando la dirección para tus amigos.');
    for (let attempt = 0; attempt < 20; attempt += 1) {
      const info = await Panel.api('/api/server/connection-info').catch(() => null);
      if (info?.can_share_with_friends) return info.public_address;
      const tunnel = await Panel.api('/api/tunnel/status').catch(() => null);
      if (tunnel?.last_error) throw new Error(tunnel.last_error);
      if (tunnel?.external_agent === 'running') {
        await Panel.api('/api/tunnel/external/address?use_agent_key=false', { method: 'POST' }).catch(() => null);
      }
      await sleep(1500);
    }
    return null;
  };

  // A new server may need a newer Java than the one found: download it first, in the same click.
  const ensureJavaFor = async (version, button) => {
    const check = await Panel.api(`/api/onboarding/status?minecraft_version=${encodeURIComponent(version)}`);
    if (check.java_ready) return true;
    say('#install-feedback', `${check.java_message} Primero bajamos Java, después el juego.`);
    const job = await PanelJobs.start('/api/onboarding/java', { mount: '#install-progress', button, body: { minecraft_version: version } });
    return job.status === 'succeeded';
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
        if (!status.server_ready) throw new Error('Todavía no encontramos el archivo que lo enciende (run.bat) dentro de la carpeta server.');
        say('#install-feedback', 'Encontramos tu servidor. No cambiamos nada.');
        await refresh();
      } catch (error) { say('#install-feedback', error.message); }
    });

    $('#install-server')?.addEventListener('click', async ({ currentTarget }) => {
      if (!$('#accept-eula').checked) { say('#install-feedback', 'Para seguir tenés que aceptar las reglas de uso de Minecraft.'); return; }
      try {
        if (!(await ensureJavaFor($('#minecraft-version').value, currentTarget))) return;
        say('#install-feedback', 'Con mods puede tardar varios minutos. Si cerrás esta ventana, la instalación sigue.');
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

    // The official Playit app: turn it on, read its address, or save one pasted by hand.
    $('#start-playit')?.addEventListener('click', ({ currentTarget }) => withButton(currentTarget, 'Encendiendo…', async () => {
      try {
        await Panel.api('/api/tunnel/external/start', { method: 'POST' });
        say('#connection-feedback', 'Listo, Playit está encendido.');
        await refresh();
      } catch (error) { say('#connection-feedback', error.message); }
    }));
    $('#use-playit-address')?.addEventListener('click', ({ currentTarget }) => withButton(currentTarget, 'Buscando…', async () => {
      try {
        const result = await Panel.api('/api/tunnel/external/address', { method: 'POST' });
        say('#connection-feedback', result.message);
        await refresh();
      } catch (error) { say('#connection-feedback', `${error.message} También podés pegar la dirección abajo.`); }
    }));
    $('#friend-address-form')?.addEventListener('submit', async (event) => {
      event.preventDefault();
      const input = $('#friend-address-input');
      if (!input.value.trim()) { say('#connection-feedback', 'Pegá la dirección que te muestra Playit.'); return; }
      try {
        const result = await Panel.api('/api/tunnel/address', { method: 'POST', body: { public_address: input.value } });
        input.value = '';
        say('#connection-feedback', result.message);
        await refresh();
      } catch (error) { say('#connection-feedback', error.message); }
    });

    $('#onboarding-review-access')?.addEventListener('click', () => {
      reviewingAccess = true;
      refresh();
    });

    $('#friends-continue')?.addEventListener('click', async () => {
      state = await Panel.api('/api/onboarding/status');
      // Reviewing access with the server already on: there is nothing to start, go home.
      if (state.server_running || state.external_server) {
        window.location.assign('/');
        return;
      }
      if (!internetReady()) {
        say('#connection-feedback', 'Primero instalá Playit, o elegí "Jugar solo en esta casa" en Otras opciones.');
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
        try { address = await waitForFriendAddress(); } catch (error) { say('#ready-feedback', error.message); }
      }
      say('#ready-feedback', address
        ? `¡Listo! Pasales esta dirección a tus amigos: ${address}`
        : 'Tu servidor está encendido. En el Inicio vas a ver la dirección para tus amigos.');
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
