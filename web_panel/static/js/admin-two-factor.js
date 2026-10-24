// "Verificación en dos pasos" in Ajustes: turn TOTP on, move it to another phone, or turn it off.
document.addEventListener('DOMContentLoaded', () => {
  const section = document.querySelector('#two-factor');
  if (!section) return;
  const $ = (selector) => section.querySelector(selector);

  const stateText = $('#two-factor-state');
  const actionsOff = $('#two-factor-actions-off');
  const actionsOn = $('#two-factor-actions-on');
  const confirmForm = $('#two-factor-confirm');
  const confirmLabel = $('#two-factor-confirm-label');
  const currentCodeInput = $('#two-factor-current-code');
  const setupForm = $('#two-factor-setup');
  const qrImage = $('#two-factor-qr');
  const keyText = $('#two-factor-key');
  const setupCodeInput = $('#two-factor-setup-code');
  const errorText = $('#two-factor-error');

  let enabled = section.dataset.enabled === 'true';
  // What the current-code form does when submitted: 'change' or 'turn-off'.
  let pendingAction = null;

  const isSixDigits = (value) => /^\d{6}$/.test(value);
  const show = (element, visible) => element.classList.toggle('hidden', !visible);

  const render = () => {
    stateText.textContent = enabled ? 'Está activada.' : 'Está apagada.';
    show(actionsOff, !enabled);
    show(actionsOn, enabled);
  };

  const resetForms = () => {
    pendingAction = null;
    show(confirmForm, false);
    show(setupForm, false);
    currentCodeInput.value = '';
    setupCodeInput.value = '';
    qrImage.removeAttribute('src');
    keyText.textContent = '';
    errorText.textContent = '';
  };

  const withBusy = async (button, work) => {
    errorText.textContent = '';
    button.disabled = true;
    try {
      await work();
    } catch (issue) {
      errorText.textContent = issue.message;
    } finally {
      button.disabled = false;
    }
  };

  const startSetup = async (currentCode) => {
    const body = currentCode ? { code: currentCode } : {};
    const data = await Panel.api('/api/auth/2fa/setup', { method: 'POST', body });
    show(confirmForm, false);
    qrImage.src = `data:image/png;base64,${data.qr_code_base64}`;
    keyText.textContent = data.manual_entry_key;
    show(setupForm, true);
    setupCodeInput.focus();
  };

  const askForCurrentCode = (action) => {
    resetForms();
    pendingAction = action;
    confirmLabel.textContent = action === 'turn-off'
      ? 'Para apagarla, escribí el código que te muestra ahora la app'
      : 'Para pasarla a otro celular, escribí el código que te muestra ahora la app';
    show(confirmForm, true);
    currentCodeInput.focus();
  };

  $('#two-factor-start').addEventListener('click', (event) => {
    resetForms();
    withBusy(event.currentTarget, () => startSetup(null));
  });
  $('#two-factor-change').addEventListener('click', () => askForCurrentCode('change'));
  $('#two-factor-turn-off').addEventListener('click', () => askForCurrentCode('turn-off'));
  $('#two-factor-confirm-cancel').addEventListener('click', resetForms);
  $('#two-factor-setup-cancel').addEventListener('click', resetForms);

  $('#two-factor-copy-key').addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(keyText.textContent);
      Panel.toast('Clave copiada.');
    } catch {
      Panel.toast('No se pudo copiar. Seleccioná la clave y copiala a mano.', 'error');
    }
  });

  confirmForm.addEventListener('submit', (event) => {
    event.preventDefault();
    const code = currentCodeInput.value.trim();
    if (!isSixDigits(code)) {
      errorText.textContent = 'Escribí los 6 números que te muestra la app.';
      return;
    }
    const button = $('#two-factor-confirm-submit');
    withBusy(button, async () => {
      if (pendingAction === 'turn-off') {
        await Panel.api('/api/auth/2fa/disable', { method: 'POST', body: { code } });
        enabled = false;
        resetForms();
        render();
        Panel.toast('La verificación en dos pasos quedó apagada.');
      } else {
        await startSetup(code);
      }
    });
  });

  setupForm.addEventListener('submit', (event) => {
    event.preventDefault();
    const code = setupCodeInput.value.trim();
    if (!isSixDigits(code)) {
      errorText.textContent = 'Escribí los 6 números que te muestra la app.';
      return;
    }
    withBusy($('#two-factor-setup-submit'), async () => {
      await Panel.api('/api/auth/2fa/verify', { method: 'POST', body: { code } });
      enabled = true;
      resetForms();
      render();
      Panel.toast('Listo. Desde ahora el panel te pide el código al entrar.');
    });
  });

  render();
});
