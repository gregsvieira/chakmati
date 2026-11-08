// Inside a WhatsApp conversation the two text boxes never show together, and both start folded into one bar:
//   "Peça algo ao Chakmati"  (opens the usual command line; after the request is sent it folds again and a shortcut to the Chakmati's conversation appears)
//   "Responder mensagem diretamente" (opens a box whose text goes straight to WhatsApp, not through the Chakmati; it folds after sending)
// In the big window the conversation takes the middle column and the sides (topics, the Chakmati's screen) stay where they are.

(function () {
  const P = window.Panel;
  const { $, api } = P;

  let mode = 'collapsed';       // 'collapsed' | 'ask' | 'direct' (only means something inside a conversation)
  let shortcut = false;         // the person asked the Chakmati from here: a way back to read his answer
  let wasChat = false;

  const inChat = () => $('panel').dataset.screen === 'chat';

  // the conversation is a page of its own in the small card; in the big window it sits in the middle column, between the sides
  function placeChatView() {
    const chatView = $('chat-view');
    const wide = $('panel').dataset.layout === 'wide';
    if (wide && inChat()) {
      $('content').hidden = false;
      if (chatView.parentNode !== $('content')) $('content').insertBefore(chatView, $('screen'));
    } else {
      if (chatView.parentNode !== $('page')) $('page').appendChild(chatView);
      $('content').hidden = $('panel').dataset.screen !== 'main';
    }
  }

  function apply() {
    const chat = inChat();
    $('wa-dock').hidden = !(chat && mode === 'collapsed');
    $('composer').hidden = chat && mode !== 'ask';
    $('wa-reply').hidden = !(chat && mode === 'direct');
    $('ask-collapse').hidden = !chat;
    $('dock-thread').hidden = !shortcut;
    $('dock-ask').setAttribute('aria-expanded', String(chat && mode === 'ask'));
    $('panel').dataset.dock = chat ? mode : '';
  }

  function setMode(next) {
    mode = next;
    apply();
    if (!inChat()) return;
    if (mode === 'ask') $('input').focus();
    else if (mode === 'direct') $('wa-reply-input').focus();
  }

  // called by core.js on every page change and by layout.js when the window changes size
  P.onScreen = function (name, resized) {
    const chat = name === 'chat';
    if (chat && !wasChat && !resized) { mode = 'collapsed'; shortcut = false; note(''); }   // a conversation always opens with both boxes folded
    wasChat = chat;
    placeChatView();
    apply();
  };

  function note(text) {
    const p = $('wa-reply-note');
    p.textContent = text;
    p.hidden = !text;
  }

  const grow = () => { const t = $('wa-reply-input'); t.style.height = 'auto'; t.style.height = `${Math.min(t.scrollHeight, 110)}px`; };

  async function sendDirect() {
    const chat = P.currentChat;
    const text = $('wa-reply-input').value.trim();
    if (!chat || !text) return;
    $('wa-reply-send').disabled = true;
    note('');
    const res = await api.sendWa(chat.id, text);
    $('wa-reply-send').disabled = false;
    if (!res || res.error) { note((res && res.error) || 'Não consegui enviar a mensagem.'); return; }   // the text stays in the box
    $('wa-reply-input').value = '';
    grow();
    setMode('collapsed');
    if (P.reloadChat) P.reloadChat();
  }

  P.inits.push(function () {
    $('dock-ask').addEventListener('click', () => setMode('ask'));
    $('dock-direct').addEventListener('click', () => setMode('direct'));
    $('ask-collapse').addEventListener('click', () => setMode('collapsed'));
    $('reply-collapse').addEventListener('click', () => setMode('collapsed'));
    $('dock-thread').addEventListener('click', () => {
      shortcut = false;
      P.showView('main');   // the Chakmati's own conversation
      if ($('panel').dataset.layout === 'compact') { P.store.set('chakmati.focus', true); P.applyLayout(); P.renderThread(true); }
    });

    $('wa-reply').addEventListener('submit', (e) => { e.preventDefault(); sendDirect(); });
    $('wa-reply-input').addEventListener('input', grow);
    $('wa-reply-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); $('wa-reply').requestSubmit(); }
    });

    // a request to the Chakmati sent from inside a conversation: the box folds and a shortcut to his answer shows up
    $('composer').addEventListener('submit', () => {
      if (!inChat() || !$('input').value.trim() || (P.state && P.state.busy)) return;
      setTimeout(() => { shortcut = true; setMode('collapsed'); }, 0);
    }, true);
  });
})();
