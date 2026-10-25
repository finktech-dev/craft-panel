document.addEventListener('DOMContentLoaded', () => {
  const container = document.querySelector('#terminal-container');
  const output = document.querySelector('#terminal-output');
  const form = document.querySelector('#command-form');
  const input = document.querySelector('#command-input');
  const socketBadge = document.querySelector('#socket-badge');
  const socketDot = document.querySelector('#socket-dot');
  const socketText = document.querySelector('#socket-text');
  const linesCounter = document.querySelector('#lines-counter');
  const countAll = document.querySelector('#count-all');
  const countErrors = document.querySelector('#count-errors');
  const countChat = document.querySelector('#count-chat');
  const searchInput = document.querySelector('#search-filter');
  const clearSearchBtn = document.querySelector('#clear-search');
  const scrollToggle = document.querySelector('#scroll-toggle');
  const scrollLabel = document.querySelector('#scroll-label');
  const scrollIcon = document.querySelector('#scroll-icon');
  const scrollToBottomBtn = document.querySelector('#scroll-to-bottom-btn');
  const copyLogsBtn = document.querySelector('#copy-logs');
  const clearBtn = document.querySelector('#clear-terminal');
  const fullscreenToggle = document.querySelector('#fullscreen-toggle');
  const filterTabs = document.querySelectorAll('.filter-tab');
  const quickCmdChips = document.querySelectorAll('.quick-cmd-chip');

  let paused = false;
  let socket = null;
  let currentFilter = 'all';
  let searchQuery = '';
  let isFullscreen = false;

  // In-memory structured lines
  const MAX_LINES = 1500;
  const linesData = [];
  let errorCount = 0;
  let chatCount = 0;

  // Command History setup with localStorage
  const HISTORY_KEY = 'terminal_command_history';
  let commandHistory = [];
  try {
    const saved = localStorage.getItem(HISTORY_KEY);
    if (saved) commandHistory = JSON.parse(saved);
  } catch {}
  let historyCursor = commandHistory.length;

  const saveCommandToHistory = (cmd) => {
    if (!cmd) return;
    if (commandHistory[commandHistory.length - 1] !== cmd) {
      commandHistory.push(cmd);
      if (commandHistory.length > 60) commandHistory.shift();
      try {
        localStorage.setItem(HISTORY_KEY, JSON.stringify(commandHistory));
      } catch {}
    }
    historyCursor = commandHistory.length;
  };

  // Syntax parser and formatter
  const parseLogLine = (rawLine) => {
    const rawText = rawLine.message || '';
    const ts = rawLine.timestamp ? new Date(rawLine.timestamp).toLocaleTimeString() : '';

    const isError = /\b(error|exception|fatal)\b/i.test(rawText) || rawText.includes('[ERROR]');
    const isWarn = /\b(warn|warning)\b/i.test(rawText) || rawText.includes('[WARN]');
    const isChat = /<[a-zA-Z0-9_]+>|logged in|joined the game|left the game/i.test(rawText);

    // Build formatted HTML
    let formattedHtml = '';
    if (ts) {
      formattedHtml += `<span class="text-zinc-500 mr-2 select-none">${ts}</span>`;
    }

    // Stacktrace line detection (starts with whitespace + at)
    if (/^\s+at\s+/i.test(rawText)) {
      formattedHtml += `<span class="pl-4 text-[11px] text-[#f3a79b]/90">${escapeHtml(rawText)}</span>`;
    } else {
      let content = escapeHtml(rawText);

      // Highlight Thread and Mod prefixes e.g. [Server thread/INFO] [minecraft/DedicatedServer]:
      content = content.replace(/\[([^\]]+?\/(?:INFO|WARN|ERROR|DEBUG|FATAL))\]/gi, (match, inner) => {
        if (/ERROR|FATAL/i.test(inner)) {
          return `<span class="font-semibold text-[#f3a79b]">[${inner}]</span>`;
        }
        if (/WARN/i.test(inner)) {
          return `<span class="font-semibold text-[#e8b04b]">[${inner}]</span>`;
        }
        return `<span class="text-zinc-400 font-semibold">[${inner}]</span>`;
      });

      // Highlight Mod Names in brackets [modname/Class]
      content = content.replace(/\[([a-zA-Z0-9_.-]+)\/([^\]]+)\]/gi, (match, mod, cls) => {
        return `<span class="text-zinc-300">[${mod}/<span class="text-zinc-500">${cls}</span>]</span>`;
      });

      // Highlight Player Chat messages: <PlayerName> message
      content = content.replace(/(&lt;[a-zA-Z0-9_]{2,16}&gt;)(.*)/g, (match, player, msg) => {
        return `<strong class="font-semibold text-emerald-300">${player}</strong><span class="text-zinc-100">${msg}</span>`;
      });

      // Highlight Player login/logout
      if (/logged in with entity id/i.test(rawText)) {
        content = `<span class="text-emerald-300">→ ${content}</span>`;
      } else if (/left the game/i.test(rawText)) {
        content = `<span class="text-[#e8b04b]">← ${content}</span>`;
      } else if (isError) {
        content = `<span class="text-[#f3a79b]">${content}</span>`;
      } else if (isWarn) {
        content = `<span class="text-[#e8b04b]">${content}</span>`;
      }

      formattedHtml += content;
    }

    return {
      rawText,
      formattedHtml,
      isError,
      isWarn,
      isChat,
    };
  };

  const escapeHtml = (str) => {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  };

  const matchesFilter = (item) => {
    // Level filter
    if (currentFilter === 'errors' && !item.isError && !item.isWarn) return false;
    if (currentFilter === 'chat' && !item.isChat) return false;

    // Search query filter
    if (searchQuery) {
      return item.rawText.toLowerCase().includes(searchQuery);
    }
    return true;
  };

  const updateCounters = () => {
    linesCounter.textContent = `${linesData.length} líneas`;
    countAll.textContent = linesData.length;
    countErrors.textContent = errorCount;
    countChat.textContent = chatCount;
  };

  // Lines that arrived while the reader was scrolled up or paused.
  const NEAR_BOTTOM_PX = 40;
  let unseenLines = 0;

  const isNearBottom = () => output.scrollHeight - output.scrollTop - output.clientHeight <= NEAR_BOTTOM_PX;

  const isSelectingText = () => {
    const selection = window.getSelection?.();
    return Boolean(selection && !selection.isCollapsed && output.contains(selection.anchorNode));
  };

  const shouldFollow = () => !paused && isNearBottom() && !isSelectingText();

  const showNewLinesButton = () => {
    scrollToBottomBtn.textContent = unseenLines === 1 ? '1 línea nueva ↓' : unseenLines > 1 ? `${unseenLines} líneas nuevas ↓` : 'Ver lo más nuevo';
    scrollToBottomBtn.classList.remove('hidden');
  };

  const hideNewLinesButton = () => {
    unseenLines = 0;
    scrollToBottomBtn.classList.add('hidden');
  };

  const jumpToBottom = () => {
    output.scrollTop = output.scrollHeight;
    hideNewLinesButton();
  };

  const appendLine = (rawLine) => {
    const item = parseLogLine(rawLine);
    if (item.isError || item.isWarn) errorCount++;
    if (item.isChat) chatCount++;

    const row = document.createElement('div');
    row.className = 'rounded px-1 py-0.5 whitespace-pre-wrap break-all hover:bg-zinc-900';
    row.innerHTML = item.formattedHtml;

    const visible = matchesFilter(item);
    if (!visible) {
      row.style.display = 'none';
    }

    // Decide before adding the row: only follow new lines when the reader was already at the bottom.
    const follow = shouldFollow();
    item.element = row;
    linesData.push(item);
    output.append(row);

    if (linesData.length > MAX_LINES) {
      const removed = linesData.shift();
      if (removed.isError || removed.isWarn) errorCount = Math.max(0, errorCount - 1);
      if (removed.isChat) chatCount = Math.max(0, chatCount - 1);
      if (removed.element && removed.element.parentNode) {
        // Dropping a row at the top shifts everything up; compensate so the text being read stays put.
        const before = output.scrollHeight;
        removed.element.remove();
        if (!follow) output.scrollTop -= before - output.scrollHeight;
      }
    }

    updateCounters();

    if (!visible) return;
    if (follow) {
      output.scrollTop = output.scrollHeight;
    } else {
      unseenLines++;
      showNewLinesButton();
    }
  };

  const reapplyFilters = () => {
    let visibleCount = 0;
    linesData.forEach((item) => {
      const match = matchesFilter(item);
      item.element.style.display = match ? '' : 'none';
      if (match) visibleCount++;
    });

    if (!paused) {
      jumpToBottom();
    }
  };

  // Reaching the bottom by hand counts as having seen the new lines.
  output.addEventListener('scroll', () => {
    if (isNearBottom()) {
      hideNewLinesButton();
    } else {
      showNewLinesButton();
    }
  });

  scrollToBottomBtn.addEventListener('click', jumpToBottom);

  // Filter Tabs
  filterTabs.forEach((tab) => {
    tab.addEventListener('click', (e) => {
      filterTabs.forEach((t) => {
        t.classList.remove('active', 'text-zinc-100', 'bg-zinc-800');
        t.classList.add('text-zinc-400');
      });
      tab.classList.add('active', 'text-zinc-100', 'bg-zinc-800');
      tab.classList.remove('text-zinc-400');

      currentFilter = tab.getAttribute('data-filter') || 'all';
      reapplyFilters();
    });
  });

  // Search Input Filter
  searchInput.addEventListener('input', (e) => {
    searchQuery = e.target.value.toLowerCase().trim();
    clearSearchBtn.classList.toggle('hidden', !searchQuery);
    reapplyFilters();
  });

  clearSearchBtn.addEventListener('click', () => {
    searchInput.value = '';
    searchQuery = '';
    clearSearchBtn.classList.add('hidden');
    reapplyFilters();
  });

  // Scroll Toggle
  scrollToggle.addEventListener('click', () => {
    paused = !paused;
    scrollLabel.textContent = paused ? 'Seguir' : 'Pausar';
    scrollToggle.setAttribute('aria-pressed', String(paused));
    scrollToggle.classList.toggle('border-[#e8b04b]/50', paused);
    scrollToggle.classList.toggle('text-[#e8b04b]', paused);
    if (!paused) {
      jumpToBottom();
    }
  });

  // Clear Terminal
  clearBtn.addEventListener('click', () => {
    output.replaceChildren();
    linesData.length = 0;
    errorCount = 0;
    chatCount = 0;
    updateCounters();
    hideNewLinesButton();
    Panel.toast('Pantalla limpia. El servidor sigue igual.', 'success');
  });

  // Copy Logs Button
  copyLogsBtn.addEventListener('click', async () => {
    const visibleLines = linesData
      .filter((item) => item.element.style.display !== 'none')
      .map((item) => item.rawText);

    if (visibleLines.length === 0) {
      Panel.toast('No hay nada para copiar todavía.', 'error');
      return;
    }

    const textToCopy = visibleLines.join('\n');
    try {
      await navigator.clipboard.writeText(textToCopy);
      Panel.toast(`Copiaste ${visibleLines.length} líneas.`, 'success');
    } catch {
      Panel.toast('No pudimos copiar. Probá de nuevo.', 'error');
    }
  });

  // Full Screen Toggle
  fullscreenToggle.addEventListener('click', () => {
    isFullscreen = !isFullscreen;
    if (isFullscreen) {
      container.classList.add('fixed', 'inset-0', 'z-50', 'rounded-none', 'border-none');
      output.classList.remove('h-[60vh]', 'min-h-[350px]');
      output.classList.add('h-[calc(100vh-170px)]');
      fullscreenToggle.textContent = 'Salir de pantalla completa';
    } else {
      container.classList.remove('fixed', 'inset-0', 'z-50', 'rounded-none', 'border-none');
      output.classList.add('h-[60vh]', 'min-h-[350px]');
      output.classList.remove('h-[calc(100vh-170px)]');
      fullscreenToggle.textContent = 'Pantalla completa';
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && isFullscreen) {
      fullscreenToggle.click();
    }
  });

  // Quick Command Chips
  quickCmdChips.forEach((chip) => {
    chip.addEventListener('click', () => {
      const cmd = chip.getAttribute('data-cmd');
      if (!cmd) return;
      input.value = cmd;
      input.focus();
    });

    // Double click directly sends command
    chip.addEventListener('dblclick', () => {
      const cmd = chip.getAttribute('data-cmd');
      if (!cmd || !socket || socket.readyState !== WebSocket.OPEN) return;
      socket.send(JSON.stringify({ type: 'command', command: cmd }));
      saveCommandToHistory(cmd);
      input.value = '';
      Panel.toast(`Enviado: ${cmd}`, 'success');
    });
  });

  // Keyboard navigation for History (Arrow Up / Arrow Down)
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (commandHistory.length === 0) return;
      if (historyCursor > 0) {
        historyCursor--;
        input.value = commandHistory[historyCursor] || '';
      }
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (commandHistory.length === 0) return;
      if (historyCursor < commandHistory.length - 1) {
        historyCursor++;
        input.value = commandHistory[historyCursor] || '';
      } else {
        historyCursor = commandHistory.length;
        input.value = '';
      }
    }
  });

  // Form Submit
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const command = input.value.trim();
    if (!command || !socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ type: 'command', command }));
    saveCommandToHistory(command);
    input.value = '';
  });

  // Each line carries a number; after a reconnect only the missing ones are added.
  // A new panel session restarts the numbering, so the count starts over too.
  let lastSeq = 0;
  let logSession = null;
  let dropNotified = false;
  const appendNew = (line) => {
    if (Number.isInteger(line?.seq)) {
      if (line.seq <= lastSeq) return;
      lastSeq = line.seq;
    }
    appendLine(line);
  };

  // WebSocket Connection with Status Badge
  const connect = () => {
    socketDot.className = 'h-2 w-2 rounded-full bg-[#e8b04b]';
    socketText.textContent = 'Conectando…';

    socket = new WebSocket(Panel.websocketUrl('/ws/terminal'));

    socket.addEventListener('open', () => {
      socketDot.className = 'h-2 w-2 rounded-full bg-emerald-400';
      socketText.textContent = 'Conectada, en vivo';
      dropNotified = false;
    });

    socket.addEventListener('message', (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === 'history') {
          if (payload.session && payload.session !== logSession) {
            logSession = payload.session;
            lastSeq = 0;
          }
          payload.lines.forEach(appendNew);
        }
        if (payload.type === 'log') {
          appendNew(payload.line);
        }
        if (payload.type === 'error') {
          Panel.toast(payload.message, 'error');
        }
      } catch (err) {
        console.error('Error procesando mensaje:', err);
      }
    });

    socket.addEventListener('close', () => {
      socketDot.className = 'h-2 w-2 rounded-full bg-[#ec7a6a]';
      socketText.textContent = 'Sin conexión';
      // One notice per outage, not one every retry.
      if (!dropNotified) Panel.toast('Se cortó la consola. Volvemos a conectar solos.', 'error');
      dropNotified = true;
      window.setTimeout(connect, 3000);
    });
  };

  connect();
});
