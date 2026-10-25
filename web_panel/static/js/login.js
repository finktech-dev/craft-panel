document.addEventListener('DOMContentLoaded', () => {
  document.querySelector('#copy-initial-pin')?.addEventListener('click', async () => {
    await navigator.clipboard.writeText(document.querySelector('#initial-admin-pin').textContent);
  });
  const form = document.querySelector('#login-form');
  if (!form) return;
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = form.querySelector('button');
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
      button.disabled = false;
    }
  });
});
