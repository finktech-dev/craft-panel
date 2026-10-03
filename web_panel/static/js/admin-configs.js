/**
 * Editor de Configuraciones TOML/JSON, Reglas del Mundo, Moderación de Jugadores,
 * Auditoría Spark y Programador de Backups para el Panel de Administración.
 */
(() => {
  const initAdminConfigs = () => {
    // Helpers
    const $ = (s) => document.querySelector(s);
    const esc = (s) => (window.Panel && window.Panel.escapeHtml) ? window.Panel.escapeHtml(s) : String(s);
    const label = (s) => String(s).replaceAll('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase());

    // State
    let files = [];
    let current;

    // Configs tree renderer: node(n) handling 'section', 'boolean', 'number', 'list', etc.
    const node = (n) =>
      n.type === 'section'
        ? `<details class="rounded-lg border border-zinc-800 bg-zinc-950/40 p-3" open><summary class="cursor-pointer text-sm font-semibold">${esc(label(n.key))}</summary><div class="mt-3 space-y-3">${n.children.map(node).join('')}</div></details>`
        : n.type === 'boolean'
        ? `<label class="flex justify-between gap-4 rounded-lg border border-zinc-800 bg-zinc-950/40 p-3"><span><b class="text-sm">${esc(label(n.key))}</b><small class="mt-1 block text-zinc-500">${esc(n.comment || 'Activar o desactivar')}</small></span><input data-path="${esc(n.path)}" type="checkbox" ${n.value ? 'checked' : ''} class="h-5 w-5 accent-emerald-400"></label>`
        : n.type === 'number'
        ? `<label class="block rounded-lg border border-zinc-800 bg-zinc-950/40 p-3"><b class="text-sm">${esc(label(n.key))}</b><small class="mt-1 block text-zinc-500">${esc(n.comment || '')}</small><input data-path="${esc(n.path)}" type="number" value="${n.value}" ${n.minimum !== null ? `min="${n.minimum}"` : ''} ${n.maximum !== null ? `max="${n.maximum}"` : ''} class="mt-2 min-h-10 w-full rounded bg-zinc-900 px-3"></label>`
        : `<div class="rounded-lg border border-zinc-800 bg-zinc-950/40 p-3"><b class="text-sm">${esc(label(n.key))}</b><small class="mt-1 block text-zinc-500">${n.type === 'list' ? 'Editalo en modo avanzado.' : esc(n.comment || '')}</small></div>`;

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
              `<button data-file="${esc(x.path)}" class="choice rounded-lg border border-zinc-800 bg-zinc-950/40 p-3 text-left hover:border-emerald-400/60"><small class="block text-emerald-300">${esc(x.category)}</small><b class="mt-1 block truncate text-sm">${esc(x.title)}</b><small class="mt-1 block text-zinc-500">${x.format.toUpperCase()} · ${x.size_kb} KB</small></button>`
          )
          .join('') || '<p class="text-sm text-zinc-500">No encontré ese mod.</p>';
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
              ? 'Usá los controles: se conserva el formato y los comentarios.'
              : 'Abrí modo avanzado para no alterar este formato.';
        }
        if (formEl) {
          formEl.innerHTML =
            current.format === 'toml'
              ? node(current.tree)
              : '<p class="rounded bg-amber-400/10 p-3 text-sm text-amber-100">Este archivo se edita desde modo avanzado.</p>';
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
          Panel.toast('Configuración validada y guardada.');
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
                `<label class="flex justify-between rounded-lg border border-zinc-800 bg-zinc-950/40 p-3"><span><b class="text-sm">${esc(x.name)}</b><small class="mt-1 block text-zinc-500">${x.kind === 'boolean' ? 'Activar o desactivar' : 'Valor numérico'}</small></span>${x.kind === 'boolean' ? `<input data-rule="${x.name}" type="checkbox" ${x.value === 'true' ? 'checked' : ''} class="h-5 w-5 accent-emerald-400">` : `<input data-rule="${x.name}" type="number" value="${x.value}" class="w-20 rounded bg-zinc-900 p-2">`}</label>`
            )
            .join('');
        }

        const playersEl = $('#players-list');
        if (playersEl && Array.isArray(p)) {
          playersEl.innerHTML =
            p
              .map(
                (x) =>
                  `<div class="flex justify-between rounded-lg border border-zinc-800 bg-zinc-950/40 p-3"><span><b class="text-sm">${esc(x.username)}</b><small class="mt-1 block text-zinc-500">${x.is_op ? 'Operador' : x.is_whitelisted ? 'En whitelist' : x.is_banned ? 'Baneado' : 'Registrado'}</small></span><div><button data-action="spawn" data-player="${x.username}" class="text-xs text-emerald-200">Spawn</button><button data-action="${x.is_op ? 'deop' : 'op'}" data-player="${x.username}" class="ml-3 text-xs text-zinc-300">${x.is_op ? 'Quitar OP' : 'Dar OP'}</button></div></div>`
              )
              .join('') || '<p class="text-sm text-zinc-500">Aún no hay jugadores registrados.</p>';
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
          if (statusEl) statusEl.textContent = 'Copias automáticas activadas.';
          Panel.toast('Programación guardada.');
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
