(() => {
  const labels = {
    windows: 'Windows detectado', linux: 'Linux detectado', macos: 'macOS detectado', other: 'Sistema detectado',
    available: 'Listo para usar', missing: 'Falta instalar Java', unusable: 'Java necesita atención',
    detected: 'Servidor encontrado', not_detected: 'No encontramos un servidor',
    online_accounts: 'Cuentas online activas', whitelist: 'Lista blanca activa', unrestricted: 'Acceso sin protección', unknown: 'Sin datos de protección',
  };
  let launchSettings = null;
  const card = (name) => document.querySelector(`[data-check="${name}"]`);
  const fill = (name, status, message, detail = '') => {
    const node = card(name); if (!node) return;
    const positive = ['available', 'detected', 'online_accounts', 'whitelist'].includes(status);
    const warning = ['missing', 'unusable', 'not_detected', 'unrestricted', 'unknown'].includes(status);
    node.querySelector('[data-title]').textContent = labels[status] || status;
    node.querySelector('[data-message]').textContent = message || 'Sin información adicional.';
    const detailNode = node.querySelector('[data-detail]'); if (detailNode) detailNode.textContent = detail;
    const icon = node.querySelector('[data-icon]');
    icon.textContent = positive ? '✓' : warning ? '!' : '◌';
    icon.className = `grid h-9 w-9 place-items-center rounded-full ${positive ? 'bg-emerald-400/15 text-emerald-300' : 'bg-amber-400/15 text-amber-300'}`;
  };
  const setPlayitConnectVisibility = (status) => {
    const box = document.querySelector('#playit-connect');
    if (box) box.classList.toggle('hidden', Boolean(status && !status.needs_setup));
  };
  const currentPreferences = () => ({
    allocated_ram_gb: Number(document.querySelector('#launch-ram')?.value),
    playit_enabled: !document.querySelector('#local-only')?.checked,
  });
  const savePreferences = async () => Panel.api('/api/runtime/launch-settings', { method: 'PUT', body: currentPreferences() });
  const load = async () => {
    try {
      const response = await fetch('/api/runtime/discovery', { credentials: 'same-origin' });
      if (!response.ok) throw new Error('runtime discovery failed');
      const runtime = await response.json();
      fill('system', runtime.operating_system, 'El panel adapta sus indicaciones a este sistema operativo.');
      const javaDetail = runtime.java.version ? `Java ${runtime.java.version}${runtime.java.executable ? ` · ${runtime.java.executable}` : ''}` : '';
      fill('java', runtime.java.state, runtime.java.message, javaDetail);
      const minecraftDetail = runtime.minecraft.loader ? `${runtime.minecraft.loader}${runtime.minecraft.start_script ? ` · ${runtime.minecraft.start_script}` : ''}` : '';
      fill('minecraft', runtime.minecraft.state, runtime.minecraft.message, minecraftDetail);
      fill('accounts', runtime.accounts.state, runtime.accounts.message);
      const launch = await fetch('/api/runtime/launch-settings', { credentials: 'same-origin' }).then(response => response.ok ? response.json() : null);
      const tunnel = await fetch('/api/tunnel/status', { credentials: 'same-origin' }).then(response => response.ok ? response.json() : null);
      const select = document.querySelector('#launch-ram');
      if (launch && select) {
        launchSettings = launch;
        for (let value = 1; value <= launch.maximum_recommended_ram_gb; value += 1) select.add(new Option(`${value} GB`, String(value), value === launch.allocated_ram_gb, value === launch.allocated_ram_gb));
        document.querySelector('#launch-ram-hint').textContent = `${launch.total_ram_gb} GB totales · ${launch.available_ram_gb} GB libres ahora · recomendado: hasta ${launch.maximum_recommended_ram_gb} GB.`;
        document.querySelector('#local-only').checked = !launch.playit_enabled;
        document.querySelector('#launch-feedback').textContent = launch.server_running ? 'El servidor ya está encendido. Apagalo antes de cambiar la RAM.' : launch.playit_enabled && tunnel?.needs_setup ? 'Conectá Playit para que tus amigos entren desde Internet.' : 'Listo para iniciar.';
      }
      setPlayitConnectVisibility(tunnel);
      document.querySelector('#setup-loading')?.classList.add('hidden');
      document.querySelector('#setup-results')?.classList.remove('hidden');
    } catch {
      document.querySelector('#setup-loading')?.classList.add('hidden');
      document.querySelector('#setup-error')?.classList.remove('hidden');
    }
  };
  document.addEventListener('DOMContentLoaded', () => {
    load();
    document.querySelector('#local-only')?.addEventListener('change', (event) => {
      const localOnly = event.currentTarget.checked;
      document.querySelector('#playit-connect')?.classList.toggle('hidden', localOnly);
    });
    document.querySelector('#save-launch-ram')?.addEventListener('click', async () => {
      const feedback = document.querySelector('#launch-feedback');
      try { const saved = await savePreferences(); feedback.textContent = saved.playit_enabled ? 'Preferencias guardadas. Playit se iniciará junto al servidor.' : 'Preferencias guardadas: sólo red local.'; Panel.toast('Preferencias guardadas.'); } catch (error) { feedback.textContent = error.message; Panel.toast(error.message, 'error'); }
    });
    document.querySelector('#connect-playit')?.addEventListener('click', async () => {
      const secret = document.querySelector('#playit-secret')?.value?.trim(); const feedback = document.querySelector('#launch-feedback');
      if (!secret) { feedback.textContent = 'Pegá la clave de agente de Playit para continuar.'; return; }
      try { const tunnel = await Panel.api('/api/tunnel/setup', { method: 'POST', body: { agent_secret: secret } }); document.querySelector('#playit-secret').value = ''; setPlayitConnectVisibility(tunnel); feedback.textContent = 'Playit conectado. Al encender, el panel instalará e iniciará el agente.'; Panel.toast('Playit conectado.'); } catch (error) { feedback.textContent = error.message; Panel.toast(error.message, 'error'); }
    });
    document.querySelector('#launch-server')?.addEventListener('click', async (event) => {
      const button = event.currentTarget; const feedback = document.querySelector('#launch-feedback'); button.disabled = true; feedback.textContent = 'Preparando conexión e iniciando servidor…';
      try { await savePreferences(); const result = await Panel.api('/api/server/start', { method: 'POST' }); feedback.textContent = result.message; Panel.toast(result.message); } catch (error) { feedback.textContent = error.message; Panel.toast(error.message, 'error'); } finally { button.disabled = false; }
    });
  });
})();
