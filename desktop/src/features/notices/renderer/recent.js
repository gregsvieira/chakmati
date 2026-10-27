// Recent notices on the panel.

(function () {
  const P = window.Panel;
  const { $, relativeTime, fill } = P;

  function renderRecent() {
    // messages live under "Mensagens", and what Chakmati itself said is not a notice: here only agenda, approvals and system
    const notices = (P.state.notices || []).filter((n) => n.kind !== 'whatsapp' && n.kind !== 'reply').slice(-6).reverse();
    if (!notices.length) { fill($('recent-body'), P.h('p', { class: 'empty' }, 'Quando algo acontecer, eu aviso aqui.')); return; }
    const now = Date.now() / 1000;
    fill($('recent-body'), notices.map((n) => P.h('div', { class: 'row' },
      P.h('span', { title: n.text.split('\n')[0] }, P.state.settings.masked && n.masked ? n.masked : window.NoticeTitle.noticeTitle(n)), P.h('span', { class: 'when' }, relativeTime(n.ts, now)))));
  }

  Object.assign(P, { renderRecent });

})();
