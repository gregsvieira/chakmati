// WhatsApp on the panel: unread messages, conversations, a chat, voice messages, the notice about blocks, linking.

(function () {
  const P = window.Panel;
  const { $, api, plural, fill } = P;

  // The notice before WhatsApp and automations: read once ("Compreendi e estou ciente!"), then never again. Esc or a click outside closes it
  // without doing the action. Remembered in this window's storage.
  const waGate = window.NoticeGate.createGate((() => { try { return window.localStorage; } catch { return { getItem: () => null, setItem: () => {} }; } })(), 'chakmati.whatsapp-notice');
  let closeNotice = null;
  function showWhatsAppNotice(onAck, onCancel) {
    const modal = $('notice-modal');
    const finish = (fn) => { modal.hidden = true; closeNotice = null; document.removeEventListener('keydown', onKey, true); modal.removeEventListener('mousedown', onOutside); fn(); };
    const onKey = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); finish(onCancel); }
      else if (e.key === 'Tab') { e.preventDefault(); $('notice-ok').focus(); }   // the only thing to press is the button
    };
    const onOutside = (e) => { if (e.target === modal) finish(onCancel); };
    $('notice-ok').onclick = () => finish(onAck);
    modal.hidden = false;
    closeNotice = () => finish(onCancel);
    document.addEventListener('keydown', onKey, true);
    modal.addEventListener('mousedown', onOutside);
    $('notice-ok').focus();
  }

  let waNote = '';
  async function connectWhatsApp() {
    return waGate.run(showWhatsAppNotice, doConnectWhatsApp);
  }
  async function doConnectWhatsApp() {
    waNote = 'Abrindo o OpenWA…';
    renderMessages();
    const res = await api.openWa();
    waNote = res && res.ok ? res.message || 'OpenWA aberto.' : (res && res.error) || 'Não consegui abrir o OpenWA.';
    renderMessages();
  }

  // A titled sub-block; sub-blocks sit one under the other.
  const subgroup = (title, ...kids) => P.h('div', { class: 'subgroup' }, P.h('h3', {}, title), kids);

  function whatsappNodes() {
    const wa = (P.state.overview && P.state.overview.whatsapp) || { enabled: false };
    if (!wa.enabled) return [P.h('p', { class: 'empty' }, 'WhatsApp desativado em Ajustes.')];
    if (wa.error || wa.connected === false) {
      return [
        P.h('p', { class: 'warn' }, wa.error
          ? 'O OpenWA respondeu com erro ao ler o WhatsApp (a sessão pode estar travada). Reinicie o OpenWA.'
          : 'O WhatsApp está desconectado. Abra o OpenWA e escaneie o QR em Aparelhos conectados.'),
        P.state.canOpenWa ? P.h('button', { class: 'primary', type: 'button', id: 'wa-connect-inline', onclick: connectWhatsApp }, 'Conectar WhatsApp via OpenWa') : null,
        P.h('p', { class: 'hint', id: 'wa-connect-note' }, waNote)];
    }
    const unread = wa.unread || [];
    if (!unread.length) return [P.h('p', { class: 'empty' }, 'Nenhuma mensagem nova.')];
    const masked = P.state.settings.masked;
    const rowFor = (c) => {
      const label = [P.h('span', { class: 'name' }, masked ? 'Uma conversa' : c.name, c.is_group && !masked ? P.h('span', { class: 'tag' }, ' (grupo)') : null),
        P.h('span', { class: 'badge', 'aria-label': plural(c.unread, 'mensagem nova', 'mensagens novas') }, String(c.unread))];
      return masked ? P.h('div', { class: 'row' }, label) : P.h('button', { class: 'row row-btn', type: 'button', onclick: () => openChat(c, 'main') }, label);
    };
    return [unread.slice(0, 2).map(rowFor),
      unread.length > 2 && !masked ? P.h('button', { class: 'more', type: 'button', onclick: openChats }, `Ver mais (${unread.length - 2})`) : null];
  }

  function renderMessages() {
    $('messages').hidden = false;
    fill($('messages-body'),
      subgroup('WhatsApp', whatsappNodes()),
      subgroup('Email', P.h('p', { class: 'empty' }, 'Email ainda não está conectado.')));
  }

  function renderPendingMark() {
    const n = ((P.state && P.state.overview && P.state.overview.pending) || []).length;
    const bell = (P.state && P.state.bell) || { state: 'idle', label: 'Nenhuma novidade' };
    const mark = $('head-approval');
    mark.dataset.state = bell.state;                  // idle (outline) | notice (red) | request (yellow)
    mark.setAttribute('aria-label', bell.label);
    mark.title = bell.label;
    const btn = $('open-notices');   // the bell of the header: same state, with a dot when there is news
    btn.dataset.state = bell.state;
    btn.setAttribute('aria-label', bell.state === 'idle' ? 'Avisos recentes' : `Avisos recentes: ${bell.label}`);
    const badge = $('fold-left-badge');  // the list of decisions is on the left: when it is minimized the number stays on its button
    badge.hidden = !(n > 0);
    badge.textContent = String(n);
    badge.setAttribute('aria-label', plural(n, 'aprovação pendente', 'aprovações pendentes'));
  }

  const fmtDuration = (s) => (Number.isFinite(s) ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}` : '');
  const fmtTime = (iso) => new Date(iso).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });

  async function openChats() {
    P.backTo = 'main';
    P.showView('chats');
    fill($('chats-body'), P.h('p', { class: 'empty' }, 'Carregando…'));
    const res = await api.chats();
    if (!res || res.error) { fill($('chats-body'), P.h('p', { class: 'warn' }, (res && res.error) || 'Não consegui carregar as conversas.')); return; }
    const unread = res.chats.filter((c) => c.unread > 0);
    const rest = res.chats.filter((c) => c.unread === 0).slice(0, 30);
    const row = (c) => P.h('button', { class: 'row row-btn', type: 'button', onclick: () => openChat(c, 'chats') },
      P.h('span', { class: 'name' }, c.name, c.is_group ? P.h('span', { class: 'tag' }, ' (grupo)') : null),
      c.unread > 0 ? P.h('span', { class: 'badge' }, String(c.unread)) : null);
    fill($('chats-body'),
      unread.length ? [P.h('h3', {}, 'Com mensagens novas'), unread.map(row)] : P.h('p', { class: 'empty' }, 'Nenhuma mensagem nova.'),
      rest.length ? [P.h('h3', {}, 'Recentes'), rest.map(row)] : null);
  }

  async function openChat(chat, from) {
    P.backTo = from;
    P.currentChat = chat;
    P.showView('chat', chat.name);
    $('title').textContent = chat.name;
    fill($('chat-body'), P.h('p', { class: 'empty' }, 'Carregando…'));
    await loadMessages(chat);
  }

  async function loadMessages(chat) {
    const res = await api.messages(chat.id);
    if (!res || res.error) { fill($('chat-body'), P.h('p', { class: 'warn' }, (res && res.error) || 'Não consegui carregar as mensagens.')); return; }
    if (!res.messages.length) { fill($('chat-body'), P.h('p', { class: 'empty' }, 'Nenhuma mensagem carregada.')); return; }
    fill($('chat-body'), res.messages.map((m) => messageNode(chat, m)));
    $('chat-view').scrollTop = $('chat-view').scrollHeight;
  }

  function messageNode(chat, m) {
    let body;
    if (m.audio) body = audioNode(chat, m);
    else if (m.kind !== 'chat') body = P.h('span', { class: 'media-note' }, `[${m.kind === 'ptt' || m.kind === 'audio' ? 'áudio' : m.kind === 'image' ? 'imagem' : m.kind}]`, m.text ? ` ${m.text}` : '');
    else body = P.h('span', {}, m.text);
    return P.h('div', { class: `msg ${m.from_me ? 'out' : 'in'}` }, body, P.h('span', { class: 'msg-time' }, fmtTime(m.ts)));
  }

  function audioNode(chat, m) {
    const holder = P.h('div', { class: 'audio' });
    const play = P.h('button', { class: 'ghost play', type: 'button' }, `▶ Ouvir áudio ${fmtDuration(m.duration)}`.trim());
    play.addEventListener('click', async () => {
      play.disabled = true;
      play.textContent = 'Carregando…';
      const res = await api.audio(chat.id, m.id);
      if (!res || res.error) { play.disabled = false; play.textContent = '▶ Tentar de novo'; holder.append(P.h('p', { class: 'warn' }, (res && res.error) || 'Não foi possível carregar o áudio.')); return; }
      const player = P.h('audio', { controls: true, src: res.dataUrl, 'aria-label': 'Áudio de ' + chat.name });
      holder.replaceChildren(player);
      player.play().catch(() => { /* the person can press play */ });
    });
    holder.append(play);
    return holder;
  }

  P.inits.push(function () {
    $('set-whatsapp').addEventListener('change', (e) => {
      const box = e.target;
      if (!box.checked) { api.setSetting('whatsapp', false); return; }
      box.checked = false;  // it only turns on after the notice was acknowledged
      waGate.run(showWhatsAppNotice, () => { box.checked = true; api.setSetting('whatsapp', true); });
    });

    $('wa-connect').addEventListener('click', connectWhatsApp);
  });

  P.reloadChat = () => (P.currentChat ? loadMessages(P.currentChat) : null);
  Object.assign(P, { waGate, showWhatsAppNotice, subgroup, renderMessages, renderPendingMark });

})();
