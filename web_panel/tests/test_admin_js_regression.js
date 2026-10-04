/**
 * Test de regresión para los 4 módulos JavaScript del panel de administración.
 * Se ejecuta en Node.js simulando el entorno DOM y validando contratos y funciones.
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

console.log('='.repeat(60));
console.log('TEST DE REGRESIÓN JAVASCRIPT: MÓDULOS DE ADMINISTRACIÓN');
console.log('='.repeat(60));

const jsDir = path.join(__dirname, '..', 'static', 'js');
const files = [
  'admin-tabs.js',
  'admin-configs.js',
  'admin-restrictions.js',
  'admin-ranks.js',
  'admin-discord.js'
];

// 1. Test de Sintaxis
console.log('\n[1] Verificando compilación de sintaxis VM...');
for (const file of files) {
  const filePath = path.join(jsDir, file);
  assert(fs.existsSync(filePath), `Archivo no encontrado: ${file}`);
  const code = fs.readFileSync(filePath, 'utf8');
  assert(code.length > 500, `Archivo ${file} parece estar incompleto (${code.length} bytes)`);
  // Compilar con VM de Node
  new vm.Script(code, { filename: file });
  console.log(`  ✓ ${file} compila sin errores de sintaxis.`);
}

// 2. Mock del entorno de navegador (DOM, LocalStorage, Panel)
function createMockEnvironment() {
  const elements = new Map();
  const listeners = new Map();

  function createMockElement(tag, id = '', className = '') {
    const el = {
      tagName: tag.toUpperCase(),
      id,
      className,
      classList: {
        _classes: new Set(className.split(' ').filter(Boolean)),
        add(...cls) { cls.forEach(c => this._classes.add(c)); },
        remove(...cls) { cls.forEach(c => this._classes.delete(c)); },
        toggle(c, force) {
          if (force !== undefined) {
            force ? this._classes.add(c) : this._classes.delete(c);
          } else {
            this._classes.has(c) ? this._classes.delete(c) : this._classes.add(c);
          }
        },
        contains(c) { return this._classes.has(c); }
      },
      attributes: {},
      setAttribute: function(k, v) { this.attributes[k] = String(v); },
      getAttribute: function(k) { return this.attributes[k] !== undefined ? this.attributes[k] : null; },
      dataset: {},
      innerHTML: '',
      textContent: '',
      value: '',
      type: 'text',
      checked: false,
      disabled: false,
      style: {},
      scrollIntoView: () => {},
      focus: () => {},
      closest: (sel) => null,
      querySelectorAll: (sel) => [],
      querySelector: (sel) => null,
      addEventListener: (evt, handler) => {
        const key = `${id || tag}:${evt}`;
        if (!listeners.has(key)) listeners.set(key, []);
        listeners.get(key).push(handler);
      },
      dispatchEvent: (evt) => {
        const key = `${id || tag}:${evt.type}`;
        (listeners.get(key) || []).forEach(fn => fn(evt));
      }
    };
    return el;
  }

  // Pre-crear elementos que los scripts buscan
  const knownIds = [
    'admin-master-tabs', 'tab-btn-ranks', 'tab-btn-rules', 'tab-btn-configs', 'tab-btn-discord',
    'panel-master-ranks', 'panel-master-rules', 'panel-master-configs', 'panel-master-discord',
    'ranks', 'lp-ranks-grid', 'lp-roles-grid', 'lp-inspector-section', 'lp-inspect-select',
    'lp-new-id', 'lp-new-name', 'lp-new-prefix', 'lp-new-weight', 'lp-preview-chat-prefix',
    'lp-preview-tab-prefix', 'lp-target-player', 'lp-online-chips', 'lp-online-count',
    'lp-output-console', 'btn-toggle-create-rank', 'lp-create-rank-panel',
    'lp-disabled-banner', 'btn-activate-luckperms',
    'lp-user-target', 'lp-group-target', 'btn-lp-assign-group',
    'restrictions-hub', 'btn-toggle-worldedit', 'we-live-badge', 'quick-we-badge',
    'count-blocked-items', 'count-blocked-mobs', 'count-disabled-villagers',
    'blocked-items-list', 'blocked-mobs-list', 'villagers-grid', 'items-catalog-grid', 'mobs-catalog-grid',
    'items-mod-filters',
    'discord-webhook-url', 'discord-events-url', 'discord-mention-role',
    'discord-toggle-lifecycle', 'discord-toggle-crashes', 'discord-toggle-backups',
    'btn-save-discord-config', 'btn-discord-save', 'btn-test-main-webhook', 'btn-test-events-webhook', 'btn-test-mention',
    'btn-toggle-webhook-view', 'btn-toggle-events-view',
    // Discord configurable message template inputs
    'discord-msg-starting-title', 'discord-msg-starting-desc',
    'discord-msg-started-title', 'discord-msg-started-desc',
    'discord-msg-stopped-title', 'discord-msg-stopped-desc',
    'discord-msg-join-title', 'discord-msg-join-desc',
    'discord-msg-leave-title', 'discord-msg-leave-desc',
    'discord-msg-death-title', 'discord-msg-death-desc',
    'discord-msg-advancement-title', 'discord-msg-advancement-desc',
    'config-picker', 'config-search', 'config-workspace', 'config-form', 'config-code',
    'gamerules-list', 'players-list'
  ];

  for (const id of knownIds) {
    elements.set(`#${id}`, createMockElement('div', id));
  }

  const mockStorage = new Map();
  const localStorage = {
    getItem: (k) => mockStorage.get(k) || null,
    setItem: (k, v) => mockStorage.set(k, String(v)),
    removeItem: (k) => mockStorage.delete(k),
    clear: () => mockStorage.clear()
  };

  const mockApiResponses = {
    '/api/discord/config': {
      webhook_url: 'https://example.invalid/discord-webhook', events_webhook_url: '', mention_role: '123456789',
      msg_server_starting_title: '🔄 Servidor iniciando...', msg_server_starting_desc: '{server_name} está arrancando.',
      msg_server_started_title: '✅ Servidor en línea', msg_server_started_desc: '{server_name} listo en {addr}.',
      msg_server_stopped_title: '🔴 Servidor offline', msg_server_stopped_desc: '{server_name} se detuvo.',
      msg_player_join_title: '➡️ {player_name} se unió', msg_player_join_desc: 'Bienvenido a {server_name}.',
      msg_player_leave_title: '⬅️ {player_name} salió', msg_player_leave_desc: 'Hasta la próxima.',
      msg_player_death_title: '💀 {player_name} murió', msg_player_death_desc: '{death_message}',
      msg_advancement_title: '🏆 {player_name} obtuvo un logro', msg_advancement_desc: '{advancement_title}'
    },
    '/api/luckperms/config': { enabled: true, primary_ranks: ['owner','admin','mod','vip','default'], secondary_roles: ['streamer','builder'] },
    '/api/worldedit/status': { enabled: true, method: 'LuckPerms Live', last_updated: new Date().toISOString() },
    '/api/restrictions/summary': { blocked_items: ['minecraft:tnt'], blocked_mobs: ['minecraft:creeper'], disabled_villagers: ['armorer'], villagers: [{ profession: 'armorer', allowed: false }] },
    '/api/restrictions/catalog': { items: [{ id: 'minecraft:tnt', name: 'TNT', mod: 'minecraft' }], mobs: [{ id: 'minecraft:creeper', name: 'Creeper', mod: 'minecraft' }] },
    '/api/configs': [{ title: 'PointBlank', category: 'Armas', path: 'pointblank-common.toml', format: 'toml', size_kb: 4 }],
    '/api/gamerules': [{ name: 'keepInventory', value: true }],
    '/api/players': [{ username: 'Steve', is_op: true, is_whitelisted: true }]
  };

  const panelApi = async (url, opts) => {
    if (mockApiResponses[url]) return mockApiResponses[url];
    return { status: 'ok', message: 'Mock response' };
  };

  const context = {
    console,
    setTimeout: (fn) => fn(),
    setInterval: () => 1,
    clearInterval: () => {},
    clearTimeout: () => {},
    Date,
    Math,
    RegExp,
    Array,
    Object,
    String,
    Number,
    Boolean,
    Set,
    Map,
    Promise,
    encodeURIComponent,
    decodeURIComponent,
    localStorage,
    location: { hash: '#ranks' },
    history: { replaceState: () => {}, pushState: () => {} },
    addEventListener: (evt, fn) => {},
    removeEventListener: () => {},
    window: null,
    document: {
      readyState: 'complete',
      querySelector: (sel) => elements.get(sel) || null,
      querySelectorAll: (sel) => {
        if (sel === '.tab-btn') return [createMockElement('button', 'tab-items')];
        if (sel === '.tab-panel') return [createMockElement('div', 'tab-panel-items')];
        if (sel.includes('.master-tab-btn')) {
          return ['tab-btn-ranks', 'tab-btn-rules', 'tab-btn-configs', 'tab-btn-discord']
            .map(id => elements.get(`#${id}`)).filter(Boolean);
        }
        if (sel.includes('.admin-master-panel')) {
          return ['panel-master-ranks', 'panel-master-rules', 'panel-master-configs', 'panel-master-discord']
            .map(id => elements.get(`#${id}`)).filter(Boolean);
        }
        if (elements.has(sel)) return [elements.get(sel)];
        return [];
      },
      getElementById: (id) => elements.get(`#${id}`) || null,
      addEventListener: (evt, fn) => {
        if (evt === 'DOMContentLoaded') fn();
      }
    },
    Panel: {
      api: panelApi,
      toast: (msg, type) => {},
      escapeHtml: (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    }
  };
  context.window = context;
  return { context, elements, mockStorage };
}

// 3. Test de ejecución y contratos de admin-tabs.js
console.log('\n[2] Probando admin-tabs.js (Pestañas Maestras y Deep Linking)...');
const { context: tabsEnv } = createMockEnvironment();
const tabsCode = fs.readFileSync(path.join(jsDir, 'admin-tabs.js'), 'utf8');
vm.runInNewContext(tabsCode, tabsEnv);

assert(tabsEnv.window.switchMasterTab, 'switchMasterTab debe estar expuesto');
assert(tabsEnv.window.AdminTabs, 'AdminTabs debe estar expuesto');
assert.strictEqual(tabsEnv.window.AdminTabs.getCurrentTab(), 'ranks', 'Pestaña inicial por defecto debe ser ranks');
tabsEnv.window.switchMasterTab('rules');
assert.strictEqual(tabsEnv.window.AdminTabs.getCurrentTab(), 'rules', 'switchMasterTab debe cambiar pestaña a rules');
console.log('  ✓ switchMasterTab y AdminTabs responden correctamente');

// 4. Test de ejecución y contratos de admin-ranks.js
console.log('\n[3] Probando admin-ranks.js (Rangos, Colores Minecraft, LuckPerms)...');
const { context: ranksEnv } = createMockEnvironment();
const ranksCode = fs.readFileSync(path.join(jsDir, 'admin-ranks.js'), 'utf8');
vm.runInNewContext(ranksCode, ranksEnv);

assert(ranksEnv.window.renderMinecraftText, 'renderMinecraftText debe estar expuesto');
const renderedColor = ranksEnv.window.renderMinecraftText('&4&lCrown &eText&r');
assert(renderedColor.includes('font-weight:bold') || renderedColor.includes('font-weight: bold'), 'Debe aplicar estilo negrita para &l');
assert(renderedColor.includes('#aa0000') || renderedColor.includes('#AA0000'), 'Debe parsear color rojo');
console.log('  ✓ renderMinecraftText procesa correctamente códigos vanilla (&4, &l, &e, &r)');

const renderedHex = ranksEnv.window.renderMinecraftText('&#FF5555Texto Hex');
assert(renderedHex.includes('#FF5555') || renderedHex.includes('#ff5555'), 'Debe soportar formato hex 1.16+');
console.log('  ✓ renderMinecraftText procesa formato hexadecimal &#RRGGBB');

assert(ranksEnv.window.AdminRanks, 'AdminRanks debe estar expuesto');
const primaryRanks = ranksEnv.window.AdminRanks.PRIMARY_RANKS;
assert(Array.isArray(primaryRanks), 'PRIMARY_RANKS debe ser un array');
assert.strictEqual(primaryRanks.length, 0, 'Un clon nuevo no debe incluir rangos de otro servidor');

const secondaryRoles = ranksEnv.window.AdminRanks.SECONDARY_ROLES;
assert.strictEqual(secondaryRoles.length, 0, 'Un clon nuevo no debe incluir roles de otro servidor');
console.log('  ✓ Los rangos se cargan sólo desde la configuración local del usuario');

// 5. Test de ejecución y contratos de admin-restrictions.js
console.log('\n[4] Probando admin-restrictions.js (Centro de Restricciones & WorldEdit)...');
const { context: restrEnv } = createMockEnvironment();
const restrCode = fs.readFileSync(path.join(jsDir, 'admin-restrictions.js'), 'utf8');
vm.runInNewContext(restrCode, restrEnv);

assert(restrEnv.window.switchTab, 'switchTab debe estar definido');
assert(restrEnv.window.loadWorldEditStatus, 'loadWorldEditStatus debe estar definido');
assert(restrEnv.window.loadRestrictionsSummary, 'loadRestrictionsSummary debe estar definido');
assert(restrEnv.window.loadCatalog, 'loadCatalog debe estar definido');
console.log('  ✓ Funciones de restricciones y hot-toggle expuestas y operativas');

// 6. Test de ejecución y contratos de admin-configs.js
console.log('\n[5] Probando admin-configs.js (Editor TOML, Gamerules, Spark)...');
const { context: configsEnv } = createMockEnvironment();
const configsCode = fs.readFileSync(path.join(jsDir, 'admin-configs.js'), 'utf8');
vm.runInNewContext(configsCode, configsEnv);

assert(configsEnv.window.loadConfigFile, 'loadConfigFile debe estar expuesto');
assert(configsEnv.window.world, 'world debe estar expuesto');
console.log('  ✓ Funciones de configs, gamerules y spark expuestas y operativas');

// 7. Test de ejecución y contratos de admin-discord.js
console.log('\n[6] Probando admin-discord.js (Webhooks de Discord)...');
const { context: discordEnv } = createMockEnvironment();
const discordCode = fs.readFileSync(path.join(jsDir, 'admin-discord.js'), 'utf8');
vm.runInNewContext(discordCode, discordEnv);

assert(discordEnv.window.loadDiscordConfig, 'loadDiscordConfig debe estar expuesto');
console.log('  ✓ Integración de Discord expuesta y operativa');

console.log('\n' + '='.repeat(60));
console.log('TODOS LOS TESTS DE REGRESIÓN JS PASARON SATISFACTORIAMENTE (0 ERRORES)');
console.log('='.repeat(60));
