(() => {
  const text = (selector, value) => { const node = document.querySelector(selector); if (node) node.textContent = value; };
  const duration = (seconds) => { const total = Math.max(0, Number(seconds) || 0); const hours = Math.floor(total / 3600); const minutes = Math.floor((total % 3600) / 60); return hours ? `${hours} h ${minutes} min` : `${minutes} min`; };
  const formatDate = (value) => { const date = new Date(value); return Number.isNaN(date.getTime()) ? 'Fecha no disponible' : date.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }); };
  const setHealth = (health, metrics) => {
    const running = Boolean(health?.is_running ?? metrics?.is_running); const title = health?.health_label || (running ? 'Servidor activo' : 'Servidor detenido'); const status = health?.health_status || (running ? 'ACTIVO' : 'DETENIDO');
    const className = health?.health_color === 'emerald' ? 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200' : health?.health_color === 'rose' ? 'border-rose-400/30 bg-rose-400/10 text-rose-200' : 'border-amber-400/30 bg-amber-400/10 text-amber-200';
    text('#health-title', title); text('#health-description', running ? 'El panel está observando el servidor. Las acciones de control están separadas de esta vista.' : 'El panel no controla automáticamente un servidor detenido. Revisá la preparación o la actividad si esperabas que estuviera activo.');
    const badge = document.querySelector('#health-badge'); if (badge) { badge.textContent = status; badge.className = `rounded-full border px-3 py-1.5 text-xs font-bold ${className}`; }
    text('#tps-value', running ? `${Number(health?.tps || 0).toFixed(1)} TPS` : 'Sin actividad'); text('#ram-value', metrics ? `${Math.round(metrics.ram_used_mb || 0)} MB` : '—'); text('#ram-caption', metrics ? `${Math.round(metrics.ram_percent || 0)}% de ${Math.round(metrics.ram_total_mb || 0)} MB` : 'Uso del proceso'); text('#uptime-value', running ? duration(metrics?.uptime_seconds) : '—'); text('#cpu-caption', metrics ? `CPU: ${Math.round(metrics.cpu_percent || 0)}%` : 'CPU: —'); text('#dashboard-summary', running ? 'Tu servidor está activo. Compartí la dirección sólo cuando la conexión indique que está lista.' : 'Esta vista te ayuda a revisar la salud y el acceso. No cambia nada por sí sola.');
  };
  const setConnection = (connection) => { const address = connection?.public_address || 'Dirección no disponible'; text('#connection-address', address); text('#connection-message', connection?.message || 'No se encontró una dirección de conexión.'); text('#connection-next-step', connection?.next_step || 'Configurá una forma de acceso externo antes de invitar amigos.'); const button = document.querySelector('#copy-connection'); if (button) button.disabled = !connection?.can_share_with_friends; };
  const setBackup = (backups) => { const latest = Array.isArray(backups) && backups.length ? [...backups].sort((a, b) => new Date(b.created_at) - new Date(a.created_at))[0] : null; if (!latest) { text('#backup-status', 'Todavía no encontramos una copia en el panel. Revisá el historial antes de hacer cambios grandes.'); text('#backup-detail', ''); return; } text('#backup-status', `Guardada ${formatDate(latest.created_at)} · ${Number(latest.size_mb || 0).toFixed(1)} MB`); text('#backup-detail', latest.filename); };
  const query = async (path) => { try { return await Panel.api(path); } catch { return null; } };
  const refresh = async () => { const [metrics, health, connection, backups] = await Promise.all([query('/api/server/metrics'), query('/api/server/health-summary'), query('/api/server/connection-info'), query('/api/backups')]); setHealth(health, metrics); setConnection(connection); setBackup(backups); text('#dashboard-updated', `Actualizado ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`); };
  const setOperationFeedback = (value) => text('#operation-feedback', value);
  const runServerAction = async (button) => {
    const action = button.dataset.serverAction;
    const prompts = {
      stop: '¿Apagar el servidor normalmente? Las personas conectadas se desconectarán.',
      kill: '¿Forzar el cierre? Podés perder progreso que todavía no se guardó. Usalo sólo si el apagado normal no responde.',
    };
    if (prompts[action] && !window.confirm(prompts[action])) return;
    button.disabled = true;
    setOperationFeedback('Enviando la solicitud…');
    try {
      const result = await Panel.api(`/api/server/${action}`, { method: 'POST' });
      Panel.toast(result.message || 'Solicitud enviada.');
      setOperationFeedback(result.message || 'Solicitud enviada.');
      await refresh();
    } catch (error) {
      Panel.toast(error.message, 'error');
      setOperationFeedback(error.message);
    } finally { button.disabled = false; }
  };
  const createBackup = async (button) => {
    if (!window.confirm('¿Crear una copia de seguridad ahora? El servidor sigue funcionando mientras se prepara.')) return;
    const original = button.textContent;
    button.disabled = true; button.textContent = 'Creando copia…'; setOperationFeedback('Creando una copia de seguridad…');
    try {
      const result = await Panel.api('/api/backups', { method: 'POST' });
      Panel.toast(result.message || 'Copia creada.'); setOperationFeedback(result.message || 'Copia creada.'); await refresh();
    } catch (error) { Panel.toast(error.message, 'error'); setOperationFeedback(error.message); }
    finally { button.disabled = false; button.textContent = original; }
  };
  const gracefulRestart = async (button) => {
    if (!window.confirm('¿Avisar a quienes están jugando y reiniciar en 10 segundos?')) return;
    button.disabled = true; setOperationFeedback('Avisando y preparando el reinicio…');
    try {
      const result = await Panel.api('/api/server/graceful-restart?countdown=10', { method: 'POST' });
      Panel.toast(result.message || 'Reinicio programado.'); setOperationFeedback(result.message || 'Reinicio programado.');
    } catch (error) { Panel.toast(error.message, 'error'); setOperationFeedback(error.message); }
    finally { button.disabled = false; }
  };
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelector('#copy-connection')?.addEventListener('click', async () => { const value = document.querySelector('#connection-address')?.textContent || ''; try { await navigator.clipboard.writeText(value); Panel.toast('Dirección copiada.'); } catch { Panel.toast('No se pudo copiar la dirección.', 'error'); } });
    document.querySelectorAll('[data-server-action]').forEach((button) => button.addEventListener('click', () => runServerAction(button)));
    document.querySelector('#create-backup')?.addEventListener('click', ({ currentTarget }) => createBackup(currentTarget));
    document.querySelector('#graceful-restart')?.addEventListener('click', ({ currentTarget }) => gracefulRestart(currentTarget));
    refresh(); window.setInterval(refresh, 15_000);
  });
})();
