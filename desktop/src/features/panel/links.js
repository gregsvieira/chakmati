'use strict';
// Addresses written in a message ("Fontes: https://..."): cut out of the text so the panel can put a small clickable link icon after each.
// Only http and https open; the same check runs again in the main process before anything is opened.
(function (root) {
  const URL_RE = /https?:\/\/[^\s<>"'`]+/gi;
  const TRAILING = /[.,;:!?)\]}»”’]+$/;

  function safeLink(raw) {
    try {
      const u = new URL(String(raw));
      if ((u.protocol !== 'https:' && u.protocol !== 'http:') || u.username || u.password || !u.hostname) return null;
      return u.href;
    } catch { return null; }
  }

  // "text https://a.b/c." -> [{ text: 'text ' }, { url: 'https://a.b/c' }, { text: '.' }]
  function splitLinks(text) {
    const parts = [];
    let last = 0;
    String(text).replace(URL_RE, (match, index) => {
      const url = match.replace(TRAILING, '');
      if (!safeLink(url)) return match;
      if (index > last) parts.push({ text: text.slice(last, index) });
      parts.push({ url });
      last = index + url.length;
      return match;
    });
    if (last < text.length) parts.push({ text: text.slice(last) });
    return parts;
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = { splitLinks, safeLink };
  else root.Links = { splitLinks, safeLink };
})(typeof window !== 'undefined' ? window : globalThis);
