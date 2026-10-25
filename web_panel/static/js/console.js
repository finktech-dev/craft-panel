document.addEventListener('DOMContentLoaded', () => {
  const container = document.querySelector('#terminal-container');
  const output = document.querySelector('#terminal-output');
  const form = document.querySelector('#command-form');
  const input = document.querySelector('#command-input');
  const prompt = document.querySelector('#command-prompt');
  const modeButtons = document.querySelectorAll('[data-send-mode]');
  const socketDot = document.querySelector('#socket-dot');
  const socketText = document.querySelector('#socket-text');
  const linesCounter = document.querySelector('#lines-counter');
  const countAll = document.querySelector('#count-all');
  const countErrors = document.querySelector('#count-errors');
  const countChat = document.querySelector('#count-chat');
  const searchInput = document.querySelector('#search-filter');
  const clearSearchBtn = document.querySelector('#clear-search');
  const searchCount = document.querySelector('#search-count');
  const searchPrev = document.querySelector('#search-prev');
  const searchNext = document.querySelector('#search-next');
  const scrollToggle = document.querySelector('#scroll-toggle');
  const scrollLabel = document.querySelector('#scroll-label');
  const scrollToBottomBtn = document.querySelector('#scroll-to-bottom-btn');
  const copyLogsBtn = document.querySelector('#copy-logs');
  const clearBtn = document.querySelector('#clear-terminal');
  const fullscreenToggle = document.querySelector('#fullscreen-toggle');
  const playerMenu = document.querySelector('#player-menu');
  const playerMenuName = document.querySelector('#player-menu-name');
  const playerMenuCrashes = document.querySelector('#player-menu-crashes');
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
  // Last line that is not part of a stack trace: continuations fold under it.
  let lastHead = null;

  const storage = {
    get(key) {
      try {
        return localStorage.getItem(key);
      } catch {
        return null;
      }
    },
    set(key, value) {
      try {
        localStorage.setItem(key, value);
      } catch {}
    },
  };

  // Command History setup with localStorage
  const HISTORY_KEY = 'terminal_command_history';
  let commandHistory = [];
  try {
    const saved = storage.get(HISTORY_KEY);
    if (saved) commandHistory = JSON.parse(saved);
  } catch {}
  let historyCursor = commandHistory.length;

  const saveCommandToHistory = (cmd) => {
    if (!cmd) return;
    if (commandHistory[commandHistory.length - 1] !== cmd) {
      commandHistory.push(cmd);
      if (commandHistory.length > 60) commandHistory.shift();
      storage.set(HISTORY_KEY, JSON.stringify(commandHistory));
    }
    historyCursor = commandHistory.length;
  };

  const escapeHtml = (str) => {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  };

  // --- Reading a line -----------------------------------------------------------

  // The real level comes from the log tag ("[Server thread/WARN]" or "[12:00:00 WARN]"),
  // so a mod named "errorlib" or a line saying "0 errors" is not shown as a problem.
  const LEVEL_TAG = /\[[^\]\/]*\/(INFO|WARN|WARNING|ERROR|FATAL|SEVERE|DEBUG|TRACE)\]|^\[\d{1,2}:\d{2}:\d{2}\s+(INFO|WARN|ERROR|FATAL)\]/i;
  const EXCEPTION_LINE = /^(?:Exception in thread\b|[\w$]+(?:\.[\w$]+)+(?:Exception|Error|Throwable)\b)/;
  // Lines that belong to the error above them: "at ...", "Caused by:", "... 12 more".
  const CONTINUATION = /^\s+at\s|^\s*\.\.\.\s*\d+\s+more\b|^\s*Caused by:|^\s+Suppressed:/;
  // Leading time stamps differ between repeats of the same message.
  const LEADING_TIME = /^\[[^\]]*\d{1,2}:\d{2}:\d{2}[^\]]*\]\s*/;
  const PLAYER_EVENT = /(^|[\s>:])([A-Za-z0-9_]{3,16})(?=(?: joined the game| left the game|\[\/| lost connection:| was kicked| has (?:made|completed|reached) ))/g;

  const levelOf = (text, stream) => {
    const tag = text.match(LEVEL_TAG);
    if (tag) {
      const level = (tag[1] || tag[2]).toUpperCase();
      if (level === 'ERROR' || level === 'FATAL' || level === 'SEVERE') return 'error';
      if (level === 'WARN' || level === 'WARNING') return 'warn';
      return 'info';
    }
    if (EXCEPTION_LINE.test(text.trim())) return 'error';
    if (stream === 'stderr' && /\b(?:exception|error)\b/i.test(text)) return 'error';
    return 'info';
  };

  const playerButton = (name, label = name) =>
    `<button type="button" data-player="${name}" class="rounded font-semibold text-emerald-300 underline decoration-dotted underline-offset-2 hover:text-emerald-200">${label}</button>`;

  const formatBody = (rawText, level) => {
    // Stacktrace line detection (starts with whitespace + at)
    if (/^\s+at\s+/i.test(rawText)) {
      return `<span class="pl-4 text-[11px] text-[#f3a79b]/90">${escapeHtml(rawText)}</span>`;
    }
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

    // Player Chat messages: <PlayerName> message; the name opens the player menu.
    content = content.replace(/&lt;([a-zA-Z0-9_]{2,16})&gt;(.*)/g, (match, player, msg) => {
      return `${playerButton(player, `&lt;${player}&gt;`)}<span class="text-zinc-100">${msg}</span>`;
    });
    content = content.replace(PLAYER_EVENT, (match, before, player) => `${before}${playerButton(player)}`);

    // Highlight Player login/logout
    if (/logged in with entity id/i.test(rawText)) {
      return `<span class="text-emerald-300">→ ${content}</span>`;
    }
    if (/left the game/i.test(rawText)) {
      return `<span class="text-[#e8b04b]">← ${content}</span>`;
    }
    if (level === 'error') return `<span class="text-[#f3a79b]">${content}</span>`;
    if (level === 'warn') return `<span class="text-[#e8b04b]">${content}</span>`;
    return content;
  };

  const parseLogLine = (rawLine) => {
    const rawText = rawLine.message || '';
    const continuation = CONTINUATION.test(rawText) && rawLine.stream !== 'system';
    const level = continuation ? 'error' : levelOf(rawText, rawLine.stream);
    return {
      rawText,
      key: rawText.replace(LEADING_TIME, ''),
      time: rawLine.timestamp ? new Date(rawLine.timestamp).toLocaleTimeString() : '',
      level,
      continuation,
      isChat: /<[a-zA-Z0-9_]+>|logged in|joined the game|left the game/i.test(rawText),
      bodyHtml: formatBody(rawText, level),
      repeat: 1,
      head: null,
      continuations: [],
      expanded: false,
    };
  };

  const isProblem = (item) => item.level === 'error' || item.level === 'warn';

  // --- Filters and search -------------------------------------------------------------

  const passesTab = (item) => {
    const owner = item.head || item;
    if (currentFilter === 'errors' && !isProblem(owner)) return false;
    if (currentFilter === 'chat' && !owner.isChat) return false;
    return true;
  };

  const isShown = (item) => passesTab(item) && (!item.head || item.head.expanded);

  const matchesSearch = (item) => Boolean(searchQuery) && item.rawText.toLowerCase().includes(searchQuery);

  // Wrap the search text in <mark> inside one row, without touching the markup around it.
  const highlight = (item) => {
    item.body.innerHTML = item.bodyHtml;
    if (!matchesSearch(item) || typeof document.createTreeWalker !== 'function') return;
    const walker = document.createTreeWalker(item.body, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach((node) => {
      const text = node.nodeValue;
      const lower = text.toLowerCase();
      let index = lower.indexOf(searchQuery);
      if (index < 0) return;
      const fragment = document.createDocumentFragment();
      let start = 0;
      while (index >= 0) {
        fragment.append(text.slice(start, index));
        const mark = document.createElement('mark');
        mark.className = 'rounded-sm bg-[#e8b04b]/40 text-zinc-50';
        mark.textContent = text.slice(index, index + searchQuery.length);
        fragment.append(mark);
        start = index + searchQuery.length;
        index = lower.indexOf(searchQuery, start);
      }
      fragment.append(text.slice(start));
      node.replaceWith(fragment);
    });
  };

  let searchMatches = [];
  let searchIndex = -1;

  const updateSearchCount = () => {
    if (!searchCount) return;
    const active = Boolean(searchQuery);
    searchCount.classList.toggle('hidden', !active);
    searchPrev?.classList.toggle('hidden', !active);
    searchNext?.classList.toggle('hidden', !active);
    if (!active) return;
    searchCount.textContent = searchMatches.length
      ? `${searchIndex + 1} de ${searchMatches.length}`
      : 'Sin resultados';
  };

  const collectMatches = () => {
    searchMatches = searchQuery ? linesData.filter((item) => passesTab(item) && matchesSearch(item)) : [];
  };

  // --- Rows ---------------------------------------------------------------------------

  const renderExtras = (item) => {
    if (item.repeat > 1) {
      item.repeatBadge.textContent = `× ${item.repeat}`;
      item.repeatBadge.title = `Se repitió ${item.repeat} veces seguidas. La última, a las ${item.lastTime || item.time}.`;
      item.repeatBadge.classList.remove('hidden');
    }
    const hidden = item.continuations.length;
    if (hidden) {
      item.toggle.textContent = item.expanded ? 'Ocultar detalle' : hidden === 1 ? 'Ver 1 línea más' : `Ver ${hidden} líneas más`;
      item.toggle.setAttribute('aria-expanded', String(item.expanded));
      item.toggle.classList.remove('hidden');
    }
  };

  const buildRow = (item) => {
    const row = document.createElement('div');
    row.className = 'rounded px-1 py-0.5 whitespace-pre-wrap break-all hover:bg-zinc-900';
    if (item.time) {
      const time = document.createElement('span');
      time.className = 'mr-2 select-none text-zinc-500';
      time.textContent = item.time;
      row.append(time);
    }
    item.body = document.createElement('span');
    item.repeatBadge = document.createElement('span');
    item.repeatBadge.className = 'ml-2 hidden select-none rounded-full bg-zinc-800 px-1.5 text-[11px] font-semibold text-zinc-300';
    item.toggle = document.createElement('button');
    item.toggle.type = 'button';
    item.toggle.className = 'ml-2 hidden select-none rounded px-1.5 text-[11px] font-semibold text-[#f3a79b] underline underline-offset-2 hover:text-zinc-100';
    item.toggle.addEventListener('click', () => toggleGroup(item));
    row.append(item.body, item.repeatBadge, item.toggle);
    item.element = row;
    highlight(item);
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

  const removeOldest = (follow) => {
    const removed = linesData.shift();
    if (!removed.continuation && isProblem(removed)) errorCount = Math.max(0, errorCount - 1);
    if (!removed.continuation && removed.isChat) chatCount = Math.max(0, chatCount - 1);
    if (removed === lastHead) lastHead = null;
    if (removed.element && removed.element.parentNode) {
      // Dropping a row at the top shifts everything up; compensate so the text being read stays put.
      const before = output.scrollHeight;
      removed.element.remove();
      if (!follow) output.scrollTop -= before - output.scrollHeight;
    }
  };

  const afterNewRow = (follow, visible) => {
    updateCounters();
    if (searchQuery) {
      collectMatches();
      updateSearchCount();
    }
    if (!visible) return;
    if (follow) {
      output.scrollTop = output.scrollHeight;
    } else {
      unseenLines++;
      showNewLinesButton();
    }
  };

  const appendLine = (rawLine) => {
    const item = parseLogLine(rawLine);
    // Decide before adding the row: only follow new lines when the reader was already at the bottom.
    const follow = shouldFollow();

    // The same message again right after itself: count it instead of adding a row.
    const last = linesData[linesData.length - 1];
    if (!item.continuation && last && last === lastHead && !last.continuations.length && last.key === item.key) {
      last.repeat++;
      last.lastTime = item.time;
      renderExtras(last);
      afterNewRow(follow, false);
      return;
    }

    // "java.lang.Foo: message" right under an error is that error's detail, not a new one.
    if (!item.continuation && lastHead?.level === 'error' && !LEVEL_TAG.test(item.rawText) && EXCEPTION_LINE.test(item.rawText.trim())) {
      item.continuation = true;
    }

    if (item.continuation && lastHead) {
      item.head = lastHead;
      lastHead.continuations.push(item);
    } else {
      item.continuation = false;
      lastHead = item;
      if (isProblem(item)) errorCount++;
      if (item.isChat) chatCount++;
    }

    buildRow(item);
    if (!isShown(item)) item.element.style.display = 'none';
    linesData.push(item);
    output.append(item.element);
    if (item.head) renderExtras(item.head);

    while (linesData.length > MAX_LINES) removeOldest(follow);
    afterNewRow(follow, isShown(item));
  };

  const toggleGroup = (head) => {
    head.expanded = !head.expanded;
    head.continuations.forEach((item) => {
      item.element.style.display = isShown(item) ? '' : 'none';
    });
    renderExtras(head);
  };

  const reapplyFilters = () => {
    linesData.forEach((item) => {
      item.element.style.display = isShown(item) ? '' : 'none';
    });
    if (!paused) {
      jumpToBottom();
    }
  };

  const showMatch = (step) => {
    if (!searchMatches.length) return;
    const previous = searchMatches[searchIndex];
    previous?.element.classList.remove('ring-1', 'ring-[#e8b04b]');
    searchIndex = (searchIndex + step + searchMatches.length) % searchMatches.length;
    const item = searchMatches[searchIndex];
    // A match inside a folded error opens it.
    if (item.head && !item.head.expanded) toggleGroup(item.head);
    item.element.classList.add('ring-1', 'ring-[#e8b04b]');
    output.scrollTop = item.element.offsetTop - output.clientHeight / 2;
    updateSearchCount();
  };

  let searchTimer = null;
  const applySearch = () => {
    searchMatches.forEach((item) => item.element.classList.remove('ring-1', 'ring-[#e8b04b]'));
    linesData.forEach(highlight);
    collectMatches();
    searchIndex = -1;
    updateSearchCount();
    // Jump to the newest match, like reading the console from the bottom.
    if (searchMatches.length) {
      searchIndex = searchMatches.length;
      showMatch(-1);
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
    tab.addEventListener('click', () => {
      filterTabs.forEach((t) => {
        t.classList.remove('active', 'text-zinc-100', 'bg-zinc-800');
        t.classList.add('text-zinc-400');
      });
      tab.classList.add('active', 'text-zinc-100', 'bg-zinc-800');
      tab.classList.remove('text-zinc-400');

      currentFilter = tab.getAttribute('data-filter') || 'all';
      reapplyFilters();
      if (searchQuery) applySearch();
    });
  });

  // Search highlights the matches and moves between them; nothing is hidden, so the context stays.
  searchInput.addEventListener('input', (e) => {
    searchQuery = e.target.value.toLowerCase().trim();
    clearSearchBtn.classList.toggle('hidden', !searchQuery);
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(applySearch, 150);
  });

  searchInput.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    window.clearTimeout(searchTimer);
    if (searchIndex < 0) applySearch();
    else showMatch(e.shiftKey ? -1 : 1);
  });

  searchPrev?.addEventListener('click', () => showMatch(-1));
  searchNext?.addEventListener('click', () => showMatch(1));

  clearSearchBtn.addEventListener('click', () => {
    searchInput.value = '';
    searchQuery = '';
    clearSearchBtn.classList.add('hidden');
    applySearch();
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
    lastHead = null;
    errorCount = 0;
    chatCount = 0;
    searchMatches = [];
    searchIndex = -1;
    updateCounters();
    updateSearchCount();
    hideNewLinesButton();
    Panel.toast('Pantalla limpia. El servidor sigue igual.', 'success');
  });

  // Copy what is on screen; a folded error is copied whole so it can be shared.
  copyLogsBtn.addEventListener('click', async () => {
    const visibleLines = [];
    linesData.forEach((item) => {
      const shown = item.head ? passesTab(item) : item.element.style.display !== 'none';
      if (!shown) return;
      visibleLines.push(item.repeat > 1 ? `${item.rawText} (× ${item.repeat})` : item.rawText);
    });

    if (visibleLines.length === 0) {
      Panel.toast('No hay nada para copiar todavía.', 'error');
      return;
    }

    try {
      await navigator.clipboard.writeText(visibleLines.join('\n'));
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

  // --- Player menu --------------------------------------------------------------

  let menuPlayer = '';

  const closePlayerMenu = () => {
    playerMenu?.classList.add('hidden');
    menuPlayer = '';
  };

  const openPlayerMenu = (name, anchor) => {
    if (!playerMenu) return;
    menuPlayer = name;
    playerMenuName.textContent = name;
    playerMenuCrashes.href = `/crashes?player=${encodeURIComponent(name)}`;
    playerMenu.classList.remove('hidden');
    const area = playerMenu.parentNode.getBoundingClientRect();
    const spot = anchor.getBoundingClientRect();
    const left = Math.min(spot.left - area.left, area.width - playerMenu.offsetWidth - 8);
    playerMenu.style.left = `${Math.max(8, left)}px`;
    playerMenu.style.top = `${spot.bottom - area.top + 4}px`;
    playerMenu.querySelector('button, a')?.focus();
  };

  output.addEventListener('click', (e) => {
    const link = e.target.closest?.('[data-player]');
    if (!link) return;
    e.stopPropagation();
    openPlayerMenu(link.getAttribute('data-player'), link);
  });

  playerMenu?.addEventListener('click', async (e) => {
    const action = e.target.closest?.('[data-player-action]')?.getAttribute('data-player-action');
    const name = menuPlayer;
    if (!action || !name) return;
    if (action === 'message') {
      setMode('command');
      input.value = `/tell ${name} `;
      input.focus();
    } else if (action === 'copy') {
      try {
        await navigator.clipboard.writeText(name);
        Panel.toast(`Copiaste ${name}.`, 'success');
      } catch {
        Panel.toast('No pudimos copiar. Probá de nuevo.', 'error');
      }
    } else if (action === 'kick') {
      if (!window.confirm(`¿Echar a ${name} del servidor? Puede volver a entrar cuando quiera.`)) return;
      try {
        await Panel.api('/api/players/kick', { method: 'POST', body: { username: name } });
        Panel.toast(`Echaste a ${name}.`, 'success');
      } catch (error) {
        Panel.toast(error.message || 'No se pudo echar al jugador.', 'error');
      }
    }
    closePlayerMenu();
  });

  document.addEventListener('click', (e) => {
    if (playerMenu && !playerMenu.contains(e.target)) closePlayerMenu();
  });

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (menuPlayer) closePlayerMenu();
    else if (isFullscreen) fullscreenToggle.click();
  });

  // --- Sending ------------------------------------------------------------------

  // Commands that are hard to undo ask first, in plain words.
  const RISKY_COMMANDS = [
    [/^stop$/i, 'Esto apaga el servidor sin avisar a nadie. El botón Apagar del inicio avisa a los jugadores. ¿Mandarlo igual?'],
    [/^(?:op|deop)\b/i, 'Esto cambia quién es administrador del servidor. ¿Seguimos?'],
    [/^(?:ban|ban-ip|pardon|pardon-ip)\b/i, 'Esto bloquea o desbloquea a alguien para entrar. ¿Seguimos?'],
    [/^kill\s+@e(?!\[[^\]]*type=)/i, 'Esto elimina todas las criaturas y objetos del mundo, también mascotas y animales de granja. No se puede deshacer. ¿Seguimos?'],
    [/^kill\s+@a\b/i, 'Esto mata a todos los jugadores conectados y pierden lo que llevan. ¿Seguimos?'],
    [/^whitelist\s+off\b/i, 'Cualquiera que tenga la dirección va a poder entrar. ¿Seguimos?'],
    [/^save-off\b/i, 'El servidor deja de guardar el mundo hasta que mandes save-on. ¿Seguimos?'],
    [/^(?:fill|clone)\b/i, 'Esto cambia muchos bloques de golpe y no se puede deshacer. ¿Seguimos?'],
  ];

  const confirmRisky = (command) => {
    const bare = command.replace(/^\//, '').trim();
    const risky = RISKY_COMMANDS.find(([pattern]) => pattern.test(bare));
    return !risky || window.confirm(risky[1]);
  };

  const sendRaw = (command) => {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      Panel.toast('La consola no está conectada. Esperá un momento.', 'error');
      return false;
    }
    socket.send(JSON.stringify({ type: 'command', command }));
    return true;
  };

  const sendCommand = (command) => {
    if (!confirmRisky(command)) return false;
    if (!sendRaw(command)) return false;
    saveCommandToHistory(command);
    return true;
  };

  // "Chat" mode sends what you type as a message for everyone, without knowing about /say.
  const MODE_KEY = 'terminal_send_mode';
  let sendMode = storage.get(MODE_KEY) === 'chat' ? 'chat' : 'command';

  const setMode = (mode) => {
    sendMode = mode;
    storage.set(MODE_KEY, mode);
    modeButtons.forEach((button) => {
      const active = button.getAttribute('data-send-mode') === mode;
      button.setAttribute('aria-pressed', String(active));
      button.classList.toggle('bg-zinc-800', active);
      button.classList.toggle('text-zinc-100', active);
      button.classList.toggle('text-zinc-400', !active);
    });
    input.placeholder = mode === 'chat' ? 'Un mensaje para todos los que están jugando' : 'Por ejemplo: time set day';
    if (prompt) prompt.textContent = mode === 'chat' ? 'Chat' : '>';
  };

  modeButtons.forEach((button) => {
    button.addEventListener('click', () => {
      setMode(button.getAttribute('data-send-mode'));
      input.focus();
    });
  });
  setMode(sendMode);

  // Quick Command Chips
  quickCmdChips.forEach((chip) => {
    chip.addEventListener('click', () => {
      const cmd = chip.getAttribute('data-cmd');
      if (!cmd) return;
      setMode('command');
      input.value = cmd;
      input.focus();
    });

    // Double click directly sends command
    chip.addEventListener('dblclick', () => {
      const cmd = chip.getAttribute('data-cmd');
      if (!cmd || !sendCommand(cmd)) return;
      input.value = '';
      Panel.toast(`Enviado: ${cmd}`, 'success');
    });
  });

  // Keyboard navigation for History (Arrow Up / Arrow Down)
  input.addEventListener('keydown', (e) => {
    if (sendMode !== 'command') return;
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
    const text = input.value.trim();
    if (!text) return;
    const sent = sendMode === 'chat' ? sendRaw(`/say ${text}`) : sendCommand(text);
    if (sent) input.value = '';
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
