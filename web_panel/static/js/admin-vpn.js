// "Por una VPN" in Ajustes > Acceso por Internet: the VPNs found on this PC, the address
// friends use through each one, and opening the panel to the VPN.
document.addEventListener('DOMContentLoaded', () => {
  const section = document.querySelector('#vpn-access');
  if (!section) return;
  const $ = (selector) => section.querySelector(selector);

  const stateText = $('#vpn-state');
  const list = $('#vpn-list');
  const panelBox = $('#vpn-panel');
  const toggle = $('#vpn-panel-toggle');
  const localOnly = $('#vpn-panel-local-only');
  const restartNote = $('#vpn-panel-restart');
  const warning = $('#vpn-panel-warning');
  const twoFactorOn = section.dataset.twoFactor === 'true';

  const show = (element, visible) => element.classList.toggle('hidden', !visible);

  const copyButton = (text) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'v2-button btn-quiet min-h-9 shrink-0 px-3 py-1 text-sm';
    button.textContent = 'Copiar';
    button.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(text);
        Panel.toast('Copiado.', 'success');
      } catch {
        Panel.toast('No pudimos copiar. Probá de nuevo.', 'error');
      }
    });
    return button;
  };

  const row = (label, value, href) => {
    const line = document.createElement('div');
    line.className = 'mt-2 flex flex-wrap items-center gap-2';
    const caption = document.createElement('span');
    caption.className = 'w-32 shrink-0 text-sm text-zinc-500';
    caption.textContent = label;
    const shown = document.createElement(href ? 'a' : 'code');
    shown.className = 'min-w-0 break-all font-mono text-sm text-zinc-100';
    shown.textContent = value;
    if (href) {
      shown.href = href;
      shown.className += ' underline underline-offset-2';
    }
    line.append(caption, shown, copyButton(value));
    return line;
  };

  const render = (state, connection) => {
    const gameAddresses = new Map((connection?.vpn_addresses || []).map((item) => [item.name, item.address]));
    list.replaceChildren();
    if (!state.networks.length) {
      stateText.textContent = 'No encontramos ninguna VPN conectada en esta computadora. Si instalás una, volvé a esta pantalla.';
      show(panelBox, false);
      return;
    }
    stateText.textContent = state.networks.length === 1 ? 'Encontramos esta VPN:' : 'Encontramos estas VPN:';
    state.networks.forEach((network) => {
      const item = document.createElement('li');
      item.className = 'rounded-xl border border-zinc-800 p-4';
      const title = document.createElement('p');
      title.className = 'font-semibold text-zinc-100';
      title.textContent = network.name;
      item.append(title);
      const game = gameAddresses.get(network.name);
      if (game) item.append(row('Para Minecraft', game));
      if (network.panel_link) item.append(row('Para el panel', network.panel_link, network.panel_link));
      list.append(item);
    });

    show(panelBox, true);
    toggle.checked = state.panel_access_enabled;
    toggle.disabled = !state.can_change;
    show(localOnly, !state.can_change);
    show(restartNote, state.needs_restart);
    show(warning, state.panel_access_enabled && !twoFactorOn);
  };

  const load = async () => {
    try {
      const [state, connection] = await Promise.all([
        Panel.api('/api/network/vpn'),
        Panel.api('/api/server/connection-info').catch(() => null),
      ]);
      render(state, connection);
    } catch (error) {
      stateText.textContent = `No pudimos revisar las VPN. ${error.message || ''}`.trim();
    }
  };

  toggle.addEventListener('change', async () => {
    const wanted = toggle.checked;
    if (wanted && !window.confirm('¿Abrir el panel a las otras computadoras de tu VPN? Van a ver la pantalla para poner la contraseña.')) {
      toggle.checked = false;
      return;
    }
    toggle.disabled = true;
    try {
      const state = await Panel.api('/api/network/vpn', { method: 'PUT', body: { panel_access: wanted } });
      const connection = await Panel.api('/api/server/connection-info').catch(() => null);
      render(state, connection);
      Panel.toast(wanted ? 'Listo. Falta reiniciar el panel.' : 'Listo. Al reiniciar el panel queda solo para esta computadora.', 'success');
    } catch (error) {
      toggle.checked = !wanted;
      toggle.disabled = false;
      Panel.toast(error.message || 'No se pudo guardar el cambio.', 'error');
    }
  });

  load();
});
