/**
 * Editor de Configuraciones TOML/JSON, Reglas del Mundo, Moderación de Jugadores,
 * Auditoría Spark y Programador de Backups para el Panel de Administración.
 */
(() => {
  const initAdminConfigs = () => {
    // Helpers
    const $ = (s) => document.querySelector(s);
    const esc = (s) => (window.Panel && window.Panel.escapeHtml)
      ? window.Panel.escapeHtml(s)
      // Fail closed: escape locally if the shared helper is missing.
      : String(s ?? '').replace(/[&<>'"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[c]);
    const label = (s) => String(s).replaceAll('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase());

    // State
    let files = [];
    let current;

    // On/off switch, same markup as the mods list. The checkbox keeps its data-* hooks.
    const SWITCH_TRACK = `<span aria-hidden="true" class="block h-6 w-11 rounded-full bg-zinc-700 after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:bg-zinc-200 after:transition-all after:content-[''] peer-checked:bg-emerald-400 peer-checked:after:translate-x-full peer-checked:after:bg-[#16250c] peer-focus-visible:ring-2 peer-focus-visible:ring-emerald-200"></span>`;
    const switchControl = (attrs, checked) =>
      `<span class="relative inline-flex shrink-0 items-center"><input ${attrs} type="checkbox" ${checked ? 'checked' : ''} class="peer sr-only">${SWITCH_TRACK}</span>`;
    const ROW = 'border-b border-zinc-800 py-4';
    // Plain names for the game rules the panel exposes; the technical name stays as small text.
    const GAMERULE_LABELS = {
      keepInventory: 'Conservar el inventario al morir',
      naturalRegeneration: 'Recuperar vida con el tiempo',
      mobGriefing: 'Las criaturas rompen bloques',
      doFireTick: 'El fuego se propaga',
      doDaylightCycle: 'Pasan el día y la noche',
      doWeatherCycle: 'Cambia el clima',
      randomTickSpeed: 'Velocidad a la que crecen las plantas',
      maxEntityCramming: 'Máximo de criaturas en un mismo lugar',
    };
    const ruleLabel = (name) => (Object.prototype.hasOwnProperty.call(GAMERULE_LABELS, name) ? GAMERULE_LABELS[name] : name);
    const NUMBER_INPUT ='min-h-11 w-32 shrink-0 rounded-lg border border-zinc-800 bg-zinc-900 px-4 text-zinc-100 outline-none focus:border-emerald-400';

    // Configs tree renderer: node(n) handling 'section', 'boolean', 'number', 'list', etc.
    const node = (n) =>
      n.type === 'section'
        ? `<details class="${ROW}" open><summary class="cursor-pointer font-semibold text-zinc-100">${esc(label(n.key))}</summary><div class="mt-2 border-l border-zinc-800 pl-4">${n.children.map(node).join('')}</div></details>`
        : n.type === 'boolean'
        ? `<label class="flex cursor-pointer items-center justify-between gap-4 ${ROW}"><span class="min-w-0"><span class="block font-medium text-zinc-100">${esc(label(n.key))}</span>${n.comment ? `<span class="mt-0.5 block text-sm leading-relaxed text-zinc-500">${esc(n.comment)}</span>` : ''}</span>${switchControl(`data-path="${esc(n.path)}"`, n.value)}</label>`
        : n.type === 'number'
        ? `<label class="flex flex-wrap items-center justify-between gap-4 ${ROW}"><span class="min-w-0 flex-1"><span class="block font-medium text-zinc-100">${esc(label(n.key))}</span>${n.comment ? `<span class="mt-0.5 block text-sm leading-relaxed text-zinc-500">${esc(n.comment)}</span>` : ''}</span><input data-path="${esc(n.path)}" type="number" value="${esc(n.value)}" ${n.minimum !== null ? `min="${esc(n.minimum)}"` : ''} ${n.maximum !== null ? `max="${esc(n.maximum)}"` : ''} class="${NUMBER_INPUT}"></label>`
        : `<div class="${ROW}"><span class="block font-medium text-zinc-100">${esc(label(n.key))}</span><span class="mt-0.5 block text-sm leading-relaxed text-zinc-500">${n.type === 'list' ? 'Esto se cambia editando el archivo como texto, en Opciones avanzadas.' : esc(n.comment || '')}</span></div>`;

    // showFiles(): search filter on #config-search and rendering into #config-picker
    function showFiles() {
      const picker = $('#config-picker');
      if (!picker) return;
      const searchInput = $('#config-search');
      const q = searchInput ? searchInput.value.toLowerCase() : '';
      const xs = files.filter((x) => `${x.title} ${x.category} ${x.path}`.toLowerCase().includes(q)).slice(0, 18);
      picker.innerHTML =
        xs
          .map(
            (x) =>
              `<button type="button" data-file="${esc(x.path)}" class="choice group flex w-full items-center gap-4 border-b border-zinc-800 py-4 text-left"><span class="min-w-0 flex-1"><span class="block truncate font-semibold text-zinc-50">${esc(x.title)}</span><span class="mt-0.5 block truncate text-sm text-zinc-500">${esc(x.category)} · ${esc(String(x.format).toUpperCase())} · ${esc(x.size_kb)} KB</span></span><span class="link shrink-0 text-sm group-hover:underline">Abrir</span></button>`
          )
          .join('') || '<p class="py-6 text-zinc-500">No encontramos ningún archivo con ese nombre.</p>';
    }

    // load(path): fetching /api/configs/... and setting up tree or raw view in #config-workspace
    async function load(path) {
      try {
        current = await Panel.api('/api/configs/' + encodeURIComponent(path).replaceAll('%2F', '/'));
        const nameEl = $('#selected-config-name');
        const helpEl = $('#selected-config-help');
        const formEl = $('#config-form');
        const codeEl = $('#config-code');
        const workspaceEl = $('#config-workspace');

        if (nameEl) nameEl.textContent = current.path;
        if (helpEl) {
          helpEl.textContent =
            current.format === 'toml'
              ? 'Cada cambio se guarda al momento y respeta los comentarios del archivo.'
              : 'Este tipo de archivo se cambia editándolo como texto, en Opciones avanzadas.';
        }
        if (formEl) {
          formEl.innerHTML =
            current.format === 'toml'
              ? node(current.tree)
              : '<p class="py-4 text-zinc-400">Abrí «Opciones avanzadas» más abajo para editar este archivo como texto.</p>';
        }
        if (codeEl) codeEl.value = current.raw_content;
        if (workspaceEl) workspaceEl.classList.remove('hidden');
      } catch (e) {
        Panel.toast(e.message, 'error');
      }
    }

    // Config search input & picker click delegation
    const configSearch = $('#config-search');
    if (configSearch) {
      configSearch.oninput = showFiles;
    }

    const configPicker = $('#config-picker');
    if (configPicker) {
      configPicker.onclick = (e) => {
        const b = e.target.closest('.choice');
        if (b && b.dataset.file) load(b.dataset.file);
      };
    }

    // Close workspace on #close-config
    const closeConfigBtn = $('#close-config');
    if (closeConfigBtn) {
      closeConfigBtn.onclick = () => {
        const workspaceEl = $('#config-workspace');
        if (workspaceEl) workspaceEl.classList.add('hidden');
      };
    }

    // Form change handler on #config-form saving changes to /api/configs/...
    const configForm = $('#config-form');
    if (configForm) {
      configForm.onchange = async (e) => {
        const x = e.target;
        if (!x || !x.dataset.path || !current) return;
        try {
          current = await Panel.api('/api/configs/' + encodeURIComponent(current.path).replaceAll('%2F', '/'), {
            method: 'POST',
            body: { changes: { [x.dataset.path]: x.type === 'checkbox' ? x.checked : Number(x.value) } },
          });
          const codeEl = $('#config-code');
          if (codeEl) codeEl.value = current.raw_content;
          Panel.toast('Cambio guardado.');
        } catch (err) {
          Panel.toast(err.message, 'error');
        }
      };
    }

    // Raw editor save on #save-config
    const saveConfigBtn = $('#save-config');
    if (saveConfigBtn) {
      saveConfigBtn.onclick = async () => {
        if (!current) return;
        try {
          const codeEl = $('#config-code');
          current = await Panel.api('/api/configs/' + encodeURIComponent(current.path).replaceAll('%2F', '/'), {
            method: 'POST',
            body: { content: codeEl ? codeEl.value : '' },
          });
          Panel.toast('Archivo revisado y guardado.');
        } catch (e) {
          Panel.toast(e.message, 'error');
        }
      };
    }

    // Gamerules and players: world() querying /api/gamerules and /api/players, populating #gamerules-list and #players-list
    async function world() {
      try {
        const [r, p] = await Promise.all([Panel.api('/api/gamerules'), Panel.api('/api/players')]);
        const gamerulesEl = $('#gamerules-list');
        if (gamerulesEl && Array.isArray(r)) {
          gamerulesEl.innerHTML = r
            .map(
              (x) =>
                `<label class="flex cursor-pointer items-center justify-between gap-4 ${ROW}"><span class="min-w-0"><span class="block font-medium text-zinc-100">${esc(ruleLabel(x.name))}</span><span class="mt-0.5 block truncate font-mono text-xs text-zinc-500">${esc(x.name)}</span></span>${x.kind === 'boolean' ? switchControl(`data-rule="${esc(x.name)}"`, x.value === 'true') : `<input data-rule="${esc(x.name)}" type="number" value="${esc(x.value)}" aria-label="${esc(ruleLabel(x.name))}" class="${NUMBER_INPUT}">`}</label>`
            )
            .join('') || '<p class="py-6 text-zinc-500">No hay reglas del juego para mostrar.</p>';
        }

        const playersEl = $('#players-list');
        if (playersEl && Array.isArray(p)) {
          playersEl.innerHTML =
            p
              .map(
                (x) =>
                  `<div class="flex flex-wrap items-center gap-x-4 gap-y-2 ${ROW}"><div class="min-w-0 flex-1"><p class="truncate font-semibold text-zinc-50">${esc(x.username)}</p><p class="mt-0.5 text-sm text-zinc-500">${x.is_op ? 'Administrador' : x.is_whitelisted ? 'Invitado' : x.is_banned ? 'Bloqueado' : 'Entró alguna vez'}</p></div><div class="flex shrink-0 items-center gap-1"><button type="button" data-action="spawn" data-player="${esc(x.username)}" class="rounded-lg px-2 py-1.5 text-sm text-zinc-500 hover:bg-zinc-800 hover:text-zinc-100">Mandar al inicio</button><button type="button" data-action="${x.is_op ? 'deop' : 'op'}" data-player="${esc(x.username)}" class="v2-button btn-quiet min-h-0 py-1.5 text-sm">${x.is_op ? 'Quitar admin' : 'Hacer admin'}</button></div></div>`
              )
              .join('') || '<p class="py-6 text-zinc-500">Todavía no entró nadie.</p>';
        }
      } catch (err) {
        Panel.toast(err.message, 'error');
      }
    }

    // Change handler on #gamerules-list saving gamerules
    const gamerulesList = $('#gamerules-list');
    if (gamerulesList) {
      gamerulesList.onchange = async (e) => {
        const x = e.target;
        if (!x || !x.dataset.rule) return;
        try {
          await Panel.api(`/api/gamerules/${x.dataset.rule}?value=${x.type === 'checkbox' ? x.checked : x.value}`, {
            method: 'POST',
          });
          Panel.toast('Regla aplicada.');
        } catch (err) {
          Panel.toast(err.message, 'error');
          world();
        }
      };
    }

    // Click handler on #players-list dispatching actions (spawn, op, deop)
    const playersList = $('#players-list');
    if (playersList) {
      playersList.onclick = async (e) => {
        const b = e.target.closest('[data-action]');
        if (b && b.dataset.action && b.dataset.player) {
          try {
            await Panel.api('/api/players/' + b.dataset.action, {
              method: 'POST',
              body: { username: b.dataset.player },
            });
            Panel.toast('Acción enviada.');
          } catch (err) {
            Panel.toast(err.message, 'error');
          }
        }
      };
    }

    // #spark-audit click handler calling /api/spark/audit
    const sparkAuditBtn = $('#spark-audit');
    if (sparkAuditBtn) {
      sparkAuditBtn.onclick = async () => {
        try {
          const r = await Panel.api('/api/spark/audit', { method: 'POST' });
          Panel.toast(r.message);
        } catch (e) {
          Panel.toast(e.message, 'error');
        }
      };
    }

    // #save-schedule click handler saving /api/scheduler/backup/{hours}
    const saveScheduleBtn = $('#save-schedule');
    if (saveScheduleBtn) {
      saveScheduleBtn.onclick = async () => {
        try {
          const hoursInput = $('#backup-hours');
          const hours = hoursInput ? hoursInput.value : '6';
          await Panel.api('/api/scheduler/backup/' + hours, { method: 'POST' });
          const statusEl = $('#schedule-status');
          if (statusEl) statusEl.textContent = 'Copias automáticas encendidas.';
          Panel.toast('Listo: las copias se hacen solas.');
        } catch (e) {
          Panel.toast(e.message, 'error');
        }
      };
    }

    // Global exports for coordination or external calls
    window.loadConfigsFiles = async () => {
      try {
        files = await Panel.api('/api/configs');
        showFiles();
        return files;
      } catch (e) {
        Panel.toast(e.message, 'error');
      }
    };
    window.showFiles = showFiles;
    window.loadConfigFile = load;
    window.world = world;

    // Automatic initial load when DOM elements are present
    (async () => {
      try {
        if ($('#config-picker')) {
          await window.loadConfigsFiles();
        }
        if ($('#gamerules-list') || $('#players-list')) {
          await world();
        }
      } catch (e) {
        Panel.toast(e.message, 'error');
      }
    })();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAdminConfigs);
  } else {
    initAdminConfigs();
  }
})();
