// The browser the Chakmati drives: the screenshots in the conversation, the screen on the right, questions it asks the person.

(function () {
  const P = window.Panel;
  const { api, $, thread } = P;

  // The browser at work: the screenshot of the latest step, replaced as each new one arrives, with what it was doing.
  function shotNode(turn) {
    if (!turn.shot || !turn.shot.image) return null;
    return P.h('figure', { class: 'shot' },
      P.h('img', { src: turn.shot.image, alt: turn.shot.title || 'navegador' }),
      P.h('figcaption', {}, turn.shot.note, P.h('span', {}, turn.shot.url)));
  }

  // The question of the browser ("qual é o seu usuário?", the password): an input in the conversation. The node is made once and kept
  // across redraws, so what is being typed is not lost; a password input is masked, and what is typed is cleared as soon as it is sent.
  function askNode(turn) {
    if (turn.askSent) return P.h('p', { class: 'hint' }, 'Resposta enviada.');
    if (!turn.ask) return null;
    if (!turn.askEl) {
      const ask = turn.ask;
      const input = P.h('input', { type: ask.secret ? 'password' : 'text', class: 'ask-input', autocomplete: ask.secret ? 'new-password' : 'off', spellcheck: 'false',
        maxlength: 500, 'aria-label': ask.prompt, placeholder: ask.secret ? 'Digite a senha (ela fica oculta)' : 'Digite aqui' });
      const send = P.h('button', { type: 'submit', class: 'primary small' }, ask.confirm ? 'Já resolvi' : 'Enviar');
      const fail = ask.confirm ? P.h('button', { type: 'button', class: 'small', onclick: () => { value = 'nao'; form.requestSubmit(); } }, 'Não consegui') : null;
      let value = null;
      const problem = P.h('p', { class: 'warn', hidden: true }, 'Não consegui enviar. Tente de novo.');
      const form = turn.askEl = P.h('form', { class: 'ask', autocomplete: 'off', onsubmit: async (e) => {
        e.preventDefault();
        const answer = ask.confirm ? (value || 'ok') : input.value;   // a confirmation has nothing to type: "Já resolvi" is ok, "Não consegui" is nao
        value = null;
        if (!answer) return;
        input.disabled = true; send.disabled = true; if (fail) fail.disabled = true;
        const res = await api.answerInput(ask.job_id, ask.request_id, answer);
        input.value = '';
        if (res && res.ok) { turn.ask = null; turn.askEl = null; turn.askInput = null; turn.askSent = true; } else { input.disabled = false; send.disabled = false; if (fail) fail.disabled = false; problem.hidden = false; }
        P.renderThread(false);
      } }, P.h('label', { class: 'ask-label' }, ask.prompt), P.h('div', { class: 'ask-row' }, input, send, fail), problem);
      if (ask.confirm) input.hidden = true;
      turn.askInput = input;
    }
    return turn.askEl;
  }

  // the screen: the browser as it is right now. Each new picture fades in over the last one: nothing says it is a sequence of pictures.
  let frontImg = $('screen-img-a');
  let backImg = $('screen-img-b');
  let shownSrc = '';
  function renderScreen() {
    const view = Shots.screenView(thread, null);
    $('screen-empty').hidden = !!view;
    $('screen-view').hidden = !view;
    $('screen-live').hidden = !(view && view.live);
    $('fold-right-live').hidden = !(view && view.live);
    if (!view) { shownSrc = ''; return; }
    const cur = view.current;
    $('screen-url').textContent = cur.url;
    $('screen-note').textContent = cur.note;
    if (cur.image && cur.image !== shownSrc) {
      shownSrc = cur.image;
      const next = backImg;
      next.setAttribute('src', cur.image);
      const show = () => { next.classList.add('on'); frontImg.classList.remove('on'); [frontImg, backImg] = [next, frontImg]; };
      if (typeof next.decode === 'function') next.decode().then(show, show); else show();
    }
  }

  Object.assign(P, { shotNode, askNode, renderScreen });

})();
