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

  // Generador de metadatos y badges visuales para cada categoría
  const getBadgeData = (evt) => {
    switch (evt.category) {
      case 'NORMAL_DISCONNECT':
        return {
          label: 'Salida Voluntaria',
          icon: '🚪',
          classes: 'bg-zinc-800/80 text-zinc-400 border border-zinc-700/50',
        };
      case 'TIMEOUT':
        return {
          label: 'Tiempo Agotado / Lag',
          icon: '⏳',
          classes: 'bg-violet-950/50 text-violet-300 border border-violet-700/50',
        };
      case 'KICKED_BANNED':
        return {
          label: 'Expulsión / Kick',
          icon: '🚫',
          classes: 'bg-sky-950/50 text-sky-300 border border-sky-700/50',
        };
      case 'MOD_ERROR':
        return {
          label: 'Fallo Crítico / Crash',
          icon: '💥',
          classes: 'bg-rose-950/60 text-rose-300 border border-rose-600/60 shadow-sm shadow-rose-900/30',
        };
      case 'INVALID_DATA':
        return {
          label: 'Fallo Crítico / Crash',
          icon: '💥',
          classes: 'bg-rose-950/60 text-rose-300 border border-rose-600/60 shadow-sm shadow-rose-900/30',
        };
      case 'CLIENT_MISMATCH':
        return {
          label: 'Cliente Incompatible',
          icon: '🔌',
          classes: 'bg-amber-950/50 text-amber-300 border border-amber-700/50',
        };
      case 'SERVER_CRASH':
        return {
          label: 'Fallo de Servidor',
          icon: '🔥',
          classes: 'bg-rose-950/70 text-rose-200 border border-rose-500',
        };
      default:
        return {
          label: evt.category_label || 'Desconexión',
          icon: 'ℹ️',
          classes: 'bg-zinc-800 text-zinc-300 border border-zinc-700/50',
        };
    }
  };

  const renderSeverityBadge = (evt) => {
    const b = getBadgeData(evt);
    return `<span class="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ${b.classes}"><span>${b.icon}</span><span>${esc(b.label)}</span></span>`;
  };

  // Renderizado dinámico de tarjetas de eventos
  const renderEvents = (events) => {
    if (!events.length) {
      crashesList.innerHTML = `
        <div class="rounded-xl border border-zinc-800 bg-zinc-900/40 p-12 text-center text-sm text-zinc-500">
          No se encontraron desconexiones o errores con los filtros aplicados.
        </div>
      `;
      return;
    }

    crashesList.innerHTML = events.map((evt) => {
      const isNormal = evt.category === 'NORMAL_DISCONNECT';
      const isCritical = evt.category === 'MOD_ERROR' || evt.category === 'INVALID_DATA' || evt.severity === 'error';
      const isTimeout = evt.category === 'TIMEOUT';
      const isKick = evt.category === 'KICKED_BANNED';

      let cardClasses = 'rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 sm:p-5 transition hover:border-zinc-700 space-y-3 opacity-90 hover:opacity-100';
      if (isCritical) {
        cardClasses = 'rounded-xl border border-rose-500/30 bg-rose-950/10 p-4 sm:p-5 transition hover:border-rose-500/60 space-y-3 border-l-4 border-l-rose-500 shadow-sm';
      } else if (isTimeout) {
        cardClasses = 'rounded-xl border border-violet-500/30 bg-violet-950/10 p-4 sm:p-5 transition hover:border-violet-500/60 space-y-3 border-l-4 border-l-violet-500';
      } else if (isKick) {
        cardClasses = 'rounded-xl border border-sky-500/30 bg-sky-950/10 p-4 sm:p-5 transition hover:border-sky-500/60 space-y-3 border-l-4 border-l-sky-500';
      } else if (!isNormal) {
        cardClasses = 'rounded-xl border border-amber-500/30 bg-amber-950/10 p-4 sm:p-5 transition hover:border-amber-500/60 space-y-3 border-l-4 border-l-amber-500';
      }

      return `
        <article class="${cardClasses}">
          <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div class="flex items-center gap-3">
              <img src="${evt.avatar_url}" alt="${esc(evt.player)}" class="h-10 w-10 rounded-lg border border-zinc-800 bg-zinc-950 object-cover shrink-0" onerror="this.src='https://mc-heads.net/avatar/MHF_Steve/64'">
              <div>
                <div class="flex items-center gap-2">
                  <span class="font-bold text-sm text-zinc-100">${esc(evt.player)}</span>
                  ${renderSeverityBadge(evt)}
                </div>
                <p class="text-xs text-zinc-400 mt-0.5">🕒 ${esc(evt.timestamp)} · <span class="font-mono text-[11px] text-zinc-500">${esc(evt.file_source)}</span></p>
              </div>
            </div>

            <button data-view-event="${esc(evt.id)}" class="rounded-lg bg-zinc-800 px-3.5 py-1.5 text-xs font-semibold text-zinc-200 hover:bg-zinc-700 hover:text-emerald-300 transition shrink-0 flex items-center gap-1">
              <span>Ver Log y Traza</span> <span>➔</span>
            </button>
          </div>

          <div class="rounded-lg border border-zinc-800/80 bg-zinc-950/60 px-3.5 py-2.5 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs">
            <div class="flex items-center gap-2 overflow-hidden text-ellipsis">
              <span class="text-zinc-500 font-semibold uppercase text-[10px] tracking-wider shrink-0">Motivo:</span>
              ${isNormal ? `
                <span class="text-zinc-300 font-medium flex items-center gap-1.5">
                  <span class="text-emerald-400/80">✔</span> El jugador se desconectó voluntariamente del servidor.
                  <span class="text-zinc-500 font-mono text-[11px]">(${esc(evt.summary)})</span>
                </span>
              ` : `
                <span class="text-zinc-200 font-mono">${esc(evt.summary)}</span>
              `}
            </div>
            ${evt.suspected_mod ? `
              <div class="inline-flex items-center gap-1.5 rounded-md bg-rose-500/20 border border-rose-500/40 px-2.5 py-1 text-xs font-bold text-rose-200 shadow-sm shrink-0">
                <span>📦 Mod sospechoso:</span>
                <span class="font-mono underline decoration-rose-400/50">${esc(evt.suspected_mod)}</span>
              </div>
            ` : ''}
          </div>
        </article>
      `;
    }).join('');
  };

  // Aplica filtro de sólo anomalías y renderiza la lista
  const applyFiltersAndRender = () => {
    let filtered = allLoadedEvents;
    const errorsOnly = filterErrorsOnly && filterErrorsOnly.checked;

    if (errorsOnly) {
      filtered = filtered.filter((evt) => evt.category !== 'NORMAL_DISCONNECT');
    }

    if (filterCounter) {
      if (errorsOnly) {
        const hiddenCount = allLoadedEvents.length - filtered.length;
        filterCounter.textContent = `Mostrando ${filtered.length} eventos anómalos (ocultas ${hiddenCount} salidas normales)`;
      } else {
        filterCounter.textContent = `Mostrando ${filtered.length} eventos`;
      }
    }

    renderEvents(filtered);
  };

  // Carga de eventos desde el endpoint
  const loadEvents = async () => {
    const p = playerSelect ? playerSelect.value : '';
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

      // Calcular salidas normales registradas
      const normalCount = (data.events || []).filter((evt) => evt.category === 'NORMAL_DISCONNECT').length;
      const statNormal = $('#stat-normal');
      if (statNormal) {
        statNormal.textContent = normalCount;
      }

      // Llenar selector de jugadores si está vacío
      if (playerSelect && playerSelect.options.length <= 1) {
        data.unique_players.forEach((name) => {
          const opt = document.createElement('option');
          opt.value = name;
          opt.textContent = name;
          playerSelect.append(opt);
        });
      }

      // Llenar selector de categorías si está vacío
      if (categorySelect && categorySelect.options.length <= 1) {
        data.categories.forEach((cat) => {
          const opt = document.createElement('option');
          opt.value = cat.key;
          opt.textContent = cat.label;
          categorySelect.append(opt);
        });
      }

      allLoadedEvents = data.events || [];
      applyFiltersAndRender();
    } catch (e) {
      crashesList.innerHTML = `<p class="text-sm text-rose-400">Error al cargar registros: ${esc(e.message)}</p>`;
    }
  };

  // Listeners de filtros
  if (playerSelect) {
    playerSelect.onchange = loadEvents;
  }

  if (categorySelect) {
    categorySelect.onchange = () => {
      // Si el usuario selecciona explícitamente "Desconexión Normal", desactivar el checkbox de solo errores
      if (categorySelect.value === 'NORMAL_DISCONNECT' && filterErrorsOnly && filterErrorsOnly.checked) {
        filterErrorsOnly.checked = false;
      }
      loadEvents();
    };
  }

  if (filterErrorsOnly) {
    filterErrorsOnly.onchange = () => {
      // Si se activa solo errores y la categoría era "NORMAL_DISCONNECT", resetearla
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

  // Escanear logs ahora (incremental)
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

  // Re-escanear historial limpio (limpiar + escanear)
  const btnRescanClean = $('#btn-rescan-clean');
  if (btnRescanClean) {
    btnRescanClean.onclick = async () => {
      if (!confirm('¿Deseás vaciar el historial actual y volver a escanear todos los logs desde cero?')) return;
      btnRescanClean.disabled = true;
      try {
        await Panel.api('/api/player-crashes', { method: 'DELETE' });
        const res = await Panel.api('/api/player-crashes/scan', { method: 'POST' });
        Panel.toast(`Historial reiniciado. ${res.message || 'Escaneo completado.'}`, 'success');
        await loadEvents();
      } catch (err) {
        Panel.toast(`Error en el re-escaneo: ${err.message}`, 'error');
      } finally {
        btnRescanClean.disabled = false;
      }
    };
  }

  // Limpiar historial
  const btnClearLogs = $('#btn-clear-logs');
  if (btnClearLogs) {
    btnClearLogs.onclick = async () => {
      if (!confirm('¿Deseás vaciar el historial de desconexiones guardadas? Los logs de Minecraft seguirán en disco.')) return;
      try {
        await Panel.api('/api/player-crashes', { method: 'DELETE' });
        Panel.toast('Historial limpiado.', 'success');
        await loadEvents();
      } catch (err) {
        Panel.toast(err.message, 'error');
      }
    };
  }

  // Modal Inspector de Log Completo
  crashesList.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-view-event]');
    if (!btn) return;
    const id = btn.dataset.viewEvent;
    const evt = allLoadedEvents.find((x) => x.id === id);
    if (!evt) return;

    selectedEvent = evt;
    $('#viewer-player-avatar').src = evt.avatar_url;
    $('#viewer-player-name').textContent = evt.player;
    $('#viewer-timestamp').textContent = `${evt.timestamp} · Archivo: ${evt.file_source}`;
    $('#viewer-source-file').textContent = `Origen: ${evt.file_source}`;

    // Actualizar badge visual en el modal
    const badge = $('#viewer-category-badge');
    const b = getBadgeData(evt);
    badge.className = `inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ${b.classes}`;
    badge.innerHTML = `<span>${b.icon}</span><span>${esc(b.label)}</span>`;

    // Diagnóstico sugerido adaptado a si es salida voluntaria o error real
    const sugBox = $('#viewer-suggestion-box');
    const sugTitle = $('#viewer-suggestion-title') || sugBox.querySelector('p:first-child');
    const sugText = $('#viewer-suggestion-text');

    if (evt.category === 'NORMAL_DISCONNECT') {
      sugBox.className = 'mt-4 rounded-lg border border-zinc-700/60 bg-zinc-900/60 p-4 text-xs leading-relaxed text-zinc-300';
      sugTitle.className = 'font-bold text-zinc-400 uppercase tracking-wider text-[10px] flex items-center gap-1.5';
      sugTitle.innerHTML = '<span>🚪</span> <span>Diagnóstico: Salida Voluntaria</span>';
      sugText.innerHTML = 'El jugador cerró su sesión o salió del servidor de forma normal (desconexión voluntaria / quit). <strong>No representa un error ni incompatibilidad de mods.</strong>';
      sugBox.classList.remove('hidden');
    } else if (evt.category === 'MOD_ERROR' || evt.category === 'INVALID_DATA' || evt.severity === 'error') {
      sugBox.className = 'mt-4 rounded-lg border border-rose-500/30 bg-rose-950/20 p-4 text-xs leading-relaxed text-rose-200';
      sugTitle.className = 'font-bold text-rose-300 uppercase tracking-wider text-[10px] flex items-center gap-1.5';
      sugTitle.innerHTML = '<span>💥</span> <span>Diagnóstico: Fallo Crítico / Incompatibilidad</span>';
      let desc = evt.suggestion || 'Se produjo un error crítico o incompatibilidad de datos durante la sesión del jugador.';
      if (evt.suspected_mod) {
        desc += ` Actividad anómala asociada al mod <strong class="text-rose-100 underline decoration-rose-400/60">${esc(evt.suspected_mod)}</strong>.`;
      }
      sugText.innerHTML = desc;
      sugBox.classList.remove('hidden');
    } else if (evt.category === 'TIMEOUT') {
      sugBox.className = 'mt-4 rounded-lg border border-violet-500/30 bg-violet-950/20 p-4 text-xs leading-relaxed text-violet-200';
      sugTitle.className = 'font-bold text-violet-300 uppercase tracking-wider text-[10px] flex items-center gap-1.5';
      sugTitle.innerHTML = '<span>⏳</span> <span>Diagnóstico: Tiempo de Espera Agotado</span>';
      sugText.innerHTML = evt.suggestion || 'El jugador perdió conexión debido a saturación de paquetes, lag de red o cierre inesperado de la conexión keep-alive.';
      sugBox.classList.remove('hidden');
    } else if (evt.category === 'KICKED_BANNED') {
      sugBox.className = 'mt-4 rounded-lg border border-sky-500/30 bg-sky-950/20 p-4 text-xs leading-relaxed text-sky-200';
      sugTitle.className = 'font-bold text-sky-300 uppercase tracking-wider text-[10px] flex items-center gap-1.5';
      sugTitle.innerHTML = '<span>🚫</span> <span>Diagnóstico: Expulsión / Baneo</span>';
      sugText.innerHTML = evt.suggestion || 'El jugador fue expulsado por la lista blanca (whitelist), comando o sistema de moderación.';
      sugBox.classList.remove('hidden');
    } else {
      sugBox.className = 'mt-4 rounded-lg border border-amber-500/30 bg-amber-950/20 p-4 text-xs leading-relaxed text-amber-200';
      sugTitle.className = 'font-bold text-amber-300 uppercase tracking-wider text-[10px] flex items-center gap-1.5';
      sugTitle.innerHTML = '<span>⚠️</span> <span>Diagnóstico Sugerido</span>';
      sugText.innerHTML = evt.suggestion || 'Desconexión anómala detectada. Revise el extracto de log para obtener más información.';
      sugBox.classList.remove('hidden');
    }

    // Renderizar líneas con coloreado de errores
    const logContent = $('#viewer-log-content');
    logContent.innerHTML = evt.context_lines.map((line) => {
      const escapedLine = esc(line);
      if (line.includes('ERROR') || line.includes('FATAL') || line.includes('Exception')) {
        return `<span class="text-rose-400 font-bold bg-rose-950/40">${escapedLine}</span>`;
      }
      if (line.includes('WARN')) {
        return `<span class="text-amber-300">${escapedLine}</span>`;
      }
      if (line.includes('lost connection') || line.includes('left the game')) {
        return `<span class="text-cyan-300 font-semibold">${escapedLine}</span>`;
      }
      return escapedLine;
    }).join('\n');

    logModal.showModal();
  });

  // Copiar log completo al portapapeles
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
        `\n=== EXTRACTO DE LOG Y TRAZA ===`,
        selectedEvent.context_lines.join('\n'),
      ].join('\n');

      try {
        await navigator.clipboard.writeText(fullTrace);
        Panel.toast('Log completo copiado al portapapeles.', 'success');
      } catch {
        Panel.toast('No se pudo copiar el log.', 'error');
      }
    };
  }

  loadEvents();
});
