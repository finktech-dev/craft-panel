/**
 * The console only follows new lines when the reader is at the bottom:
 * scrolling up to read must not be undone by every new log line.
 * Runs console.js in Node with a tiny DOM that models row heights and scrolling.
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const ROW_HEIGHT = 20;
const VIEW_HEIGHT = 200;

function element(id) {
  const listeners = {};
  const classes = new Set();
  return {
    id,
    listeners,
    children: [],
    style: {},
    textContent: '',
    innerHTML: '',
    value: '',
    className: '',
    parentNode: null,
    classList: {
      add: (...names) => names.forEach((name) => classes.add(name)),
      remove: (...names) => names.forEach((name) => classes.delete(name)),
      toggle: (name, force) => ((force ?? !classes.has(name)) ? classes.add(name) : classes.delete(name)),
      contains: (name) => classes.has(name),
    },
    setAttribute() {},
    getAttribute: () => null,
    focus() {},
    addEventListener(type, handler) {
      (listeners[type] ||= []).push(handler);
    },
    fire(type, event = {}) {
      (listeners[type] || []).forEach((handler) => handler(event));
    },
  };
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

function load() {
  const elements = {};
  const get = (selector) => {
    const id = selector.replace('#', '');
    if (!elements[id]) {
      elements[id] = id === 'terminal-output' ? output() : element(id);
      // Hidden in console.html until there is something new to see.
      if (id === 'scroll-to-bottom-btn') elements[id].classList.add('hidden');
    }
    return elements[id];
  };
  let ready;
  let socket;
  let selection = { isCollapsed: true, anchorNode: null };
  class FakeSocket {
    constructor() {
      socket = this;
      this.listeners = {};
      this.readyState = 1;
    }
    addEventListener(type, handler) {
      this.listeners[type] = handler;
    }
    send() {}
  }
  FakeSocket.OPEN = 1;
  const context = {
    document: {
      querySelector: get,
      querySelectorAll: () => [],
      addEventListener: (type, handler) => {
        if (type === 'DOMContentLoaded') ready = handler;
      },
      createElement: () => element(''),
    },
    window: { getSelection: () => selection, setTimeout: () => 0 },
    localStorage: { getItem: () => null, setItem() {} },
    WebSocket: FakeSocket,
    Panel: { websocketUrl: (url) => url, toast() {} },
    console,
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'console.js'), 'utf8'), context);
  ready();
  let seq = 0;
  const send = (count) => {
    for (let index = 0; index < count; index++) {
      seq++;
      socket.listeners.message({ data: JSON.stringify({ type: 'log', line: { seq, message: `linea ${seq}` } }) });
    }
  };
  return {
    out: elements['terminal-output'],
    button: elements['scroll-to-bottom-btn'],
    send,
    select: (node) => {
      selection = node ? { isCollapsed: false, anchorNode: node } : { isCollapsed: true, anchorNode: null };
    },
  };
}

const atBottom = (out) => out.scrollTop === out.scrollHeight - out.clientHeight;

// 1. At the bottom, new lines are followed.
{
  const { out, button, send } = load();
  send(30);
  assert(atBottom(out), 'should follow new lines while at the bottom');
  assert(button.classList.contains('hidden'));
  console.log('  ✓ sigue lo nuevo cuando estás abajo de todo');
}

// 2. Scrolled up, new lines do not move the view and the button counts them.
{
  const { out, button, send } = load();
  send(30);
  out.scrollTop = 100;
  out.fire('scroll');
  send(3);
  assert.strictEqual(out.scrollTop, 100, 'reading position must stay put');
  assert(!button.classList.contains('hidden'));
  assert.strictEqual(button.textContent, '3 líneas nuevas ↓');
  button.fire('click');
  assert(atBottom(out) && button.classList.contains('hidden'));
  send(1);
  assert(atBottom(out), 'after jumping down it follows again');
  console.log('  ✓ no te baja si subiste a leer, y te cuenta las líneas nuevas');
}

// 3. Trimming old lines keeps the text being read in place.
{
  const { out, send } = load();
  send(1500);
  out.scrollTop = 1000;
  out.fire('scroll');
  const firstVisible = out.children[Math.floor(out.scrollTop / ROW_HEIGHT)].innerHTML;
  send(5);
  assert.strictEqual(out.children.length, 1500);
  assert.strictEqual(out.children[Math.floor(out.scrollTop / ROW_HEIGHT)].innerHTML, firstVisible);
  console.log('  ✓ al borrar líneas viejas, lo que estás leyendo no se corre');
}

// 4. Selecting text at the bottom does not get interrupted.
{
  const { out, send, select } = load();
  send(30);
  const top = out.scrollTop;
  select(out.children[20]);
  send(2);
  assert.strictEqual(out.scrollTop, top, 'selected text must not scroll away');
  select(null);
  console.log('  ✓ no se mueve mientras seleccionás texto');
}

console.log('Consola: desplazamiento OK');
