document.addEventListener('DOMContentLoaded', () => {
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => document.querySelectorAll(s);
  const esc = Panel.escapeHtml;

  // Manejo de pestañas principales
  const tabs = {
    worlds: { btn: $('#tab-btn-worlds'), content: $('#tab-content-worlds') },
    props: { btn: $('#tab-btn-props'), content: $('#tab-content-props') },
    whitelist: { btn: $('#tab-btn-whitelist'), content: $('#tab-content-whitelist') },
    advancements: { btn: $('#tab-btn-advancements'), content: $('#tab-content-advancements') },
    luckperms: { btn: $('#tab-btn-luckperms'), content: $('#tab-content-luckperms') },
  };

  const switchTab = (activeKey) => {
    Object.entries(tabs).forEach(([key, tab]) => {
      if (key === activeKey) {
        tab.btn.className = 'tab-btn rounded-lg bg-emerald-400 px-4 py-2 text-sm font-semibold text-zinc-950';
        tab.content.classList.remove('hidden');
      } else {
        tab.btn.className = 'tab-btn rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-2 text-sm font-semibold text-zinc-300 hover:border-emerald-400/60';
        tab.content.classList.add('hidden');
      }
    });
  };

  $('#tab-btn-worlds').onclick = () => switchTab('worlds');
  $('#tab-btn-props').onclick = () => switchTab('props');
  $('#tab-btn-whitelist').onclick = () => switchTab('whitelist');
  $('#tab-btn-advancements').onclick = () => switchTab('advancements');
  $('#tab-btn-luckperms').onclick = () => switchTab('luckperms');

  // Tooltip Modal
  const tooltipModal = $('#modal-tooltip-info');
  const showTooltip = (title, desc, rec, impact) => {
    $('#tooltip-title').textContent = title;
    $('#tooltip-desc').textContent = desc || 'Sin descripción disponible.';
    $('#tooltip-rec').textContent = rec || 'Configuración predeterminada.';
    $('#tooltip-impact').textContent = impact || 'Sin impacto crítico reportado.';
    tooltipModal.showModal();
  };
  $('#close-tooltip-modal').onclick = () => tooltipModal.close();
  tooltipModal.onclick = (e) => { if (e.target === tooltipModal) tooltipModal.close(); };

  document.addEventListener('click', (e) => {
    const btn = e.target.closest('.tooltip-trigger');
    if (btn && btn.dataset.tooltip) {
      showTooltip(
        btn.dataset.title || 'Información de la opción',
        btn.dataset.tooltip,
        btn.dataset.rec || '',
        btn.dataset.impact || ''
      );
    }
  });

  // ==========================================
  // 1. GESTOR DE MUNDOS
  // ==========================================
  const loadWorlds = async () => {
    const grid = $('#worlds-grid');
    try {
      const worlds = await Panel.api('/api/worlds');
      if (!worlds.length) {
        grid.innerHTML = '<p class="text-sm text-zinc-500 col-span-full">No se encontraron mundos en server/.</p>';
        return;
      }

      grid.innerHTML = worlds.map((w) => `
        <article class="rounded-xl border ${w.is_active ? 'border-emerald-400/60 bg-emerald-950/15 ring-1 ring-emerald-400/30' : 'border-zinc-800 bg-zinc-900/60'} p-5 flex flex-col justify-between space-y-4">
          <div>
            <div class="flex items-start justify-between gap-2">
              <h3 class="font-bold text-base text-zinc-100 truncate">${esc(w.name)}</h3>
              ${w.is_active ? '<span class="rounded-full bg-emerald-400/20 px-2.5 py-0.5 text-xs font-bold text-emerald-300 ring-1 ring-emerald-400/40">Activo</span>' : ''}
            </div>
            <div class="mt-3 space-y-1.5 text-xs text-zinc-400">
              <p>📦 Tamaño en disco: <span class="font-medium text-zinc-200">${w.size_formatted}</span></p>
              <p>🕒 Modificado: <span class="font-medium text-zinc-300">${w.last_modified}</span></p>
              <p>🌌 Dimensiones: 
                ${w.has_nether ? '<span class="text-rose-300 font-medium">Nether</span> ' : ''}
                ${w.has_the_end ? '<span class="text-violet-300 font-medium">End</span>' : ''}
                ${!w.has_nether && !w.has_the_end ? '<span class="text-zinc-500">Solo Overworld</span>' : ''}
              </p>
            </div>
          </div>

          <div class="border-t border-zinc-800/80 pt-3 flex items-center justify-between gap-2">
            ${w.is_active 
              ? '<span class="text-xs text-emerald-400 font-semibold">Cargado en el servidor</span>' 
              : `<button data-switch-world="${esc(w.name)}" class="rounded-lg bg-emerald-400 px-3 py-1.5 text-xs font-bold text-zinc-950 hover:bg-emerald-300 transition">Activar este mundo</button>`
            }
            ${!w.is_active ? `<button data-delete-world="${esc(w.name)}" class="text-xs text-rose-400 hover:text-rose-300">Eliminar</button>` : ''}
          </div>
        </article>
      `).join('');
    } catch (e) {
      grid.innerHTML = `<p class="text-sm text-rose-400 col-span-full">Error al cargar mundos: ${esc(e.message)}</p>`;
    }
  };

  // Switch y Delete de mundos
  $('#worlds-grid').addEventListener('click', async (e) => {
    const switchBtn = e.target.closest('[data-switch-world]');
    if (switchBtn) {
      const worldName = switchBtn.dataset.switchWorld;
      switchBtn.disabled = true;
      try {
        const res = await Panel.api('/api/worlds/switch', {
          method: 'POST',
          body: { world_name: worldName },
        });
        Panel.toast(res.message, 'success');
        await loadWorlds();
      } catch (err) {
        Panel.toast(err.message, 'error');
      } finally {
        switchBtn.disabled = false;
      }
      return;
    }

    const deleteBtn = e.target.closest('[data-delete-world]');
    if (deleteBtn) {
      const worldName = deleteBtn.dataset.deleteWorld;
      if (!confirm(`¿Estás seguro de que querés eliminar permanentemente el mundo "${worldName}"? Esta acción no se puede deshacer.`)) return;
      try {
        const res = await Panel.api(`/api/worlds/${encodeURIComponent(worldName)}`, { method: 'DELETE' });
        Panel.toast(res.message, 'success');
        await loadWorlds();
      } catch (err) {
        Panel.toast(err.message, 'error');
      }
    }
  });

  // Modal Crear Mundo
  const createWorldModal = $('#modal-create-world');
  $('#open-create-world-modal').onclick = () => createWorldModal.showModal();
  $('#close-create-world-modal').onclick = () => createWorldModal.close();
  $('#cancel-create-world').onclick = () => createWorldModal.close();

  $('#create-world-form').onsubmit = async (e) => {
    e.preventDefault();
    const payload = {
      world_name: $('#new-world-name').value.trim(),
      seed: $('#new-world-seed').value.trim() || null,
      gamemode: $('#new-world-gamemode').value,
      difficulty: $('#new-world-difficulty').value,
      generate_structures: $('#new-world-structures').checked,
      hardcore: $('#new-world-hardcore').checked,
    };

    try {
      const res = await Panel.api('/api/worlds/create', { method: 'POST', body: payload });
      Panel.toast(res.message, 'success');
      createWorldModal.close();
      $('#create-world-form').reset();
      await loadWorlds();
    } catch (err) {
      Panel.toast(err.message, 'error');
    }
  };

  // ==========================================
  // 2. EDITOR DE SERVER.PROPERTIES
  // ==========================================
  let propertiesData = null;
  let currentCategory = 'Jugabilidad y Dificultad';
  const modifiedProperties = {};

  const renderMotdPreview = (rawMotd) => {
    const preview = $('#motd-preview');
    // Mini parseador cliente de códigos §
    const map = {
      '0':'#000000','1':'#0000AA','2':'#00AA00','3':'#00AAAA',
      '4':'#AA0000','5':'#AA00AA','6':'#FFAA00','7':'#AAAAAA',
      '8':'#555555','9':'#5555FF','a':'#55FF55','b':'#55FFFF',
      'c':'#FF5555','d':'#FF55FF','e':'#FFFF55','f':'#FFFFFF'
    };
    let html = '';
    let currentColor = '#FFFFFF';
    let bold = false;
    let italic = false;
    let i = 0;
    while (i < rawMotd.length) {
      if (rawMotd[i] === '§' && i + 1 < rawMotd.length) {
        const c = rawMotd[i + 1].toLowerCase();
        if (map[c]) currentColor = map[c];
        else if (c === 'l') bold = true;
        else if (c === 'o') italic = true;
        else if (c === 'r') { currentColor = '#FFFFFF'; bold = false; italic = false; }
        i += 2;
      } else {
        html += `<span style="color:${currentColor};${bold?'font-weight:bold;':''}${italic?'font-style:italic;':''}">${esc(rawMotd[i])}</span>`;
        i++;
      }
    }
    preview.innerHTML = html || '<span class="text-zinc-500">Sin mensaje del día</span>';
  };

  const renderProperties = () => {
    if (!propertiesData) return;
    const container = $('#props-container');
    const filtered = propertiesData.properties.filter((p) => p.category === currentCategory);

    container.innerHTML = filtered.map((p) => {
      let inputHtml = '';
      if (p.type === 'boolean') {
        const isChecked = (modifiedProperties[p.key] !== undefined ? modifiedProperties[p.key] : p.current_value).toLowerCase() === 'true';
        inputHtml = `
          <label class="relative inline-flex cursor-pointer items-center">
            <input type="checkbox" data-prop-key="${esc(p.key)}" ${isChecked ? 'checked' : ''} class="peer sr-only">
            <div class="h-6 w-11 rounded-full bg-zinc-800 peer-checked:bg-emerald-400 peer-focus:outline-none after:absolute after:top-[2px] after:left-[2px] after:h-5 after:w-5 after:rounded-full after:bg-zinc-100 after:transition-all after:content-[''] peer-checked:after:translate-x-full peer-checked:after:border-white"></div>
          </label>
        `;
      } else if (p.type === 'select' && p.options) {
        const currentVal = modifiedProperties[p.key] !== undefined ? modifiedProperties[p.key] : p.current_value;
        inputHtml = `
          <select data-prop-key="${esc(p.key)}" class="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-1.5 text-xs text-zinc-100">
            ${p.options.map((opt) => `<option value="${esc(opt.value)}" ${opt.value === currentVal ? 'selected' : ''}>${esc(opt.label)}</option>`).join('')}
          </select>
        `;
      } else if (p.type === 'number') {
        const currentVal = modifiedProperties[p.key] !== undefined ? modifiedProperties[p.key] : p.current_value;
        inputHtml = `
          <input type="number" data-prop-key="${esc(p.key)}" value="${esc(currentVal)}" ${p.min_value !== null ? `min="${p.min_value}"` : ''} ${p.max_value !== null ? `max="${p.max_value}"` : ''} class="w-24 rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-1.5 text-xs text-zinc-100">
        `;
      } else {
        const currentVal = modifiedProperties[p.key] !== undefined ? modifiedProperties[p.key] : p.current_value;
        inputHtml = `
          <input type="text" data-prop-key="${esc(p.key)}" value="${esc(currentVal)}" class="flex-1 min-w-[14rem] rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-1.5 text-xs text-zinc-100">
        `;
      }

      return `
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 transition hover:border-zinc-700">
          <div class="space-y-1">
            <div class="flex items-center gap-2">
              <span class="font-semibold text-sm text-zinc-200">${esc(p.label)}</span>
              <button type="button" class="tooltip-trigger inline-grid h-4 w-4 place-items-center rounded-full bg-emerald-500/20 text-[10px] font-bold text-emerald-300 ring-1 ring-emerald-400/40" data-title="${esc(p.label)}" data-tooltip="${esc(p.description)}" data-rec="${esc(p.recommended_value)}" data-impact="${esc(p.impact)}">?</button>
            </div>
            <p class="text-xs text-zinc-400">${esc(p.description)}</p>
            <p class="text-[11px] text-emerald-300/80">💡 Recomendado: <span class="font-medium text-emerald-200">${esc(p.recommended_value)}</span></p>
          </div>
          <div class="shrink-0">
            ${inputHtml}
          </div>
        </div>
      `;
    }).join('');
  };

  const loadProperties = async () => {
    try {
      propertiesData = await Panel.api('/api/server-properties');
      $('#motd-preview').innerHTML = propertiesData.motd_preview_html;

      // Renderizar nav de categorías
      const nav = $('#props-categories-nav');
      nav.innerHTML = propertiesData.categories.map((cat) => `
        <button data-cat="${esc(cat)}" class="cat-btn rounded-lg ${cat === currentCategory ? 'bg-zinc-800 text-emerald-300 ring-1 ring-emerald-400/30' : 'border border-zinc-800 text-zinc-400 hover:text-zinc-100'} px-3 py-1.5 text-xs font-semibold transition">${esc(cat)}</button>
      `).join('');

      renderProperties();
    } catch (e) {
      Panel.toast(e.message, 'error');
    }
  };

  $('#props-categories-nav').onclick = (e) => {
    const btn = e.target.closest('[data-cat]');
    if (btn) {
      currentCategory = btn.dataset.cat;
      $$('.cat-btn').forEach((b) => {
        b.className = b.dataset.cat === currentCategory 
          ? 'cat-btn rounded-lg bg-zinc-800 text-emerald-300 ring-1 ring-emerald-400/30 px-3 py-1.5 text-xs font-semibold transition' 
          : 'cat-btn rounded-lg border border-zinc-800 text-zinc-400 hover:text-zinc-100 px-3 py-1.5 text-xs font-semibold transition';
      });
      renderProperties();
    }
  };

  $('#props-container').onchange = (e) => {
    const input = e.target;
    if (!input.dataset.propKey) return;
    const key = input.dataset.propKey;
    const val = input.type === 'checkbox' ? (input.checked ? 'true' : 'false') : input.value;
    modifiedProperties[key] = val;

    if (key === 'motd') {
      renderMotdPreview(val);
    }
  };

  $('#save-properties-btn').onclick = async () => {
    if (!Object.keys(modifiedProperties).length) {
      Panel.toast('No hay cambios pendientes por guardar.', 'success');
      return;
    }

    const btn = $('#save-properties-btn');
    btn.disabled = true;
    try {
      const res = await Panel.api('/api/server-properties', {
        method: 'POST',
        body: { properties: modifiedProperties },
      });
      propertiesData = res;
      Object.keys(modifiedProperties).forEach((k) => delete modifiedProperties[k]);
      Panel.toast('server.properties guardado con éxito. Los cambios aplicarán al reiniciar el servidor.', 'success');
      renderProperties();
    } catch (e) {
      Panel.toast(e.message, 'error');
    } finally {
      btn.disabled = false;
    }
  };

  // ==========================================
  // 3. WHITELIST Y WAYPOINTS
  // ==========================================
  const loadWhitelist = async () => {
    try {
      const s = await Panel.api('/api/whitelist');
      $('#whitelist-toggle').checked = s.enabled;
      $('#whitelist-count').textContent = s.total;

      const list = $('#whitelist-players-list');
      if (!s.players.length) {
        list.innerHTML = '<p class="text-xs text-zinc-500 col-span-full">No hay jugadores en la lista blanca.</p>';
        return;
      }

      list.innerHTML = s.players.map((p) => `
        <div class="flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-950/40 p-2.5">
          <div class="flex items-center gap-2.5 min-w-0">
            <img src="${p.avatar_url}" alt="${esc(p.name)}" class="h-7 w-7 rounded bg-zinc-900 object-cover shrink-0">
            <span class="font-medium text-xs text-zinc-200 truncate">${esc(p.name)}</span>
          </div>
          <button data-remove-whitelist="${esc(p.name)}" class="text-xs text-rose-400 hover:text-rose-300">Quitar</button>
        </div>
      `).join('');
    } catch (e) {
      Panel.toast(e.message, 'error');
    }
  };

  $('#whitelist-toggle').onchange = async (e) => {
    try {
      const res = await Panel.api('/api/whitelist/toggle', {
        method: 'POST',
        body: { enabled: e.target.checked },
      });
      Panel.toast(res.message, 'success');
    } catch (err) {
      Panel.toast(err.message, 'error');
      loadWhitelist();
    }
  };

  $('#whitelist-add-form').onsubmit = async (e) => {
    e.preventDefault();
    const input = $('#whitelist-player-input');
    const username = input.value.trim();
    try {
      const res = await Panel.api('/api/whitelist/add', {
        method: 'POST',
        body: { username },
      });
      Panel.toast(res.message, 'success');
      input.value = '';
      loadWhitelist();
    } catch (err) {
      Panel.toast(err.message, 'error');
    }
  };

  $('#whitelist-players-list').onclick = async (e) => {
    const btn = e.target.closest('[data-remove-whitelist]');
    if (btn) {
      const username = btn.dataset.removeWhitelist;
      try {
        const res = await Panel.api('/api/whitelist/remove', {
          method: 'POST',
          body: { username },
        });
        Panel.toast(res.message, 'success');
        loadWhitelist();
      } catch (err) {
        Panel.toast(err.message, 'error');
      }
    }
  };

  // Waypoints
  const loadWaypoints = async () => {
    const list = $('#waypoints-list');
    try {
      const wps = await Panel.api('/api/waypoints');
      if (!wps.length) {
        list.innerHTML = '<p class="text-xs text-zinc-500">No hay marcadores guardados.</p>';
        return;
      }

      list.innerHTML = wps.map((wp) => `
        <div class="rounded-lg border border-zinc-800 bg-zinc-950/50 p-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <div class="flex items-center gap-2">
              <span class="font-bold text-sm text-emerald-300">${esc(wp.name)}</span>
              <span class="rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-[10px] text-zinc-400">${esc(wp.dimension.replace('minecraft:', ''))}</span>
            </div>
            <p class="mt-1 font-mono text-xs text-zinc-300">X: ${wp.x} · Y: ${wp.y} · Z: ${wp.z}</p>
            ${wp.description ? `<p class="mt-0.5 text-xs text-zinc-500">${esc(wp.description)}</p>` : ''}
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <button data-tp-all="${esc(wp.id)}" class="rounded bg-emerald-400 px-2.5 py-1 text-xs font-bold text-zinc-950 hover:bg-emerald-300">TP Todos (@a)</button>
            <button data-delete-wp="${esc(wp.id)}" class="text-xs text-zinc-400 hover:text-rose-400 p-1">×</button>
          </div>
        </div>
      `).join('');
    } catch (e) {
      Panel.toast(e.message, 'error');
    }
  };

  $('#waypoints-list').onclick = async (e) => {
    const tpBtn = e.target.closest('[data-tp-all]');
    if (tpBtn) {
      const id = tpBtn.dataset.tpAll;
      try {
        const res = await Panel.api(`/api/waypoints/${encodeURIComponent(id)}/teleport`, {
          method: 'POST',
          body: { target: '@a' },
        });
        Panel.toast(res.message, res.success ? 'success' : 'error');
      } catch (err) {
        Panel.toast(err.message, 'error');
      }
      return;
    }

    const delBtn = e.target.closest('[data-delete-wp]');
    if (delBtn) {
      const id = delBtn.dataset.deleteWp;
      try {
        await Panel.api(`/api/waypoints/${encodeURIComponent(id)}`, { method: 'DELETE' });
        Panel.toast('Marcador eliminado.', 'success');
        loadWaypoints();
      } catch (err) {
        Panel.toast(err.message, 'error');
      }
    }
  };

  // Modal Waypoint
  const wpModal = $('#modal-create-waypoint');
  $('#open-create-waypoint-btn').onclick = () => wpModal.showModal();
  $('#close-create-waypoint-modal').onclick = () => wpModal.close();
  $('#cancel-create-waypoint').onclick = () => wpModal.close();

  $('#create-waypoint-form').onsubmit = async (e) => {
    e.preventDefault();
    const payload = {
      name: $('#wp-name').value.trim(),
      x: parseFloat($('#wp-x').value),
      y: parseFloat($('#wp-y').value),
      z: parseFloat($('#wp-z').value),
      dimension: $('#wp-dim').value,
      description: $('#wp-desc').value.trim(),
    };
    try {
      await Panel.api('/api/waypoints', { method: 'POST', body: payload });
      Panel.toast('Marcador guardado con éxito.', 'success');
      wpModal.close();
      $('#create-waypoint-form').reset();
      loadWaypoints();
    } catch (err) {
      Panel.toast(err.message, 'error');
    }
  };

  // ==========================================
  // 4. LUCKPERMS
  // ==========================================
  $('#btn-luckperms-editor').onclick = async () => {
    const btn = $('#btn-luckperms-editor');
    const msg = $('#luckperms-status-msg');
    const link = $('#link-luckperms-editor');
    btn.disabled = true;
    msg.textContent = 'Enviando comando /lp editor al servidor...';

    try {
      const res = await Panel.api('/api/luckperms/editor', { method: 'POST' });
      if (res.success && res.editor_url) {
        link.href = res.editor_url;
        link.classList.remove('hidden');
        link.classList.add('inline-flex');
        msg.textContent = '¡Enlace obtenido! Abrí el editor con el botón de la derecha.';
        Panel.toast('Enlace de LuckPerms listo.', 'success');
      } else {
        msg.textContent = res.message;
        Panel.toast(res.message, 'error');
      }
    } catch (err) {
      msg.textContent = err.message;
      Panel.toast(err.message, 'error');
    } finally {
      btn.disabled = false;
    }
  };

  $('#btn-lp-assign-group').onclick = async () => {
    const user = $('#lp-user-target').value.trim();
    const group = $('#lp-group-target').value.trim();
    if (!user || !group) {
      Panel.toast('Ingresá el usuario y el grupo.', 'error');
      return;
    }
    try {
      const res = await Panel.api('/api/luckperms/command', {
        method: 'POST',
        body: { command: `/lp user ${user} parent set ${group}` },
      });
      Panel.toast(res.message, res.success ? 'success' : 'error');
    } catch (e) {
      Panel.toast(e.message, 'error');
    }
  };

  // ==========================================
  // 5. GESTOR DE LOGROS Y PROGRESOS
  // ==========================================
  let currentAdvancements = [];
  let currentAdvPlayer = '';
  let currentAdvWorld = '';

  const loadAdvancementWorlds = async () => {
    const select = $('#adv-world-select');
    if (!select) return;
    try {
      const worlds = await Panel.api('/api/advancements/worlds');
      if (!worlds || !worlds.length) {
        select.innerHTML = '<option value="">No hay mundos</option>';
        return;
      }

      select.innerHTML = worlds.map((w) => `
        <option value="${esc(w.name)}" ${w.is_active ? 'selected' : ''}>
          ${esc(w.name)} ${w.is_active ? '(Activo)' : '(Inactivo)'} [${w.players_with_advancements} jugadores]
        </option>
      `).join('');

      const activeWorld = worlds.find((w) => w.is_active) || worlds[0];
      currentAdvWorld = select.value || (activeWorld ? activeWorld.name : '');
      await loadAdvancementPlayers(currentAdvWorld);
    } catch (e) {
      Panel.toast(e.message, 'error');
    }
  };

  const loadAdvancementPlayers = async (worldName) => {
    const select = $('#adv-player-select');
    if (!select) return;
    const targetWorld = worldName !== undefined ? worldName : currentAdvWorld;
    try {
      const url = targetWorld ? `/api/advancements/players?world=${encodeURIComponent(targetWorld)}` : '/api/advancements/players';
      const players = await Panel.api(url);
      if (!players.length) {
        select.innerHTML = '<option value="">Sin jugadores registrados</option>';
        currentAdvPlayer = '';
        const container = $('#adv-list-container');
        if (container) container.innerHTML = '<p class="p-6 text-center text-xs text-zinc-500">No hay jugadores registrados en este mundo.</p>';
        return;
      }

      select.innerHTML = players.map((p) => `
        <option value="${esc(p.username)}">${esc(p.username)} (${p.advancements_count} logros)</option>
      `).join('');

      currentAdvPlayer = players[0].username;
      await loadPlayerAdvancements(currentAdvPlayer, targetWorld);
    } catch (e) {
      Panel.toast(e.message, 'error');
    }
  };

  const renderAdvancementsList = () => {
    const container = $('#adv-list-container');
    if (!container) return;
    const query = ($('#adv-search-input')?.value || '').toLowerCase().trim();

    const filtered = currentAdvancements.filter((a) => {
      if (!query) return true;
      return a.title.toLowerCase().includes(query) || a.id.toLowerCase().includes(query) || a.category.toLowerCase().includes(query);
    });

    if (!filtered.length) {
      container.innerHTML = `<p class="p-6 text-center text-xs text-zinc-500">${query ? 'No se encontraron logros que coincidan con la búsqueda.' : 'El jugador no tiene logros completados.'}</p>`;
      return;
    }

    container.innerHTML = filtered.map((a) => `
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 rounded-lg border border-zinc-800 bg-zinc-950/40 p-3">
        <div class="space-y-0.5">
          <div class="flex items-center gap-2">
            <span class="font-semibold text-xs text-zinc-200">${esc(a.title)}</span>
            <span class="rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-[10px] text-emerald-300">${esc(a.category)}</span>
          </div>
          <p class="font-mono text-[10px] text-zinc-500">${esc(a.id)}</p>
        </div>
        <div class="flex items-center gap-2 shrink-0">
          <button data-revoke-adv="${esc(a.id)}" class="rounded bg-rose-500/10 border border-rose-500/20 px-2.5 py-1 text-xs font-semibold text-rose-300 hover:bg-rose-500/20 transition">
            Quitar logro
          </button>
        </div>
      </div>
    `).join('');
  };

  const loadPlayerAdvancements = async (username, worldName) => {
    if (!username) return;
    currentAdvPlayer = username;
    const targetWorld = worldName !== undefined ? worldName : currentAdvWorld;
    const container = $('#adv-list-container');
    if (!container) return;
    container.innerHTML = '<p class="p-6 text-center text-xs text-zinc-500">Cargando logros...</p>';

    try {
      const url = targetWorld ? `/api/advancements/player/${encodeURIComponent(username)}?world=${encodeURIComponent(targetWorld)}` : `/api/advancements/player/${encodeURIComponent(username)}`;
      const data = await Panel.api(url);
      $('#adv-player-avatar').src = data.avatar_url;
      $('#adv-player-name').textContent = data.username;
      $('#adv-total-count').textContent = data.total_advancements;
      $('#adv-recipes-count').textContent = data.total_recipes;

      currentAdvancements = data.advancements;
      renderAdvancementsList();
    } catch (e) {
      container.innerHTML = `<p class="p-6 text-center text-xs text-rose-400">Error al cargar logros: ${esc(e.message)}</p>`;
    }
  };

  $('#adv-world-select')?.addEventListener('change', async (e) => {
    currentAdvWorld = e.target.value;
    await loadAdvancementPlayers(currentAdvWorld);
  });

  $('#adv-player-select')?.addEventListener('change', (e) => {
    loadPlayerAdvancements(e.target.value, currentAdvWorld);
  });

  $('#adv-search-input')?.addEventListener('input', () => {
    renderAdvancementsList();
  });

  // Reiniciar TODOS los logros
  $('#btn-adv-revoke-all')?.addEventListener('click', async () => {
    if (!currentAdvPlayer) return;
    const worldMsg = currentAdvWorld ? ` en el mundo "${currentAdvWorld}"` : '';
    if (!confirm(`¿Estás seguro de que querés reiniciar TODOS los logros de "${currentAdvPlayer}"${worldMsg}? Se borrará todo el árbol de Vanilla y mods.`)) return;

    try {
      const res = await Panel.api('/api/advancements/revoke', {
        method: 'POST',
        body: { username: currentAdvPlayer, advancement_id: 'everything', world_name: currentAdvWorld },
      });
      Panel.toast(res.message, 'success');
      await loadPlayerAdvancements(currentAdvPlayer, currentAdvWorld);
      await loadAdvancementPlayers(currentAdvWorld);
    } catch (err) {
      Panel.toast(err.message, 'error');
    }
  });

  // Botones con comandos prellenados
  document.addEventListener('click', async (e) => {
    const quickBtn = e.target.closest('[data-adv-quick]');
    if (!quickBtn || !currentAdvPlayer) return;

    const actionData = quickBtn.dataset.advQuick;
    const colonIdx = actionData.indexOf(':');
    const action = colonIdx > -1 ? actionData.slice(0, colonIdx) : actionData;
    const targetId = colonIdx > -1 ? actionData.slice(colonIdx + 1) : '';

    quickBtn.disabled = true;
    try {
      const endpoint = action === 'grant' ? '/api/advancements/grant' : '/api/advancements/revoke';
      const res = await Panel.api(endpoint, {
        method: 'POST',
        body: { username: currentAdvPlayer, advancement_id: targetId, world_name: currentAdvWorld },
      });
      Panel.toast(res.message, 'success');
      await loadPlayerAdvancements(currentAdvPlayer, currentAdvWorld);
    } catch (err) {
      Panel.toast(err.message, 'error');
    } finally {
      quickBtn.disabled = false;
    }
  });

  // Botón para revocar rama personalizada
  $('#btn-adv-quick-revoke-root')?.addEventListener('click', async (e) => {
    const btn = e.target;
    if (!currentAdvPlayer) {
      Panel.toast('Seleccioná un jugador primero.', 'warning');
      return;
    }
    const inp = $('#adv-quick-root-input');
    const targetId = (inp?.value || '').trim();
    if (!targetId) {
      Panel.toast('Ingresá una raíz o ID de avance.', 'warning');
      return;
    }

    btn.disabled = true;
    try {
      const res = await Panel.api('/api/advancements/revoke', {
        method: 'POST',
        body: { username: currentAdvPlayer, advancement_id: targetId, world_name: currentAdvWorld },
      });
      Panel.toast(res.message, 'success');
      await loadPlayerAdvancements(currentAdvPlayer, currentAdvWorld);
    } catch (err) {
      Panel.toast(err.message, 'error');
    } finally {
      btn.disabled = false;
    }
  });

  // Quitar logro individual de la lista
  $('#adv-list-container')?.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-revoke-adv]');
    if (!btn || !currentAdvPlayer) return;
    const advId = btn.dataset.revokeAdv;

    if (!confirm(`¿Quitar el logro "${advId}" a ${currentAdvPlayer}?`)) return;

    btn.disabled = true;
    try {
      const res = await Panel.api('/api/advancements/revoke', {
        method: 'POST',
        body: { username: currentAdvPlayer, advancement_id: advId, world_name: currentAdvWorld },
      });
      Panel.toast(res.message, 'success');
      await loadPlayerAdvancements(currentAdvPlayer, currentAdvWorld);
    } catch (err) {
      Panel.toast(err.message, 'error');
    } finally {
      btn.disabled = false;
    }
  });

  // Acciones manuales por ID
  $('#btn-adv-custom-revoke')?.addEventListener('click', async () => {
    const id = $('#adv-custom-id').value.trim();
    if (!id || !currentAdvPlayer) {
      Panel.toast('Ingresá el ID del logro a quitar.', 'error');
      return;
    }
    try {
      const res = await Panel.api('/api/advancements/revoke', {
        method: 'POST',
        body: { username: currentAdvPlayer, advancement_id: id, world_name: currentAdvWorld },
      });
      Panel.toast(res.message, 'success');
      $('#adv-custom-id').value = '';
      await loadPlayerAdvancements(currentAdvPlayer, currentAdvWorld);
    } catch (e) {
      Panel.toast(e.message, 'error');
    }
  });

  $('#btn-adv-custom-grant')?.addEventListener('click', async () => {
    const id = $('#adv-custom-id').value.trim();
    if (!id || !currentAdvPlayer) {
      Panel.toast('Ingresá el ID del logro a otorgar.', 'error');
      return;
    }
    try {
      const res = await Panel.api('/api/advancements/grant', {
        method: 'POST',
        body: { username: currentAdvPlayer, advancement_id: id, world_name: currentAdvWorld },
      });
      Panel.toast(res.message, 'success');
      $('#adv-custom-id').value = '';
      await loadPlayerAdvancements(currentAdvPlayer, currentAdvWorld);
    } catch (e) {
      Panel.toast(e.message, 'error');
    }
  });

  // Carga inicial
  loadWorlds();
  loadProperties();
  loadWhitelist();
  loadWaypoints();
  loadAdvancementWorlds();
});
