// Set the server-list icon (server-icon.png) from Ajustes > Tu servidor.
(() => {
  const byId = (id) => document.getElementById(id);
  const pick = byId('server-icon-pick');
  const fileInput = byId('server-icon-file');
  const preview = byId('server-icon-preview');
  const empty = byId('server-icon-empty');
  const removeBtn = byId('server-icon-remove');
  const statusText = byId('server-icon-status');
  if (!pick || !fileInput || !preview || !empty || !removeBtn) return;

  const ICON_URL = '/api/server/icon.png';
  const MAX_BYTES = 8 * 1024 * 1024;

  const setStatus = (text) => { if (statusText) statusText.textContent = text || ''; };

  const showIcon = (present) => {
    preview.classList.toggle('hidden', !present);
    empty.classList.toggle('hidden', present);
    removeBtn.classList.toggle('hidden', !present);
    if (present) preview.src = ICON_URL + '?t=' + Date.now();
  };

  const loadState = async () => {
    try {
      const data = await Panel.api('/api/server/icon/status');
      showIcon(Boolean(data && data.has_icon));
    } catch {
      showIcon(false);
    }
  };

  pick.addEventListener('click', () => fileInput.click());

  fileInput.addEventListener('change', async () => {
    const file = fileInput.files && fileInput.files[0];
    fileInput.value = '';
    if (!file) return;
    if (file.size > MAX_BYTES) {
      Panel.toast('La imagen es muy grande (máximo 8 MB).', 'error');
      return;
    }
    const form = new FormData();
    form.append('file', file);
    pick.disabled = true;
    setStatus('Subiendo la imagen…');
    try {
      await Panel.api('/api/server/icon', { method: 'POST', body: form });
      showIcon(true);
      setStatus('Listo. Se ve cuando reinicies el servidor.');
      Panel.toast('Imagen del servidor actualizada.', 'success');
    } catch (error) {
      setStatus('');
      Panel.toast((error && error.message) || 'No pudimos guardar la imagen.', 'error');
    } finally {
      pick.disabled = false;
    }
  });

  removeBtn.addEventListener('click', async () => {
    removeBtn.disabled = true;
    try {
      await Panel.api('/api/server/icon', { method: 'DELETE' });
      showIcon(false);
      setStatus('Se quitó la imagen. El cambio se ve cuando reinicies el servidor.');
      Panel.toast('Imagen del servidor quitada.', 'success');
    } catch (error) {
      Panel.toast((error && error.message) || 'No pudimos quitar la imagen.', 'error');
    } finally {
      removeBtn.disabled = false;
    }
  });

  loadState();
})();
