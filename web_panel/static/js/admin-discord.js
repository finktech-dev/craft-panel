/**
 * Gestor de Integración y Alertas de Discord para el Panel de Administración.
 * Maneja la carga y guardado de configuración de Webhooks (/api/discord/config),
 * pruebas de webhooks y menciones (/api/discord/test), y toggles de visibilidad de contraseñas.
 */
(() => {
  const initDiscordAdmin = () => {
    const $ = (s) => document.querySelector(s);

    // Si la sección de Discord no está presente en la página, no ejecutar
    if (!$('#discord-webhook-url') && !$('#btn-save-discord-config') && !$('#btn-discord-save')) {
      return;
    }

    // 1. Cargar configuración actual desde el backend
    const loadDiscordConfig = async () => {
      try {
        const cfg = await Panel.api('/api/discord/config');
        const webhookInput = $('#discord-webhook-url');
        const eventsInput = $('#discord-events-url');
        const mentionInput = $('#discord-mention-role');
        const serverNameInput = $('#discord-server-name');
        const softwareInput = $('#discord-server-software');
        const worldNameInput = $('#discord-world-name');
        const testPlayerInput = $('#discord-test-player-name');
        const avatarTemplateInput = $('#discord-avatar-url-template');

        if (webhookInput) webhookInput.value = cfg.webhook_url || '';
        if (eventsInput) eventsInput.value = cfg.events_webhook_url || '';
        if (mentionInput) mentionInput.value = cfg.mention_role || '';
        if (serverNameInput) serverNameInput.value = cfg.server_name || '';
        if (softwareInput) softwareInput.value = cfg.server_software_label || '';
        if (worldNameInput) worldNameInput.value = cfg.world_name || '';
        if (testPlayerInput) testPlayerInput.value = cfg.test_player_name || '';
        if (avatarTemplateInput) avatarTemplateInput.value = cfg.player_avatar_url_template || '';

        const tLife = $('#discord-toggle-lifecycle');
        const tCrash = $('#discord-toggle-crashes');
        const tBack = $('#discord-toggle-backups');
        const tJoin = $('#discord-toggle-joinleave');
        const tDeath = $('#discord-toggle-deaths');
        const tAdv = $('#discord-toggle-advancements');

        if (tLife) tLife.checked = cfg.notify_server_lifecycle ?? true;
        if (tCrash) tCrash.checked = cfg.notify_crashes ?? true;
        if (tBack) tBack.checked = cfg.notify_backups ?? true;
        if (tJoin) tJoin.checked = cfg.notify_player_join_leave ?? true;
        if (tDeath) tDeath.checked = cfg.notify_player_deaths ?? true;
        if (tAdv) tAdv.checked = cfg.notify_advancements ?? true;

        const msgStartTitle = $('#discord-msg-starting-title');
        const msgStartDesc = $('#discord-msg-starting-desc');
        const msgStartedTitle = $('#discord-msg-started-title');
        const msgStartedDesc = $('#discord-msg-started-desc');
        const msgStopTitle = $('#discord-msg-stopped-title');
        const msgStopDesc = $('#discord-msg-stopped-desc');
        const msgJoinTitle = $('#discord-msg-join-title');
        const msgJoinDesc = $('#discord-msg-join-desc');
        const msgLeaveTitle = $('#discord-msg-leave-title');
        const msgLeaveDesc = $('#discord-msg-leave-desc');
        const msgDeathTitle = $('#discord-msg-death-title');
        const msgDeathDesc = $('#discord-msg-death-desc');
        const msgAdvTitle = $('#discord-msg-adv-title');
        const msgAdvDesc = $('#discord-msg-adv-desc');

        if (msgStartTitle) msgStartTitle.value = cfg.msg_server_starting_title || '';
        if (msgStartDesc) msgStartDesc.value = cfg.msg_server_starting_desc || '';
        if (msgStartedTitle) msgStartedTitle.value = cfg.msg_server_started_title || '';
        if (msgStartedDesc) msgStartedDesc.value = cfg.msg_server_started_desc || '';
        if (msgStopTitle) msgStopTitle.value = cfg.msg_server_stopped_title || '';
        if (msgStopDesc) msgStopDesc.value = cfg.msg_server_stopped_desc || '';
        if (msgJoinTitle) msgJoinTitle.value = cfg.msg_player_join_title || '';
        if (msgJoinDesc) msgJoinDesc.value = cfg.msg_player_join_desc || '';
        if (msgLeaveTitle) msgLeaveTitle.value = cfg.msg_player_leave_title || '';
        if (msgLeaveDesc) msgLeaveDesc.value = cfg.msg_player_leave_desc || '';
        if (msgDeathTitle) msgDeathTitle.value = cfg.msg_player_death_title || '';
        if (msgDeathDesc) msgDeathDesc.value = cfg.msg_player_death_desc || '';
        if (msgAdvTitle) msgAdvTitle.value = cfg.msg_advancement_title || '';
        if (msgAdvDesc) msgAdvDesc.value = cfg.msg_advancement_desc || '';
      } catch (e) {
        console.warn('No se pudo cargar la configuración de Discord:', e);
      }
    };

    // Exponer loadDiscordConfig globalmente para compatibilidad con llamadas externas
    window.loadDiscordConfig = loadDiscordConfig;

    // 2. Guardar configuración de Discord
    const handleSaveDiscordConfig = async (btn) => {
      if (!btn) return;
      btn.disabled = true;
      const prev = btn.innerHTML;
      btn.innerHTML = '<span>⏳</span> Guardando...';
      try {
        const payload = {
          webhook_url: $('#discord-webhook-url')?.value.trim() || '',
          events_webhook_url: $('#discord-events-url')?.value.trim() || '',
          mention_role: $('#discord-mention-role')?.value.trim() || '',
          server_name: $('#discord-server-name')?.value.trim() || '',
          server_software_label: $('#discord-server-software')?.value.trim() || '',
          world_name: $('#discord-world-name')?.value.trim() || '',
          test_player_name: $('#discord-test-player-name')?.value.trim() || '',
          player_avatar_url_template: $('#discord-avatar-url-template')?.value.trim() || '',
          notify_server_lifecycle: $('#discord-toggle-lifecycle')?.checked ?? true,
          notify_crashes: $('#discord-toggle-crashes')?.checked ?? true,
          notify_backups: $('#discord-toggle-backups')?.checked ?? true,
          notify_player_join_leave: $('#discord-toggle-joinleave')?.checked ?? true,
          notify_player_deaths: $('#discord-toggle-deaths')?.checked ?? true,
          notify_advancements: $('#discord-toggle-advancements')?.checked ?? true,
          msg_server_starting_title: $('#discord-msg-starting-title')?.value.trim() || '',
          msg_server_starting_desc: $('#discord-msg-starting-desc')?.value.trim() || '',
          msg_server_started_title: $('#discord-msg-started-title')?.value.trim() || '',
          msg_server_started_desc: $('#discord-msg-started-desc')?.value.trim() || '',
          msg_server_stopped_title: $('#discord-msg-stopped-title')?.value.trim() || '',
          msg_server_stopped_desc: $('#discord-msg-stopped-desc')?.value.trim() || '',
          msg_player_join_title: $('#discord-msg-join-title')?.value.trim() || '',
          msg_player_join_desc: $('#discord-msg-join-desc')?.value.trim() || '',
          msg_player_leave_title: $('#discord-msg-leave-title')?.value.trim() || '',
          msg_player_leave_desc: $('#discord-msg-leave-desc')?.value.trim() || '',
          msg_player_death_title: $('#discord-msg-death-title')?.value.trim() || '',
          msg_player_death_desc: $('#discord-msg-death-desc')?.value.trim() || '',
          msg_advancement_title: $('#discord-msg-adv-title')?.value.trim() || '',
          msg_advancement_desc: $('#discord-msg-adv-desc')?.value.trim() || '',
        };
        const res = await Panel.api('/api/discord/config', { method: 'POST', body: payload });
        Panel.toast(res.message || 'Configuración de Discord guardada con éxito.', 'success');
      } catch (err) {
        Panel.toast(err.message, 'error');
      } finally {
        btn.innerHTML = prev;
        btn.disabled = false;
      }
    };

    // Soporta tanto #btn-save-discord-config como #btn-discord-save
    ['#btn-save-discord-config', '#btn-discord-save'].forEach((selector) => {
      const btn = $(selector);
      if (btn) {
        btn.addEventListener('click', (e) => handleSaveDiscordConfig(e.currentTarget));
      }
    });

    // 3. Probar Webhook Principal (Estado / General)
    const testMainWebhook = async (btn) => {
      if (!btn) return;
      btn.disabled = true;
      const prev = btn.innerHTML;
      btn.innerHTML = '<span>⏳</span> Probando...';
      try {
        const testUrl = $('#discord-webhook-url')?.value.trim() || '';
        if (!testUrl) {
          Panel.toast('Por favor, ingresá la URL del Webhook Principal para probar.', 'error');
          return;
        }
        const res = await Panel.api('/api/discord/test', {
          method: 'POST',
          body: { webhook_url: testUrl, test_type: 'test' },
        });
        Panel.toast(res.message || 'Alerta de estado enviada a Discord.', 'success');
      } catch (err) {
        Panel.toast(err.message, 'error');
      } finally {
        btn.innerHTML = prev;
        btn.disabled = false;
      }
    };

    ['#btn-test-main-webhook', '#btn-discord-test'].forEach((selector) => {
      const btn = $(selector);
      if (btn) {
        btn.addEventListener('click', (e) => testMainWebhook(e.currentTarget));
      }
    });

    // 4. Probar Webhook de Jugadores y Muertes (Feed con avatar 3D)
    $('#btn-test-events-webhook')?.addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      const prev = btn.innerHTML;
      btn.innerHTML = '<span>⏳</span> Probando feed...';
      try {
        const eventsUrl = $('#discord-events-url')?.value.trim() || $('#discord-webhook-url')?.value.trim() || '';
        if (!eventsUrl) {
          Panel.toast('Ingresá la URL del Webhook de Jugadores o la Principal para probar.', 'error');
          return;
        }
        const res = await Panel.api('/api/discord/test', {
          method: 'POST',
          body: { webhook_url: eventsUrl, test_type: 'events' },
        });
        Panel.toast(res.message || 'Prueba de muerte y avatar enviada al canal de Jugadores.', 'success');
      } catch (err) {
        Panel.toast(err.message, 'error');
      } finally {
        btn.innerHTML = prev;
        btn.disabled = false;
      }
    });

    // 5. Probar Mención de Rol
    $('#btn-test-mention')?.addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      const prev = btn.innerHTML;
      btn.innerHTML = '<span>⏳</span> Probando mención...';
      try {
        const mainUrl = $('#discord-webhook-url')?.value.trim() || '';
        const mention = $('#discord-mention-role')?.value.trim() || '';
        if (!mainUrl) {
          Panel.toast('Se necesita la URL del Webhook Principal para enviar la mención de prueba.', 'error');
          return;
        }
        if (!mention) {
          Panel.toast('Ingresá una mención o rol (ej. @everyone o <@&ID>) para probar.', 'error');
          return;
        }
        const res = await Panel.api('/api/discord/test', {
          method: 'POST',
          body: { webhook_url: mainUrl, test_type: 'mention', mention_role: mention },
        });
        Panel.toast(res.message || 'Mención enviada a Discord con éxito.', 'success');
      } catch (err) {
        Panel.toast(err.message, 'error');
      } finally {
        btn.innerHTML = prev;
        btn.disabled = false;
      }
    });

    // 6. Conmutadores de visibilidad (Mostrar / Ocultar webhook token)
    $('#btn-toggle-webhook-view')?.addEventListener('click', () => {
      const inp = $('#discord-webhook-url');
      const btn = $('#btn-toggle-webhook-view');
      if (!inp || !btn) return;
      if (inp.type === 'password') {
        inp.type = 'text';
        btn.textContent = 'Ocultar';
      } else {
        inp.type = 'password';
        btn.textContent = 'Mostrar';
      }
    });

    $('#btn-toggle-events-view')?.addEventListener('click', () => {
      const inp = $('#discord-events-url');
      const btn = $('#btn-toggle-events-view');
      if (!inp || !btn) return;
      if (inp.type === 'password') {
        inp.type = 'text';
        btn.textContent = 'Ocultar';
      } else {
        inp.type = 'password';
        btn.textContent = 'Mostrar';
      }
    });

    // 7. Carga inicial
    loadDiscordConfig();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initDiscordAdmin);
  } else {
    initDiscordAdmin();
  }
})();
