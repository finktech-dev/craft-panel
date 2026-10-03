/**
 * LuckPerms Visual Ranks Management
 * web_panel/static/js/admin-ranks.js
 *
 * Self-contained visual management for LuckPerms ranks, roles, permissions,
 * and live player assignment in the Minecraft Web Panel.
 */

document.addEventListener('DOMContentLoaded', () => {
  // 1. Helpers
  const $ = s => document.querySelector(s);
  const esc = (s) => (window.Panel && window.Panel.escapeHtml) ? window.Panel.escapeHtml(s) : String(s);

  // If ranks section is not present on this page, exit early
  if (!$('#ranks') && !$('#lp-ranks-grid')) {
    return;
  }

  // 2. The rank definitions are supplied by the authenticated local configuration API.
  // Historical values were migrated to a local LuckPerms preset file.
  let PRIMARY_RANKS = [];
  let SECONDARY_ROLES = [];
  const MC_COLORS = {
    '0': '#000000', '1': '#0000aa', '2': '#00aa00', '3': '#00aaaa',
    '4': '#aa0000', '5': '#aa00aa', '6': '#ffaa00', '7': '#aaaaaa',
    '8': '#555555', '9': '#5555ff', 'a': '#55ff55', 'b': '#55ffff',
    'c': '#ff5555', 'd': '#ff55ff', 'e': '#ffff55', 'f': '#ffffff'
  };

  const PERM_DEFINITIONS = {
    fly: ['essentialcommands.fly', 'minecraft.command.fly'],
    god: ['essentialcommands.god'],
    heal: ['essentialcommands.heal', 'essentialcommands.feed'],
    speed: ['essentialcommands.speed'],
    tp: ['minecraft.command.tp', 'minecraft.command.teleport'],
    tpa: ['essentialcommands.tpa', 'essentialcommands.tpaccept', 'essentialcommands.tpdeny'],
    home: ['essentialcommands.home', 'essentialcommands.sethome', 'essentialcommands.delhome'],
    back: ['essentialcommands.back'],
    spawn: ['essentialcommands.spawn'],
    gamemode: ['minecraft.command.gamemode'],
    time_weather: ['minecraft.command.time', 'minecraft.command.weather'],
    workbench: ['essentialcommands.workbench'],
    enderchest: ['essentialcommands.enderchest'],
    anvil: ['essentialcommands.anvil'],
    pointblank: ['pointblank.*'],
    voice_groups: ['voicechat.groups'],
    voice_speak: ['voicechat.speak'],
    all: ['*']
  };

  // 3. Formatting & Animation
  function renderMinecraftText(text) {
    if (!text) return '';
    let html = '';
    let curColor = '#ffffff';
    let bold = false, italic = false, strikethrough = false, underline = false, obfuscated = false;
    let i = 0;
    while (i < text.length) {
      const c = text[i];
      const next = text[i + 1];
      const isMarker = (c === '&' || c === '§');

      // Formato Hexadecimal 1.16+: &#RRGGBB o §#RRGGBB
      if (isMarker && next === '#' && i + 7 < text.length) {
        const hexCandidate = text.slice(i + 2, i + 8);
        if (/^[0-9a-fA-F]{6}$/.test(hexCandidate)) {
          curColor = '#' + hexCandidate;
          bold = false; italic = false; strikethrough = false; underline = false; obfuscated = false;
          i += 8; continue;
        }
      }
      // Formato Hexadecimal Spigot/Bungee: &x&r&r&g&g&b&b o §x§r§r§g§g§b§b
      if (isMarker && next && next.toLowerCase() === 'x' && i + 13 < text.length) {
        const m = text.slice(i, i + 14).match(/^[&§]x[&§]([0-9a-fA-F])[&§]([0-9a-fA-F])[&§]([0-9a-fA-F])[&§]([0-9a-fA-F])[&§]([0-9a-fA-F])$/i);
        if (m) {
          curColor = '#' + m.slice(1).join('');
          bold = false; italic = false; strikethrough = false; underline = false; obfuscated = false;
          i += 14; continue;
        }
      }
      // Formato estándar de 2 caracteres: &0-f, &k-o, &r
      if (isMarker && next) {
        const code = next.toLowerCase();
        if (MC_COLORS[code] !== undefined) {
          curColor = MC_COLORS[code];
          bold = false; italic = false; strikethrough = false; underline = false; obfuscated = false;
          i += 2; continue;
        } else if (code === 'k') {
          obfuscated = true; i += 2; continue;
        } else if (code === 'l') {
          bold = true; i += 2; continue;
        } else if (code === 'm') {
          strikethrough = true; i += 2; continue;
        } else if (code === 'n') {
          underline = true; i += 2; continue;
        } else if (code === 'o') {
          italic = true; i += 2; continue;
        } else if (code === 'r') {
          curColor = '#ffffff';
          bold = false; italic = false; strikethrough = false; underline = false; obfuscated = false;
          i += 2; continue;
        }
      }
      let nextAmp = -1;
      for (let k = i; k < text.length; k++) {
        if (text[k] === '&' || text[k] === '§') {
          nextAmp = k;
          break;
        }
      }
      let chunk = nextAmp === -1 ? text.slice(i) : text.slice(i, nextAmp);
      if (!chunk) { chunk = text[i]; i++; } else { i += chunk.length; }

      let decs = [];
      if (underline) decs.push('underline');
      if (strikethrough) decs.push('line-through');

      let style = `color:${curColor};`;
      if (bold) style += 'font-weight:bold;';
      if (italic) style += 'font-style:italic;';
      if (decs.length) style += `text-decoration:${decs.join(' ')};`;

      if (obfuscated) {
        html += `<span class="mc-obfuscated font-mono" data-orig-length="${chunk.length}" style="${style}">${esc(chunk)}</span>`;
      } else {
        html += `<span style="${style}">${esc(chunk)}</span>`;
      }
    }
    return html || esc(text);
  }

  // Ticker de animación en vivo para letras que se mueven (&k Mágico / Obfuscated)
  const OBFUSCATED_GLYPHS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!@#$%&*?+-=';
  function scrambleObfuscatedNodes() {
    const nodes = document.querySelectorAll('.mc-obfuscated');
    if (!nodes.length) return;
    for (let n = 0; n < nodes.length; n++) {
      const node = nodes[n];
      if (!node.dataset.origLength && node.textContent) {
        node.dataset.origLength = node.textContent.length;
      }
      const len = parseInt(node.dataset.origLength) || node.textContent.length || 2;
      let s = '';
      for (let j = 0; j < len; j++) {
        s += OBFUSCATED_GLYPHS.charAt(Math.floor(Math.random() * OBFUSCATED_GLYPHS.length));
      }
      node.textContent = s;
    }
  }
  setInterval(scrambleObfuscatedNodes, 45);

  // 4. Local Storage / Custom Ranks Persistence
  const CUSTOM_RANKS_KEY = 'minecraft_panel_custom_ranks';
  function getCustomRanks() {
    try {
      const raw = localStorage.getItem(CUSTOM_RANKS_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch (_) { return []; }
  }
  const loadCustomRanks = getCustomRanks;

  function saveCustomRank(rank) {
    const list = getCustomRanks().filter(r => r.id !== rank.id);
    list.push(rank);
    try { localStorage.setItem(CUSTOM_RANKS_KEY, JSON.stringify(list)); } catch (_) {}
  }

  function removeCustomRank(id) {
    const list = getCustomRanks().filter(r => r.id !== id);
    try { localStorage.setItem(CUSTOM_RANKS_KEY, JSON.stringify(list)); } catch (_) {}
  }

  function getAllPrimaryRanks() {
    const customs = getCustomRanks().filter(r => r.type !== 'secondary');
    return [...PRIMARY_RANKS, ...customs];
  }

  function getAllSecondaryRoles() {
    const customs = getCustomRanks().filter(r => r.type === 'secondary');
    return [...SECONDARY_ROLES, ...customs];
  }

  function getAllRanksCombined() {
    const p = getAllPrimaryRanks().map(r => ({ ...r, isSecondary: false }));
    const s = getAllSecondaryRoles().map(r => ({ ...r, isSecondary: true }));
    return [...p, ...s];
  }

  async function loadLuckPermsConfiguration() {
    try {
      const config = window.Panel && window.Panel.api
        ? await window.Panel.api('/api/luckperms/config')
        : await fetch('/api/luckperms/config').then(response => response.json());
      if (!config || !config.enabled) {
        document.querySelectorAll('[data-luckperms-module]').forEach(node => node.classList.add('hidden'));
        return false;
      }
      PRIMARY_RANKS = Array.isArray(config.primary_ranks) ? config.primary_ranks : [];
      SECONDARY_ROLES = Array.isArray(config.secondary_roles) ? config.secondary_roles : [];
      return true;
    } catch (_) {
      document.querySelectorAll('[data-luckperms-module]').forEach(node => node.classList.add('hidden'));
      return false;
    }
  }

  // 5. Execution & Terminal Logging
  function logLP(msg, isCmd = false) {
    const c = $('#lp-output-console'); if (!c) return;
    const time = new Date().toLocaleTimeString();
    const p = document.createElement('p');
    p.className = isCmd ? 'text-amber-300 font-semibold' : 'text-emerald-300';
    p.innerHTML = `<span class="text-zinc-500">[${time}]</span> ${esc(msg)}`;
    c.appendChild(p);
    c.scrollTop = c.scrollHeight;
  }

  async function runLP(cmd, label) {
    const target = ($('#lp-target-player') ? $('#lp-target-player').value.trim() : '');
    const fullCmd = cmd.replaceAll('{player}', target);
    const badge = $('#lp-last-cmd-badge');
    if (badge) badge.textContent = label || fullCmd;
    logLP(`> /lp ${fullCmd}`, true);
    try {
      let res;
      if (window.Panel && window.Panel.api) {
        res = await window.Panel.api('/api/luckperms/command', { method: 'POST', body: { command: fullCmd } });
      } else {
        const resp = await fetch('/api/luckperms/command', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ command: fullCmd })
        });
        res = await resp.json();
      }
      if (res && res.success) {
        if (window.Panel && window.Panel.toast) window.Panel.toast(label || 'Comando ejecutado con éxito.');
        if (res.message) logLP(res.message);
      } else {
        const errMsg = (res && res.message) ? res.message : 'Error al ejecutar.';
        if (window.Panel && window.Panel.toast) window.Panel.toast(errMsg, 'error');
        logLP(errMsg);
      }
    } catch (e) {
      if (window.Panel && window.Panel.toast) window.Panel.toast(e.message, 'error');
      logLP('Error: ' + e.message);
    }
  }

  // 6. Player Selection
  function selectPlayer(name, isOnline = false) {
    const targetInp = $('#lp-target-player');
    if (targetInp) targetInp.value = name;
    const selName = $('#lp-selected-name');
    if (selName) selName.textContent = name;
    const avatar = $('#lp-selected-avatar');
    if (avatar) avatar.src = `https://mc-heads.net/avatar/${encodeURIComponent(name)}/40`;
    const badge = $('#lp-selected-online-badge');
    if (badge) {
      badge.textContent = isOnline ? 'ONLINE' : 'REGISTRADO';
      badge.className = isOnline
        ? 'rounded bg-emerald-500/20 px-1.5 py-0.2 text-[10px] font-bold text-emerald-300 ring-1 ring-emerald-500/30'
        : 'rounded bg-zinc-800 px-1.5 py-0.2 text-[10px] font-bold text-zinc-400';
    }
    const card = $('#lp-selected-card');
    if (card) {
      card.classList.remove('hidden');
      card.classList.add('flex');
    }
    const infoText = $('#lp-selected-info-text');
    if (infoText) infoText.textContent = 'Hacé clic en cualquier rango de abajo para asignárselo a ' + name + '.';
  }

  // 7. Rank Cards Rendering
  function renderRanksCards() {
    const grid = $('#lp-ranks-grid');
    if (grid) {
      const allPrimary = getAllPrimaryRanks();
      grid.innerHTML = allPrimary.map(r => `
        <div class="rounded-xl border ${r.border} ${r.bg} p-4 flex flex-col justify-between transition-all duration-200 hover:-translate-y-0.5 shadow-md relative group">
          <div>
            <div class="flex items-center justify-between gap-2">
              <div class="flex items-center gap-2">
                <span class="text-xl">${r.icon}</span>
                <b class="text-sm text-zinc-100">${esc(r.name)}</b>
              </div>
              <div class="flex items-center gap-1">
                ${r.isCustom ? `<button type="button" data-delete-custom="${esc(r.id)}" data-rank-name="${esc(r.name)}" class="rounded p-1 text-zinc-500 hover:text-rose-400 transition" title="Eliminar rango">🗑️</button>` : ''}
                <span class="rounded px-2 py-0.5 text-[10px] font-bold border ${r.permColor}">${esc(r.perm)}</span>
              </div>
            </div>
            <div class="mt-3 flex items-center gap-2">
              <span class="text-[11px] text-zinc-500">Prefijo:</span>
              <span class="rounded-lg px-2.5 py-1 text-sm font-mono tracking-wide ${r.badge}">${renderMinecraftText(r.tag)}</span>
            </div>
            <p class="mt-2 text-xs text-zinc-400 leading-relaxed">${esc(r.desc)}</p>
          </div>
          <div class="mt-4 pt-3 border-t border-zinc-800/80 flex items-center justify-between gap-2">
            <span class="text-[10px] font-mono text-zinc-500">Peso: ${r.weight}</span>
            <button type="button" data-set-rank="${esc(r.id)}" data-rank-name="${esc(r.name)}" class="rounded-lg bg-amber-400 hover:bg-amber-300 text-zinc-950 px-3 py-1.5 text-xs font-bold transition shadow-sm flex items-center gap-1">
              <span>⭐</span> Asignar Rango
            </button>
          </div>
        </div>
      `).join('');
    }

    const rolesGrid = $('#lp-roles-grid');
    if (rolesGrid) {
      const allSecondary = getAllSecondaryRoles();
      rolesGrid.innerHTML = allSecondary.map(role => `
        <div class="rounded-xl border ${role.border} bg-zinc-950/80 p-4 flex flex-col justify-between transition hover:-translate-y-0.5 shadow relative">
          <div>
            <div class="flex items-center justify-between gap-2">
              <div class="flex items-center gap-2">
                <span class="text-lg">${role.icon}</span>
                <b class="text-sm text-zinc-100">${esc(role.name)}</b>
              </div>
              ${role.isCustom ? `<button type="button" data-delete-custom="${esc(role.id)}" data-rank-name="${esc(role.name)}" class="rounded p-1 text-zinc-500 hover:text-rose-400 transition" title="Eliminar rol">🗑️</button>` : ''}
            </div>
            <div class="mt-2.5 flex items-center gap-2">
              <span class="rounded-lg px-2.5 py-1 text-sm font-mono ${role.badge}">${renderMinecraftText(role.tag)}</span>
            </div>
            <p class="mt-2 text-xs text-zinc-400 leading-relaxed">${esc(role.desc)}</p>
          </div>
          <div class="mt-4 pt-3 border-t border-zinc-800 flex items-center gap-2">
            <button type="button" data-add-role="${esc(role.id)}" data-role-name="${esc(role.name)}" class="flex-1 rounded-lg bg-emerald-500/20 border border-emerald-500/40 hover:bg-emerald-500/30 text-emerald-200 py-1.5 text-xs font-bold transition">
              + Dar Rol
            </button>
            <button type="button" data-remove-role="${esc(role.id)}" data-role-name="${esc(role.name)}" class="flex-1 rounded-lg bg-rose-500/20 border border-rose-500/40 hover:bg-rose-500/30 text-rose-200 py-1.5 text-xs font-bold transition">
              - Quitar
            </button>
          </div>
        </div>
      `).join('');
    }
  }

  // 8. Players Loading & Online Chips
  async function loadRanksPlayers() {
    try {
      const fetchApi = (url) => window.Panel && window.Panel.api ? window.Panel.api(url) : fetch(url).then(r => r.json());
      const [onlineData, allPlayers] = await Promise.all([
        fetchApi('/api/server/online-players'),
        fetchApi('/api/players')
      ]);
      const onlineList = (onlineData && onlineData.players) || [];
      const countEl = $('#lp-online-count');
      if (countEl) countEl.textContent = `${onlineList.length} en línea (${(onlineData && onlineData.count) || 0}/${(onlineData && onlineData.max_players) || 10})`;
      const chipsEl = $('#lp-online-chips');
      if (chipsEl) {
        if (onlineList.length === 0) {
          chipsEl.innerHTML = '<span class="text-xs text-zinc-500 italic">No hay jugadores conectados en este momento. Podés escribir el nombre abajo.</span>';
        } else {
          chipsEl.innerHTML = onlineList.map(p => `
            <button type="button" data-online-player="${esc(p.username)}" class="flex items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-950/40 hover:bg-emerald-900/60 px-3 py-1.5 text-xs font-semibold text-emerald-200 transition shadow-sm">
              <img src="${esc(p.avatar_url || `https://mc-heads.net/avatar/${encodeURIComponent(p.username)}/24`)}" class="h-5 w-5 rounded object-cover" onerror="this.src='https://mc-heads.net/avatar/steve/24'">
              <span>${esc(p.username)}</span>
              <span class="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
            </button>
          `).join('');
        }
      }
      const sel = $('#lp-known-players');
      if (sel && Array.isArray(allPlayers)) {
        sel.innerHTML = '<option value="">-- Seleccionar de registrados (' + allPlayers.length + ') --</option>' +
          allPlayers.map(p => `<option value="${esc(p.username)}">${esc(p.username)} (${p.is_op ? 'OP' : p.is_whitelisted ? 'Whitelist' : 'Jugador'})</option>`).join('');
      }
      // Pre-seleccionar al primer jugador conectado si el campo está vacío
      const targetInput = $('#lp-target-player');
      if (onlineList.length > 0 && targetInput && !targetInput.value.trim()) {
        selectPlayer(onlineList[0].username, true);
      }
    } catch (err) {
      console.warn('Error al cargar jugadores para rangos:', err);
    }
  }

  // 9. Rank Creator & Live Preview
  function updateCreateRankPreview() {
    const prefixInput = $('#lp-new-prefix');
    if (!prefixInput) return;
    const prefix = prefixInput.value || '';
    const parsed = renderMinecraftText(prefix);

    const chatPrefixEl = $('#lp-preview-chat-prefix');
    if (chatPrefixEl) chatPrefixEl.innerHTML = parsed;

    const tabPrefixEl = $('#lp-preview-tab-prefix');
    if (tabPrefixEl) tabPrefixEl.innerHTML = parsed;

    scrambleObfuscatedNodes();
  }

  const btnToggleCreate = $('#btn-toggle-create-rank');
  if (btnToggleCreate) {
    btnToggleCreate.onclick = () => {
      const p = $('#lp-create-rank-panel');
      if (!p) return;
      p.classList.toggle('hidden');
      if (!p.classList.contains('hidden')) {
        const idInput = $('#lp-new-id');
        if (idInput) idInput.focus();
        updateCreateRankPreview();
      }
    };
  }

  const btnCloseCreate = $('#btn-close-create-rank');
  if (btnCloseCreate) btnCloseCreate.onclick = () => {
    const p = $('#lp-create-rank-panel');
    if (p) p.classList.add('hidden');
  };

  const btnCancelCreate = $('#btn-cancel-create-rank');
  if (btnCancelCreate) btnCancelCreate.onclick = () => {
    const p = $('#lp-create-rank-panel');
    if (p) p.classList.add('hidden');
  };

  // Color palette buttons (.mc-color-btn)
  document.querySelectorAll('.mc-color-btn').forEach(btn => {
    btn.onclick = () => {
      const code = btn.dataset.mcCode;
      const input = $('#lp-new-prefix');
      if (!input || !code) return;
      const start = input.selectionStart || input.value.length;
      const end = input.selectionEnd || input.value.length;
      input.value = input.value.substring(0, start) + code + input.value.substring(end);
      input.focus();
      input.setSelectionRange(start + code.length, start + code.length);
      updateCreateRankPreview();
    };
  });

  // Hex Picker & Insert Button
  const btnInsertHex = $('#btn-insert-hex');
  if (btnInsertHex) {
    btnInsertHex.onclick = () => {
      const picker = $('#mc-hex-picker');
      const color = picker ? picker.value.toUpperCase() : '#FF0077';
      const code = '&' + color;
      const input = $('#lp-new-prefix');
      if (!input) return;
      const start = input.selectionStart || input.value.length;
      const end = input.selectionEnd || input.value.length;
      input.value = input.value.substring(0, start) + code + input.value.substring(end);
      input.focus();
      input.setSelectionRange(start + code.length, start + code.length);
      updateCreateRankPreview();
    };
  }

  // Template Presets (.btn-mc-preset)
  document.querySelectorAll('.btn-mc-preset').forEach(btn => {
    btn.onclick = () => {
      const tpl = btn.dataset.template;
      const input = $('#lp-new-prefix');
      const nameInput = $('#lp-new-name');
      let name = (nameInput && nameInput.value.trim()) ? nameInput.value.trim() : '';
      if (!name) {
        const idInput = $('#lp-new-id');
        if (idInput && idInput.value.trim()) {
          name = idInput.value.trim().toUpperCase();
        }
      }
      if (!name) name = 'RANGO';
      if (input && tpl) {
        input.value = tpl.replaceAll('{name}', name);
        input.focus();
        updateCreateRankPreview();
      }
    };
  });

  // Quick Weight Buttons (.btn-quick-weight)
  document.querySelectorAll('.btn-quick-weight').forEach(btn => {
    btn.onclick = () => {
      const w = $('#lp-new-weight');
      if (w) w.value = btn.dataset.val;
    };
  });

  const newPrefixInp = $('#lp-new-prefix');
  if (newPrefixInp) newPrefixInp.oninput = updateCreateRankPreview;

  const newNameInp = $('#lp-new-name');
  if (newNameInp) newNameInp.oninput = updateCreateRankPreview;

  // Submit Create Rank (#btn-submit-create-rank)
  const btnSubmitCreate = $('#btn-submit-create-rank');
  if (btnSubmitCreate) {
    btnSubmitCreate.onclick = async () => {
      const idEl = $('#lp-new-id');
      const rawId = idEl ? idEl.value.trim().toLowerCase().replace(/[^a-z0-9_-]/g, '') : '';
      if (!rawId) {
        if (window.Panel && window.Panel.toast) window.Panel.toast('Ingresá un identificador válido (ej. vip, streamer).', 'error');
        if (idEl) idEl.focus();
        return;
      }
      const nameVal = $('#lp-new-name') ? $('#lp-new-name').value.trim() : '';
      const name = nameVal || rawId.toUpperCase();
      const prefixVal = $('#lp-new-prefix') ? $('#lp-new-prefix').value.trim() : '';
      const prefix = prefixVal || `[${name}]`;
      const type = $('#lp-new-type') ? $('#lp-new-type').value : 'primary';
      const weight = parseInt($('#lp-new-weight') ? $('#lp-new-weight').value : '50') || 50;

      if (window.Panel && window.Panel.toast) window.Panel.toast(`Creando rango '${name}' en LuckPerms...`);
      btnSubmitCreate.disabled = true;
      try {
        await runLP(`creategroup ${rawId}`, `Creando grupo ${rawId}`);
        await runLP(`group ${rawId} setweight ${weight}`, `Asignando peso ${weight}`);
        await runLP(`group ${rawId} meta setprefix ${weight} "${prefix} "`, `Asignando prefijo ${prefix}`);

        // Permisos iniciales marcados
        const permsToSet = [];
        if ($('#init-perm-fly') && $('#init-perm-fly').checked) permsToSet.push(...PERM_DEFINITIONS.fly);
        if ($('#init-perm-tp') && $('#init-perm-tp').checked) permsToSet.push(...PERM_DEFINITIONS.tp);
        if ($('#init-perm-gm') && $('#init-perm-gm').checked) permsToSet.push(...PERM_DEFINITIONS.gamemode);
        if ($('#init-perm-voice') && $('#init-perm-voice').checked) permsToSet.push(...PERM_DEFINITIONS.voice_groups);
        if ($('#init-perm-pointblank') && $('#init-perm-pointblank').checked) permsToSet.push(...PERM_DEFINITIONS.pointblank);
        if ($('#init-perm-all') && $('#init-perm-all').checked) permsToSet.push('*');

        for (const p of permsToSet) {
          await runLP(`group ${rawId} permission set ${p} true`, `Concediendo ${p} a ${rawId}`);
        }

        // Guardar en custom ranks
        const newRank = {
          id: rawId,
          name,
          weight,
          tag: prefix,
          border: type === 'primary' ? 'border-amber-500/50 hover:border-amber-400' : 'border-purple-500/40 hover:border-purple-400',
          bg: type === 'primary' ? 'bg-gradient-to-br from-amber-950/30 via-zinc-900 to-zinc-900' : 'bg-gradient-to-br from-purple-950/30 via-zinc-900 to-zinc-900',
          badge: 'bg-zinc-800 text-amber-300 font-bold border border-amber-500/40',
          icon: type === 'primary' ? '⭐' : '✨',
          desc: `Rango personalizado '${name}' creado desde el panel web.`,
          perm: `${permsToSet.length} permisos`,
          permColor: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
          type,
          isCustom: true
        };
        saveCustomRank(newRank);
        renderRanksCards();
        populateInspectorDropdown();
        if ($('#lp-inspect-select')) {
          $('#lp-inspect-select').value = rawId;
          updateInspectorView();
        }
        const panel = $('#lp-create-rank-panel');
        if (panel) panel.classList.add('hidden');
        if (window.Panel && window.Panel.toast) window.Panel.toast(`¡Rango '${name}' creado exitosamente!`);
      } catch (err) {
        if (window.Panel && window.Panel.toast) window.Panel.toast(err.message, 'error');
      } finally {
        btnSubmitCreate.disabled = false;
      }
    };
  }

  // 10. Inspector & Interactive Command Runner
  function populateInspectorDropdown() {
    const sel = $('#lp-inspect-select');
    if (!sel) return;
    const curVal = sel.value;
    const all = getAllRanksCombined();
    sel.innerHTML = all.map(r => `
      <option value="${esc(r.id)}">${r.icon || '⭐'} ${esc(r.name)} (${esc(r.id)}) · Peso: ${r.weight || 10} [${r.isSecondary ? 'Rol Secundario' : 'Jerarquía'}]</option>
    `).join('');
    if (curVal && all.some(r => r.id === curVal)) {
      sel.value = curVal;
    }
    updateInspectorView();
  }

  function updateInspectorView() {
    const sel = $('#lp-inspect-select');
    if (!sel) return;
    const rankId = sel.value;
    const rank = getAllRanksCombined().find(r => r.id === rankId);
    if (!rank) return;

    const iconEl = $('#lp-inspect-icon'); if (iconEl) iconEl.textContent = rank.icon || '⭐';
    const nameEl = $('#lp-inspect-name'); if (nameEl) nameEl.textContent = rank.name;
    const idEl = $('#lp-inspect-id-badge'); if (idEl) idEl.textContent = rank.id;
    const typeEl = $('#lp-inspect-type-badge'); if (typeEl) typeEl.textContent = rank.isSecondary ? 'Rol Secundario' : 'Jerarquía Principal';
    const wEl = $('#lp-inspect-weight'); if (wEl) wEl.textContent = rank.weight || 10;
    const pfxEl = $('#lp-inspect-prefix-badge'); if (pfxEl) pfxEl.innerHTML = renderMinecraftText(rank.tag || rank.name);
  }

  const inspectSel = $('#lp-inspect-select');
  if (inspectSel) inspectSel.onchange = updateInspectorView;

  // Direct rank inspect buttons
  const btnInspectInfo = $('#btn-inspect-lp-info');
  if (btnInspectInfo) {
    btnInspectInfo.onclick = () => {
      const sel = $('#lp-inspect-select');
      const rankId = sel ? sel.value : '';
      if (!rankId) return;
      runLP(`group ${rankId} permission info`, `Consultando permisos activos de ${rankId}`);
    };
  }

  const btnInspectMembers = $('#btn-inspect-lp-members');
  if (btnInspectMembers) {
    btnInspectMembers.onclick = () => {
      const sel = $('#lp-inspect-select');
      const rankId = sel ? sel.value : '';
      if (!rankId) return;
      runLP(`group ${rankId} listmembers`, `Listando jugadores con rango ${rankId}`);
    };
  }

  const btnInspectDelete = $('#btn-inspect-lp-delete');
  if (btnInspectDelete) {
    btnInspectDelete.onclick = async () => {
      const sel = $('#lp-inspect-select');
      const rankId = sel ? sel.value : '';
      if (!rankId) return;
      if (!confirm(`¿Estás seguro de que querés eliminar el rango '${rankId}' de LuckPerms?`)) return;
      await runLP(`deletegroup ${rankId}`, `Eliminando grupo ${rankId}`);
      removeCustomRank(rankId);
      renderRanksCards();
      populateInspectorDropdown();
    };
  }

  // Inspector section click delegation (quick commands & perm chips)
  const inspectorSection = $('#lp-inspector-section');
  if (inspectorSection) {
    inspectorSection.onclick = async e => {
      const b = e.target.closest('[data-cmd-perm]');
      if (b) {
        const sel = $('#lp-inspect-select');
        const rankId = sel ? sel.value : '';
        if (!rankId) {
          if (window.Panel && window.Panel.toast) window.Panel.toast('Seleccioná un rango primero.', 'error');
          return;
        }
        const permKey = b.dataset.cmdPerm;
        const action = b.dataset.permAction; // 'grant' or 'revoke'
        const nodes = PERM_DEFINITIONS[permKey] || [permKey];
        for (const node of nodes) {
          if (action === 'grant') {
            await runLP(`group ${rankId} permission set ${node} true`, `Permiso ${node} concedido a ${rankId}`);
          } else {
            await runLP(`group ${rankId} permission unset ${node}`, `Permiso ${node} revocado de ${rankId}`);
          }
        }
        return;
      }
      const quickChip = e.target.closest('.quick-perm-chip');
      if (quickChip) {
        const input = $('#lp-custom-perm-input');
        if (input) input.value = quickChip.dataset.perm;
        return;
      }
    };
  }

  // Custom permission buttons
  const btnCustomGrant = $('#btn-custom-perm-grant');
  if (btnCustomGrant) {
    btnCustomGrant.onclick = () => {
      const sel = $('#lp-inspect-select');
      const rankId = sel ? sel.value : '';
      const input = $('#lp-custom-perm-input');
      const node = input ? input.value.trim() : '';
      if (!rankId || !node) {
        if (window.Panel && window.Panel.toast) window.Panel.toast('Escribí un nodo de permiso primero.', 'error');
        return;
      }
      runLP(`group ${rankId} permission set ${node} true`, `Permiso ${node} concedido a ${rankId}`);
    };
  }

  const btnCustomDeny = $('#btn-custom-perm-deny');
  if (btnCustomDeny) {
    btnCustomDeny.onclick = () => {
      const sel = $('#lp-inspect-select');
      const rankId = sel ? sel.value : '';
      const input = $('#lp-custom-perm-input');
      const node = input ? input.value.trim() : '';
      if (!rankId || !node) {
        if (window.Panel && window.Panel.toast) window.Panel.toast('Escribí un nodo de permiso primero.', 'error');
        return;
      }
      runLP(`group ${rankId} permission set ${node} false`, `Permiso ${node} denegado (false) a ${rankId}`);
    };
  }

  const btnCustomUnset = $('#btn-custom-perm-unset');
  if (btnCustomUnset) {
    btnCustomUnset.onclick = () => {
      const sel = $('#lp-inspect-select');
      const rankId = sel ? sel.value : '';
      const input = $('#lp-custom-perm-input');
      const node = input ? input.value.trim() : '';
      if (!rankId || !node) {
        if (window.Panel && window.Panel.toast) window.Panel.toast('Escribí un nodo de permiso primero.', 'error');
        return;
      }
      runLP(`group ${rankId} permission unset ${node}`, `Permiso ${node} eliminado de ${rankId}`);
    };
  }

  // 11. Event Delegation for Ranks and Roles grids
  const ranksGrid = $('#lp-ranks-grid');
  if (ranksGrid) {
    ranksGrid.onclick = async e => {
      const delCustomBtn = e.target.closest('[data-delete-custom]');
      if (delCustomBtn) {
        const rankId = delCustomBtn.dataset.deleteCustom;
        const rankName = delCustomBtn.dataset.rankName || rankId;
        if (confirm(`¿Estás seguro de que querés borrar el rango '${rankName}' (${rankId}) del servidor?`)) {
          runLP(`deletegroup ${rankId}`, `Eliminando grupo ${rankId}`);
          removeCustomRank(rankId);
          renderRanksCards();
          populateInspectorDropdown();
        }
        return;
      }
      const b = e.target.closest('[data-set-rank]');
      if (!b) return;
      const targetInput = $('#lp-target-player');
      const target = targetInput ? targetInput.value.trim() : '';
      if (!target) {
        if (window.Panel && window.Panel.toast) window.Panel.toast('Seleccioná o escribí un jugador en el Paso 1 primero.', 'error');
        if (targetInput) targetInput.focus();
        return;
      }
      const rankId = b.dataset.setRank, rankName = b.dataset.rankName;
      const rankObj = getAllPrimaryRanks().find(r => r.id === rankId);
      if (rankObj && rankObj.tag) {
        await runLP(`group ${rankId} meta setprefix ${rankObj.weight || 50} "${rankObj.tag} "`);
      }
      await runLP(`user ${target} parent set ${rankId}`, `Rango principal ${rankName} asignado a ${target}`);
    };
  }

  const rolesGrid = $('#lp-roles-grid');
  if (rolesGrid) {
    rolesGrid.onclick = async e => {
      const delCustomBtn = e.target.closest('[data-delete-custom]');
      if (delCustomBtn) {
        const roleId = delCustomBtn.dataset.deleteCustom;
        const roleName = delCustomBtn.dataset.rankName || roleId;
        if (confirm(`¿Estás seguro de que querés borrar el rol '${roleName}' (${roleId}) del servidor?`)) {
          runLP(`deletegroup ${roleId}`, `Eliminando rol ${roleId}`);
          removeCustomRank(roleId);
          renderRanksCards();
          populateInspectorDropdown();
        }
        return;
      }
      const addBtn = e.target.closest('[data-add-role]');
      const rmBtn = e.target.closest('[data-remove-role]');
      const targetInput = $('#lp-target-player');
      const target = targetInput ? targetInput.value.trim() : '';
      if (!target) {
        if (window.Panel && window.Panel.toast) window.Panel.toast('Seleccioná o escribí un jugador en el Paso 1 primero.', 'error');
        if (targetInput) targetInput.focus();
        return;
      }
      if (addBtn) {
        const roleId = addBtn.dataset.addRole, roleName = addBtn.dataset.roleName;
        const roleObj = getAllSecondaryRoles().find(r => r.id === roleId);
        if (roleObj && roleObj.tag) {
          await runLP(`group ${roleId} meta setprefix ${roleObj.weight || 35} "${roleObj.tag} "`);
        }
        await runLP(`user ${target} parent add ${roleId}`, `Rol ${roleName} otorgado a ${target}`);
      } else if (rmBtn) {
        await runLP(`user ${target} parent remove ${rmBtn.dataset.removeRole}`, `Rol ${rmBtn.dataset.roleName} quitado a ${target}`);
      }
    };
  }

  // 12. Player Input & Quick Actions
  const onlineChips = $('#lp-online-chips');
  if (onlineChips) {
    onlineChips.onclick = e => {
      const b = e.target.closest('[data-online-player]');
      if (b) selectPlayer(b.dataset.onlinePlayer, true);
    };
  }

  const knownPlayersSel = $('#lp-known-players');
  if (knownPlayersSel) {
    knownPlayersSel.onchange = e => {
      if (e.target.value) selectPlayer(e.target.value, false);
    };
  }

  const targetPlayerInp = $('#lp-target-player');
  if (targetPlayerInp) {
    targetPlayerInp.oninput = e => {
      const val = e.target.value.trim();
      const card = $('#lp-selected-card');
      if (val) {
        const nameEl = $('#lp-selected-name');
        if (nameEl) nameEl.textContent = val;
        const avatar = $('#lp-selected-avatar');
        if (avatar) avatar.src = `https://mc-heads.net/avatar/${encodeURIComponent(val)}/40`;
        if (card) {
          card.classList.remove('hidden');
          card.classList.add('flex');
        }
        const badge = $('#lp-selected-online-badge');
        if (badge) {
          badge.textContent = 'MANUAL';
          badge.className = 'rounded bg-zinc-800 px-1.5 py-0.2 text-[10px] font-bold text-zinc-400';
        }
      } else {
        if (card) {
          card.classList.add('hidden');
          card.classList.remove('flex');
        }
      }
    };
  }

  const btnInspectPlayer = $('#btn-inspect-player');
  if (btnInspectPlayer) {
    btnInspectPlayer.onclick = () => {
      const targetInput = $('#lp-target-player');
      const target = targetInput ? targetInput.value.trim() : '';
      if (!target) {
        if (window.Panel && window.Panel.toast) window.Panel.toast('Escribí un nombre de jugador primero.', 'error');
        return;
      }
      runLP(`user ${target} info`, `Consultando datos de ${target}`);
    };
  }

  const btnLpPromote = $('#btn-lp-promote');
  if (btnLpPromote) {
    btnLpPromote.onclick = () => {
      const targetInput = $('#lp-target-player');
      const target = targetInput ? targetInput.value.trim() : '';
      if (!target) {
        if (window.Panel && window.Panel.toast) window.Panel.toast('Seleccioná un jugador primero.', 'error');
        return;
      }
      runLP(`user ${target} promote jerarquia`, `Subiendo rango en jerarquía a ${target}`);
    };
  }

  const btnLpDemote = $('#btn-lp-demote');
  if (btnLpDemote) {
    btnLpDemote.onclick = () => {
      const targetInput = $('#lp-target-player');
      const target = targetInput ? targetInput.value.trim() : '';
      if (!target) {
        if (window.Panel && window.Panel.toast) window.Panel.toast('Seleccioná un jugador primero.', 'error');
        return;
      }
      runLP(`user ${target} demote jerarquia`, `Bajando rango en jerarquía a ${target}`);
    };
  }

  const btnLpResetDefault = $('#btn-lp-reset-default');
  if (btnLpResetDefault) {
    btnLpResetDefault.onclick = () => {
      const targetInput = $('#lp-target-player');
      const target = targetInput ? targetInput.value.trim() : '';
      if (!target) {
        if (window.Panel && window.Panel.toast) window.Panel.toast('Seleccioná un jugador primero.', 'error');
        return;
      }
      runLP(`user ${target} parent set default`, `Restableciendo ${target} a Turista (Default)`);
    };
  }

  // Header quick buttons (Sync, Web Editor, Clear Terminal)
  const btnLpSync = $('#btn-lp-sync');
  if (btnLpSync) {
    btnLpSync.onclick = async () => {
      if (window.Panel && window.Panel.toast) window.Panel.toast('Sincronizando y actualizando prefijos en LuckPerms...');
      const all = getAllRanksCombined();
      for (const r of all) {
        if (r.tag && r.id && r.id !== 'default') {
          await runLP(`group ${r.id} meta setprefix ${r.weight || 50} "${r.tag} "`);
        }
      }
      await runLP('sync', 'Sincronización completa de LuckPerms');
    };
  }

  const btnLpEditor = $('#btn-lp-editor');
  if (btnLpEditor) {
    btnLpEditor.onclick = async () => {
      if (window.Panel && window.Panel.toast) window.Panel.toast('Generando enlace del editor web...');
      try {
        let res;
        if (window.Panel && window.Panel.api) {
          res = await window.Panel.api('/api/luckperms/editor', { method: 'POST' });
        } else {
          const resp = await fetch('/api/luckperms/editor', { method: 'POST' });
          res = await resp.json();
        }
        if (res && res.success && res.editor_url) {
          if (window.Panel && window.Panel.toast) window.Panel.toast('Abriendo editor web...');
          window.open(res.editor_url, '_blank');
          logLP('Editor URL: ' + res.editor_url);
        } else {
          const msg = (res && res.message) ? res.message : 'No se pudo generar el enlace.';
          if (window.Panel && window.Panel.toast) window.Panel.toast(msg, 'error');
        }
      } catch (e) {
        if (window.Panel && window.Panel.toast) window.Panel.toast(e.message, 'error');
      }
    };
  }

  const btnClearLog = $('#btn-clear-lp-log');
  if (btnClearLog) {
    btnClearLog.onclick = () => {
      const c = $('#lp-output-console');
      if (c) c.innerHTML = '<p class="text-zinc-500 italic">Terminal limpia. Listo para nuevas acciones.</p>';
    };
  }

  // 13. WebSocket for Realtime LuckPerms Console Output
  try {
    const wsUrl = (window.Panel && window.Panel.websocketUrl)
      ? window.Panel.websocketUrl('/ws/terminal')
      : `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws/terminal`;
    const ws = new WebSocket(wsUrl);
    ws.onopen = () => {
      const dot = $('#lp-terminal-dot');
      if (dot) dot.className = 'h-2 w-2 rounded-full bg-emerald-400 animate-pulse';
    };
    ws.onmessage = e => {
      try {
        const data = JSON.parse(e.data);
        if (data.type === 'line' && data.line && data.line.message) {
          const msg = data.line.message;
          const low = msg.toLowerCase();
          if (
            msg.includes('[LP]') ||
            low.includes('luckperms') ||
            low.includes('parent') ||
            low.includes('group') ||
            low.includes('promoted') ||
            low.includes('demoted') ||
            low.includes('permission') ||
            low.includes('nodes') ||
            low.includes('weight') ||
            low.includes('meta')
          ) {
            logLP(msg);
          }
        }
      } catch (_) {}
    };
    ws.onclose = () => {
      const dot = $('#lp-terminal-dot');
      if (dot) dot.className = 'h-2 w-2 rounded-full bg-zinc-600';
    };
  } catch (_) {}

  // 14. Hash Navigation Auto-scroll for #ranks
  const handleRanksHash = () => {
    if (window.location.hash === '#ranks') {
      setTimeout(() => {
        const el = document.getElementById('ranks');
        if (el) {
          el.scrollIntoView({ behavior: 'smooth' });
          el.classList.add('ring-4', 'ring-amber-400/50');
          setTimeout(() => el.classList.remove('ring-4', 'ring-amber-400/50'), 2500);
        }
      }, 100);
    }
  };
  window.addEventListener('hashchange', handleRanksHash);

  // 15. Initial Execution on DOMContentLoaded
  (async () => {
    if (!await loadLuckPermsConfiguration()) return;
    renderRanksCards();
    populateInspectorDropdown();
    updateCreateRankPreview();
    loadRanksPlayers();
    handleRanksHash();
  })();

  // 16. Expose global namespace for interop & compatibility
  window.AdminRanks = {
    get PRIMARY_RANKS() { return PRIMARY_RANKS; },
    get SECONDARY_ROLES() { return SECONDARY_ROLES; },
    MC_COLORS,
    PERM_DEFINITIONS,
    renderMinecraftText,
    scrambleObfuscatedNodes,
    getCustomRanks,
    loadCustomRanks,
    saveCustomRank,
    removeCustomRank,
    getAllPrimaryRanks,
    getAllSecondaryRoles,
    getAllRanksCombined,
    renderRanksCards,
    updateCreateRankPreview,
    populateInspectorDropdown,
    updateInspectorView,
    loadRanksPlayers,
    selectPlayer,
    runLP,
    logLP,
    handleRanksHash
  };

  // Backwards compatibility globals
  window.renderRanksCards = renderRanksCards;
  window.populateInspectorDropdown = populateInspectorDropdown;
  window.updateCreateRankPreview = updateCreateRankPreview;
  window.loadRanksPlayers = loadRanksPlayers;
  window.runLP = runLP;
  window.logLP = logLP;
  window.renderMinecraftText = renderMinecraftText;
  window.saveCustomRank = saveCustomRank;
  window.loadCustomRanks = loadCustomRanks;
  window.getCustomRanks = getCustomRanks;
});
