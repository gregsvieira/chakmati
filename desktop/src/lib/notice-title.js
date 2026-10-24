'use strict';
// "Avisos recentes" shows only the title of what happened: one line, without the body (the text of a message to send, the
// details of an event). The full content stays on the decision card or in the conversation.
(function (root) {
  const MAX = 70;
  function noticeTitle(notice) {
    const text = String((notice && notice.text) || '').split('\n')[0].trim().replace(/[:\s]+$/, '');
    // "Há uma ação aguardando a sua aprovação: Enviar WhatsApp para Maria +55...": keep the action, drop the number and what follows
    const cleaned = text.replace(/\s\+?\d[\d\s().-]{7,}$/, '').trim();
    return cleaned.length > MAX ? `${cleaned.slice(0, MAX - 1).trimEnd()}…` : cleaned;
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = { noticeTitle };
  else root.NoticeTitle = { noticeTitle };
})(typeof window !== 'undefined' ? window : globalThis);
