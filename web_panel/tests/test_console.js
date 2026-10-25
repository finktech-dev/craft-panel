/**
 * Console page behaviour, run in Node with a tiny DOM that models row heights and scrolling:
 * following new lines, real log levels, folded stack traces, repeated lines,
 * search, risky commands, chat mode and clickable player names.
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const ROW_HEIGHT = 20;
const VIEW_HEIGHT = 200;

function element(id = '') {
  const listeners = {};
  const classes = new Set();
  const attributes = {};
  const el = {
    id,
    listeners,
    children: [],
    style: {},
    textContent: '',
    innerHTML: '',
    value: '',
    className: '',
    placeholder: '',
    parentNode: null,
    classList: {
      add: (...names) => names.forEach((name) => classes.add(name)),
      remove: (...names) => names.forEach((name) => classes.delete(name)),
      toggle: (name, force) => ((force ?? !classes.has(name)) ? classes.add(name) : classes.delete(name)),
      contains: (name) => classes.has(name),
    },
    setAttribute: (key, value) => {
      attributes[key] = String(value);
    },
    getAttribute: (key) => (key in attributes ? attributes[key] : null),
    focus() {},
    closest: () => null,
    querySelector: () => null,
    append(...nodes) {
      nodes.forEach((node) => {
        if (typeof node === 'object') {
          node.parentNode = el;
          el.children.push(node);
        }
      });
    },
    addEventListener(type, handler) {
      (listeners[type] ||= []).push(handler);
    },
    fire(type, event = {}) {
      (listeners[type] || []).forEach((handler) => handler({ preventDefault() {}, stopPropagation() {}, ...event }));
    },
  };
  return el;
}

function output() {
  const out = element('terminal-output');
  let top = 0;
  const height = () => out.children.filter((row) => row.style.display !== 'none').length * ROW_HEIGHT;
  Object.defineProperties(out, {
    scrollHeight: { get: height },
    clientHeight: { get: () => VIEW_HEIGHT },
    scrollTop: {
      get: () => top,
      set: (value) => {
        top = Math.max(0, Math.min(value, Math.max(0, height() - VIEW_HEIGHT)));
      },
    },
  });
  out.append = (row) => {
    row.parentNode = out;
    row.remove = () => {
      out.children.splice(out.children.indexOf(row), 1);
      row.parentNode = null;
    };
    out.children.push(row);
  };
  out.replaceChildren = () => {
    out.children.length = 0;
  };
  out.contains = (node) => node === out || out.children.includes(node);
  return out;
}

function load({ confirmAnswer = true } = {}) {
  const elements = {};
  const get = (selector) => {
    const id = selector.replace('#', '');
    if (!elements[id]) {
      elements[id] = id === 'terminal-output' ? output() : element(id);
      // Hidden in console.html until there is something new to see.
      if (['scroll-to-bottom-btn', 'search-count', 'player-menu'].includes(id)) elements[id].classList.add('hidden');
    }
    return elements[id];
  };
  const modeButtons = ['command', 'chat'].map((mode) => {
    const button = element(`mode-${mode}`);
    button.setAttribute('data-send-mode', mode);
    return button;
  });
  let ready;
  let socket;
  let selection = { isCollapsed: true, anchorNode: null };
  const sent = [];
  const confirms = [];
  class FakeSocket {
    constructor() {
      socket = this;
      this.listeners = {};
      this.readyState = 1;
    }
    addEventListener(type, handler) {
      this.listeners[type] = handler;
    }
    send(data) {
      sent.push(JSON.parse(data).command);
    }
  }
  FakeSocket.OPEN = 1;
  const context = {
    document: {
      querySelector: get,
      querySelectorAll: (selector) => (selector === '[data-send-mode]' ? modeButtons : []),
      addEventListener: (type, handler) => {
        if (type === 'DOMContentLoaded') ready = handler;
      },
      createElement: () => element(),
    },
    window: {
      getSelection: () => selection,
      setTimeout: (fn) => {
        fn();
        return 0;
      },
      clearTimeout() {},
      confirm: (message) => {
        confirms.push(message);
        return confirmAnswer;
      },
    },
    localStorage: { getItem: () => null, setItem() {} },
    WebSocket: FakeSocket,
    Panel: { websocketUrl: (url) => url, toast() {}, api: async () => ({}) },
    console,
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'console.js'), 'utf8'), context);
  ready();
  let seq = 0;
  const line = (message, stream = 'stdout') => {
    seq++;
    socket.listeners.message({ data: JSON.stringify({ type: 'log', line: { seq, message, stream } }) });
  };
  const send = (count) => {
    for (let index = 0; index < count; index++) line(`linea ${seq + 1}`);
  };
  const submit = (text) => {
    get('command-input').value = text;
    get('command-form').fire('submit');
  };
  return {
    get,
    out: get('terminal-output'),
    button: get('scroll-to-bottom-btn'),
    modeButtons,
    send,
    line,
    submit,
    sent,
    confirms,
    select: (node) => {
      selection = node ? { isCollapsed: false, anchorNode: node } : { isCollapsed: true, anchorNode: null };
    },
  };
}

const atBottom = (out) => out.scrollTop === out.scrollHeight - out.clientHeight;
const bodyOf = (row) => row.children[row.children.length - 3];
const shown = (out) => out.children.filter((row) => row.style.display !== 'none');

// --- Scrolling ---------------------------------------------------------------------

{
  const { out, button, send } = load();
  send(30);
  assert(atBottom(out), 'should follow new lines while at the bottom');
  assert(button.classList.contains('hidden'));
  console.log('  ✓ sigue lo nuevo cuando estás abajo de todo');
}

{
  const { out, button, send } = load();
  send(30);
  out.scrollTop = 100;
  out.fire('scroll');
  send(3);
  assert.strictEqual(out.scrollTop, 100, 'reading position must stay put');
  assert.strictEqual(button.textContent, '3 líneas nuevas ↓');
  button.fire('click');
  assert(atBottom(out) && button.classList.contains('hidden'));
  send(1);
  assert(atBottom(out), 'after jumping down it follows again');
  console.log('  ✓ no te baja si subiste a leer, y te cuenta las líneas nuevas');
}

{
  const { out, send } = load();
  send(1500);
  out.scrollTop = 1000;
  out.fire('scroll');
  const firstVisible = bodyOf(out.children[Math.floor(out.scrollTop / ROW_HEIGHT)]).innerHTML;
  send(5);
  assert.strictEqual(out.children.length, 1500);
  assert.strictEqual(bodyOf(out.children[Math.floor(out.scrollTop / ROW_HEIGHT)]).innerHTML, firstVisible);
  console.log('  ✓ al borrar líneas viejas, lo que estás leyendo no se corre');
}

{
  const { out, send, select } = load();
  send(30);
  const top = out.scrollTop;
  select(out.children[20]);
  send(2);
  assert.strictEqual(out.scrollTop, top, 'selected text must not scroll away');
  console.log('  ✓ no se mueve mientras seleccionás texto');
}

// --- 1. Real log levels ---------------------------------------------------------------

{
  const { get, line } = load();
  line('[12:00:00] [Server thread/INFO] [errorlib/Main]: Loaded 0 errors');
  line('[12:00:01] [Server thread/WARN] [minecraft/MinecraftServer]: Can\'t keep up!');
  line('[12:00:02] [Server thread/ERROR] [create/Create]: Failed to load');
  line('java.lang.IllegalStateException: boom', 'stderr');
  assert.strictEqual(get('count-errors').textContent, 2, 'only the WARN and the ERROR lines are problems');
  console.log('  ✓ los errores salen del nivel real de la línea, no de la palabra "error"');
}

// --- 2. Folded stack traces ------------------------------------------------------------

{
  const { out, line, get } = load();
  line('[12:00:02] [Server thread/ERROR] [minecraft/MinecraftServer]: Exception ticking world');
  line('\tat net.minecraft.world.level.Level.tick(Level.java:10)');
  line('\tat net.minecraft.server.MinecraftServer.run(MinecraftServer.java:20)');
  line('Caused by: java.lang.NullPointerException');
  line('\t... 12 more');
  assert.strictEqual(shown(out).length, 1, 'the trace is folded under the error');
  const head = out.children[0];
  const toggle = head.children[head.children.length - 1];
  assert.strictEqual(toggle.textContent, 'Ver 4 líneas más');
  toggle.fire('click');
  assert.strictEqual(shown(out).length, 5);
  assert.strictEqual(toggle.textContent, 'Ocultar detalle');
  assert.strictEqual(get('count-errors').textContent, 1, 'a folded trace counts as one error');
  console.log('  ✓ los errores largos vienen plegados con "Ver N líneas más"');
}

// --- 3. Repeated lines ----------------------------------------------------------------

{
  const { out, line } = load();
  for (let index = 0; index < 5; index++) {
    line(`[12:00:0${index}] [Server thread/WARN] [minecraft/MinecraftServer]: Can't keep up! Is the server overloaded?`);
  }
  line('[12:00:09] [Server thread/INFO] [minecraft/MinecraftServer]: Otra cosa');
  assert.strictEqual(out.children.length, 2, 'five repeats become one row');
  const badge = out.children[0].children[out.children[0].children.length - 2];
  assert.strictEqual(badge.textContent, '× 5');
  console.log('  ✓ las líneas repetidas seguidas se juntan con "× N"');
}

// --- 4. Search highlights and moves between matches -----------------------------------

{
  const { out, line, get } = load();
  line('[Server thread/INFO]: Steve joined the game');
  line('[Server thread/INFO]: algo');
  line('[Server thread/INFO]: Steve left the game');
  const search = get('search-filter');
  search.value = 'steve';
  search.fire('input', { target: search });
  assert.strictEqual(shown(out).length, 3, 'searching does not hide the context');
  assert.strictEqual(get('search-count').textContent, '2 de 2', 'starts at the newest match');
  get('search-next').fire('click');
  assert.strictEqual(get('search-count').textContent, '1 de 2');
  console.log('  ✓ la búsqueda marca y recorre los resultados sin ocultar el resto');
}

// --- 5. Risky commands ask first ---------------------------------------------------------

{
  const declined = load({ confirmAnswer: false });
  declined.submit('/kill @e');
  declined.submit('stop');
  assert.deepStrictEqual(declined.sent, [], 'declined risky commands are not sent');
  assert.strictEqual(declined.confirms.length, 2);
  declined.submit('/kill @e[type=item]');
  declined.submit('time set day');
  assert.deepStrictEqual(declined.sent, ['/kill @e[type=item]', 'time set day']);
  console.log('  ✓ los comandos que no se pueden deshacer preguntan antes');
}

// --- 6. Player names are clickable ---------------------------------------------------------

{
  const { out, line } = load();
  line('[Server thread/INFO]: <Steve> hola a todos');
  line('[Server thread/INFO]: Alex joined the game');
  assert(bodyOf(out.children[0]).innerHTML.includes('data-player="Steve"'));
  assert(bodyOf(out.children[1]).innerHTML.includes('data-player="Alex"'));
  console.log('  ✓ los nombres de los jugadores se pueden tocar');
}

// --- 7. Chat mode ---------------------------------------------------------------------------

{
  const { submit, sent, modeButtons } = load();
  modeButtons[1].fire('click');
  submit('hola, se reinicia en 5 minutos');
  assert.deepStrictEqual(sent, ['/say hola, se reinicia en 5 minutos']);
  console.log('  ✓ el modo Chat manda el mensaje a todos sin escribir /say');
}

console.log('Consola: OK');
