/**
 * Gestor de Mods (web_panel/static/js/mods.js)
 * Controlador modular para la administración interactiva de mods locales y catálogo Modrinth.
 * Soporta operaciones en lote, subida múltiple, metadatos enriquecidos, configs y verificación de versiones.
 */

document.addEventListener('DOMContentLoaded', () => {
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => document.querySelectorAll(selector);
  const esc = Panel.escapeHtml;
  // Every change to the mods folder is recorded, so success messages point to the undo.
  const UNDO_HINT = ' Podés deshacerlo en Historial.';

  // Estado del cliente
  let installedMods = [];
  let currentFilter = 'all';
  let currentSort = 'name';
  let searchTerm = '';
  let modToDelete = null;
  const selectedFilenames = new Set();
  let updatesMap = {};
  let detectedEnv = { loader: null, minecraft_version: null };

  // Elementos DOM principales
  const envBadgeText = $('#env-badge-text');
  const modrinthLoaderSelect = $('#modrinth-loader-select');
  const modrinthVersionInput = $('#modrinth-version-input');
  const installedContainer = $('#installed-mods-container');
  const emptyState = $('#installed-mods-empty');
  const searchInput = $('#local-mod-search');
  const sortSelect = $('#local-mod-sort');
  const filterButtons = $$('.filter-pill');
  const selectAllCheckbox = $('#select-all-mods');
  const btnCheckUpdates = $('#btn-check-updates');

  // Barra de acciones en lote
  const bulkBar = $('#bulk-actions-bar');
  const bulkCount = $('#bulk-selected-count');
  const btnBulkEnable = $('#btn-bulk-enable');
  const btnBulkDisable = $('#btn-bulk-disable');
  const btnBulkDelete = $('#btn-bulk-delete');
  const bulkDeleteModal = $('#modal-bulk-delete');
  const bulkDeleteCountTarget = $('#bulk-delete-count-target');

  // KPIs
  const kpiTotal = $('#kpi-total-mods');
  const kpiActive = $('#kpi-active-mods');
  const kpiDisabled = $('#kpi-disabled-mods');
  const kpiSize = $('#kpi-total-size');

  // Modales
  const uploadModal = $('#modal-upload-mod');
  // The empty state's button opens the same upload dialog (no inline handlers: strict CSP).
  $('#btn-empty-upload')?.addEventListener('click', () => $('#btn-open-upload-modal')?.click());
  const deleteModal = $('#modal-delete-mod');
  const fileInput = $('#mod-file-input');
  const dropZone = $('#modal-drop-zone');
  const uploadStatus = $('#modal-upload-status');
  const uploadProgress = $('#modal-upload-progress');

  // Modrinth
  const modrinthForm = $('#modrinth-search-form');
  const modrinthInput = $('#modrinth-query');
  const modrinthResults = $('#modrinth-results-container');

  // Modpack Export
  const exportBtn = $('#btn-export-pack');
  const downloadBtn = $('#btn-download-pack');
  const packInfo = $('#pack-export-info');

  // 0. DETECCIÓN DINÁMICA DE ENTORNO
  async function loadEnvironment() {
    try {
      const env = await Panel.api('/api/mods/environment');
      if (env) {
        detectedEnv = env;
        // The backend builds the label and leaves out whatever it could not detect.
        if (envBadgeText) envBadgeText.textContent = env.label || 'Minecraft';
        if (modrinthVersionInput && !modrinthVersionInput.value && env.minecraft_version) {
          modrinthVersionInput.placeholder = env.minecraft_version;
        }
      }
    } catch (err) {
      console.warn('No se pudo detectar el motor del servidor:', err);
      if (envBadgeText) {
        envBadgeText.textContent = 'Minecraft';
      }
    }
  }

  // 1. CARGA DE MODS
  async function loadMods() {
    try {
      if (installedContainer) {
        installedContainer.innerHTML = `
          <p class="py-12 text-center text-zinc-500">Cargando tus mods…</p>
        `;
      }
      installedMods = await Panel.api('/api/mods');
      selectedFilenames.clear();
      if (selectAllCheckbox) selectAllCheckbox.checked = false;
      updateBulkBar();
      updateKpis();
      renderInstalledMods();
    } catch (err) {
      Panel.toast(err.message, 'error');
      if (installedContainer) {
        installedContainer.innerHTML = `
          <p class="py-12 text-center text-[#f3a79b]">No pudimos cargar tus mods. ${esc(err.message)}</p>
        `;
      }
    }
  }

  // 2. ACTUALIZACIÓN DE KPIS
  function updateKpis() {
    const total = installedMods.length;
    const active = installedMods.filter(m => m.is_enabled).length;
    const disabled = total - active;
    const totalMb = installedMods.reduce((acc, m) => acc + (m.size_mb || 0), 0).toFixed(1);

    if (kpiTotal) kpiTotal.textContent = total;
    if (kpiActive) kpiActive.textContent = active;
    if (kpiDisabled) kpiDisabled.textContent = disabled;
    if (kpiSize) kpiSize.textContent = `${totalMb} MB`;

    const badgeInstalled = $('#tab-badge-installed');
    if (badgeInstalled) badgeInstalled.textContent = total;
  }

  // 3. BARRA DE ACCIONES EN LOTE (BULK ACTIONS)
  function updateBulkBar() {
    if (!bulkBar) return;
    const count = selectedFilenames.size;
    if (count > 0) {
      bulkBar.classList.remove('hidden');
      if (bulkCount) bulkCount.textContent = `${count} seleccionado${count > 1 ? 's' : ''}`;
    } else {
      bulkBar.classList.add('hidden');
    }
  }

  // 4. RENDERIZADO DE MODS INSTALADOS
  function renderInstalledMods() {
    if (!installedContainer) return;

    // Filtrado
    const query = searchTerm.trim().toLowerCase();
    let filtered = installedMods.filter(mod => {
      const matchSearch =
        !query ||
        mod.name.toLowerCase().includes(query) ||
        mod.filename.toLowerCase().includes(query) ||
        (mod.mod_id && mod.mod_id.toLowerCase().includes(query));
      if (!matchSearch) return false;

      if (currentFilter === 'active') return mod.is_enabled;
      if (currentFilter === 'disabled') return !mod.is_enabled;
      if (currentFilter === 'server_only') return !!mod.is_server_only;
      return true;
    });

    // Ordenamiento
    filtered.sort((a, b) => {
      if (currentSort === 'name') return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
      if (currentSort === 'size_desc') return b.size_mb - a.size_mb;
      if (currentSort === 'size_asc') return a.size_mb - b.size_mb;
      if (currentSort === 'recent') return (b.modified_at || '').localeCompare(a.modified_at || '');
      return 0;
    });

    if (filtered.length === 0) {
      installedContainer.classList.add('hidden');
      if (emptyState) {
        emptyState.classList.remove('hidden');
        const emptyMsg = $('#installed-empty-msg');
        if (emptyMsg) {
          emptyMsg.textContent = searchTerm
            ? 'Ningún mod coincide con lo que buscaste.'
            : 'Buscá uno en "Buscar mods nuevos" o agregalo desde un archivo.';
        }
      }
      return;
    }

    if (emptyState) emptyState.classList.add('hidden');
    installedContainer.classList.remove('hidden');

    installedContainer.innerHTML = filtered.map(mod => {
      const encodedFilename = encodeURIComponent(mod.filename);
      const isEnabled = mod.is_enabled;
      const isServerOnly = !!mod.is_server_only;
      const isSelected = selectedFilenames.has(mod.filename);

      const versionText = mod.version ? `<span class="text-sm text-zinc-500">${esc(mod.version)}</span>` : '';
      const serverOnlyText = isServerOnly
        ? `<span class="text-sm text-zinc-500" title="Tus amigos no necesitan instalarlo">· solo del servidor</span>`
        : '';
      const descriptionText = mod.description
        ? `<p class="mt-0.5 line-clamp-1 text-sm leading-relaxed text-zinc-400">${esc(mod.description)}</p>`
        : '';
      const configLink = mod.has_config
        ? `<a href="/administration#configs" class="link text-sm" title="Cambiar la configuración de ${esc(mod.config_filename || 'este mod')}">Configurar</a>`
        : '';
      const updateData = updatesMap[mod.filename];
      const updateButton = (updateData && updateData.has_update)
        ? `<button type="button" data-update-project="${esc(updateData.project_id || '')}" data-update-filename="${encodedFilename}" class="mod-update-btn link text-sm" title="Hay una versión nueva en Modrinth">Actualizar a ${esc(updateData.latest_version || 'la nueva versión')}</button>`
        : '';

      return `
        <article class="flex items-center gap-4 border-b border-zinc-800 py-4 ${isEnabled ? '' : 'opacity-60'}" title="${esc(mod.filename)} · ${mod.size_mb.toFixed(1)} MB">
          <input type="checkbox" data-select-filename="${esc(mod.filename)}" ${isSelected ? 'checked' : ''} aria-label="Elegir ${esc(mod.name)}" class="mod-select-checkbox h-4 w-4 shrink-0 rounded border-zinc-700 bg-zinc-800 text-emerald-500">
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-baseline gap-x-2">
              <h3 class="truncate font-semibold text-zinc-50">${esc(mod.name)}</h3>
              ${versionText}
              ${serverOnlyText}
            </div>
            ${descriptionText}
            ${(configLink || updateButton) ? `<div class="mt-1.5 flex flex-wrap gap-4">${updateButton}${configLink}</div>` : ''}
          </div>
          <label class="relative inline-flex shrink-0 cursor-pointer select-none items-center" title="${isEnabled ? 'Encendido' : 'Apagado'}">
            <input type="checkbox" ${isEnabled ? 'checked' : ''} data-toggle-filename="${encodedFilename}" class="mod-switch-checkbox peer sr-only" aria-label="${isEnabled ? 'Apagar' : 'Encender'} ${esc(mod.name)}">
            <div class="h-6 w-11 rounded-full bg-zinc-700 after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:bg-zinc-200 after:transition-all after:content-[''] peer-checked:bg-emerald-400 peer-checked:after:translate-x-full peer-checked:after:bg-[#16250c] peer-focus-visible:ring-2 peer-focus-visible:ring-emerald-200"></div>
          </label>
          <button type="button" data-delete-filename="${encodedFilename}" data-mod-name="${esc(mod.name)}" class="delete-mod-btn shrink-0 rounded-lg px-2 py-1.5 text-sm text-zinc-500 hover:bg-zinc-800 hover:text-[#f3a79b]">Quitar</button>
        </article>
      `;
    }).join('');
  }

  // 5. BÚSQUEDA Y FILTRADO LOCAL
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      searchTerm = e.target.value;
      renderInstalledMods();
    });
  }

  if (sortSelect) {
    sortSelect.addEventListener('change', (e) => {
      currentSort = e.target.value;
      renderInstalledMods();
    });
  }

  filterButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      filterButtons.forEach(b => {
        b.classList.remove('bg-zinc-800', 'text-zinc-50');
        b.classList.add('text-zinc-400');
      });
      btn.classList.add('bg-zinc-800', 'text-zinc-50');
      btn.classList.remove('text-zinc-400');
      currentFilter = btn.dataset.filter || 'all';
      renderInstalledMods();
    });
  });

  // 6. SELECCIÓN INDIVIDUAL Y MASTER (BULK ACTIONS)
  if (installedContainer) {
    installedContainer.addEventListener('change', async (event) => {
      const target = event.target;

      // Checkbox de selección para bulk
      if (target.classList.contains('mod-select-checkbox')) {
        const fn = target.dataset.selectFilename;
        if (target.checked) selectedFilenames.add(fn);
        else selectedFilenames.delete(fn);
        updateBulkBar();
        return;
      }

      // Switch toggle individual
      if (target.classList.contains('mod-switch-checkbox')) {
        const filename = target.dataset.toggleFilename;
        if (!filename) return;

        target.disabled = true;
        try {
          const result = await Panel.api(`/api/mods/${filename}/toggle`, { method: 'POST' });
          Panel.toast(result.message + UNDO_HINT, 'success');
          await loadMods();
        } catch (err) {
          Panel.toast(err.message, 'error');
          target.checked = !target.checked;
        } finally {
          target.disabled = false;
        }
      }
    });

    // Clicks en la lista (Delete individual o Update en 1 clic)
    installedContainer.addEventListener('click', async (event) => {
      const deleteBtn = event.target.closest('.delete-mod-btn');
      if (deleteBtn) {
        const filename = deleteBtn.dataset.deleteFilename;
        const modName = deleteBtn.dataset.modName;
        openDeleteModal(filename, modName);
        return;
      }

      const updateBtn = event.target.closest('.mod-update-btn');
      if (updateBtn) {
        const projectId = updateBtn.dataset.updateProject;
        if (!projectId) return;
        const replaceFilename = decodeURIComponent(updateBtn.dataset.updateFilename || '');
        updateBtn.disabled = true;
        updateBtn.textContent = 'Actualizando…';
        try {
          const body = { project_id: projectId };
          // The old jar is removed once the new version is in place.
          if (replaceFilename) body.replace_filename = replaceFilename;
          const mod = await Panel.api('/api/mods/install', { method: 'POST', body });
          Panel.toast(`Actualizaste ${mod.name}.${UNDO_HINT}`, 'success');
          await loadMods();
        } catch (err) {
          Panel.toast(err.message, 'error');
          updateBtn.disabled = false;
          updateBtn.textContent = 'Reintentar';
        }
      }
    });
  }

  // Master checkbox: Seleccionar todos
  if (selectAllCheckbox) {
    selectAllCheckbox.addEventListener('change', (e) => {
      const checkboxes = $$('.mod-select-checkbox');
      if (e.target.checked) {
        checkboxes.forEach(cb => {
          cb.checked = true;
          selectedFilenames.add(cb.dataset.selectFilename);
        });
      } else {
        checkboxes.forEach(cb => {
          cb.checked = false;
        });
        selectedFilenames.clear();
      }
      updateBulkBar();
    });
  }

  // Ejecutor de operaciones en lote
  async function executeBulkAction(action) {
    if (selectedFilenames.size === 0) return;
    const filenames = Array.from(selectedFilenames);
    try {
      const res = await Panel.api('/api/mods/bulk-action', {
        method: 'POST',
        body: { action, filenames },
      });
      Panel.toast(res.affected_count ? res.message + UNDO_HINT : res.message, res.errors.length ? 'info' : 'success');
      selectedFilenames.clear();
      if (selectAllCheckbox) selectAllCheckbox.checked = false;
      updateBulkBar();
      await loadMods();
    } catch (err) {
      Panel.toast(err.message, 'error');
    }
  }

  btnBulkEnable?.addEventListener('click', () => executeBulkAction('enable'));
  btnBulkDisable?.addEventListener('click', () => executeBulkAction('disable'));
  btnBulkDelete?.addEventListener('click', () => {
    if (bulkDeleteCountTarget) bulkDeleteCountTarget.textContent = `${selectedFilenames.size} mods seleccionados`;
    if (bulkDeleteModal) bulkDeleteModal.showModal();
  });

  $('#confirm-bulk-delete')?.addEventListener('click', async () => {
    if (bulkDeleteModal) bulkDeleteModal.close();
    await executeBulkAction('delete');
  });

  $('#cancel-bulk-delete')?.addEventListener('click', () => {
    if (bulkDeleteModal) bulkDeleteModal.close();
  });

  // 7. VERIFICADOR DE ACTUALIZACIONES (UPDATE CHECKER)
  if (btnCheckUpdates) {
    btnCheckUpdates.addEventListener('click', async () => {
      btnCheckUpdates.disabled = true;
      btnCheckUpdates.textContent = 'Buscando actualizaciones…';
      try {
        const updates = await Panel.api('/api/mods/updates');
        updatesMap = {};
        let count = 0;
        updates.forEach(u => {
          if (u.has_update) {
            updatesMap[u.filename] = u;
            count++;
          }
        });
        if (count > 0) {
          Panel.toast(`¡Se encontraron ${count} actualización(es) disponibles en Modrinth!`, 'success');
        } else {
          Panel.toast('Todos los mods compatibles están al día.', 'info');
        }
        renderInstalledMods();
      } catch (err) {
        Panel.toast(err.message, 'error');
      } finally {
        btnCheckUpdates.disabled = false;
        btnCheckUpdates.textContent = 'Ver si hay actualizaciones';
      }
    });
  }

  // 8. MODAL DE ELIMINACIÓN SEGURA INDIVIDUAL
  function openDeleteModal(encodedFilename, modName) {
    modToDelete = decodeURIComponent(encodedFilename);
    const targetLabel = $('#delete-mod-name-target');
    if (targetLabel) targetLabel.textContent = modName || modToDelete;
    if (deleteModal) deleteModal.showModal();
  }

  $('#cancel-delete-mod')?.addEventListener('click', () => {
    modToDelete = null;
    if (deleteModal) deleteModal.close();
  });

  $('#confirm-delete-mod')?.addEventListener('click', async () => {
    if (!modToDelete) return;
    const btn = $('#confirm-delete-mod');
    btn.disabled = true;
    try {
      await Panel.api(`/api/mods/${encodeURIComponent(modToDelete)}`, { method: 'DELETE' });
      Panel.toast(`Quitaste ${modToDelete}.${UNDO_HINT}`, 'success');
      if (deleteModal) deleteModal.close();
      modToDelete = null;
      await loadMods();
    } catch (err) {
      Panel.toast(err.message, 'error');
    } finally {
      btn.disabled = false;
    }
  });

  // 9. SUBIDA MÚLTIPLE DE ARCHIVOS (BATCH UPLOAD + DROPZONE)
  $('#btn-open-upload-modal')?.addEventListener('click', () => {
    if (uploadStatus) uploadStatus.textContent = '';
    if (uploadProgress) uploadProgress.classList.add('hidden');
    if (uploadModal) uploadModal.showModal();
  });

  $('#close-upload-modal')?.addEventListener('click', () => {
    if (uploadModal) uploadModal.close();
  });

  async function handleBatchFileUpload(files) {
    if (!files || files.length === 0) return;
    const jarFiles = Array.from(files).filter(f => f.name.toLowerCase().endsWith('.jar'));
    if (jarFiles.length === 0) {
      Panel.toast('Elegí archivos válidos que terminen en .jar.', 'error');
      return;
    }

    if (uploadProgress) uploadProgress.classList.remove('hidden');
    let uploadedCount = 0;
    let failedCount = 0;
    const total = jarFiles.length;

    for (let i = 0; i < total; i++) {
      const file = jarFiles[i];
      if (uploadStatus) uploadStatus.textContent = `Subiendo ${i + 1} de ${total}: ${file.name}...`;

      const formData = new FormData();
      formData.append('file', file);

      try {
        const response = await fetch('/api/mods/upload', {
          method: 'POST',
          body: formData,
          credentials: 'same-origin',
        });
        await Panel.readResponse(response);
        uploadedCount++;
      } catch (err) {
        failedCount++;
        Panel.toast(`${file.name}: ${err.message}`, 'error');
      }
    }

    if (uploadStatus) {
      uploadStatus.textContent = `Finalizado: ${uploadedCount} mod(s) subido(s)${failedCount > 0 ? `, ${failedCount} con error` : ''}.`;
    }

    if (uploadedCount > 0) {
      Panel.toast(`Agregaste ${uploadedCount === 1 ? '1 mod' : `${uploadedCount} mods`}.${UNDO_HINT}`, 'success');
      await loadMods();
    }

    setTimeout(() => {
      if (uploadModal) uploadModal.close();
      if (uploadProgress) uploadProgress.classList.add('hidden');
      if (uploadStatus) uploadStatus.textContent = '';
      if (fileInput) fileInput.value = '';
    }, 1200);
  }

  if (fileInput) {
    fileInput.addEventListener('change', () => {
      if (fileInput.files && fileInput.files.length > 0) {
        handleBatchFileUpload(fileInput.files);
      }
    });
  }

  if (dropZone) {
    ['dragenter', 'dragover'].forEach(type => {
      dropZone.addEventListener(type, (e) => {
        e.preventDefault();
        dropZone.classList.add('border-emerald-400', 'bg-emerald-400/10');
      });
    });

    ['dragleave', 'drop'].forEach(type => {
      dropZone.addEventListener(type, (e) => {
        e.preventDefault();
        dropZone.classList.remove('border-emerald-400', 'bg-emerald-400/10');
      });
    });

    dropZone.addEventListener('drop', (e) => {
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        handleBatchFileUpload(e.dataTransfer.files);
      }
    });
  }

  // 10. PESTAÑAS PRINCIPALES: TUS MODS, BUSCAR Y HISTORIAL
  const TAB_ACTIVE = 'tab-pill -mb-px border-b-2 border-emerald-400 pb-3 font-semibold text-zinc-50';
  const TAB_IDLE = 'tab-pill -mb-px border-b-2 border-transparent pb-3 font-semibold text-zinc-400 hover:text-zinc-200';
  const mainTabs = ['installed', 'modrinth', 'history'];

  function switchMainTab(tab) {
    mainTabs.forEach((name) => {
      const button = $(`#tab-btn-${name}`);
      const panel = $(`#panel-${name}`);
      if (button) {
        button.className = name === tab ? TAB_ACTIVE : TAB_IDLE;
        button.setAttribute('aria-current', name === tab ? 'page' : 'false');
      }
      panel?.classList.toggle('hidden', name !== tab);
    });
    if (tab === 'history') loadHistory();
  }

  mainTabs.forEach((name) => $(`#tab-btn-${name}`)?.addEventListener('click', () => switchMainTab(name)));

  // 11. BÚSQUEDA Y CATÁLOGO MODRINTH CON RESOLUCIÓN DE DEPENDENCIAS
  if (modrinthForm) {
    modrinthForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const query = modrinthInput.value.trim();
      if (!query) return;

      const selectedLoader = modrinthLoaderSelect ? modrinthLoaderSelect.value : 'auto';
      const selectedVersion = modrinthVersionInput ? modrinthVersionInput.value.trim() : '';

      const queryParams = new URLSearchParams({ query });
      if (selectedLoader && selectedLoader !== 'auto') {
        queryParams.set('loader', selectedLoader);
      }
      if (selectedVersion) {
        queryParams.set('game_version', selectedVersion);
      }

      modrinthResults.innerHTML = `<p class="py-12 text-center text-zinc-500">Buscando…</p>`;

      try {
        const hits = await Panel.api(`/api/mods/search?${queryParams.toString()}`);
        if (!hits.length) {
          modrinthResults.innerHTML = `
            <div class="py-12 text-center">
              <p class="font-semibold text-zinc-200">No encontramos mods con ese nombre que funcionen en tu servidor</p>
              <p class="mt-1 text-zinc-500">Probá con otro nombre o revisá las opciones avanzadas.</p>
            </div>
          `;
          return;
        }

        const installedNames = new Set(installedMods.map(m => m.name.toLowerCase()));

        modrinthResults.innerHTML = hits.map(hit => {
          const isAlreadyInstalled = installedNames.has(hit.title.toLowerCase()) || installedNames.has(hit.slug.toLowerCase());
          const icon = hit.icon_url
            ? `<img class="h-11 w-11 shrink-0 rounded-lg object-cover" src="${esc(hit.icon_url)}" alt="">`
            : `<div class="h-11 w-11 shrink-0 rounded-lg bg-zinc-800"></div>`;
          const downloads = Number(hit.downloads || 0).toLocaleString('es-AR');

          return `
            <article class="flex items-start gap-4 border-b border-zinc-800 py-5">
              ${icon}
              <div class="min-w-0 flex-1">
                <h3 class="font-semibold text-zinc-50">${esc(hit.title)}</h3>
                <p class="mt-0.5 line-clamp-2 text-sm leading-relaxed text-zinc-400">${esc(hit.description)}</p>
                <p class="mt-1.5 text-sm text-zinc-500">${downloads} descargas · <a href="https://modrinth.com/mod/${esc(hit.slug)}" target="_blank" rel="noopener noreferrer" class="link">Ver en Modrinth</a></p>
              </div>
              ${isAlreadyInstalled
                ? `<span class="shrink-0 py-2 text-sm text-zinc-500">Ya lo tenés</span>`
                : `<button type="button" data-install-project="${esc(hit.project_id)}" class="install-mod-btn v2-button btn-primary shrink-0 min-h-0 py-2 text-sm">Instalar</button>`
              }
            </article>
          `;
        }).join('');
      } catch (err) {
        modrinthResults.innerHTML = `<p class="py-12 text-center text-[#f3a79b]">${esc(err.message)}</p>`;
      }
    });

    modrinthResults.addEventListener('click', async (e) => {
      const installBtn = e.target.closest('.install-mod-btn');
      if (!installBtn) return;
      const projectId = installBtn.dataset.installProject;
      if (!projectId) return;

      const selectedLoader = modrinthLoaderSelect ? modrinthLoaderSelect.value : 'auto';
      const selectedVersion = modrinthVersionInput ? modrinthVersionInput.value.trim() : '';
      const installBody = {
        project_id: projectId,
        install_dependencies: true,
      };
      if (selectedLoader && selectedLoader !== 'auto') {
        installBody.loader = selectedLoader;
      }
      if (selectedVersion) {
        installBody.game_version = selectedVersion;
      }

      installBtn.disabled = true;
      installBtn.textContent = 'Instalando mod y librerías...';
      try {
        const mod = await Panel.api('/api/mods/install', {
          method: 'POST',
          body: installBody,
        });
        Panel.toast(`Instalaste ${mod.name}.${UNDO_HINT}`, 'success');
        installBtn.replaceWith(document.createRange().createContextualFragment(
          `<span class="shrink-0 py-2 text-sm text-zinc-500">Ya lo tenés</span>`
        ));
        await loadMods();
      } catch (err) {
        Panel.toast(err.message, 'error');
        installBtn.disabled = false;
        installBtn.textContent = 'Instalar';
      }
    });
  }

  // 12. EXPORTAR MODPACK CLIENTE
  if (exportBtn) {
    exportBtn.addEventListener('click', async () => {
      exportBtn.disabled = true;
      exportBtn.textContent = 'Generando ZIP...';
      try {
        const res = await Panel.api('/api/mods/export-client-pack', { method: 'POST' });
        Panel.toast(res.message, 'success');
        if (downloadBtn) {
          downloadBtn.classList.remove('hidden');
          downloadBtn.classList.add('inline-flex');
        }
        if (packInfo) {
          packInfo.textContent = `Paquete listo (${res.size_mb} MB). Los mods exclusivos de servidor fueron excluidos automáticamente.`;
          packInfo.classList.remove('hidden');
        }
      } catch (err) {
        Panel.toast(err.message, 'error');
      } finally {
        exportBtn.disabled = false;
        exportBtn.textContent = 'Regenerar Modpack';
      }
    });
  }

  // 13. HISTORIAL Y VOLVER ATRÁS
  const historyList = $('#history-list');
  const historyEmpty = $('#history-empty');
  const historyDialog = $('#modal-history-restore');
  const historyConsequence = $('#history-restore-consequence');
  const confirmHistoryRestore = $('#confirm-history-restore');
  let historyTarget = null;

  // "12 de octubre a las 18:04", the way people say it.
  const formatMoment = (value) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    const sameYear = date.getFullYear() === new Date().getFullYear();
    const dayOptions = sameYear ? { day: 'numeric', month: 'long' } : { day: 'numeric', month: 'long', year: 'numeric' };
    const day = date.toLocaleDateString('es-AR', dayOptions);
    const time = date.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' });
    return `${day} a las ${time}`;
  };

  // "hace 5 minutos", "ayer", "hace 3 días"; older points show their date.
  const relativeTime = (value) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    const seconds = Math.round((date.getTime() - Date.now()) / 1000);
    const abs = Math.abs(seconds);
    const format = new Intl.RelativeTimeFormat('es-AR', { numeric: 'auto' });
    if (abs < 60) return 'recién';
    if (abs < 3600) return format.format(Math.round(seconds / 60), 'minute');
    if (abs < 86400) return format.format(Math.round(seconds / 3600), 'hour');
    if (abs < 86400 * 7) return format.format(Math.round(seconds / 86400), 'day');
    return `el ${formatMoment(value)}`;
  };

  async function loadHistory() {
    if (!historyList) return;
    try {
      const entries = await Panel.api('/api/mods/history');
      if (!entries.length) {
        historyList.classList.add('hidden');
        historyEmpty?.classList.remove('hidden');
        return;
      }
      historyEmpty?.classList.add('hidden');
      historyList.classList.remove('hidden');
      historyList.innerHTML = entries.map((entry) => {
        const id = esc(entry.id);
        const missingNote = entry.restorable
          ? ''
          : ' · <span class="text-[#f3a79b]">Faltan archivos de este punto, no se puede volver</span>';
        return `
          <article class="flex flex-col gap-3 border-b border-zinc-800 py-4 sm:flex-row sm:items-start sm:justify-between">
            <div class="min-w-0 flex-1">
              <h3 class="font-semibold text-zinc-50">${esc(entry.summary)}</h3>
              <p class="mt-0.5 text-sm text-zinc-500"><time datetime="${esc(entry.created_at)}" title="${esc(formatMoment(entry.created_at))}">${esc(relativeTime(entry.created_at))}</time>${missingNote}</p>
              <details class="history-details mt-2 text-sm" data-history-id="${id}">
                <summary class="cursor-pointer text-zinc-400 hover:text-zinc-200">Qué cambia si volvés acá</summary>
                <div class="history-diff mt-2 leading-relaxed text-zinc-400"><p class="text-zinc-500">Revisando…</p></div>
              </details>
            </div>
            <button type="button" class="history-restore-btn v2-button btn-quiet shrink-0" data-history-id="${id}" data-created-at="${esc(entry.created_at)}" ${entry.restorable ? '' : 'disabled'}>Volver a este punto</button>
          </article>`;
      }).join('');
    } catch (err) {
      historyEmpty?.classList.add('hidden');
      historyList.classList.remove('hidden');
      historyList.innerHTML = `<p class="py-12 text-center text-[#f3a79b]">No pudimos cargar el historial. ${esc(err.message)}</p>`;
    }
  }

  async function loadHistoryDiff(details) {
    if (details.dataset.loaded === 'true') return;
    const target = details.querySelector('.history-diff');
    try {
      const detail = await Panel.api(`/api/mods/history/${encodeURIComponent(details.dataset.historyId)}`);
      const lines = detail.lines.length
        ? `<ul class="space-y-1">${detail.lines.map((line) => `<li>${esc(line)}</li>`).join('')}</ul>`
        : '<p>Tus mods ya están así.</p>';
      const missing = detail.missing.length
        ? `<p class="mt-2 text-[#f3a79b]">Ya no tenemos: ${detail.missing.map((mod) => esc(mod.name)).join(', ')}.</p>`
        : '';
      target.innerHTML = lines + missing;
      details.dataset.loaded = 'true';
    } catch (err) {
      target.innerHTML = `<p class="text-[#f3a79b]">${esc(err.message)}</p>`;
    }
  }

  if (historyList) {
    // "toggle" does not bubble, so listen in the capture phase.
    historyList.addEventListener('toggle', (event) => {
      const details = event.target;
      if (details.classList && details.classList.contains('history-details') && details.open) loadHistoryDiff(details);
    }, true);

    historyList.addEventListener('click', (event) => {
      const button = event.target.closest('.history-restore-btn');
      if (!button || button.disabled) return;
      historyTarget = button.dataset.historyId;
      if (historyConsequence) {
        historyConsequence.textContent = `Tus mods quedan como estaban el ${formatMoment(button.dataset.createdAt)}. Primero apagá el servidor.`;
      }
      historyDialog?.showModal();
    });
  }

  $('#cancel-history-restore')?.addEventListener('click', () => {
    historyTarget = null;
    historyDialog?.close();
  });

  confirmHistoryRestore?.addEventListener('click', async () => {
    if (!historyTarget) return;
    confirmHistoryRestore.disabled = true;
    confirmHistoryRestore.textContent = 'Volviendo…';
    try {
      const result = await Panel.api(`/api/mods/history/${encodeURIComponent(historyTarget)}/restore`, {
        method: 'POST',
        body: { confirm: true },
      });
      historyDialog?.close();
      Panel.toast(result.undo_id ? result.message + UNDO_HINT : result.message, 'success');
      historyTarget = null;
      await Promise.all([loadMods(), loadHistory()]);
    } catch (err) {
      Panel.toast(err.message, 'error');
    } finally {
      confirmHistoryRestore.disabled = false;
      confirmHistoryRestore.textContent = 'Volver a este punto';
    }
  });

  // Carga inicial
  loadEnvironment();
  loadMods();
});
