(() => {
  const showError = (message) => { const node = document.querySelector('#onboarding-error'); node.textContent = message; node.classList.remove('hidden'); };
  const selectedFlavor = () => document.querySelector('input[name="flavor"]:checked')?.value || 'vanilla';
  const setServerMode = () => {
    const isImport = selectedFlavor() === 'import';
    document.querySelector('#install-new-server')?.classList.toggle('hidden', isImport);
    document.querySelector('#import-existing-server')?.classList.toggle('hidden', !isImport);
  };
  const showStep = (name) => {
    document.querySelectorAll('.onboarding-step').forEach(node => node.classList.toggle('hidden', node.dataset.step !== name));
    document.querySelectorAll('[data-step-indicator]').forEach(node => node.classList.toggle('border-emerald-400', node.dataset.stepIndicator === name));
  };
  const waitForPublicAddress = async (feedback) => {
    feedback.textContent = 'El servidor está iniciando. Preparando tu dirección de Playit…';
    for (let attempt = 0; attempt < 30; attempt += 1) {
      await new Promise(resolve => window.setTimeout(resolve, 1000));
      const tunnel = await Panel.api('/api/tunnel/status');
      if (tunnel.public_address) {
        feedback.textContent = `¡Listo! Compartí esta dirección con tus amigos: ${tunnel.public_address}`;
        return;
      }
      if (tunnel.last_error) throw new Error(tunnel.last_error);
    }
    feedback.textContent = 'El servidor está iniciando. Playit todavía no informó una dirección; esperá un momento y actualizá esta página.';
  };
  const refresh = async () => {
    try {
      const state = await Panel.api('/api/onboarding/status');
      document.querySelector('#onboarding-loading').classList.add('hidden');
      document.querySelector('#java-message').textContent = state.java_message;
      const flavor = selectedFlavor();
      const version = document.querySelector('#minecraft-version');
      version.replaceChildren(...(state.recommended_versions[flavor] || []).map(value => new Option(value, value)));
      setServerMode();
      const launch = await Panel.api('/api/runtime/launch-settings');
      const ram = document.querySelector('#onboarding-ram');
      ram.replaceChildren(...Array.from({ length: launch.maximum_recommended_ram_gb }, (_, index) => { const value = index + 1; return new Option(`${value} GB`, String(value), false, value === launch.allocated_ram_gb); }));
      document.querySelector('#onboarding-ram-hint').textContent = `${launch.available_ram_gb} GB libres ahora · hasta ${launch.maximum_recommended_ram_gb} GB recomendados.`;
      showStep(state.first_step);
      if (state.public_address) document.querySelector('#ready-feedback').textContent = `Dirección para compartir: ${state.public_address}`;
    } catch (error) { showError(error.message); }
  };

  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-refresh]').forEach(button => button.addEventListener('click', refresh));
    document.querySelector('#download-java')?.addEventListener('click', async () => {
      const feedback = document.querySelector('#java-feedback');
      const button = document.querySelector('#download-java');
      const version = document.querySelector('#minecraft-version')?.value || '1.21.1';
      button.disabled = true;
      feedback.textContent = `Descargando Java compatible con Minecraft ${version}…`;
      try {
        const result = await Panel.api('/api/onboarding/java', { method: 'POST', body: { minecraft_version: version } });
        feedback.textContent = result.message;
        await refresh();
      } catch (error) {
        feedback.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    });
    document.querySelectorAll('input[name="flavor"]').forEach(input => input.addEventListener('change', refresh));
    document.querySelector('#check-imported-server')?.addEventListener('click', async () => {
      const feedback = document.querySelector('#install-feedback');
      feedback.textContent = 'Revisando tu carpeta…';
      try {
        const state = await Panel.api('/api/onboarding/status');
        if (!state.server_ready) throw new Error('Todavía no encontré un script de inicio en la carpeta server. Revisá que hayas copiado run.bat o run.sh junto con los archivos del servidor.');
        feedback.textContent = 'Servidor existente detectado. Tus archivos no fueron modificados.';
        await refresh();
      } catch (error) { feedback.textContent = error.message; }
    });
    document.querySelector('#install-server')?.addEventListener('click', async () => {
      const feedback = document.querySelector('#install-feedback');
      const button = document.querySelector('#install-server');
      button.disabled = true;
      feedback.textContent = 'Descargando e instalando…';
      try {
        const result = await Panel.api('/api/onboarding/install', { method: 'POST', body: { flavor: selectedFlavor(), minecraft_version: document.querySelector('#minecraft-version').value, accept_eula: document.querySelector('#accept-eula').checked } });
        feedback.textContent = result.message;
        await refresh();
      } catch (error) { feedback.textContent = error.message; } finally { button.disabled = false; }
    });
    const showPlayitClaim = (claimUrl) => {
      const container = document.querySelector('#playit-claim');
      const link = document.querySelector('#playit-claim-link');
      if (!claimUrl || !container || !link) return false;
      link.href = claimUrl;
      link.textContent = '2. Abrir Playit para aprobar esta computadora →';
      container.classList.remove('hidden');
      return true;
    };
    document.querySelector('#begin-playit-onboarding')?.addEventListener('click', async () => {
      const feedback = document.querySelector('#connection-feedback');
      const button = document.querySelector('#begin-playit-onboarding');
      button.disabled = true;
      feedback.textContent = 'Preparando la vinculación segura…';
      try {
        let tunnel = await Panel.api('/api/tunnel/begin-claim', { method: 'POST' });
        for (let attempt = 0; !tunnel.claim_url && attempt < 20; attempt += 1) {
          await new Promise(resolve => window.setTimeout(resolve, 500));
          tunnel = await Panel.api('/api/tunnel/status');
        }
        if (!showPlayitClaim(tunnel.claim_url)) throw new Error('Playit no mostró el enlace de vinculación. Revisá tu conexión e intentá de nuevo.');
        feedback.textContent = 'Paso 2 de 3: aprobá esta computadora en Playit y después volvé acá.';
      } catch (error) { feedback.textContent = error.message; } finally { button.disabled = false; }
    });
    document.querySelector('#complete-playit-claim')?.addEventListener('click', async () => {
      const feedback = document.querySelector('#connection-feedback');
      try {
        await Panel.api('/api/tunnel/complete-claim', { method: 'POST' });
        feedback.textContent = 'Listo: Playit quedó vinculado. Seguimos con el inicio del servidor.';
        await refresh();
      } catch (error) { feedback.textContent = error.message; }
    });

    document.querySelector('#show-manual-playit')?.addEventListener('click', () => {
      document.querySelector('#manual-playit-secret')?.classList.remove('hidden');
      document.querySelector('#show-manual-playit')?.classList.add('hidden');
      document.querySelector('#onboarding-playit-secret')?.focus();
    });

    document.querySelector('#connect-playit-onboarding')?.addEventListener('click', async () => {
      const feedback = document.querySelector('#connection-feedback');
      try {
        await Panel.api('/api/tunnel/setup', { method: 'POST', body: { agent_secret: document.querySelector('#onboarding-playit-secret').value } });
        feedback.textContent = 'Playit conectado.';
        await refresh();
      } catch (error) { feedback.textContent = error.message; }
    });
    document.querySelector('#local-only-onboarding')?.addEventListener('click', async () => {
      const feedback = document.querySelector('#connection-feedback');
      try {
        const current = await Panel.api('/api/runtime/launch-settings');
        await Panel.api('/api/runtime/launch-settings', { method: 'PUT', body: { allocated_ram_gb: current.allocated_ram_gb, playit_enabled: false } });
        feedback.textContent = 'Elegiste red local solamente.';
        await refresh();
      } catch (error) { feedback.textContent = error.message; }
    });
    document.querySelector('#start-from-onboarding')?.addEventListener('click', async () => {
      const feedback = document.querySelector('#ready-feedback');
      const button = document.querySelector('#start-from-onboarding');
      button.disabled = true;
      feedback.textContent = 'Iniciando tu servidor…';
      try {
        const current = await Panel.api('/api/runtime/launch-settings');
        await Panel.api('/api/runtime/launch-settings', { method: 'PUT', body: { allocated_ram_gb: Number(document.querySelector('#onboarding-ram').value), playit_enabled: current.playit_enabled } });
        const result = await Panel.api('/api/server/start', { method: 'POST' });
        if (current.playit_enabled) {
          await waitForPublicAddress(feedback);
        } else {
          feedback.textContent = `${result.message} La primera copia de seguridad se creará cuando el mundo esté listo.`;
        }
      } catch (error) { feedback.textContent = error.message; } finally { button.disabled = false; }
    });
    refresh();
  });
})();
