/**
 * Ajustes (/administration): an overview of sections that opens one screen at a time.
 * web_panel/static/js/admin-tabs.js
 *
 * The URL hash keeps the open screen and sub-screen (#myserver/copias, #discord, #worldedit…),
 * so deep links and reloads land in the same place and the browser Back button returns to the overview.
 */

(() => {
  const MASTER_TABS = ['ranks', 'rules', 'configs', 'discord', 'myserver', 'access', 'security'];

  // Older or alternative hashes that still have to open the right screen.
  const HASH_MAP = {
    '#jugadores': { main: 'ranks' },
    '#roles': { main: 'ranks' },
    '#restrictions': { main: 'rules', sub: 'items' },
    '#restrictions-hub': { main: 'rules', sub: 'items' },
    '#items': { main: 'rules', sub: 'items' },
    '#mobs': { main: 'rules', sub: 'mobs' },
    '#villagers': { main: 'rules', sub: 'villagers' },
    '#worldedit': { main: 'rules', sub: 'worldedit' },
    '#server': { main: 'configs' },
    '#world': { main: 'configs', sub: 'reglas' },
    '#health': { main: 'configs', sub: 'lento' },
    '#backups': { main: 'myserver', sub: 'copias' },
    '#tu-servidor': { main: 'myserver' },
    '#server-file': { main: 'myserver' },
    '#two-factor': { main: 'security' },
    '#seguridad': { main: 'security' },
    '#acceso': { main: 'access' },
    '#cartel': { main: 'discord', sub: 'cartel' },
    '#banner': { main: 'discord', sub: 'cartel' },
  };

  let currentMasterTab = null;
  // True when the open screen was reached from the overview of this same page,
  // so "Volver" can simply go back one step in the browser history.
  let openedFromOverview = false;

  const byId = (id) => document.getElementById(id);
  const scrollTop = () => { if (typeof window.scrollTo === 'function') window.scrollTo(0, 0); };
  const focusQuietly = (element) => { if (element && typeof element.focus === 'function') element.focus({ preventScroll: true }); };

  function writeHash(hash, push) {
    if (window.location.hash === hash) return;
    try {
      if (push) history.pushState(null, '', hash);
      else history.replaceState(null, '', hash);
    } catch {
      // Sandboxed frames may refuse history changes; the screen still switches.
    }
  }

  // Sub-screens: [data-subtabs="<group>"] buttons and [data-subpanel="<group>"] panels.
  function openSub(group, key) {
    if (group === 'rules') {
      // Reglas del servidor keeps its own tabs in admin-restrictions.js.
      if (typeof window.switchTab === 'function') window.switchTab(key || 'items');
      return key || 'items';
    }
    const panels = Array.from(document.querySelectorAll(`[data-subpanel="${group}"]`));
    if (!panels.length) return null;
    const target = panels.find((panel) => panel.dataset.subpanelKey === key) || panels[0];
    panels.forEach((panel) => { panel.hidden = panel !== target; });
    document.querySelectorAll(`[data-subtabs="${group}"] [data-subtab]`).forEach((button) => {
      button.setAttribute('aria-selected', button.dataset.subtab === target.dataset.subpanelKey ? 'true' : 'false');
    });
    // Shared rows (such as a Guardar bar) that make no sense on one sub-screen.
    document.querySelectorAll(`[data-hide-for-sub^="${group}/"]`).forEach((element) => {
      element.hidden = element.dataset.hideForSub === `${group}/${target.dataset.subpanelKey}`;
    });
    return target.dataset.subpanelKey;
  }

  function showOverview() {
    const previous = currentMasterTab;
    currentMasterTab = null;
    openedFromOverview = false;
    MASTER_TABS.forEach((key) => byId(`panel-master-${key}`)?.classList.add('hidden'));
    byId('admin-overview')?.classList.remove('hidden');
    scrollTop();
    // Put the keyboard back on the row that was opened.
    focusQuietly(previous ? byId(`tab-btn-${previous}`) : null);
  }

  function switchMasterTab(tabKey, updateHash = true, sub = null) {
    if (!MASTER_TABS.includes(tabKey)) {
      showOverview();
      if (updateHash) writeHash(window.location.pathname + window.location.search, false);
      return;
    }
    const changed = currentMasterTab !== tabKey;
    currentMasterTab = tabKey;

    byId('admin-overview')?.classList.add('hidden');
    MASTER_TABS.forEach((key) => {
      const panel = byId(`panel-master-${key}`);
      if (panel) panel.classList.toggle('hidden', key !== tabKey);
    });
    const openSubKey = openSub(tabKey, sub);

    if (updateHash) {
      const hash = sub && openSubKey ? `#${tabKey}/${openSubKey}` : `#${tabKey}`;
      openedFromOverview = true;
      writeHash(hash, true);
    }
    if (changed) {
      scrollTop();
      const panel = byId(`panel-master-${tabKey}`);
      focusQuietly(panel?.querySelector ? panel.querySelector('.screen-title') : null);
    }
  }

  function parseHash() {
    const raw = (window.location.hash || '').toLowerCase();
    if (HASH_MAP[raw]) return HASH_MAP[raw];
    const [main, sub] = raw.replace(/^#/, '').split('/');
    if (MASTER_TABS.includes(main)) return { main, sub: sub || null };
    return null;
  }

  function handleHashNavigation() {
    const route = parseHash();
    if (!route) {
      showOverview();
      return;
    }
    switchMasterTab(route.main, false, route.sub);
  }

  function initMasterTabs() {
    if (!byId('admin-master-tabs')) return;

    // Overview rows are links (#ranks, #discord…); remember that the screen came from the overview.
    MASTER_TABS.forEach((key) => {
      byId(`tab-btn-${key}`)?.addEventListener('click', () => { openedFromOverview = true; });
    });

    document.addEventListener('click', (event) => {
      const target = event.target;
      if (!target || typeof target.closest !== 'function') return;

      const back = target.closest('[data-admin-back]');
      if (back) {
        event.preventDefault();
        if (openedFromOverview) {
          history.back();
        } else {
          writeHash(window.location.pathname + window.location.search, false);
          showOverview();
        }
        return;
      }

      // Sub-screen tabs replace the hash so Back still returns to the overview.
      const subButton = target.closest('[data-subtabs] [data-subtab]');
      if (subButton) {
        const group = subButton.closest('[data-subtabs]').dataset.subtabs;
        const key = openSub(group, subButton.dataset.subtab);
        if (key) writeHash(`#${group}/${key}`, false);
        return;
      }
      const rulesTab = target.closest('#restrictions-hub .tab-btn[data-tab]');
      if (rulesTab) {
        writeHash(`#rules/${rulesTab.dataset.tab}`, false);
        return;
      }

      // Any link elsewhere on the page can open a screen with data-master-target.
      const link = target.closest('[data-master-target]');
      if (link && link.dataset.masterTarget) {
        event.preventDefault();
        switchMasterTab(link.dataset.masterTarget, true);
      }
    });

    // Arrow keys move between sub-screen tabs, as in any tab list.
    document.addEventListener('keydown', (event) => {
      if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
      const current = event.target && typeof event.target.closest === 'function' ? event.target.closest('[data-subtabs] [data-subtab]') : null;
      if (!current) return;
      const buttons = Array.from(current.closest('[data-subtabs]').querySelectorAll('[data-subtab]'));
      const step = event.key === 'ArrowRight' ? 1 : -1;
      const next = buttons[(buttons.indexOf(current) + step + buttons.length) % buttons.length];
      next.focus();
      next.click();
    });

    window.addEventListener('hashchange', handleHashNavigation);
    handleHashNavigation();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initMasterTabs);
  } else {
    initMasterTabs();
  }

  // Exported for the other Ajustes scripts and the regression tests.
  window.switchMasterTab = switchMasterTab;
  window.handleAdminMasterHash = handleHashNavigation;
  window.AdminTabs = {
    switchMasterTab,
    handleHashNavigation,
    openSub,
    showOverview,
    getCurrentTab: () => currentMasterTab,
    MASTER_TABS,
  };
})();
