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

  // 1. Pestañas (Tabs)
  function switchTab(tabName) {
    if (tabName === 'worldedit') document.querySelector('#worldedit-optional-tab')?.setAttribute('open', '');
    document.querySelectorAll('.tab-btn').forEach(btn => {
      const isActive = btn.dataset?.tab === tabName;
      btn.classList.toggle('active', isActive);
      if (isActive) {
        btn.classList.add('bg-emerald-500/20', 'text-emerald-300', 'border', 'border-emerald-500/30');
        btn.classList.remove('text-zinc-400', 'hover:text-zinc-200');
      } else {
        btn.classList.remove('bg-emerald-500/20', 'text-emerald-300', 'border', 'border-emerald-500/30');
        btn.classList.add('text-zinc-400', 'hover:text-zinc-200');
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

      if (worldEditEnabled) {
        if (badge) {
          badge.textContent = 'ACTIVADO (LIVE)';
          badge.className = 'rounded-full px-4 py-1.5 text-sm font-black tracking-wide shadow bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 ring-1 ring-emerald-500/30';
        }
        if (tabBadge) {
          tabBadge.textContent = 'ON';
          tabBadge.className = 'ml-1 rounded-full bg-emerald-500/20 text-emerald-300 px-2 py-0.5 text-[10px] font-bold';
        }
        if (quickBadge) {
          quickBadge.textContent = 'HOT-TOGGLE (ON)';
          quickBadge.className = 'rounded bg-emerald-500/20 px-2 py-0.5 text-[10px] font-bold text-emerald-300 ring-1 ring-emerald-500/30';
        }
        if (btn) {
          btn.innerHTML = '<span>🛑</span> Desactivar WorldEdit';
          btn.className = 'w-full mt-2 rounded-xl py-3 px-5 text-xs font-bold transition shadow-lg flex items-center justify-center gap-2 bg-rose-500 hover:bg-rose-400 text-white cursor-pointer';
        }
      } else {
        if (badge) {
          badge.textContent = 'DESACTIVADO';
          badge.className = 'rounded-full px-4 py-1.5 text-sm font-black tracking-wide shadow bg-zinc-800 text-zinc-400 border border-zinc-700';
        }
        if (tabBadge) {
          tabBadge.textContent = 'OFF';
          tabBadge.className = 'ml-1 rounded-full bg-zinc-800 text-zinc-400 px-2 py-0.5 text-[10px]';
        }
        if (quickBadge) {
          quickBadge.textContent = 'HOT-TOGGLE (OFF)';
          quickBadge.className = 'rounded bg-zinc-800 px-2 py-0.5 text-[10px] font-bold text-zinc-400 border border-zinc-700';
        }
        if (btn) {
          btn.innerHTML = '<span>⚡</span> Activar WorldEdit';
          btn.className = 'w-full mt-2 rounded-xl py-3 px-5 text-xs font-bold transition shadow-lg flex items-center justify-center gap-2 bg-emerald-500 hover:bg-emerald-400 text-zinc-950 cursor-pointer';
        }
      }
      if (msg && s.last_updated) {
        const time = new Date(s.last_updated).toLocaleTimeString();
        msg.textContent = `Último cambio: ${time} (${s.method || 'LuckPerms Live'})`;
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
      if (sumEl) sumEl.textContent = `${itemsCount} ítems · ${mobsCount} mobs · ${villCount} mesas bloqueadas`;
      const tcItems = $('#tab-count-items'); if (tcItems) tcItems.textContent = itemsCount;
      const tcMobs = $('#tab-count-mobs'); if (tcMobs) tcMobs.textContent = mobsCount;
      const tcVill = $('#tab-count-villagers'); if (tcVill) tcVill.textContent = villCount;
      const bItems = $('#badge-blocked-items-count'); if (bItems) bItems.textContent = `${itemsCount} bloqueados`;
      const bMobs = $('#badge-blocked-mobs-count'); if (bMobs) bMobs.textContent = `${mobsCount} suprimidos`;

      const listItems = $('#list-blocked-items');
      if (listItems) {
        if (itemsCount === 0) {
          listItems.innerHTML = '<li class="text-xs text-zinc-500 italic p-3 text-center">No hay ítems restringidos actualmente.</li>';
        } else {
          listItems.innerHTML = restrictionsSummary.blocked_items.map(id => {
            const mod = id.includes(':') ? id.split(':')[0].replace('!', '') : 'item';
            const isWildcard = id.includes('*') || id.startsWith('!');
            return `
              <li class="flex items-center justify-between rounded-lg bg-zinc-900/80 px-3 py-2 border border-zinc-800/90 hover:border-zinc-700 transition">
                <div class="flex items-center gap-2 min-w-0">
                  <span class="rounded ${isWildcard ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30' : 'bg-zinc-800 text-emerald-400'} px-1.5 py-0.5 text-[10px] font-mono shrink-0">${esc(mod)}</span>
                  <span class="font-mono text-xs text-zinc-200 truncate" title="${esc(id)}">${esc(id)}</span>
                  ${isWildcard ? '<span class="text-[10px] text-amber-400 font-bold shrink-0">WILDCARD</span>' : ''}
                </div>
                <button data-unblock-item="${esc(id)}" class="text-xs font-semibold text-rose-400 hover:text-rose-300 ml-2 px-2 py-1 rounded hover:bg-rose-500/10 transition shrink-0 cursor-pointer">Quitar</button>
              </li>
            `;
          }).join('');
        }
      }

      const listMobs = $('#list-blocked-mobs');
      if (listMobs) {
        if (mobsCount === 0) {
          listMobs.innerHTML = '<li class="text-xs text-zinc-500 italic p-3 text-center">No hay spawns de mobs suprimidos actualmente.</li>';
        } else {
          listMobs.innerHTML = restrictionsSummary.blocked_mobs.map(id => {
            const mod = id.includes(':') ? id.split(':')[0] : 'mob';
            return `
              <li class="flex items-center justify-between rounded-lg bg-zinc-900/80 px-3 py-2 border border-zinc-800/90 hover:border-zinc-700 transition">
                <div class="flex items-center gap-2 min-w-0">
                  <span class="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] font-mono text-purple-400 shrink-0">${esc(mod)}</span>
                  <span class="font-mono text-xs text-zinc-200 truncate" title="${esc(id)}">${esc(id)}</span>
                </div>
                <button data-unblock-mob="${esc(id)}" class="text-xs font-semibold text-rose-400 hover:text-rose-300 ml-2 px-2 py-1 rounded hover:bg-rose-500/10 transition shrink-0 cursor-pointer">Quitar</button>
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

  const VILLAGER_ICONS = {
    'pointblank:arms_dealer': '🔫',
    'armorer': '🛡️',
    'weaponsmith': '⚔️',
    'toolsmith': '⛏️',
    'fletcher': '🏹',
    'cleric': '✨',
    'librarian': '📚',
    'cartographer': '🗺️',
    'farmer': '🌾',
    'butcher': '🥩',
    'fisherman': '🎣',
    'shepherd': '🐑',
    'leatherworker': '👞',
    'mason': '🧱'
  };

  function renderVillagersGrid() {
    const grid = $('#villagers-grid');
    if (!grid) return;
    const list = restrictionsSummary.villagers || [];
    if (list.length === 0) {
      grid.innerHTML = '<p class="text-xs text-zinc-500 italic p-4 col-span-3 text-center">No se detectaron profesiones configurables.</p>';
      return;
    }

    grid.innerHTML = list.map(v => {
      const isDis = !!v.disabled;
      const vid = String(v.id || v.profession || '');
      const icon = VILLAGER_ICONS[vid] || (vid.includes(':') ? VILLAGER_ICONS[vid.split(':').pop()] : null) || '👨‍🌾';
      return `
        <div class="rounded-xl border ${isDis ? 'border-rose-500/40 bg-rose-950/20' : 'border-zinc-800 bg-zinc-950/70'} p-4 flex flex-col justify-between transition-all hover:border-zinc-700">
          <div>
            <div class="flex items-center justify-between mb-2">
              <div class="flex items-center gap-2">
                <span class="text-2xl">${icon}</span>
                <div>
                  <b class="text-xs font-bold ${isDis ? 'text-rose-200' : 'text-zinc-100'} block">${esc(v.name)}</b>
                  <span class="text-[10px] font-mono text-zinc-500">${esc(v.id)}</span>
                </div>
              </div>
              <span class="rounded px-2 py-0.5 text-[10px] font-bold ${isDis ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30' : 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'}">
                ${isDis ? 'DESACTIVADO' : 'ACTIVO'}
              </span>
            </div>
            <div class="mt-2 text-[11px] text-zinc-400 bg-zinc-900/60 p-2 rounded-lg border border-zinc-800/80">
              <span class="text-zinc-500 block text-[10px] uppercase font-mono">Mesa de trabajo (POI):</span>
              <code class="text-zinc-300 font-mono text-[11px]">${esc(v.workstation || 'N/A')}</code>
            </div>
          </div>
          <div class="mt-4 pt-3 border-t border-zinc-800/80">
            <button data-villager-id="${esc(v.id)}" data-disable="${!isDis}" class="w-full py-2 px-3 rounded-lg text-xs font-bold transition flex items-center justify-center gap-1.5 cursor-pointer ${isDis ? 'bg-emerald-500 hover:bg-emerald-400 text-zinc-950' : 'bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border border-rose-500/30'}">
              <span>${isDis ? '✅ Activar Profesión' : '🚫 Desactivar Mesa'}</span>
            </button>
          </div>
        </div>
      `;
    }).join('');
  }

  // 4. Catálogo Dinámico (100% NO PNGs)
  async function loadCatalog() {
    try {
      const itContainer = $('#items-catalog-container');
      if (itContainer && (!restrictionsCatalog.items || restrictionsCatalog.items.length === 0)) {
        itContainer.innerHTML = '<p class="text-xs text-emerald-400/80 italic p-4 text-center animate-pulse">Escaneando mods instalados (22.000+ ítems)...</p>';
      }
      const mobContainer = $('#mobs-catalog-container');
      if (mobContainer && (!restrictionsCatalog.mobs || restrictionsCatalog.mobs.length === 0)) {
        mobContainer.innerHTML = '<p class="text-xs text-purple-400/80 italic p-4 text-center animate-pulse">Escaneando mods instalados (mobs y entidades)...</p>';
      }
      restrictionsCatalog = await Panel.api('/api/restrictions/catalog');
      renderItemsCatalog();
      renderMobsCatalog();
    } catch (err) {
      console.error('Error cargando catálogo de restricciones:', err);
    }
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
      container.innerHTML = '<p class="text-xs text-zinc-500 italic p-4 text-center">No se encontraron ítems con los filtros aplicados.</p>';
      return;
    }

    container.innerHTML = filtered.map(x => `
      <div class="flex items-center justify-between gap-2 rounded-lg border border-zinc-800 bg-zinc-950/60 p-2.5 hover:border-zinc-700 transition">
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2">
            <span class="rounded bg-zinc-800/90 px-1.5 py-0.5 text-[10px] font-mono text-emerald-400 shrink-0">${esc(x.mod)}</span>
            <b class="text-xs text-zinc-200 truncate">${esc(x.name)}</b>
          </div>
          <span class="text-[11px] font-mono text-zinc-500 block truncate mt-0.5">${esc(x.id)}</span>
        </div>
        <button data-block-item="${esc(x.id)}" class="shrink-0 rounded bg-rose-500/20 hover:bg-rose-500/30 border border-rose-500/30 px-2.5 py-1 text-xs font-semibold text-rose-300 transition cursor-pointer">
          Bloquear
        </button>
      </div>
    `).join('');
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
      container.innerHTML = '<p class="text-xs text-zinc-500 italic p-4 text-center">No se encontraron mobs con los filtros aplicados.</p>';
      return;
    }

    container.innerHTML = filtered.map(x => `
      <div class="flex items-center justify-between gap-2 rounded-lg border border-zinc-800 bg-zinc-950/60 p-2.5 hover:border-zinc-700 transition">
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2">
            <span class="rounded bg-zinc-800/90 px-1.5 py-0.5 text-[10px] font-mono text-purple-400 shrink-0">${esc(x.mod)}</span>
            <b class="text-xs text-zinc-200 truncate">${esc(x.name)}</b>
          </div>
          <span class="text-[11px] font-mono text-zinc-500 block truncate mt-0.5">${esc(x.id)}</span>
        </div>
        <button data-block-mob="${esc(x.id)}" class="shrink-0 rounded bg-purple-500/20 hover:bg-purple-500/30 border border-purple-500/30 px-2.5 py-1 text-xs font-semibold text-purple-300 transition cursor-pointer">
          Suprimir Spawn
        </button>
      </div>
    `).join('');
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
      btn.innerHTML = '<span>⏳</span> Aplicando permisos...';
      btn.disabled = true;
      try {
        const res = await Panel.api('/api/worldedit/toggle', {
          method: 'POST',
          body: { enabled: !worldEditEnabled }
        });
        Panel.toast(res.message, res.enabled ? 'success' : 'info');
        await loadWorldEditStatus();
      } catch (err) {
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

    document.querySelectorAll('#items-mod-filters .mod-filter-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('#items-mod-filters .mod-filter-btn').forEach(b => {
          b.classList.remove('active', 'bg-emerald-500/20', 'text-emerald-300', 'border-emerald-500/30');
          b.classList.add('bg-zinc-800/80', 'text-zinc-300', 'border-zinc-700');
        });
        btn.classList.add('active', 'bg-emerald-500/20', 'text-emerald-300', 'border-emerald-500/30');
        btn.classList.remove('bg-zinc-800/80', 'text-zinc-300', 'border-zinc-700');
        curItemsMod = btn.dataset.mod;
        renderItemsCatalog();
      });
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
        Panel.toast(res.message || `${itemId} bloqueado.`, 'success');
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
        Panel.toast(res.message || `${itemId} desbloqueado.`, 'info');
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
        Panel.toast(res.message || `${val} bloqueado.`, 'success');
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

    document.querySelectorAll('#mobs-mod-filters .mob-filter-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('#mobs-mod-filters .mob-filter-btn').forEach(b => {
          b.classList.remove('active', 'bg-purple-500/20', 'text-purple-300', 'border-purple-500/30');
          b.classList.add('bg-zinc-800/80', 'text-zinc-300', 'border-zinc-700');
        });
        btn.classList.add('active', 'bg-purple-500/20', 'text-purple-300', 'border-purple-500/30');
        btn.classList.remove('bg-zinc-800/80', 'text-zinc-300', 'border-zinc-700');
        curMobsMod = btn.dataset.mobMod;
        renderMobsCatalog();
      });
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
        Panel.toast(res.message || `Spawn de ${entityId} suprimido.`, 'success');
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
        Panel.toast(res.message || `Spawn de ${entityId} restaurado.`, 'info');
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
        Panel.toast(res.message || `Spawn de ${val} suprimido.`, 'success');
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
        Panel.toast(res.message || `Profesión ${id} actualizada.`, disable ? 'warning' : 'success');
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
      btn.innerHTML = '<span>⏳</span> Recargando...';
      btn.disabled = true;
      try {
        const res = await Panel.api('/api/console', {
          method: 'POST',
          body: { command: 'reload' }
        });
        Panel.toast(res.message || 'Servidor recargado (/reload exitoso).', 'success');
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
