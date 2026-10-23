/**
 * Centro de Restricciones & WorldEdit Hot-Toggle
 * Modulo de administración para gestión agnóstica de ítems, mobs, aldeanos y WorldEdit live toggle.
 */

(() => {
  // Helpers
  const $ = (s) => document.querySelector(s);
  const esc = (s) => (window.Panel && window.Panel.escapeHtml) ? window.Panel.escapeHtml(s) : String(s);

  const Panel = {
    get api() {
      return (window.Panel && window.Panel.api) ? window.Panel.api : (async () => { throw new Error('Panel API no disponible.'); });
    },
    get toast() {
      return (window.Panel && window.Panel.toast) ? window.Panel.toast : ((msg, type) => console.log(`[Toast ${type || 'info'}] ${msg}`));
    },
    get escapeHtml() {
      return (window.Panel && window.Panel.escapeHtml) ? window.Panel.escapeHtml : ((s) => String(s));
    }
  };

  // State variables
  let restrictionsSummary = { blocked_items: [], blocked_mobs: [], disabled_villagers: [], villagers: [] };
  let restrictionsCatalog = { items: [], mobs: [], villagers: [] };
  let curItemsMod = 'all';
  let curMobsMod = 'all';
  let itemsSearchTerm = '';
  let mobsSearchTerm = '';
  let searchDebounceItems, searchDebounceMobs;
  let worldEditEnabled = false;

  // Filter pills: same look as the filters on the mods page.
  const FILTER_ON_CLASSES = ['active', 'bg-zinc-800', 'text-zinc-50'];
  const FILTER_OFF_CLASSES = ['text-zinc-400', 'hover:text-zinc-200'];
  const FILTER_ON = FILTER_ON_CLASSES.join(' ');
  const FILTER_OFF = FILTER_OFF_CLASSES.join(' ');

  // 1. Pestañas (Tabs)
  function switchTab(tabName) {
    if (tabName === 'worldedit') document.querySelector('#worldedit-optional-tab')?.setAttribute('open', '');
    // Underline sub-tabs: only the border colour and text colour change.
    document.querySelectorAll('.tab-btn').forEach(btn => {
      const isActive = btn.dataset?.tab === tabName;
      btn.classList.toggle('active', isActive);
      if (btn.setAttribute) btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
      if (isActive) {
        btn.classList.add('border-emerald-400', 'text-zinc-50');
        btn.classList.remove('border-transparent', 'text-zinc-400', 'hover:text-zinc-200');
      } else {
        btn.classList.remove('border-emerald-400', 'text-zinc-50');
        btn.classList.add('border-transparent', 'text-zinc-400', 'hover:text-zinc-200');
      }
    });

    document.querySelectorAll('#restrictions-hub .tab-panel').forEach(panel => {
      panel.classList.toggle('hidden', panel.id !== `tab-panel-${tabName}`);
    });
  }

  // 2. WorldEdit Hot-Toggle
  async function loadWorldEditStatus() {
    try {
      const s = await Panel.api('/api/worldedit/status');
      worldEditEnabled = !!s.enabled;
      const worldEditAvailable = s.available !== false;
      const tools = $('#worldedit-tools');
      const optionalTab = $('#worldedit-optional-tab');
      if (!worldEditAvailable) {
        tools?.classList.add('hidden');
        optionalTab?.classList.add('hidden');
        return;
      }
      tools?.classList.remove('hidden');
      optionalTab?.classList.remove('hidden');
      const badge = $('#we-live-badge');
      const tabBadge = $('#tab-badge-worldedit');
      const quickBadge = $('#quick-we-badge');
      const btn = $('#btn-toggle-worldedit');
      const msg = $('#we-feedback-msg');

      // State is plain text; the button is the only emphasis.
      if (worldEditEnabled) {
        if (badge) {
          badge.textContent = 'encendido';
          badge.className = 'font-semibold text-zinc-50';
        }
        if (tabBadge) {
          tabBadge.textContent = '· encendidas';
          tabBadge.className = 'font-normal text-zinc-500';
        }
        if (quickBadge) {
          quickBadge.textContent = 'encendido';
          quickBadge.className = 'text-sm text-zinc-500';
        }
        if (btn) {
          btn.textContent = 'Apagar WorldEdit';
          btn.className = 'v2-button btn-quiet';
        }
      } else {
        if (badge) {
          badge.textContent = 'apagado';
          badge.className = 'font-semibold text-zinc-400';
        }
        if (tabBadge) {
          tabBadge.textContent = '· apagadas';
          tabBadge.className = 'font-normal text-zinc-500';
        }
        if (quickBadge) {
          quickBadge.textContent = 'apagado';
          quickBadge.className = 'text-sm text-zinc-500';
        }
        if (btn) {
          btn.textContent = 'Encender WorldEdit';
          btn.className = 'v2-button btn-primary';
        }
      }
      if (msg && s.last_updated) {
        const time = new Date(s.last_updated).toLocaleTimeString();
        msg.textContent = `Último cambio: ${time}`;
      }
    } catch (err) {
      console.error('Error cargando estado de WorldEdit:', err);
    }
  }

  // 3. Resumen de Restricciones y Renderizado
  async function loadRestrictionsSummary() {
    try {
      restrictionsSummary = await Panel.api('/api/restrictions/summary');

      const itemsCount = restrictionsSummary.blocked_items?.length || 0;
      const mobsCount = restrictionsSummary.blocked_mobs?.length || 0;
      const villCount = restrictionsSummary.disabled_villagers?.length || 0;

      const sumEl = $('#restrictions-quick-summary');
      if (sumEl) sumEl.textContent = `${itemsCount} objetos prohibidos · ${mobsCount} criaturas quitadas · ${villCount} oficios apagados`;
      const tcItems = $('#tab-count-items'); if (tcItems) tcItems.textContent = itemsCount;
      const tcMobs = $('#tab-count-mobs'); if (tcMobs) tcMobs.textContent = mobsCount;
      const tcVill = $('#tab-count-villagers'); if (tcVill) tcVill.textContent = villCount;
      const bItems = $('#badge-blocked-items-count'); if (bItems) bItems.textContent = `${itemsCount} prohibidos`;
      const bMobs = $('#badge-blocked-mobs-count'); if (bMobs) bMobs.textContent = `${mobsCount} criaturas`;

      // Rows separated by a hairline, same pattern as the mods list.
      const listItems = $('#list-blocked-items');
      if (listItems) {
        if (itemsCount === 0) {
          listItems.innerHTML = '<li class="py-6 text-zinc-500">No hay objetos prohibidos.</li>';
        } else {
          listItems.innerHTML = restrictionsSummary.blocked_items.map(id => {
            const mod = id.includes(':') ? id.split(':')[0].replace('!', '') : 'item';
            const isWildcard = id.includes('*') || id.startsWith('!');
            return `
              <li class="flex items-center gap-4 border-b border-zinc-800 py-3">
                <div class="min-w-0 flex-1">
                  <p class="truncate font-mono text-sm text-zinc-100" title="${esc(id)}">${esc(id)}</p>
                  <p class="text-sm text-zinc-500">${esc(mod)}${isWildcard ? ' · todo lo que coincida' : ''}</p>
                </div>
                <button type="button" data-unblock-item="${esc(id)}" class="shrink-0 rounded-lg px-2 py-1.5 text-sm text-zinc-500 hover:bg-zinc-800 hover:text-zinc-100">Permitir de nuevo</button>
              </li>
            `;
          }).join('');
        }
      }

      const listMobs = $('#list-blocked-mobs');
      if (listMobs) {
        if (mobsCount === 0) {
          listMobs.innerHTML = '<li class="py-6 text-zinc-500">Todas las criaturas aparecen normalmente.</li>';
        } else {
          listMobs.innerHTML = restrictionsSummary.blocked_mobs.map(id => {
            const mod = id.includes(':') ? id.split(':')[0] : 'mob';
            return `
              <li class="flex items-center gap-4 border-b border-zinc-800 py-3">
                <div class="min-w-0 flex-1">
                  <p class="truncate font-mono text-sm text-zinc-100" title="${esc(id)}">${esc(id)}</p>
                  <p class="text-sm text-zinc-500">${esc(mod)}</p>
                </div>
                <button type="button" data-unblock-mob="${esc(id)}" class="shrink-0 rounded-lg px-2 py-1.5 text-sm text-zinc-500 hover:bg-zinc-800 hover:text-zinc-100">Dejar que aparezca</button>
              </li>
            `;
          }).join('');
        }
      }

      renderVillagersGrid();
    } catch (err) {
      console.error('Error cargando resumen de restricciones:', err);
    }
  }

  // One row per profession; a turned-off profession is dimmed, like a disabled mod.
  function renderVillagersGrid() {
    const grid = $('#villagers-grid');
    if (!grid) return;
    const list = restrictionsSummary.villagers || [];
    if (list.length === 0) {
      grid.innerHTML = '<p class="py-6 text-zinc-500">No encontramos oficios para configurar.</p>';
      return;
    }

    grid.innerHTML = list.map(v => {
      const isDis = !!v.disabled;
      return `
        <div class="flex items-center gap-4 border-b border-zinc-800 py-4 ${isDis ? 'opacity-60' : ''}">
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-baseline gap-x-2">
              <h4 class="font-semibold text-zinc-50">${esc(v.name)}</h4>
              <span class="text-sm text-zinc-500">${isDis ? '· apagado' : '· encendido'}</span>
            </div>
            <p class="mt-0.5 truncate text-sm text-zinc-500">Mesa de trabajo: <span class="font-mono">${esc(v.workstation || 'sin mesa')}</span></p>
          </div>
          <button type="button" data-villager-id="${esc(v.id)}" data-disable="${!isDis}" class="v2-button btn-quiet min-h-0 shrink-0 py-1.5 text-sm">${isDis ? 'Encender' : 'Apagar'}</button>
        </div>
      `;
    }).join('');
  }

  // 4. Catálogo Dinámico (100% NO PNGs)
  async function loadCatalog() {
    try {
      const itContainer = $('#items-catalog-container');
      if (itContainer && (!restrictionsCatalog.items || restrictionsCatalog.items.length === 0)) {
        itContainer.innerHTML = '<p class="py-6 text-zinc-500">Revisando tus mods…</p>';
      }
      const mobContainer = $('#mobs-catalog-container');
      if (mobContainer && (!restrictionsCatalog.mobs || restrictionsCatalog.mobs.length === 0)) {
        mobContainer.innerHTML = '<p class="py-6 text-zinc-500">Revisando tus mods…</p>';
      }
      restrictionsCatalog = await Panel.api('/api/restrictions/catalog');
      populateDynamicModFilters();
      populateDynamicMobsModFilters();
      renderItemsCatalog();
      renderMobsCatalog();
    } catch (err) {
      console.error('Error cargando catálogo de restricciones:', err);
    }
  }

  function populateDynamicModFilters() {
    const filtersContainer = $('#items-mod-filters');
    if (!filtersContainer) return;
    const items = restrictionsCatalog.items || [];
    const modCounts = {};
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      if (it.mod) {
        modCounts[it.mod] = (modCounts[it.mod] || 0) + 1;
      }
    }
    const detectedMods = Object.keys(modCounts).sort((a, b) => modCounts[b] - modCounts[a]).slice(0, 8);

    filtersContainer.innerHTML = `
      <button type="button" data-mod="all" class="mod-filter-btn ${curItemsMod === 'all' ? FILTER_ON : FILTER_OFF} rounded-full px-3 py-1.5 font-medium">Todos</button>
      ${detectedMods.map(m => `
        <button type="button" data-mod="${esc(m)}" class="mod-filter-btn ${curItemsMod === m ? FILTER_ON : FILTER_OFF} rounded-full px-3 py-1.5 font-medium">${esc(m)}</button>
      `).join('')}
    `;
  }

  function markFilter(container, selector, activeBtn) {
    container.querySelectorAll(selector).forEach(b => {
      b.classList.remove(...FILTER_ON_CLASSES);
      b.classList.add(...FILTER_OFF_CLASSES);
    });
    activeBtn.classList.add(...FILTER_ON_CLASSES);
    activeBtn.classList.remove(...FILTER_OFF_CLASSES);
  }

  function populateDynamicMobsModFilters() {
    const filtersContainer = $('#mobs-mod-filters');
    if (!filtersContainer) return;
    const mobs = restrictionsCatalog.mobs || [];
    const modCounts = {};
    for (let i = 0; i < mobs.length; i++) {
      const m = mobs[i];
      if (m.mod) {
        modCounts[m.mod] = (modCounts[m.mod] || 0) + 1;
      }
    }
    const detectedMods = Object.keys(modCounts).sort((a, b) => modCounts[b] - modCounts[a]).slice(0, 8);

    filtersContainer.innerHTML = `
      <button type="button" data-mob-mod="all" class="mob-filter-btn ${curMobsMod === 'all' ? FILTER_ON : FILTER_OFF} rounded-full px-3 py-1.5 font-medium">Todos</button>
      ${detectedMods.map(m => `
        <button type="button" data-mob-mod="${esc(m)}" class="mob-filter-btn ${curMobsMod === m ? FILTER_ON : FILTER_OFF} rounded-full px-3 py-1.5 font-medium">${esc(m)}</button>
      `).join('')}
    `;
  }

  function renderItemsCatalog() {
    const container = $('#items-catalog-container');
    if (!container) return;
    const items = restrictionsCatalog.items || [];
    const q = itemsSearchTerm.trim().toLowerCase();

    const filtered = items.filter(x => {
      const matchMod = curItemsMod === 'all' || x.mod.toLowerCase() === curItemsMod.toLowerCase();
      const matchQ = !q || x.id.toLowerCase().includes(q) || x.name.toLowerCase().includes(q);
      return matchMod && matchQ;
    }).slice(0, 80);

    if (filtered.length === 0) {
      container.innerHTML = '<p class="py-6 text-zinc-500">No encontramos objetos con esa búsqueda.</p>';
      return;
    }

    container.innerHTML = filtered.map(x => catalogRow(x, `data-block-item="${esc(x.id)}"`, 'Prohibir')).join('');
  }

  function renderMobsCatalog() {
    const container = $('#mobs-catalog-container');
    if (!container) return;
    const mobs = restrictionsCatalog.mobs || [];
    const q = mobsSearchTerm.trim().toLowerCase();

    const filtered = mobs.filter(x => {
      const matchMod = curMobsMod === 'all' || x.mod.toLowerCase() === curMobsMod.toLowerCase();
      const matchQ = !q || x.id.toLowerCase().includes(q) || x.name.toLowerCase().includes(q);
      return matchMod && matchQ;
    }).slice(0, 80);

    if (filtered.length === 0) {
      container.innerHTML = '<p class="py-6 text-zinc-500">No encontramos criaturas con esa búsqueda.</p>';
      return;
    }

    container.innerHTML = filtered.map(x => catalogRow(x, `data-block-mob="${esc(x.id)}"`, 'Quitar del mundo')).join('');
  }

  // A catalogue entry (item or mob). `actionAttr` must already be escaped.
  function catalogRow(x, actionAttr, actionLabel) {
    return `
      <div class="flex items-center gap-4 border-b border-zinc-800 py-3">
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-baseline gap-x-2">
            <span class="truncate font-medium text-zinc-100">${esc(x.name)}</span>
            <span class="text-sm text-zinc-500">${esc(x.mod)}</span>
          </div>
          <p class="truncate font-mono text-xs text-zinc-500">${esc(x.id)}</p>
        </div>
        <button type="button" ${actionAttr} class="v2-button btn-quiet min-h-0 shrink-0 py-1.5 text-sm">${esc(actionLabel)}</button>
      </div>
    `;
  }

  // 5. Navegación por Hash
  function handleHashNavigation() {
    const hash = window.location.hash;
    const scrollToHub = () => {
      setTimeout(() => {
        const el = document.getElementById('restrictions-hub');
        if (el) el.scrollIntoView({ behavior: 'smooth' });
      }, 100);
    };

    if (hash === '#worldedit') {
      switchTab('worldedit');
      scrollToHub();
    } else if (hash === '#restrictions-hub' || hash === '#items') {
      switchTab('items');
      scrollToHub();
    } else if (hash === '#mobs') {
      switchTab('mobs');
      scrollToHub();
    } else if (hash === '#villagers') {
      switchTab('villagers');
      scrollToHub();
    } else if (hash === '#configs') {
      switchTab('configs');
      scrollToHub();
    }
  }

  // 6. Registro de Listeners de Eventos
  function initEventListeners() {
    // Tabs
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });

    document.querySelectorAll('.nav-shortcut-tab').forEach(a => {
      a.addEventListener('click', () => {
        const targetTab = a.dataset.tabTarget;
        if (targetTab) switchTab(targetTab);
      });
    });

    // WorldEdit Hot-Toggle
    $('#btn-toggle-worldedit')?.addEventListener('click', async () => {
      const btn = $('#btn-toggle-worldedit');
      if (!btn) return;
      const prev = btn.innerHTML;
      btn.textContent = 'Aplicando…';
      btn.disabled = true;
      try {
        const res = await Panel.api('/api/worldedit/toggle', {
          method: 'POST',
          body: { enabled: !worldEditEnabled }
        });
        Panel.toast(res.message, res.enabled ? 'success' : 'info');
        await loadWorldEditStatus();
      } catch (err) {
        btn.innerHTML = prev;
        Panel.toast(err.message, 'error');
      } finally {
        btn.disabled = false;
      }
    });

    // Filtros y búsqueda de ítems
    $('#items-catalog-search')?.addEventListener('input', (e) => {
      clearTimeout(searchDebounceItems);
      itemsSearchTerm = e.target.value;
      searchDebounceItems = setTimeout(renderItemsCatalog, 200);
    });

    $('#items-mod-filters')?.addEventListener('click', (e) => {
      const btn = e.target.closest('.mod-filter-btn');
      if (!btn) return;
      markFilter(document, '#items-mod-filters .mod-filter-btn', btn);
      curItemsMod = btn.dataset.mod || 'all';
      renderItemsCatalog();
    });

    $('#items-catalog-container')?.addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-block-item]');
      if (!btn) return;
      const itemId = btn.dataset.blockItem;
      try {
        const res = await Panel.api('/api/restrictions/items', {
          method: 'POST',
          body: { item_id: itemId }
        });
        Panel.toast(res.message || `${itemId} quedó prohibido.`, 'success');
        await loadRestrictionsSummary();
      } catch (err) {
        Panel.toast(err.message, 'error');
      }
    });

    $('#list-blocked-items')?.addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-unblock-item]');
      if (!btn) return;
      const itemId = btn.dataset.unblockItem;
      try {
        const res = await Panel.api('/api/restrictions/items/' + encodeURIComponent(itemId), {
          method: 'DELETE'
        });
        Panel.toast(res.message || `${itemId} se puede usar de nuevo.`, 'info');
        await loadRestrictionsSummary();
      } catch (err) {
        Panel.toast(err.message, 'error');
      }
    });

    $('#form-add-item-custom')?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const inp = $('#input-item-custom');
      const val = inp?.value.trim();
      if (!val) return;
      try {
        const res = await Panel.api('/api/restrictions/items', {
          method: 'POST',
          body: { item_id: val }
        });
        if (inp) inp.value = '';
        Panel.toast(res.message || `${val} quedó prohibido.`, 'success');
        await loadRestrictionsSummary();
      } catch (err) {
        Panel.toast(err.message, 'error');
      }
    });

    // Filtros y búsqueda de mobs
    $('#mobs-catalog-search')?.addEventListener('input', (e) => {
      clearTimeout(searchDebounceMobs);
      mobsSearchTerm = e.target.value;
      searchDebounceMobs = setTimeout(renderMobsCatalog, 200);
    });

    $('#mobs-mod-filters')?.addEventListener('click', (e) => {
      const btn = e.target.closest('.mob-filter-btn');
      if (!btn) return;
      markFilter(document, '#mobs-mod-filters .mob-filter-btn', btn);
      curMobsMod = btn.dataset.mobMod || 'all';
      renderMobsCatalog();
    });

    $('#mobs-catalog-container')?.addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-block-mob]');
      if (!btn) return;
      const entityId = btn.dataset.blockMob;
      try {
        const res = await Panel.api('/api/restrictions/mobs', {
          method: 'POST',
          body: { entity_id: entityId }
        });
        Panel.toast(res.message || `${entityId} ya no aparece solo.`, 'success');
        await loadRestrictionsSummary();
      } catch (err) {
        Panel.toast(err.message, 'error');
      }
    });

    $('#list-blocked-mobs')?.addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-unblock-mob]');
      if (!btn) return;
      const entityId = btn.dataset.unblockMob;
      try {
        const res = await Panel.api('/api/restrictions/mobs/' + encodeURIComponent(entityId), {
          method: 'DELETE'
        });
        Panel.toast(res.message || `${entityId} vuelve a aparecer.`, 'info');
        await loadRestrictionsSummary();
      } catch (err) {
        Panel.toast(err.message, 'error');
      }
    });

    $('#form-add-mob-custom')?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const inp = $('#input-mob-custom');
      const val = inp?.value.trim();
      if (!val) return;
      try {
        const res = await Panel.api('/api/restrictions/mobs', {
          method: 'POST',
          body: { entity_id: val }
        });
        if (inp) inp.value = '';
        Panel.toast(res.message || `${val} ya no aparece solo.`, 'success');
        await loadRestrictionsSummary();
      } catch (err) {
        Panel.toast(err.message, 'error');
      }
    });

    // Aldeanos
    $('#villagers-grid')?.addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-villager-id]');
      if (!btn) return;
      const id = btn.dataset.villagerId;
      const disable = btn.dataset.disable === 'true';
      try {
        const res = await Panel.api('/api/restrictions/villagers', {
          method: 'POST',
          body: { profession_id: id, disable: disable }
        });
        Panel.toast(res.message || `Oficio ${id} actualizado.`, disable ? 'warning' : 'success');
        await loadRestrictionsSummary();
      } catch (err) {
        Panel.toast(err.message, 'error');
      }
    });

    // Botón de recarga (/reload)
    $('#btn-restrictions-reload')?.addEventListener('click', async () => {
      const btn = $('#btn-restrictions-reload');
      if (!btn) return;
      const prev = btn.innerHTML;
      btn.textContent = 'Aplicando…';
      btn.disabled = true;
      try {
        const res = await Panel.api('/api/console', {
          method: 'POST',
          body: { command: 'reload' }
        });
        Panel.toast(res.message || 'Reglas aplicadas.', 'success');
      } catch (err) {
        Panel.toast(err.message, 'error');
      } finally {
        btn.innerHTML = prev;
        btn.disabled = false;
      }
    });

    // Listen to hash changes dynamically
    window.addEventListener('hashchange', handleHashNavigation);
  }

  // 7. Inicialización automática
  function initRestrictions() {
    const hub = document.getElementById('restrictions-hub');
    const weBtn = document.getElementById('btn-toggle-worldedit');
    const quickWe = document.getElementById('quick-we-badge');

    // Solo inicializa si los componentes de restricciones o WorldEdit están en el DOM
    if (!hub && !weBtn && !quickWe) return;

    initEventListeners();
    loadWorldEditStatus();
    loadRestrictionsSummary();
    handleHashNavigation();
    loadCatalog();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initRestrictions);
  } else {
    initRestrictions();
  }

  // Exportar funciones y métodos en window para interoperabilidad y pruebas
  window.switchTab = switchTab;
  window.loadWorldEditStatus = loadWorldEditStatus;
  window.loadRestrictionsSummary = loadRestrictionsSummary;
  window.loadCatalog = loadCatalog;
  window.renderVillagersGrid = renderVillagersGrid;
  window.renderItemsCatalog = renderItemsCatalog;
  window.renderMobsCatalog = renderMobsCatalog;
  window.handleHashNavigation = handleHashNavigation;
  window.initRestrictions = initRestrictions;

  window.AdminRestrictions = {
    switchTab,
    loadWorldEditStatus,
    loadRestrictionsSummary,
    loadCatalog,
    renderVillagersGrid,
    renderItemsCatalog,
    renderMobsCatalog,
    handleHashNavigation,
    initRestrictions,
    getSummary: () => restrictionsSummary,
    getCatalog: () => restrictionsCatalog,
    isWorldEditEnabled: () => worldEditEnabled
  };
})();
