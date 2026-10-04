/**
 * Gestor de Mods (web_panel/static/js/mods.js)
 * Controlador modular para la administración interactiva de mods locales y catálogo Modrinth.
 * Soporta operaciones en lote, subida múltiple, metadatos enriquecidos, configs y verificación de versiones.
 */

document.addEventListener('DOMContentLoaded', () => {
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => document.querySelectorAll(selector);
  const esc = Panel.escapeHtml;

  // Estado del cliente
  let installedMods = [];
  let currentFilter = 'all';
  let currentSort = 'name';
  let searchTerm = '';
  let modToDelete = null;
  const selectedFilenames = new Set();
  let updatesMap = {};

  // Elementos DOM principales
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

  // 1. CARGA DE MODS
  async function loadMods() {
    try {
      if (installedContainer) {
        installedContainer.innerHTML = `
          <div class="col-span-full py-12 text-center text-zinc-500">
            <span class="inline-block animate-spin text-2xl mb-2">⏳</span>
            <p class="text-sm">Cargando lista de mods...</p>
          </div>
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
          <div class="col-span-full rounded-xl border border-rose-500/30 bg-rose-950/20 p-6 text-center text-rose-300 text-sm">
            No se pudieron cargar los mods: ${esc(err.message)}
          </div>
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
            ? 'No se encontraron mods que coincidan con la búsqueda.'
            : 'No hay mods instalados en server/mods todavía.';
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

      const badgeType = isServerOnly
        ? `<span class="inline-flex items-center gap-1 rounded bg-indigo-500/15 border border-indigo-500/30 px-2 py-0.5 text-[11px] font-semibold text-indigo-300" title="Excluido automáticamente del paquete de clientes">⚙️ Solo Servidor</span>`
        : `<span class="inline-flex items-center gap-1 rounded bg-sky-500/15 border border-sky-500/30 px-2 py-0.5 text-[11px] font-semibold text-sky-300">👥 Servidor + Cliente</span>`;

      const statusDot = isEnabled
        ? `<span class="h-2.5 w-2.5 shrink-0 rounded-full bg-emerald-400 ring-4 ring-emerald-400/20" title="Habilitado"></span>`
        : `<span class="h-2.5 w-2.5 shrink-0 rounded-full bg-zinc-600 ring-4 ring-zinc-700/20" title="Deshabilitado"></span>`;

      const versionBadge = mod.version
        ? `<span class="rounded bg-emerald-500/10 border border-emerald-500/20 px-1.5 py-0.5 text-[10px] font-mono font-bold text-emerald-400" title="Versión declarada en metadata">v${esc(mod.version)}</span>`
        : '';

      const authorsText = mod.authors
        ? `<span class="text-[11px] text-zinc-500 truncate max-w-[12rem]">de ${esc(mod.authors)}</span>`
        : '';

      const descriptionText = mod.description
        ? `<p class="text-xs text-zinc-400 mt-1 line-clamp-1 leading-relaxed">${esc(mod.description)}</p>`
        : '';

      const configButton = mod.has_config
        ? `<a href="/administration#configs" class="inline-flex items-center gap-1 rounded-lg border border-zinc-700/80 bg-zinc-800/80 hover:bg-zinc-700/80 px-2.5 py-1 text-xs font-semibold text-zinc-300 hover:text-zinc-100 transition shadow-sm" title="Abrir editor para ${esc(mod.config_filename || 'este mod')}">⚙️ Config</a>`
        : '';

      // Check de actualización
      const updateData = updatesMap[mod.filename];
      const updateBadge = (updateData && updateData.has_update)
        ? `<button data-update-project="${esc(updateData.project_id || '')}" data-update-filename="${encodedFilename}" class="mod-update-btn inline-flex items-center gap-1 rounded-lg bg-sky-500/20 border border-sky-500/40 hover:bg-sky-500/30 px-2 py-1 text-xs font-bold text-sky-300 transition shadow-sm animate-pulse" title="Nueva versión disponible en Modrinth">🚀 Actualizar a v${esc(updateData.latest_version || '')}</button>`
        : '';

      return `
        <article class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 sm:p-5 rounded-2xl border ${isEnabled ? 'border-zinc-800 bg-zinc-900/60' : 'border-zinc-800/60 bg-zinc-950/40 opacity-80'} hover:border-zinc-700 transition">
          <div class="flex items-start sm:items-center gap-3.5 min-w-0 flex-1">
            <!-- Selector para operaciones en lote -->
            <label class="cursor-pointer pt-0.5 sm:pt-0 shrink-0">
              <input type="checkbox" data-select-filename="${esc(mod.filename)}" ${isSelected ? 'checked' : ''} class="mod-select-checkbox rounded border-zinc-700 bg-zinc-800 text-emerald-500 focus:ring-emerald-400 h-4 w-4">
            </label>

            <div class="mt-1 sm:mt-0">${statusDot}</div>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <h4 class="font-bold text-sm text-zinc-100 truncate">${esc(mod.name)}</h4>
                ${versionBadge}
                <span class="rounded bg-zinc-800/80 px-2 py-0.5 text-[11px] font-mono text-zinc-400">${mod.size_mb.toFixed(2)} MB</span>
                ${badgeType}
                ${authorsText}
                ${updateBadge}
              </div>
              <p class="text-xs text-zinc-500 font-mono mt-0.5 truncate" title="${esc(mod.filename)}">
                ${esc(mod.filename)}
              </p>
              ${descriptionText}
            </div>
          </div>

          <div class="flex items-center gap-3 self-end sm:self-center shrink-0">
            ${configButton}

            <!-- Modern Switch -->
            <label class="relative inline-flex items-center cursor-pointer select-none">
              <input type="checkbox" ${isEnabled ? 'checked' : ''} data-toggle-filename="${encodedFilename}" class="mod-switch-checkbox sr-only peer">
              <div class="w-11 h-6 bg-zinc-800 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-zinc-200 after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-emerald-400 peer-checked:after:bg-zinc-950"></div>
              <span class="ml-2 text-xs font-semibold ${isEnabled ? 'text-emerald-300' : 'text-zinc-400'}">${isEnabled ? 'Activo' : 'Inactivo'}</span>
            </label>

            <!-- Botón Borrar -->
            <button data-delete-filename="${encodedFilename}" data-mod-name="${esc(mod.name)}" class="delete-mod-btn rounded-lg p-2 text-zinc-500 hover:text-rose-400 hover:bg-rose-500/10 transition" title="Eliminar mod permanentemente">
              <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          </div>
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
        b.classList.remove('bg-emerald-400/20', 'text-emerald-300', 'border-emerald-500/40');
        b.classList.add('bg-zinc-900', 'text-zinc-400', 'border-zinc-800');
      });
      btn.classList.add('bg-emerald-400/20', 'text-emerald-300', 'border-emerald-500/40');
      btn.classList.remove('bg-zinc-900', 'text-zinc-400', 'border-zinc-800');
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
          Panel.toast(result.message, 'success');
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
        updateBtn.disabled = true;
        updateBtn.innerHTML = `⏳ Actualizando...`;
        try {
          const mod = await Panel.api('/api/mods/install', {
            method: 'POST',
            body: { project_id: projectId },
          });
          Panel.toast(`¡Mod "${mod.name}" actualizado con éxito!`, 'success');
          await loadMods();
        } catch (err) {
          Panel.toast(err.message, 'error');
          updateBtn.disabled = false;
          updateBtn.innerHTML = `🚀 Reintentar`;
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
      Panel.toast(res.message, res.errors.length ? 'info' : 'success');
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
      btnCheckUpdates.innerHTML = `<span class="inline-block animate-spin mr-1">⏳</span> Buscando...`;
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
        btnCheckUpdates.innerHTML = `<span>🔄</span> Buscar Actualizaciones`;
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
      Panel.toast(`Mod "${modToDelete}" eliminado correctamente.`, 'success');
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
      Panel.toast(`¡${uploadedCount} archivo(s) .jar subidos con éxito!`, 'success');
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

  // 10. PESTAÑAS PRINCIPALES: INSTALADOS VS MODRINTH
  const tabBtnInstalled = $('#tab-btn-installed');
  const tabBtnModrinth = $('#tab-btn-modrinth');
  const panelInstalled = $('#panel-installed');
  const panelModrinth = $('#panel-modrinth');

  function switchMainTab(tab) {
    if (tab === 'installed') {
      tabBtnInstalled.className = 'tab-pill rounded-xl bg-emerald-400 px-4 py-2 text-xs sm:text-sm font-bold text-zinc-950 shadow-sm transition';
      tabBtnModrinth.className = 'tab-pill rounded-xl border border-zinc-800 bg-zinc-900 px-4 py-2 text-xs sm:text-sm font-semibold text-zinc-400 hover:text-zinc-200 transition';
      panelInstalled.classList.remove('hidden');
      panelModrinth.classList.add('hidden');
    } else {
      tabBtnModrinth.className = 'tab-pill rounded-xl bg-emerald-400 px-4 py-2 text-xs sm:text-sm font-bold text-zinc-950 shadow-sm transition';
      tabBtnInstalled.className = 'tab-pill rounded-xl border border-zinc-800 bg-zinc-900 px-4 py-2 text-xs sm:text-sm font-semibold text-zinc-400 hover:text-zinc-200 transition';
      panelModrinth.classList.remove('hidden');
      panelInstalled.classList.add('hidden');
    }
  }

  tabBtnInstalled?.addEventListener('click', () => switchMainTab('installed'));
  tabBtnModrinth?.addEventListener('click', () => switchMainTab('modrinth'));

  // 11. BÚSQUEDA Y CATÁLOGO MODRINTH CON RESOLUCIÓN DE DEPENDENCIAS
  if (modrinthForm) {
    modrinthForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const query = modrinthInput.value.trim();
      if (!query) return;

      modrinthResults.innerHTML = `
        <div class="py-12 text-center text-zinc-500">
          <span class="inline-block animate-spin text-2xl mb-2">⏳</span>
          <p class="text-sm">Buscando mods compatibles en Modrinth...</p>
        </div>
      `;

      try {
        const hits = await Panel.api(`/api/mods/search?query=${encodeURIComponent(query)}`);
        if (!hits.length) {
          modrinthResults.innerHTML = `
            <div class="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-8 text-center text-zinc-500">
              <span class="text-3xl block mb-2">🔍</span>
              <p class="font-semibold text-zinc-300">No se encontraron mods compatibles con NeoForge 1.21.1</p>
              <p class="text-xs text-zinc-500 mt-1">Probá con otro término como "Create", "JEI", "Waystones" o "FerriteCore".</p>
            </div>
          `;
          return;
        }

        const installedNames = new Set(installedMods.map(m => m.name.toLowerCase()));

        modrinthResults.innerHTML = hits.map(hit => {
          const isAlreadyInstalled = installedNames.has(hit.title.toLowerCase()) || installedNames.has(hit.slug.toLowerCase());
          const icon = hit.icon_url
            ? `<img class="h-12 w-12 rounded-xl object-cover ring-1 ring-zinc-700/60" src="${esc(hit.icon_url)}" alt="">`
            : `<div class="grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-zinc-800 text-lg text-emerald-400 ring-1 ring-zinc-700/60 font-bold">◈</div>`;

          return `
            <article class="flex flex-col sm:flex-row gap-4 p-5 rounded-2xl border border-zinc-800 bg-zinc-900/60 hover:border-zinc-700 transition">
              <div class="shrink-0 flex items-start">${icon}</div>
              <div class="min-w-0 flex-1">
                <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div>
                    <h4 class="font-bold text-base text-zinc-100">${esc(hit.title)}</h4>
                    <span class="text-xs font-mono text-zinc-500">Slug: ${esc(hit.slug)}</span>
                  </div>
                  <div>
                    ${isAlreadyInstalled
                      ? `<span class="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/30 px-3 py-1.5 text-xs font-bold text-emerald-300">✓ Ya Instalado</span>`
                      : `<button data-install-project="${esc(hit.project_id)}" class="install-mod-btn rounded-lg bg-emerald-400 px-4 py-2 text-xs font-bold text-zinc-950 hover:bg-emerald-300 transition shadow-sm">Instalar Mod</button>`
                    }
                  </div>
                </div>
                <p class="mt-2 text-xs text-zinc-400 line-clamp-2 leading-relaxed">${esc(hit.description)}</p>
                <div class="mt-3 flex items-center gap-4 text-xs text-zinc-500">
                  <span>📥 ${Number(hit.downloads || 0).toLocaleString('es-AR')} descargas</span>
                  <span class="text-emerald-400/80">⚡ Resuelve dependencias automáticamente</span>
                  <a href="https://modrinth.com/mod/${esc(hit.slug)}" target="_blank" rel="noreferrer" class="text-emerald-400 hover:underline">Ver en Modrinth ↗</a>
                </div>
              </div>
            </article>
          `;
        }).join('');
      } catch (err) {
        modrinthResults.innerHTML = `
          <div class="rounded-xl border border-rose-500/30 bg-rose-950/20 p-5 text-center text-rose-300 text-xs">
            ${esc(err.message)}
          </div>
        `;
      }
    });

    modrinthResults.addEventListener('click', async (e) => {
      const installBtn = e.target.closest('.install-mod-btn');
      if (!installBtn) return;
      const projectId = installBtn.dataset.installProject;
      if (!projectId) return;

      installBtn.disabled = true;
      installBtn.textContent = 'Instalando mod y librerías...';
      try {
        const mod = await Panel.api('/api/mods/install', {
          method: 'POST',
          body: { project_id: projectId, install_dependencies: true },
        });
        Panel.toast(`¡Mod "${mod.name}" y sus librerías requeridas instalados correctamente!`, 'success');
        installBtn.replaceWith(document.createRange().createContextualFragment(
          `<span class="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/30 px-3 py-1.5 text-xs font-bold text-emerald-300">✓ Ya Instalado</span>`
        ));
        await loadMods();
      } catch (err) {
        Panel.toast(err.message, 'error');
        installBtn.disabled = false;
        installBtn.textContent = 'Instalar Mod';
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

  // Carga inicial
  loadMods();
});
