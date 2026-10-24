/**
 * Discord integration and alerts manager for the admin panel.
 * Handles loading and saving webhook settings (/api/discord/config),
 * webhook and mention tests (/api/discord/test), and password visibility toggles.
 */
(() => {
  const initDiscordAdmin = () => {
    const $ = (s) => document.querySelector(s);

    // Do nothing if the Discord section is not on the page
    if (!$('#discord-webhook-url') && !$('#btn-save-discord-config') && !$('#btn-discord-save')) {
      return;
    }

    // 1. Load the current settings from the backend
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

    // Expose loadDiscordConfig globally for external callers
    window.loadDiscordConfig = loadDiscordConfig;

    // 2. Save the Discord settings
    const handleSaveDiscordConfig = async (btn) => {
      if (!btn) return;
      btn.disabled = true;
      const prev = btn.innerHTML;
      btn.textContent = 'Guardando…';
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
        Panel.toast(res.message || 'Avisos de Discord guardados.', 'success');
      } catch (err) {
        Panel.toast(err.message, 'error');
      } finally {
        btn.innerHTML = prev;
        btn.disabled = false;
      }
    };

    // Supports both #btn-save-discord-config and #btn-discord-save
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
      btn.textContent = 'Probando…';
      try {
        const testUrl = $('#discord-webhook-url')?.value.trim() || '';
        if (!testUrl) {
          Panel.toast('Primero pegá el enlace del canal.', 'error');
          return;
        }
        const res = await Panel.api('/api/discord/test', {
          method: 'POST',
          body: { webhook_url: testUrl, test_type: 'test' },
        });
        Panel.toast(res.message || 'Aviso de prueba enviado. Fijate en tu canal de Discord.', 'success');
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

    // 4. Test the players and deaths webhook (feed with 3D avatar)
    $('#btn-test-events-webhook')?.addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      const prev = btn.innerHTML;
      btn.textContent = 'Probando…';
      try {
        const eventsUrl = $('#discord-events-url')?.value.trim() || $('#discord-webhook-url')?.value.trim() || '';
        if (!eventsUrl) {
          Panel.toast('Primero pegá el enlace de algún canal.', 'error');
          return;
        }
        const res = await Panel.api('/api/discord/test', {
          method: 'POST',
          body: { webhook_url: eventsUrl, test_type: 'events' },
        });
        Panel.toast(res.message || 'Muerte de prueba enviada. Fijate en tu canal de Discord.', 'success');
      } catch (err) {
        Panel.toast(err.message, 'error');
      } finally {
        btn.innerHTML = prev;
        btn.disabled = false;
      }
    });

    // 5. Test the role mention
    $('#btn-test-mention')?.addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      const prev = btn.innerHTML;
      btn.textContent = 'Probando…';
      try {
        const mainUrl = $('#discord-webhook-url')?.value.trim() || '';
        const mention = $('#discord-mention-role')?.value.trim() || '';
        if (!mainUrl) {
          Panel.toast('Para probar la mención, primero pegá el enlace del canal.', 'error');
          return;
        }
        if (!mention) {
          Panel.toast('Escribí a quién mencionar, por ejemplo @everyone.', 'error');
          return;
        }
        const res = await Panel.api('/api/discord/test', {
          method: 'POST',
          body: { webhook_url: mainUrl, test_type: 'mention', mention_role: mention },
        });
        Panel.toast(res.message || 'Mención de prueba enviada.', 'success');
      } catch (err) {
        Panel.toast(err.message, 'error');
      } finally {
        btn.innerHTML = prev;
        btn.disabled = false;
      }
    });

    // 6. Visibility toggles (show / hide the webhook token)
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

    // Status banner. Discord fetches images itself, so a link only works when the panel can be
    // reached from the internet; otherwise the image is downloaded and pasted.
    const isPrivateHost = (host) => /^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|\[?::1\]?$|.*\.local$)/i.test(host);
    let bannerOrigin = isPrivateHost(window.location.hostname) ? null : window.location.origin;
    const showBannerLink = (origin, note) => {
      bannerOrigin = origin;
      $('#copy-banner-markdown')?.classList.remove('hidden');
      const share = $('#banner-share-note');
      if (share) share.textContent = note;
    };
    if (bannerOrigin) {
      showBannerLink(bannerOrigin, 'Copiá el enlace y pegalo en Discord o en un foro: la imagen se actualiza sola. También podés descargarla.');
    } else {
      // A Cloudflare quick tunnel gives the panel a public address for a while.
      Panel.api('/api/cloudflare/status').then((tunnel) => {
        if (tunnel?.public_url) showBannerLink(tunnel.public_url.replace(/\/$/, ''), 'Copiá el enlace mientras el túnel de Cloudflare esté encendido: la imagen se actualiza sola. Si el túnel se reinicia, el enlace cambia.');
      }).catch(() => { /* No tunnel: downloading is the way. */ });
    }
    $('#copy-banner-markdown')?.addEventListener('click', async () => {
      if (!bannerOrigin) return;
      try {
        // A plain link: Discord shows the image under the message.
        await navigator.clipboard.writeText(`${bannerOrigin}/api/server/banner.png`);
        Panel.toast('Enlace copiado. Pegalo en Discord o en un foro.');
      } catch {
        Panel.toast('No pudimos copiar el enlace. Probá de nuevo.', 'error');
      }
    });

    // Chat bridge: the panel's notices need no mod; linking the game chat with Discord does.
    const renderBridge = (bridge, env) => {
      const textNode = $('#discord-bridge-text');
      const actions = $('#discord-bridge-actions');
      const steps = $('#discord-bridge-steps');
      if (!textNode || !actions) return;
      const envNode = $('#discord-bridge-env');
      if (envNode && env?.label) envNode.textContent = env.label;
      actions.replaceChildren();
      const link = (href, label) => Object.assign(document.createElement('a'), { href, textContent: label, className: 'link text-sm', target: '_blank', rel: 'noopener noreferrer' });
      const button = (label, className) => Object.assign(document.createElement('button'), { type: 'button', textContent: label, className });
      if (!bridge.installed) {
        textNode.textContent = `¿Querés que lo que escriben en Discord aparezca en el juego, y al revés? Hace falta un mod con un bot de Discord. Te recomendamos ${bridge.suggestion.name}.`;
        const install = button('Instalar desde el panel', 'v2-button btn-primary min-h-0 py-1.5 text-sm');
        install.addEventListener('click', async () => {
          install.disabled = true;
          install.textContent = 'Instalando…';
          try {
            const mod = await Panel.api('/api/mods/install', { method: 'POST', body: { project_id: bridge.suggestion.project_id, install_dependencies: true } });
            Panel.toast(`Instalaste ${mod.name}. Encendé el servidor una vez para que cree sus ajustes.`);
            await loadBridge();
          } catch (error) {
            Panel.toast(error.message, 'error');
            install.disabled = false;
            install.textContent = 'Instalar desde el panel';
          }
        });
        actions.append(install, link(bridge.suggestion.modrinth_url, 'Ver en Modrinth'));
        steps?.classList.remove('hidden');
        if (steps) steps.open = true;
        return;
      }
      steps?.classList.add('hidden');
      if (!bridge.enabled) {
        textNode.textContent = `${bridge.name} está instalado pero apagado. Encendelo en Mods y reiniciá el servidor.`;
        actions.append(Object.assign(document.createElement('a'), { href: '/mods', textContent: 'Ir a Mods', className: 'link text-sm' }));
        return;
      }
      if (!bridge.config_file) {
        textNode.textContent = `${bridge.name} está instalado. Encendé el servidor una vez para que cree su archivo de ajustes; ahí va el token del bot.`;
        actions.append(link(bridge.modrinth_url, 'Cómo se configura'));
        return;
      }
      textNode.textContent = `${bridge.name} está instalado. El token del bot y el canal van en sus ajustes. Si el mod también avisa cuando el servidor se enciende, apagá ese aviso acá o en el mod para no recibirlo dos veces.`;
      const open = button('Abrir sus ajustes', 'v2-button btn-quiet min-h-0 py-1.5 text-sm');
      open.addEventListener('click', async () => {
        open.disabled = true;
        try {
          const result = await Panel.api(`/api/config-editor/open/${encodeURIComponent(bridge.config_file).replaceAll('%2F', '/')}`, { method: 'POST' });
          Panel.toast(result.message);
        } catch (error) {
          // From another device: go to the mod settings list, already filtered to this mod.
          if (error.status === 409) {
            const search = document.querySelector('#config-search');
            if (search) search.value = bridge.config_file.split('/')[0];
            window.location.hash = 'configs';
            window.showFiles?.();
          } else {
            Panel.toast(error.message, 'error');
          }
        } finally {
          open.disabled = false;
        }
      });
      actions.append(open, link(bridge.modrinth_url, 'Cómo se configura'));
    };
    const loadBridge = async () => {
      try {
        const [bridge, env] = await Promise.all([Panel.api('/api/discord/bridge'), Panel.api('/api/mods/environment').catch(() => null)]);
        renderBridge(bridge, env);
      } catch {
        const textNode = $('#discord-bridge-text');
        if (textNode) textNode.textContent = 'No pudimos revisar tus mods ahora. Probá recargar la página.';
      }
    };

    // 7. First load
    loadDiscordConfig();
    loadBridge();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initDiscordAdmin);
  } else {
    initDiscordAdmin();
  }
})();
