// Minimal, safe Markdown renderer: builds DOM nodes (never innerHTML), so release
// notes from GitHub cannot inject markup. Supports a known subset: headings, bold,
// inline code, links (http/https only) and bullet/numbered lists.
(() => {
  const SAFE_URL = /^https?:\/\//i;

  const makeLink = (url, label) => {
    if (!SAFE_URL.test(url)) return document.createTextNode(label);
    const a = document.createElement('a');
    a.href = url;
    a.textContent = label;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    return a;
  };

  // Emit text, **bold**, `code`, [text](url) and bare URLs as nodes under parent.
  const appendInline = (parent, text) => {
    const pattern = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|\*\*([^*]+)\*\*|`([^`]+)`|(https?:\/\/[^\s<]+)/g;
    let last = 0;
    let match;
    while ((match = pattern.exec(text)) !== null) {
      if (match.index > last) parent.appendChild(document.createTextNode(text.slice(last, match.index)));
      if (match[1] !== undefined) {
        parent.appendChild(makeLink(match[2], match[1]));
      } else if (match[3] !== undefined) {
        const strong = document.createElement('strong');
        strong.textContent = match[3];
        parent.appendChild(strong);
      } else if (match[4] !== undefined) {
        const code = document.createElement('code');
        code.textContent = match[4];
        parent.appendChild(code);
      } else if (match[5] !== undefined) {
        parent.appendChild(makeLink(match[5], match[5]));
      }
      last = pattern.lastIndex;
    }
    if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)));
  };

  const render = (text) => {
    const fragment = document.createDocumentFragment();
    let list = null;      // the open <ul>/<ol>, if any
    let paragraph = null; // accumulated lines of the current paragraph

    const flushList = () => { if (list) { fragment.appendChild(list); list = null; } };
    const flushParagraph = () => {
      if (paragraph && paragraph.length) {
        const p = document.createElement('p');
        appendInline(p, paragraph.join(' '));
        fragment.appendChild(p);
      }
      paragraph = null;
    };

    for (const raw of String(text || '').split('\n')) {
      const trimmed = raw.trim();
      const heading = /^(#{1,6})\s+(.*)$/.exec(trimmed);
      const bullet = /^[-*]\s+(.*)$/.exec(trimmed);
      const numbered = /^\d+\.\s+(.*)$/.exec(trimmed);
      if (trimmed === '') {
        flushParagraph();
        flushList();
      } else if (heading) {
        flushParagraph();
        flushList();
        const level = Math.min(6, heading[1].length + 3); // "#" -> h4, "##" -> h5, ...
        const el = document.createElement('h' + level);
        appendInline(el, heading[2]);
        fragment.appendChild(el);
      } else if (bullet || numbered) {
        flushParagraph();
        const tag = bullet ? 'ul' : 'ol';
        if (!list || list.tagName.toLowerCase() !== tag) {
          flushList();
          list = document.createElement(tag);
        }
        const li = document.createElement('li');
        appendInline(li, (bullet || numbered)[1]);
        list.appendChild(li);
      } else {
        flushList();
        (paragraph = paragraph || []).push(trimmed);
      }
    }
    flushParagraph();
    flushList();
    return fragment;
  };

  window.CraftMarkdown = { render };
})();
