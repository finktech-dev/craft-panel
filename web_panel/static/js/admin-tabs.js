/**
 * Gestor de Pestañas Maestras y Deep Linking para el Centro de Control (/administration)
 * web_panel/static/js/admin-tabs.js
 *
 * Coordina la navegación de los módulos principales (Rangos, Reglas, Configs, Discord, Tu servidor),
 * controla la visibilidad con aislamiento visual y sincroniza la URL vía Hash Routing.
 */

(() => {
  const MASTER_TABS = ['ranks', 'rules', 'configs', 'discord', 'myserver'];

  const HASH_MAP = {
    '#ranks': { main: 'ranks' },
    '#jugadores': { main: 'ranks' },
    '#roles': { main: 'ranks' },
    '#rules': { main: 'rules', sub: 'items' },
    '#restrictions': { main: 'rules', sub: 'items' },
    '#restrictions-hub': { main: 'rules', sub: 'items' },
    '#items': { main: 'rules', sub: 'items' },
    '#mobs': { main: 'rules', sub: 'mobs' },
    '#villagers': { main: 'rules', sub: 'villagers' },
    '#worldedit': { main: 'rules', sub: 'worldedit' },
    '#configs': { main: 'configs' },
    '#server': { main: 'configs' },
    '#world': { main: 'configs', scrollTarget: 'world' },
    '#health': { main: 'configs', scrollTarget: 'health' },
    '#backups': { main: 'configs', scrollTarget: 'health' },
    '#discord': { main: 'discord' },
    '#myserver': { main: 'myserver' },
    '#tu-servidor': { main: 'myserver' },
    '#server-file': { main: 'myserver' },
  };

  let currentMasterTab = 'ranks';

  function switchMasterTab(tabKey, updateHash = true) {
    if (!MASTER_TABS.includes(tabKey)) {
      tabKey = 'ranks';
    }
    currentMasterTab = tabKey;

    // 1. Actualizar estilos de los botones de pestañas
    MASTER_TABS.forEach(key => {
      const btn = document.getElementById(`tab-btn-${key}`);
      const panel = document.getElementById(`panel-master-${key}`);
      const isActive = key === tabKey;

      if (btn) {
        btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
        // Underline tabs, same look as the mods page.
        if (isActive) {
          btn.className = 'master-tab-btn tab-pill -mb-px border-b-2 border-emerald-400 pb-3 font-semibold text-zinc-50';
        } else {
          btn.className = 'master-tab-btn tab-pill -mb-px border-b-2 border-transparent pb-3 font-semibold text-zinc-400 hover:text-zinc-200';
        }
      }

      if (panel) {
        if (isActive) {
          panel.classList.remove('hidden');
        } else {
          panel.classList.add('hidden');
        }
      }
    });

    // 2. Sincronizar hash en la URL sin saltos bruscos
    if (updateHash && window.location.hash !== `#${tabKey}`) {
      try {
        history.replaceState(null, '', `#${tabKey}`);
      } catch {
        // Entorno seguro / iframe fallback
      }
    }
  }

  function handleHashNavigation() {
    const rawHash = (window.location.hash || '').toLowerCase();
    const route = HASH_MAP[rawHash];

    if (route) {
      switchMasterTab(route.main, false);

      // Si tiene sub-pestaña en el módulo de reglas
      if (route.sub && typeof window.switchTab === 'function') {
        setTimeout(() => {
          window.switchTab(route.sub);
        }, 50);
      }

      // Si tiene elemento específico al cual scrollear
      if (route.scrollTarget) {
        setTimeout(() => {
          const target = document.getElementById(route.scrollTarget);
          if (target) {
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }
        }, 150);
      }
    } else if (rawHash.startsWith('#')) {
      const stripped = rawHash.slice(1);
      if (MASTER_TABS.includes(stripped)) {
        switchMasterTab(stripped, false);
      }
    }
  }

  function initMasterTabs() {
    const tabContainer = document.getElementById('admin-master-tabs');
    if (!tabContainer) return;

    // Delegación de eventos en los botones de pestañas maestras
    MASTER_TABS.forEach(key => {
      const btn = document.getElementById(`tab-btn-${key}`);
      if (btn) {
        btn.addEventListener('click', () => switchMasterTab(key, true));
      }
    });

    // Delegar cualquier enlace que tenga atributo data-master-target
    document.addEventListener('click', (e) => {
      const link = e.target.closest('[data-master-target]');
      if (link) {
        const target = link.dataset.masterTarget;
        if (target) {
          e.preventDefault();
          switchMasterTab(target, true);
        }
      }
    });

    // Escuchar cambios de hash en la ventana (navegación del historial y enlaces externos)
    window.addEventListener('hashchange', handleHashNavigation);

    // Carga inicial
    handleHashNavigation();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initMasterTabs);
  } else {
    initMasterTabs();
  }

  // Exportar a window para interoperabilidad y tests
  window.switchMasterTab = switchMasterTab;
  window.handleAdminMasterHash = handleHashNavigation;
  window.AdminTabs = {
    switchMasterTab,
    handleHashNavigation,
    getCurrentTab: () => currentMasterTab,
    MASTER_TABS,
  };
})();
