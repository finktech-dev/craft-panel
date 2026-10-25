document.addEventListener('DOMContentLoaded', () => {
  const $ = (s) => document.querySelector(s);
  const esc = Panel.escapeHtml;

  let allLoadedEvents = [];
  let selectedEvent = null;

  const playerSelect = $('#filter-player');
  const categorySelect = $('#filter-category');
  const searchInput = $('#filter-search');
  const filterErrorsOnly = $('#filter-errors-only');
  const filterCounter = $('#filter-counter');
  const crashesList = $('#crashes-list');
  const emptyTemplate = $('#crashes-empty-template');

  const logModal = $('#modal-log-viewer');
  const closeLogViewer = $('#close-log-viewer');
  if (closeLogViewer) {
    closeLogViewer.onclick = () => logModal.close();
  }
  if (logModal) {
    logModal.onclick = (e) => {
      if (e.target === logModal) logModal.close();
    };
  }

  const isCriticalEvent = (evt) =>
    evt.category === 'MOD_ERROR' ||
    evt.category === 'INVALID_DATA' ||
    evt.category === 'SERVER_CRASH' ||
    evt.severity === 'error';

  // Short, plain label for each category (also used in the copied report).
  const getBadgeData = (evt) => {
    switch (evt.category) {
      case 'NORMAL_DISCONNECT': return { label: 'Salida normal' };
      case 'TIMEOUT': return { label: 'Se cortó la conexión' };
      case 'KICKED_BANNED': return { label: 'Lo sacaron del servidor' };
      case 'KICKED': return { label: 'Lo expulsaron' };
      case 'BANNED': return { label: 'Está bloqueado' };
      case 'NOT_WHITELISTED': return { label: 'No está en la lista de amigos' };
      case 'CLIENT_CLOSED': return { label: 'Su juego se cerró de golpe' };
      case 'MOD_ERROR': return { label: 'Problema con un mod' };
      case 'INVALID_DATA': return { label: 'Datos dañados' };
      case 'CLIENT_MISMATCH': return { label: 'Juego distinto al del servidor' };
      case 'SERVER_CRASH': return { label: 'El servidor se cerró' };
      default: return { label: evt.category_label || 'Desconexión' };
    }
  };

  // Plain-language explanation shown first; the raw report stays behind "Ver el detalle técnico".
  const explain = (evt) => {
    // Newer events come with the explanation already written by the server.
    if (evt.headline) return { headline: evt.headline, advice: evt.advice || 'Todo normal, no tenés que hacer nada.' };
    const player = evt.player || 'Un jugador';
    const mod = evt.suspected_mod;
    switch (evt.category) {
      case 'NORMAL_DISCONNECT':
        return {
          headline: `${player} salió del juego.`,
          advice: 'Todo normal, no tenés que hacer nada.',
        };
      case 'TIMEOUT':
        return {
          headline: `${player} se desconectó porque la conexión se cortó o andaba muy lenta.`,
          advice: 'Suele ser el internet de quien juega o el de tu casa. Si pasa seguido, revisá la conexión o probá con menos mods pesados.',
        };
      case 'KICKED_BANNED':
        return {
          headline: `${player} fue sacado del servidor.`,
          advice: 'Pasa si no está en la lista de jugadores permitidos o si alguien lo expulsó. Podés revisarlo en Jugadores.',
        };
      case 'INVALID_DATA':
        return {
          headline: `${player} se desconectó porque sus datos de jugador están dañados.`,
          advice: 'Puede ser un objeto con error en su inventario. Antes de tocar nada, hacé una copia del mundo.',
        };
      case 'CLIENT_MISMATCH':
        return {
          headline: `${player} no pudo jugar porque su juego no coincide con el del servidor.`,
          advice: 'Necesita la misma versión de Minecraft y los mismos mods. Pasale el paquete para amigos desde la página Mods.',
        };
      case 'MOD_ERROR':
        return {
          headline: mod
            ? `${player} se desconectó por un problema con el mod ${mod}.`
            : `${player} se desconectó por un problema con un mod.`,
          advice: 'Fijate en la página Mods si hay una actualización. Si sigue pasando, probá apagar ese mod.',
        };
      case 'SERVER_CRASH':
        return {
          headline: mod
            ? `El servidor se cerró por un problema con el mod ${mod}.`
            : `El servidor se cerró de golpe mientras ${player} jugaba.`,
          advice: 'Volvé a encenderlo desde el inicio. Si se repite, buscá una actualización del mod o apagalo un rato.',
        };
      default:
        return {
          headline: `${player} se desconectó por un motivo poco común.`,
          advice: 'Mirá el detalle técnico para saber más.',
        };
    }
  };

  const markClass = (evt) => {
    if (evt.category === 'NORMAL_DISCONNECT') return '';
    return isCriticalEvent(evt) ? 'state-error' : 'state-busy';
  };

  // "22 de septiembre a las 20:00"; falls back to the raw log time.
  const formatWhen = (evt) => {
    const date = evt.occurred_at ? new Date(evt.occurred_at) : null;
    if (!date || Number.isNaN(date.getTime())) return evt.timestamp;
    const today = new Date();
    const time = date.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' });
    if (date.toDateString() === today.toDateString()) return `hoy a las ${time}`;
    const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
    if (date.toDateString() === yesterday.toDateString()) return `ayer a las ${time}`;
    return `el ${date.toLocaleDateString('es-AR', { day: 'numeric', month: 'long' })} a las ${time}`;
  };

  const formatSession = (seconds) => {
    if (!Number.isFinite(seconds)) return '';
    const minutes = Math.round(seconds / 60);
    if (minutes < 1) return 'Estuvo menos de un minuto';
    if (minutes < 60) return `Estuvo ${minutes} min`;
    const hours = Math.floor(minutes / 60);
    return `Estuvo ${hours} h ${minutes % 60} min`;
  };

  // Short facts about the session: how long, where they joined, lag.
  const sessionFacts = (evt) => [
    formatSession(evt.session_seconds),
    evt.joined_at ? `entró en ${evt.joined_at}` : '',
    evt.lag_warnings ? `${evt.lag_warnings} ${evt.lag_warnings === 1 ? 'aviso' : 'avisos'} de lag antes de irse` : '',
  ].filter(Boolean).join(' · ');

  const TIMELINE_STYLE = {
    join: 'text-zinc-200', leave: 'text-zinc-100 font-semibold', chat: 'text-zinc-300', command: 'text-zinc-300',
    admin: 'text-zinc-300', advancement: 'text-emerald-300', death: 'text-[#e8b04b]', lag: 'text-[#e8b04b]',
    error: 'text-[#f3a79b]', kick: 'text-[#f3a79b]',
  };
  const timelineHtml = (evt) => {
    const items = Array.isArray(evt.timeline) ? evt.timeline : [];
    if (!items.length) return '';
    return `<ol class="space-y-1.5">${items.map((entry) => `
      <li class="flex gap-3"><span class="w-16 shrink-0 font-mono text-xs leading-6 text-zinc-500">${esc(entry.time || '')}</span><span class="min-w-0 break-words leading-6 ${TIMELINE_STYLE[entry.kind] || 'text-zinc-300'}">${esc(entry.text)}</span></li>`).join('')}</ol>`;
  };

  const renderEmpty = (title, text) => {
    if (emptyTemplate && emptyTemplate.content) {
      const node = emptyTemplate.content.cloneNode(true);
      node.querySelector('[data-empty-title]').textContent = title;
      node.querySelector('[data-empty-text]').textContent = text;
      crashesList.replaceChildren(node);
      return;
    }
    crashesList.innerHTML = `<p class="py-12 text-center text-zinc-500">${esc(text)}</p>`;
  };

  // One row per event: plain sentence first, technical detail collapsed.
  const renderEvents = (events) => {
    if (!events.length) {
      if (allLoadedEvents.length) {
        renderEmpty('Nada para mostrar', 'Ningún evento coincide con lo que elegiste. Probá cambiar los filtros.');
      } else {
        renderEmpty('Todo tranquilo', 'No encontramos problemas. Si algo falla, va a aparecer acá.');
      }
      return;
    }

    crashesList.innerHTML = events.map((evt) => {
      const info = explain(evt);
      const label = getBadgeData(evt).label;
      const suggestion = evt.suggestion && evt.suggestion !== info.advice
        ? `<p class="mt-2 text-zinc-400">${esc(evt.suggestion)}</p>`
        : '';
      const facts = sessionFacts(evt);
      const timeline = timelineHtml(evt);
      const suspectedMod = evt.suspected_mod
        ? `<p class="mt-2 text-zinc-500">Mod que pudo causarlo: <span class="font-mono text-zinc-300">${esc(evt.suspected_mod)}</span></p>`
        : '';

      return `
        <article class="flex items-start gap-4 border-b border-zinc-800 py-4">
          <img src="${esc(evt.avatar_url)}" alt="" class="h-10 w-10 shrink-0 rounded-lg bg-zinc-800 object-cover" data-fallback-src="https://mc-heads.net/avatar/MHF_Steve/64">
          <div class="min-w-0 flex-1">
            <h3 class="font-semibold text-zinc-50">${esc(info.headline)}</h3>
            <p class="mt-0.5 flex flex-wrap items-center gap-x-2 text-sm text-zinc-500">
              <span class="${markClass(evt)} inline-flex items-center gap-2"><span class="state-mark" aria-hidden="true"></span>${esc(label)}</span>
              <span aria-hidden="true">·</span>
              <span>${esc(formatWhen(evt))}</span>
            </p>
            <p class="mt-1.5 leading-relaxed text-zinc-400">${esc(info.advice)}</p>
            ${facts ? `<p class="mt-1 text-sm text-zinc-500">${esc(facts)}</p>` : ''}
            ${timeline ? `<details class="mt-2 text-sm" ${evt.category === 'NORMAL_DISCONNECT' ? '' : 'open'}>
              <summary class="cursor-pointer text-zinc-400 hover:text-zinc-200">Qué estaba pasando</summary>
              <div class="mt-3 rounded-lg bg-zinc-900 p-3">${timeline}</div>
            </details>` : ''}
            <details class="mt-2 text-sm">
              <summary class="cursor-pointer text-zinc-400 hover:text-zinc-200">Ver el detalle técnico</summary>
              <div class="mt-3 rounded-lg bg-zinc-900 p-3">
                <p class="break-words font-mono text-xs text-zinc-300">${esc(evt.summary)}</p>
                ${suggestion}
                ${suspectedMod}
                <p class="mt-2 text-zinc-500">Archivo: <span class="font-mono">${esc(evt.file_source)}</span></p>
                <button type="button" data-view-event="${esc(evt.id)}" class="link mt-2">Ver el registro completo</button>
              </div>
            </details>
          </div>
        </article>
      `;
    }).join('');
  };

  // Applies the "hide normal exits" toggle and renders the list.
  const applyFiltersAndRender = () => {
    let filtered = allLoadedEvents;
    const errorsOnly = filterErrorsOnly && filterErrorsOnly.checked;

    if (errorsOnly) {
      filtered = filtered.filter((evt) => evt.category !== 'NORMAL_DISCONNECT');
    }

    if (filterCounter) {
      if (errorsOnly) {
        const hiddenCount = allLoadedEvents.length - filtered.length;
        filterCounter.textContent = `Se ven ${filtered.length} · ocultaste ${hiddenCount} salidas normales`;
      } else {
        filterCounter.textContent = `Se ven ${filtered.length}`;
      }
    }

    renderEvents(filtered);
  };

  // Loads events from the API.
  // The console links here as /crashes?player=Name; it applies until the list of players is filled in.
  let requestedPlayer = new URLSearchParams(window.location.search).get('player') || '';

  const loadEvents = async () => {
    const p = (playerSelect ? playerSelect.value : '') || requestedPlayer;
    const c = categorySelect ? categorySelect.value : '';
    const q = searchInput ? searchInput.value.trim() : '';

    const query = new URLSearchParams();
    if (p) query.set('player', p);
    if (c) query.set('category', c);
    if (q) query.set('search', q);

    try {
      const data = await Panel.api(`/api/player-crashes?${query.toString()}`);
      $('#stat-total').textContent = data.total_events;
      $('#stat-critical').textContent = data.critical_count;
      $('#stat-players').textContent = data.players_count;

      const normalCount = (data.events || []).filter((evt) => evt.category === 'NORMAL_DISCONNECT').length;
      const statNormal = $('#stat-normal');
      if (statNormal) {
        statNormal.textContent = normalCount;
      }

      if (playerSelect && playerSelect.options.length <= 1) {
        data.unique_players.forEach((name) => {
          const opt = document.createElement('option');
          opt.value = name;
          opt.textContent = name;
          playerSelect.append(opt);
        });
      }
      if (playerSelect && requestedPlayer) {
        if (![...playerSelect.options].some((option) => option.value === requestedPlayer)) {
          const opt = document.createElement('option');
          opt.value = requestedPlayer;
          opt.textContent = requestedPlayer;
          playerSelect.append(opt);
        }
        playerSelect.value = requestedPlayer;
        requestedPlayer = '';
      }

      if (categorySelect && categorySelect.options.length <= 1) {
        data.categories.forEach((cat) => {
          const opt = document.createElement('option');
          opt.value = cat.key;
          opt.textContent = getBadgeData({ category: cat.key, category_label: cat.label }).label;
          categorySelect.append(opt);
        });
      }

      allLoadedEvents = data.events || [];
      applyFiltersAndRender();
    } catch (e) {
      crashesList.innerHTML = `<p class="py-12 text-center text-[#f3a79b]">No pudimos cargar la lista. ${esc(e.message)}</p>`;
    }
  };

  if (playerSelect) {
    playerSelect.onchange = loadEvents;
  }

  if (categorySelect) {
    categorySelect.onchange = () => {
      // Picking "normal exit" explicitly turns off the "hide normal exits" toggle.
      if (categorySelect.value === 'NORMAL_DISCONNECT' && filterErrorsOnly && filterErrorsOnly.checked) {
        filterErrorsOnly.checked = false;
      }
      loadEvents();
    };
  }

  if (filterErrorsOnly) {
    filterErrorsOnly.onchange = () => {
      // Hiding normal exits resets a "normal exit" category filter.
      if (filterErrorsOnly.checked && categorySelect && categorySelect.value === 'NORMAL_DISCONNECT') {
        categorySelect.value = '';
      }
      applyFiltersAndRender();
    };
  }

  let searchTimer;
  if (searchInput) {
    searchInput.oninput = () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(loadEvents, 300);
    };
  }

  // Incremental scan of the server logs.
  const btnScanLogs = $('#btn-scan-logs');
  if (btnScanLogs) {
    btnScanLogs.onclick = async () => {
      btnScanLogs.disabled = true;
      try {
        const res = await Panel.api('/api/player-crashes/scan', { method: 'POST' });
        Panel.toast(res.message, 'success');
        await loadEvents();
      } catch (err) {
        Panel.toast(err.message, 'error');
      } finally {
        btnScanLogs.disabled = false;
      }
    };
  }

  // Clear the stored history, then scan every log again.
  const btnRescanClean = $('#btn-rescan-clean');
  if (btnRescanClean) {
    btnRescanClean.onclick = async () => {
      if (!confirm('¿Borrar la lista de esta página y volver a revisar todos los registros desde cero?')) return;
      btnRescanClean.disabled = true;
      try {
        await Panel.api('/api/player-crashes', { method: 'DELETE' });
        const res = await Panel.api('/api/player-crashes/scan', { method: 'POST' });
        Panel.toast(`Listo, revisamos todo de nuevo. ${res.message || ''}`.trim(), 'success');
        await loadEvents();
      } catch (err) {
        Panel.toast(`No pudimos revisar todo de nuevo: ${err.message}`, 'error');
      } finally {
        btnRescanClean.disabled = false;
      }
    };
  }

  // Clear the stored history.
  const btnClearLogs = $('#btn-clear-logs');
  if (btnClearLogs) {
    btnClearLogs.onclick = async () => {
      if (!confirm('¿Borrar el historial de esta página? Los registros del servidor quedan guardados.')) return;
      try {
        await Panel.api('/api/player-crashes', { method: 'DELETE' });
        Panel.toast('Historial borrado.', 'success');
        await loadEvents();
      } catch (err) {
        Panel.toast(err.message, 'error');
      }
    };
  }

  // Full log viewer.
  crashesList.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-view-event]');
    if (!btn) return;
    const id = btn.dataset.viewEvent;
    const evt = allLoadedEvents.find((x) => x.id === id);
    if (!evt) return;

    selectedEvent = evt;
    $('#viewer-player-avatar').src = evt.avatar_url;
    $('#viewer-player-name').textContent = evt.player;
    $('#viewer-timestamp').textContent = formatWhen(evt);
    $('#viewer-source-file').textContent = `Archivo: ${evt.file_source}`;
    $('#viewer-category-badge').textContent = getBadgeData(evt).label;

    const info = explain(evt);
    $('#viewer-suggestion-title').textContent = info.headline;
    $('#viewer-suggestion-text').textContent = info.advice;
    $('#viewer-suggestion-box').classList.remove('hidden');
    const facts = sessionFacts(evt);
    const timelineBox = $('#viewer-timeline');
    if (timelineBox) {
      timelineBox.innerHTML = (facts ? `<p class="mb-3 text-sm text-zinc-500">${esc(facts)}</p>` : '') + timelineHtml(evt);
      $('#viewer-timeline-box')?.classList.toggle('hidden', !timelineBox.innerHTML);
    }

    // Colour error, warning and disconnect lines; everything is escaped first.
    const logContent = $('#viewer-log-content');
    logContent.innerHTML = evt.context_lines.map((line) => {
      const escapedLine = esc(line);
      if (line.includes('ERROR') || line.includes('FATAL') || line.includes('Exception')) {
        return `<span class="text-[#f3a79b]">${escapedLine}</span>`;
      }
      if (line.includes('WARN')) {
        return `<span class="text-[#e8b04b]">${escapedLine}</span>`;
      }
      if (line.includes('lost connection') || line.includes('left the game')) {
        return `<span class="text-zinc-100">${escapedLine}</span>`;
      }
      return escapedLine;
    }).join('\n');

    logModal.showModal();
  });

  // Copy the full report to the clipboard.
  const btnCopyLog = $('#btn-copy-log');
  if (btnCopyLog) {
    btnCopyLog.onclick = async () => {
      if (!selectedEvent) return;
      const b = getBadgeData(selectedEvent);
      const fullTrace = [
        `=== DIAGNÓSTICO DE DESCONEXIÓN / CRASH ===`,
        `Jugador: ${selectedEvent.player}`,
        `Fecha: ${selectedEvent.timestamp}`,
        `Tipo: ${b.label} [${selectedEvent.category}]`,
        `Motivo: ${selectedEvent.summary}`,
        `Mod sospechoso: ${selectedEvent.suspected_mod || 'Ninguno identificado'}`,
        `Archivo fuente: ${selectedEvent.file_source}`,
        sessionFacts(selectedEvent) ? `Sesión: ${sessionFacts(selectedEvent)}` : '',
        (selectedEvent.timeline || []).length ? `\n=== QUÉ ESTABA PASANDO ===\n${selectedEvent.timeline.map((entry) => `${entry.time || ''} ${entry.text}`.trim()).join('\n')}` : '',
        `\n=== EXTRACTO DE LOG Y TRAZA ===`,
        selectedEvent.context_lines.join('\n'),
      ].join('\n');

      try {
        await navigator.clipboard.writeText(fullTrace);
        Panel.toast('Copiado. Ya lo podés pegar donde pidas ayuda.', 'success');
      } catch {
        Panel.toast('No pudimos copiar. Probá de nuevo.', 'error');
      }
    };
  }

  loadEvents();
});
