/**
 * Gestor de Mods (web_panel/static/js/mods.js)
 * Controlador modular para la administración interactiva de mods locales y catálogo Modrinth.
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

  // Elementos DOM principales
  const installedContainer = $('#installed-mods-container');
  const emptyState = $('#installed-mods-empty');
  const searchInput = $('#local-mod-search');
  const sortSelect = $('#local-mod-sort');
  const filterButtons = $$('.filter-pill');
  
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

  // 3. RENDERIZADO DE MODS INSTALADOS
  function renderInstalledMods() {
    if (!installedContainer) return;

    // Filtrado
    const query = searchTerm.trim().toLowerCase();
    let filtered = installedMods.filter(mod => {
      const matchSearch = !query || mod.name.toLowerCase().includes(query) || mod.filename.toLowerCase().includes(query);
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

      const badgeType = isServerOnly
        ? `<span class="inline-flex items-center gap-1 rounded bg-indigo-500/15 border border-indigo-500/30 px-2 py-0.5 text-[11px] font-semibold text-indigo-300" title="Excluido del paquete cliente">⚙️ Solo Servidor</span>`
        : `<span class="inline-flex items-center gap-1 rounded bg-sky-500/15 border border-sky-500/30 px-2 py-0.5 text-[11px] font-semibold text-sky-300">👥 Servidor + Cliente</span>`;

      const statusDot = isEnabled
        ? `<span class="h-2.5 w-2.5 shrink-0 rounded-full bg-emerald-400 ring-4 ring-emerald-400/20" title="Habilitado"></span>`
        : `<span class="h-2.5 w-2.5 shrink-0 rounded-full bg-zinc-600 ring-4 ring-zinc-700/20" title="Deshabilitado"></span>`;

      return `
        <article class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 sm:p-5 rounded-2xl border ${isEnabled ? 'border-zinc-800 bg-zinc-900/60' : 'border-zinc-800/60 bg-zinc-950/40 opacity-80'} hover:border-zinc-700 transition">
          <div class="flex items-start sm:items-center gap-3.5 min-w-0 flex-1">
            <div class="mt-1 sm:mt-0">${statusDot}</div>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <h4 class="font-bold text-sm text-zinc-100 truncate">${esc(mod.name)}</h4>
                <span class="rounded bg-zinc-800/80 px-2 py-0.5 text-[11px] font-mono text-zinc-400">${mod.size_mb.toFixed(2)} MB</span>
                ${badgeType}
              </div>
              <p class="text-xs text-zinc-500 font-mono mt-1 truncate" title="${esc(mod.filename)}">
                ${esc(mod.filename)}
              </p>
            </div>
          </div>

          <div class="flex items-center gap-4 self-end sm:self-center shrink-0">
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

  // 4. BÚSQUEDA Y FILTRADO LOCAL
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

  // 5. EVENTOS DE LA LISTA: TOGGLE Y DELETE
  if (installedContainer) {
    installedContainer.addEventListener('change', async (event) => {
      const target = event.target;
      if (!target.classList.contains('mod-switch-checkbox')) return;
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
    });

    installedContainer.addEventListener('click', (event) => {
      const deleteBtn = event.target.closest('.delete-mod-btn');
      if (deleteBtn) {
        const filename = deleteBtn.dataset.deleteFilename;
        const modName = deleteBtn.dataset.modName;
        openDeleteModal(filename, modName);
      }
    });
  }

  // 6. MODAL DE ELIMINACIÓN SEGURA
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

  // 7. SUBIDA DE ARCHIVOS (MODAL + DROPZONE)
  $('#btn-open-upload-modal')?.addEventListener('click', () => {
    if (uploadStatus) uploadStatus.textContent = '';
    if (uploadProgress) uploadProgress.classList.add('hidden');
    if (uploadModal) uploadModal.showModal();
  });

  $('#close-upload-modal')?.addEventListener('click', () => {
    if (uploadModal) uploadModal.close();
  });

  async function handleFileUpload(file) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.jar')) {
      Panel.toast('Elegí un archivo que termine en .jar.', 'error');
      return;
    }

    if (uploadStatus) uploadStatus.textContent = `Subiendo ${file.name}...`;
    if (uploadProgress) uploadProgress.classList.remove('hidden');

    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch('/api/mods/upload', {
        method: 'POST',
        body: formData,
        credentials: 'same-origin',
      });
      await Panel.readResponse(response);
      Panel.toast(`Mod "${file.name}" subido con éxito.`, 'success');
      if (uploadStatus) uploadStatus.textContent = `¡"${file.name}" subido correctamente!`;
      await loadMods();
      setTimeout(() => {
        if (uploadModal) uploadModal.close();
      }, 1000);
    } catch (err) {
      if (uploadStatus) uploadStatus.textContent = err.message;
      Panel.toast(err.message, 'error');
    } finally {
      if (uploadProgress) uploadProgress.classList.add('hidden');
      if (fileInput) fileInput.value = '';
    }
  }

  if (fileInput) {
    fileInput.addEventListener('change', () => {
      if (fileInput.files && fileInput.files[0]) {
        handleFileUpload(fileInput.files[0]);
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
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]) {
        handleFileUpload(e.dataTransfer.files[0]);
      }
    });
  }

  // 8. PESTAÑAS PRINCIPALES: INSTALADOS VS MODRINTH
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

  // 9. BÚSQUEDA Y CATÁLOGO MODRINTH
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
              <p class="text-xs text-zinc-500 mt-1">Probá con otro término como "Create", "JEI", "Waystones" o "Sodium".</p>
            </div>
          `;
          return;
        }

        // Renderizar tarjetas de Modrinth
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
      installBtn.textContent = 'Instalando...';
      try {
        const mod = await Panel.api('/api/mods/install', {
          method: 'POST',
          body: { project_id: projectId },
        });
        Panel.toast(`¡Mod "${mod.name}" instalado correctamente!`, 'success');
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

  // 10. EXPORTAR MODPACK CLIENTE
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
