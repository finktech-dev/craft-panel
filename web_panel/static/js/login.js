document.addEventListener('DOMContentLoaded', () => {
  const copyButton = document.querySelector('#copy-initial-pin');
  copyButton?.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(document.querySelector('#initial-admin-pin').textContent);
      copyButton.textContent = 'Copiada';
    } catch {
      copyButton.textContent = 'Copiala a mano';
    }
  });
  const form = document.querySelector('#login-form');
  if (!form) return;
  const button = form.querySelector('button[type="submit"]');
  // The first-run password is shown once: entering stays locked until the user confirms saving it.
  const savedBox = document.querySelector('#initial-pin-saved');
  const canSubmit = () => !savedBox || savedBox.checked;
  savedBox?.addEventListener('change', () => { button.disabled = !canSubmit(); });
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!canSubmit()) return;
    const error = document.querySelector('#login-error');
    const fields = new FormData(form);
    const pin = String(fields.get('pin') || '');
    const totpCode = String(fields.get('totp_code') || '').trim() || null;
    error.textContent = '';
    button.disabled = true;
    try {
      const result = await Panel.api('/api/auth/login', { method: 'POST', body: { pin, totp_code: totpCode } });
      // The wizard only while the server was never played; otherwise straight to the home screen.
      window.location.assign(result?.next_url === '/onboarding' ? '/onboarding' : '/');
    } catch (issue) {
      error.textContent = issue.message;
    } finally {
      button.disabled = !canSubmit();
    }
  });
});
