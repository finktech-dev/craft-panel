document.addEventListener('DOMContentLoaded', () => {
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => document.querySelectorAll(s);
  const esc = Panel.escapeHtml;

  // Main tab handling
  // Ranks moved to Ajustes; keep old links to the removed tab working.
  if (window.location.hash === '#luckperms') {
    window.location.replace('/administration#ranks');
    return;
  }
  const tabs = {
    worlds: { btn: $('#tab-btn-worlds'), content: $('#tab-content-worlds') },
    props: { btn: $('#tab-btn-props'), content: $('#tab-content-props') },
    whitelist: { btn: $('#tab-btn-whitelist'), content: $('#tab-content-whitelist') },
    advancements: { btn: $('#tab-btn-advancements'), content: $('#tab-content-advancements') },
  };

  const switchTab = (activeKey) => {
    Object.entries(tabs).forEach(([key, tab]) => {
      if (key === activeKey) {
        tab.btn.className = 'tab-btn -mb-px border-b-2 border-emerald-400 pb-3 font-semibold text-zinc-50';
        tab.btn.setAttribute('aria-current', 'true');
        tab.content.classList.remove('hidden');
      } else {
        tab.btn.className = 'tab-btn -mb-px border-b-2 border-transparent pb-3 font-semibold text-zinc-400 hover:text-zinc-200';
        tab.btn.removeAttribute('aria-current');
        tab.content.classList.add('hidden');
      }
    });
  };

  // The open tab is kept in the hash so a reload lands in the same place.
  const rememberTab = (key) => {
    const hash = key === 'worlds' ? window.location.pathname : `#${key}`;
    if (window.location.hash === hash) return;
    try { history.replaceState(null, '', hash); } catch { /* the tab still switches */ }
  };
  Object.keys(tabs).forEach((key) => {
    tabs[key].btn.onclick = () => {
      switchTab(key);
      if (key === 'props') showPropsOverview(false);
      rememberTab(key);
    };
  });
  // Deep links such as /worlds#whitelist (the "Jugadores" entry) or /worlds#props/rendimiento open directly.
  const tabFromHash = () => {
    const [key, sub] = window.location.hash.slice(1).split('/');
    if (!key || !Object.hasOwn(tabs, key)) return;
    switchTab(key);
    if (key === 'props') {
      const category = categoryFromSlug(sub);
      if (category) openCategory(category, false);
      else showPropsOverview(false);
    }
  };

  // Tooltip Modal
  const tooltipModal = $('#modal-tooltip-info');
  const showTooltip = (title, desc, rec, impact) => {
    $('#tooltip-title').textContent = title;
    $('#tooltip-desc').textContent = desc || 'No tenemos una explicación para este ajuste.';
    $('#tooltip-rec').textContent = rec || 'Dejalo como viene.';
    $('#tooltip-impact').textContent = impact || 'Nada importante.';
    tooltipModal.showModal();
  };
  $('#close-tooltip-modal').onclick = () => tooltipModal.close();
  tooltipModal.onclick = (e) => { if (e.target === tooltipModal) tooltipModal.close(); };

  document.addEventListener('click', (e) => {
    const btn = e.target.closest('.tooltip-trigger');
    if (btn && btn.dataset.tooltip) {
      showTooltip(
        btn.dataset.title || 'Sobre este ajuste',
        btn.dataset.tooltip,
        btn.dataset.rec || '',
        btn.dataset.impact || ''
      );
    }
  });

  // ==========================================
  // 1. WORLD MANAGER
  // ==========================================
  const loadWorlds = async () => {
    const grid = $('#worlds-grid');
    try {
      const worlds = await Panel.api('/api/worlds');
      if (!worlds.length) {
        grid.innerHTML = '<p class="py-6 text-zinc-500">Todavía no hay mundos. Creá uno o prendé el servidor para que arme el primero.</p>';
        return;
      }

      const dimensionsText = (w) => {
        if (w.has_nether && w.has_the_end) return 'con Nether y End';
        if (w.has_nether) return 'con Nether';
        if (w.has_the_end) return 'con End';
        return 'solo el mundo normal';
      };

      grid.innerHTML = worlds.map((w) => `
        <article class="flex flex-col gap-3 border-b border-zinc-800 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div class="min-w-0">
            <div class="flex flex-wrap items-baseline gap-x-2">
              <h3 class="truncate font-semibold text-zinc-50">${esc(w.name)}</h3>
              ${w.is_active ? '<span class="text-sm text-zinc-400">· en uso</span>' : ''}
            </div>
            <p class="mt-0.5 text-sm text-zinc-500">Ocupa ${esc(w.size_formatted)} · último cambio ${esc(w.last_modified)} · ${dimensionsText(w)}</p>
          </div>
          ${w.is_active
            ? '<p class="shrink-0 text-sm text-zinc-500">Se carga al prender el servidor</p>'
            : `<div class="flex shrink-0 items-center gap-2">
                <button type="button" data-switch-world="${esc(w.name)}" class="v2-button btn-quiet">Usar este mundo</button>
                <button type="button" data-delete-world="${esc(w.name)}" class="rounded-lg px-2 py-1.5 text-sm text-zinc-500 hover:bg-zinc-800 hover:text-[#f3a79b]">Borrar</button>
              </div>`
          }
        </article>
      `).join('');
    } catch (e) {
      grid.innerHTML = `<p class="py-6 text-[#f3a79b]">No pudimos leer los mundos. ${esc(e.message)}</p>`;
    }
  };

  // World switch and delete
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
      if (!confirm(`¿Borrar el mundo "${worldName}"? Se borra para siempre y no se puede deshacer.`)) return;
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
  // 2. SERVER.PROPERTIES EDITOR
  // ==========================================
  let propertiesData = null;
  let currentCategory = 'Jugabilidad y Dificultad';
  const modifiedProperties = {};

  const renderMotdPreview = (rawMotd) => {
    const preview = $('#motd-preview');
    // Small client-side parser for § codes
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
    preview.innerHTML = html || '<span class="text-zinc-500">Sin mensaje todavía</span>';
  };

  const renderProperties = () => {
    if (!propertiesData) return;
    const container = $('#props-container');
    const filtered = propertiesData.properties.filter((p) => p.category === currentCategory);

    if (!filtered.length) {
      container.innerHTML = '<p class="py-6 text-zinc-500">No hay ajustes en esta parte.</p>';
      return;
    }

    const fieldClass = 'min-h-11 rounded-lg border border-zinc-800 bg-zinc-900 px-4 text-zinc-100 placeholder-zinc-500 outline-none focus:border-emerald-400';

    container.innerHTML = filtered.map((p) => {
      const currentVal = modifiedProperties[p.key] !== undefined ? modifiedProperties[p.key] : p.current_value;
      const fieldLabel = `aria-label="${esc(p.label)}"`;
      let inputHtml = '';
      if (p.type === 'boolean') {
        const isChecked = String(currentVal).toLowerCase() === 'true';
        inputHtml = `
          <label class="relative inline-flex cursor-pointer select-none items-center">
            <input type="checkbox" data-prop-key="${esc(p.key)}" ${isChecked ? 'checked' : ''} ${fieldLabel} class="peer sr-only">
            <div class="h-6 w-11 rounded-full bg-zinc-700 after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:bg-zinc-200 after:transition-all after:content-[''] peer-checked:bg-emerald-400 peer-checked:after:translate-x-full peer-checked:after:bg-[#16250c] peer-focus-visible:ring-2 peer-focus-visible:ring-emerald-200"></div>
          </label>
        `;
      } else if (p.type === 'select' && p.options) {
        inputHtml = `
          <select data-prop-key="${esc(p.key)}" ${fieldLabel} class="${fieldClass} w-full sm:w-48">
            ${p.options.map((opt) => `<option value="${esc(opt.value)}" ${opt.value === currentVal ? 'selected' : ''}>${esc(opt.label)}</option>`).join('')}
          </select>
        `;
      } else if (p.type === 'number') {
        inputHtml = `
          <input type="number" data-prop-key="${esc(p.key)}" value="${esc(currentVal)}" ${p.min_value !== null ? `min="${p.min_value}"` : ''} ${p.max_value !== null ? `max="${p.max_value}"` : ''} ${fieldLabel} class="${fieldClass} w-28">
        `;
      } else {
        inputHtml = `
          <input type="text" data-prop-key="${esc(p.key)}" value="${esc(currentVal)}" ${fieldLabel} class="${fieldClass} w-full sm:w-72">
        `;
      }

      return `
        <div class="flex flex-col gap-3 border-b border-zinc-800 py-4 sm:flex-row sm:items-center sm:justify-between sm:gap-6">
          <div class="min-w-0">
            <h3 class="font-semibold text-zinc-50">${esc(p.label)}</h3>
            <p class="mt-0.5 text-sm leading-relaxed text-zinc-400">${esc(p.description)}</p>
            <p class="mt-1 text-sm text-zinc-500">
              Recomendado: ${esc(p.recommended_value)} ·
              <button type="button" class="tooltip-trigger link" data-title="${esc(p.label)}" data-tooltip="${esc(p.description)}" data-rec="${esc(p.recommended_value)}" data-impact="${esc(p.impact)}">Qué cambia</button>
              <span class="ml-1 font-mono text-xs text-zinc-600">${esc(p.key)}</span>
            </p>
          </div>
          <div class="shrink-0">
            ${inputHtml}
          </div>
        </div>
      `;
    }).join('');
  };

  // Plain names for the server.properties groups the API returns, with a short slug for the URL.
  const CATEGORY_INFO = {
    'Jugabilidad y Dificultad': { slug: 'jugabilidad', title: 'Cómo se juega', lead: 'La dificultad, el modo de juego, las criaturas y otras reglas del mundo.' },
    'Rendimiento y Chunks': { slug: 'rendimiento', title: 'Velocidad del servidor', lead: 'Hasta dónde se ve el mundo y cuánto trabaja la computadora.' },
    'Seguridad y Red': { slug: 'seguridad', title: 'Entrada y conexión', lead: 'Cuántos pueden jugar a la vez y cómo se conectan.' },
    'Mensaje y Apariencia': { slug: 'apariencia', title: 'Cómo se ve en la lista', lead: 'El mensaje que aparece en la lista de servidores de Minecraft.' },
    'Otras opciones avanzadas': { slug: 'avanzadas', title: 'Opciones avanzadas', lead: 'Ajustes poco comunes. Si no sabés qué hacen, dejalos como vienen.' },
  };
  const infoFor = (category) => CATEGORY_INFO[category] || {
    slug: String(category).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''),
    title: category,
    lead: '',
  };
  const knownCategories = () => (propertiesData ? propertiesData.categories : Object.keys(CATEGORY_INFO));
  const categoryFromSlug = (slug) => (slug ? knownCategories().find((cat) => infoFor(cat).slug === slug) || null : null);
  // True when the open group was reached from the list on this page, so "Volver" can go back one step.
  let categoryOpenedHere = false;

  const showPropsOverview = (focus = true) => {
    categoryOpenedHere = false;
    $('#props-screen').hidden = true;
    $('#props-overview').hidden = false;
    if (focus) $('#props-title').focus({ preventScroll: true });
  };

  const openCategory = (category, push) => {
    currentCategory = category;
    const info = infoFor(category);
    $('#props-category-title').textContent = info.title;
    $('#props-category-lead').textContent = info.lead;
    $('#props-category-lead').hidden = !info.lead;
    $('#motd-preview-box').hidden = category !== 'Mensaje y Apariencia';
    $('#props-overview').hidden = true;
    $('#props-screen').hidden = false;
    if (push) {
      categoryOpenedHere = true;
      try { history.pushState(null, '', `#props/${info.slug}`); } catch { /* the screen still opens */ }
    }
    renderProperties();
    window.scrollTo(0, 0);
    $('#props-category-title').focus({ preventScroll: true });
  };

  const renderCategoryList = () => {
    const countOf = (cat) => propertiesData.properties.filter((p) => p.category === cat).length;
    // Empty groups (for example no extra settings in the file) are left out of the list.
    $('#props-categories-nav').innerHTML = propertiesData.categories.filter((cat) => countOf(cat) > 0).map((cat) => {
      const info = infoFor(cat);
      const count = countOf(cat);
      const detail = [info.lead, `${count} ${count === 1 ? 'ajuste' : 'ajustes'}`].filter(Boolean).join(' · ');
      return `<button type="button" data-cat="${esc(cat)}" class="settings-row"><span><strong>${esc(info.title)}</strong><small>${esc(detail)}</small></span></button>`;
    }).join('');
  };

  const loadProperties = async () => {
    try {
      propertiesData = await Panel.api('/api/server-properties');
      $('#motd-preview').innerHTML = propertiesData.motd_preview_html;
      renderCategoryList();
      renderProperties();
    } catch (e) {
      $('#props-categories-nav').innerHTML = `<p class="px-5 py-6 text-[#f3a79b]">No pudimos leer los ajustes. ${esc(e.message)}</p>`;
      $('#props-container').innerHTML = `<p class="py-6 text-[#f3a79b]">No pudimos leer los ajustes. ${esc(e.message)}</p>`;
      Panel.toast(e.message, 'error');
    }
  };

  $('#props-categories-nav').onclick = (e) => {
    const btn = e.target.closest('[data-cat]');
    if (btn) openCategory(btn.dataset.cat, true);
  };

  $('[data-props-back]').onclick = (e) => {
    e.preventDefault();
    if (categoryOpenedHere) {
      history.back();
      return;
    }
    try { history.replaceState(null, '', '#props'); } catch { /* ignore */ }
    showPropsOverview();
  };

  window.addEventListener('hashchange', tabFromHash);
  tabFromHash();

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
      Panel.toast('No cambiaste nada todavía.', 'success');
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
      Panel.toast('Ajustes guardados. Se aplican la próxima vez que reinicies el servidor.', 'success');
      renderProperties();
    } catch (e) {
      Panel.toast(e.message, 'error');
    } finally {
      btn.disabled = false;
    }
  };

  // ==========================================
  // 3. WHITELIST AND WAYPOINTS
  // ==========================================
  const setWhitelistLabel = (enabled) => {
    const label = $('#whitelist-toggle-label');
    if (label) label.textContent = enabled ? 'Activada' : 'Apagada';
  };

  const loadWhitelist = async () => {
    const list = $('#whitelist-players-list');
    try {
      const s = await Panel.api('/api/whitelist');
      $('#whitelist-toggle').checked = s.enabled;
      setWhitelistLabel(s.enabled);
      $('#whitelist-count').textContent = s.total;

      if (!s.players.length) {
        list.innerHTML = '<p class="py-6 text-zinc-500">Todavía no agregaste a nadie.</p>';
        return;
      }

      list.innerHTML = s.players.map((p) => `
        <div class="flex items-center justify-between gap-4 border-b border-zinc-800 py-3">
          <div class="flex min-w-0 items-center gap-3">
            <img src="${esc(p.avatar_url)}" alt="" class="h-8 w-8 shrink-0 rounded bg-zinc-900 object-cover">
            <span class="truncate font-semibold text-zinc-50">${esc(p.name)}</span>
          </div>
          <button type="button" data-remove-whitelist="${esc(p.name)}" class="shrink-0 rounded-lg px-2 py-1.5 text-sm text-zinc-500 hover:bg-zinc-800 hover:text-[#f3a79b]" aria-label="Quitar a ${esc(p.name)} de la lista">Quitar</button>
        </div>
      `).join('');
    } catch (e) {
      list.innerHTML = `<p class="py-6 text-[#f3a79b]">No pudimos leer la lista. ${esc(e.message)}</p>`;
      Panel.toast(e.message, 'error');
    }
  };

  $('#whitelist-toggle').onchange = async (e) => {
    try {
      const res = await Panel.api('/api/whitelist/toggle', {
        method: 'POST',
        body: { enabled: e.target.checked },
      });
      setWhitelistLabel(e.target.checked);
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
        list.innerHTML = '<p class="py-6 text-zinc-500">Todavía no guardaste ningún lugar.</p>';
        return;
      }

      const DIMENSIONS = {
        'minecraft:overworld': 'Mundo normal',
        'minecraft:the_nether': 'Nether',
        'minecraft:the_end': 'End',
      };

      list.innerHTML = wps.map((wp) => `
        <div class="flex flex-col gap-3 border-b border-zinc-800 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div class="min-w-0">
            <div class="flex flex-wrap items-baseline gap-x-2">
              <h3 class="truncate font-semibold text-zinc-50">${esc(wp.name)}</h3>
              <span class="text-sm text-zinc-500">${esc(DIMENSIONS[wp.dimension] || String(wp.dimension).replace('minecraft:', ''))}</span>
            </div>
            <p class="mt-0.5 font-mono text-sm text-zinc-400">X ${esc(wp.x)} · Y ${esc(wp.y)} · Z ${esc(wp.z)}</p>
            ${wp.description ? `<p class="mt-0.5 text-sm text-zinc-500">${esc(wp.description)}</p>` : ''}
          </div>
          <div class="flex shrink-0 items-center gap-2">
            <button type="button" data-tp-all="${esc(wp.id)}" class="v2-button btn-quiet">Llevar a todos</button>
            <button type="button" data-delete-wp="${esc(wp.id)}" class="rounded-lg px-2 py-1.5 text-sm text-zinc-500 hover:bg-zinc-800 hover:text-[#f3a79b]" aria-label="Borrar ${esc(wp.name)}">Borrar</button>
          </div>
        </div>
      `).join('');
    } catch (e) {
      list.innerHTML = `<p class="py-6 text-[#f3a79b]">No pudimos leer los lugares. ${esc(e.message)}</p>`;
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
        Panel.toast('Lugar borrado.', 'success');
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
      Panel.toast('Lugar guardado.', 'success');
      wpModal.close();
      $('#create-waypoint-form').reset();
      loadWaypoints();
    } catch (err) {
      Panel.toast(err.message, 'error');
    }
  };

  // ==========================================
  // 5. ADVANCEMENTS AND PROGRESS MANAGER
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
          ${esc(w.name)}${w.is_active ? ' (en uso)' : ''} · ${esc(w.players_with_advancements)} jugadores
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
        select.innerHTML = '<option value="">Nadie jugó todavía</option>';
        currentAdvPlayer = '';
        const container = $('#adv-list-container');
        if (container) container.innerHTML = '<p class="py-6 text-zinc-500">Nadie jugó en este mundo todavía.</p>';
        return;
      }

      select.innerHTML = players.map((p) => `
        <option value="${esc(p.username)}">${esc(p.username)} · ${esc(p.advancements_count)} logros</option>
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
      container.innerHTML = `<p class="py-6 text-zinc-500">${query ? 'Ningún logro coincide con lo que buscaste.' : 'Todavía no consiguió ningún logro.'}</p>`;
      return;
    }

    container.innerHTML = filtered.map((a) => `
      <div class="flex items-center justify-between gap-4 border-b border-zinc-800 py-3">
        <div class="min-w-0">
          <div class="flex flex-wrap items-baseline gap-x-2">
            <h3 class="font-semibold text-zinc-50">${esc(a.title)}</h3>
            <span class="text-sm text-zinc-500">${esc(a.category)}</span>
          </div>
          <p class="mt-0.5 truncate font-mono text-xs text-zinc-600">${esc(a.id)}</p>
        </div>
        <button type="button" data-revoke-adv="${esc(a.id)}" class="shrink-0 rounded-lg px-2 py-1.5 text-sm text-zinc-500 hover:bg-zinc-800 hover:text-[#f3a79b]" aria-label="Quitar ${esc(a.title)}">Quitar</button>
      </div>
    `).join('');
  };

  const loadPlayerAdvancements = async (username, worldName) => {
    if (!username) return;
    currentAdvPlayer = username;
    const targetWorld = worldName !== undefined ? worldName : currentAdvWorld;
    const container = $('#adv-list-container');
    if (!container) return;
    container.innerHTML = '<p class="py-6 text-zinc-500">Cargando logros…</p>';

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
      container.innerHTML = `<p class="py-6 text-[#f3a79b]">No pudimos leer los logros. ${esc(e.message)}</p>`;
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

  // Reset ALL advancements
  $('#btn-adv-revoke-all')?.addEventListener('click', async () => {
    if (!currentAdvPlayer) return;
    const worldMsg = currentAdvWorld ? ` en el mundo "${currentAdvWorld}"` : '';
    if (!confirm(`¿Borrar todos los logros de ${currentAdvPlayer}${worldMsg}? Pierde todo su progreso, también el de los mods, y no se puede deshacer.`)) return;

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

  // Buttons with prefilled commands
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

  // Button to revoke a custom branch
  $('#btn-adv-quick-revoke-root')?.addEventListener('click', async (e) => {
    const btn = e.target;
    if (!currentAdvPlayer) {
      Panel.toast('Elegí un jugador primero.', 'warning');
      return;
    }
    const inp = $('#adv-quick-root-input');
    const targetId = (inp?.value || '').trim();
    if (!targetId) {
      Panel.toast('Escribí qué rama querés quitar.', 'warning');
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

  // Remove a single advancement from the list
  $('#adv-list-container')?.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-revoke-adv]');
    if (!btn || !currentAdvPlayer) return;
    const advId = btn.dataset.revokeAdv;

    if (!confirm(`¿Quitarle el logro "${advId}" a ${currentAdvPlayer}? Lo puede volver a conseguir jugando.`)) return;

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

  // Manual actions by ID
  $('#btn-adv-custom-revoke')?.addEventListener('click', async () => {
    const id = $('#adv-custom-id').value.trim();
    if (!id || !currentAdvPlayer) {
      Panel.toast('Elegí un jugador y escribí el logro que querés quitar.', 'error');
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
      Panel.toast('Elegí un jugador y escribí el logro que querés dar.', 'error');
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
