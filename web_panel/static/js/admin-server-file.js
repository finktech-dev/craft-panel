// "Tu servidor" in Ajustes: edit server/craftpanel.txt as plain fields or as the whole text file.
(() => {
  const ENDPOINT = '/api/server/settings-file';

  const start = () => {
    const section = document.querySelector('#server-file');
    if (!section) return;
    const $ = (selector) => section.querySelector(selector);
    const all = (selector) => Array.from(section.querySelectorAll(selector));

    const form = $('#server-file-form');
    const stateText = $('#server-file-state');
    const formError = $('#server-file-error');
    const rawArea = $('#server-file-raw');
    const rawError = $('#server-file-raw-error');
    const problemsBox = $('#server-file-problems');
    const problemList = $('#server-file-problem-list');
    const runningNote = $('#server-file-running-note');

    // What the file held when it was loaded, to send only what the person changed.
    let loaded = { values: {}, defaults: {}, lists: {} };

    const show = (element, visible) => { if (element) element.classList.toggle('hidden', !visible); };
    const setText = (element, value) => { if (element) element.textContent = value; };
    const linesOf = (text) => String(text || '').split(/\r?\n/).map((line) => line.trim()).filter(Boolean);

    const clearErrors = () => {
      all('[data-error-for]').forEach((node) => { node.textContent = ''; show(node, false); });
      setText(formError, ''); show(formError, false);
      setText(rawError, ''); show(rawError, false);
    };

    // A PUT that keeps the error details (field and line) so they can be shown next to each field.
    const put = async (path, body) => {
      const response = await fetch(path, {
        method: 'PUT',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      let data = null;
      try { data = await response.json(); } catch { data = null; }
      if (response.status === 401) { window.location.assign('/'); throw new Error('La sesión expiró.'); }
      if (!response.ok) {
        const detail = data && data.detail;
        const error = new Error(
          (detail && typeof detail === 'object' && detail.message) || (typeof detail === 'string' && detail) || `No se pudo guardar (${response.status}).`,
        );
        error.errors = detail && Array.isArray(detail.errors) ? detail.errors : [];
        throw error;
      }
      return data;
    };

    const render = (info) => {
      loaded = { values: { ...info.values }, defaults: { ...info.defaults }, lists: {} };
      Object.entries(info.lists || {}).forEach(([name, items]) => { loaded.lists[name] = items.join('\n'); });

      all('[data-file-key]').forEach((input) => {
        const key = input.dataset.fileKey;
        const value = info.values[key] ?? '';
        if (input.dataset.fileBool) {
          input.checked = String(value || info.defaults[key] || '').toLowerCase() === 'true';
        } else {
          input.value = value;
        }
        // start_script and java are read when the server starts, so they wait until it is off.
        input.disabled = Boolean(info.server_running && (info.stopped_only || []).includes(key));
      });
      all('[data-file-list]').forEach((area) => { area.value = loaded.lists[area.dataset.fileList] || ''; });
      if (rawArea) rawArea.value = info.raw || '';

      setText(stateText, info.exists
        ? 'Leído de craftpanel.txt.'
        : 'Todavía no hay archivo: se crea en la carpeta del servidor cuando toques Guardar.');
      show(runningNote, Boolean(info.server_running));

      const problems = info.problems || [];
      if (problemList) {
        problemList.replaceChildren(...problems.map((problem) => Object.assign(document.createElement('li'), {
          textContent: problem.line ? `Línea ${problem.line}: ${problem.message}` : problem.message,
        })));
      }
      show(problemsBox, problems.length > 0);
    };

    const load = async () => {
      try {
        render(await Panel.api(ENDPOINT));
      } catch (issue) {
        setText(stateText, `No pudimos leer los ajustes: ${issue.message}`);
      }
    };

    // Each group is its own sub-screen; bring the first one with a problem into view.
    const revealGroupOf = (node) => {
      const group = node.closest('[data-subpanel-key]');
      if (group && group.hidden && window.AdminTabs) {
        window.AdminTabs.openSub(group.dataset.subpanel, group.dataset.subpanelKey);
        try { history.replaceState(null, '', `#${group.dataset.subpanel}/${group.dataset.subpanelKey}`); } catch { /* ignore */ }
      }
    };

    const showErrors = (issue) => {
      let placed = null;
      (issue.errors || []).forEach((problem) => {
        const target = problem.field && section.querySelector(`[data-error-for="${CSS.escape(problem.field)}"]`);
        if (target) {
          target.textContent = [target.textContent, problem.message].filter(Boolean).join('\n');
          show(target, true);
          placed = placed || target;
        }
      });
      if (placed) {
        revealGroupOf(placed);
      } else {
        setText(formError, issue.message);
        show(formError, true);
      }
    };

    const collectChanges = () => {
      const values = {};
      all('[data-file-key]').forEach((input) => {
        if (input.disabled) return;
        const key = input.dataset.fileKey;
        if (input.dataset.fileBool) {
          const value = input.checked ? 'true' : 'false';
          const before = String(loaded.values[key] || loaded.defaults[key] || 'false').toLowerCase();
          if (value !== before) values[key] = value;
          return;
        }
        const value = input.value.trim();
        if (value !== String(loaded.values[key] ?? '').trim()) values[key] = value;
      });
      const lists = {};
      all('[data-file-list]').forEach((area) => {
        const name = area.dataset.fileList;
        const items = linesOf(area.value);
        if (items.join('\n') !== linesOf(loaded.lists[name]).join('\n')) lists[name] = items;
      });
      return { values, lists };
    };

    form?.addEventListener('submit', async (event) => {
      event.preventDefault();
      clearErrors();
      const changes = collectChanges();
      if (!Object.keys(changes.values).length && !Object.keys(changes.lists).length) {
        Panel.toast('No hay cambios para guardar.');
        return;
      }
      // Every group has its own Guardar; all of them save the whole form.
      const buttons = all('[data-server-file-save]');
      buttons.forEach((button) => { button.disabled = true; });
      try {
        render(await put(ENDPOINT, changes));
        Panel.toast('Listo, se guardó en craftpanel.txt.');
      } catch (issue) {
        showErrors(issue);
      } finally {
        buttons.forEach((button) => { button.disabled = false; });
      }
    });

    $('#server-file-raw-save')?.addEventListener('click', async (event) => {
      clearErrors();
      const button = event.currentTarget;
      button.disabled = true;
      try {
        render(await put(`${ENDPOINT}/raw`, { raw: rawArea ? rawArea.value : '' }));
        Panel.toast('Listo, se guardó el archivo.');
      } catch (issue) {
        setText(rawError, issue.message);
        show(rawError, true);
      } finally {
        button.disabled = false;
      }
    });

    load();
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
