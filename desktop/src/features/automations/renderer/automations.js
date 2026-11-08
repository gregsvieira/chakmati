// Automations on the panel: the list, previewing a voice reply and recording "Minha fala".

(function () {
  const P = window.Panel;
  const { api, $, fill, plural, subgroup, thread, sleep, waGate } = P;

  function renderAutomations() {
    const list = (P.state.overview && P.state.overview.automations) || [];
    $('automations-empty').hidden = list.length > 0;
    const card = (a) => P.h('div', { class: 'row automation' },
      P.h('div', { class: 'grow' }, P.h('p', { class: 'decision-title' }, a.name), P.h('p', { class: 'decision-body' }, a.description + (a.runs ? ` (${plural(a.runs, 'vez', 'vezes')})` : ''))),
      P.h('div', { class: 'decision-actions' },
        P.h('button', { class: 'ghost small', type: 'button', onclick: () => api.automation(a.id, a.enabled ? 'disable' : 'enable') }, a.enabled ? 'Pausar' : 'Ativar'),
        P.h('button', { class: 'ghost small', type: 'button', onclick: () => api.automation(a.id, 'delete') }, 'Apagar')));
    // One sub-block per channel that has automations; none for the channels without any.
    const channels = [['whatsapp', 'WhatsApp'], ['email', 'Email'], ['home', 'Casa']];
    fill($('automation-list'), channels
      .map(([key, title]) => [title, list.filter((a) => (a.channel || 'whatsapp') === key)])
      .filter(([, items]) => items.length)
      .map(([title, items]) => subgroup(title, items.map(card))));
  }

  async function previewVoice(id, button) {
    const res = await api.preview(id);
    if (res && res.dataUrl) { button.replaceWith(P.h('audio', { controls: true, autoplay: true, src: res.dataUrl, 'aria-label': 'Prévia da resposta em áudio' })); }
    else button.textContent = (res && res.error) || 'Sem prévia';
  }

  let recordingOwn = false;
  let lastHours = null;   // the hours chosen for the recording in progress, so "regravar" keeps them

  // Chakmati says something: in the thread when the panel is open (and spoken), as a bubble by the character when it is closed.
  function tell(text, extra = {}) {
    const turn = { role: 'assistant', text, status: 'done', ...extra };
    thread.push(turn);
    while (thread.length > 10) thread.shift();
    P.renderThread();
    if (P.state && P.state.panelOpen) P.sayAloud(text); else api.reply(text);
    return turn;
  }

  async function waitQuiet(maxMs) {
    const end = Date.now() + maxMs;
    await sleep(500); // the speech has not started yet at this point
    while (Date.now() < end && (P.speaking || P.otherSpeaking)) await sleep(120);
    await sleep(250);
  }

  // The countdown is silent: one line that changes every second, in the panel or in a bubble.
  let countdownTurn = null;
  function showCount(text) {
    if (P.state && P.state.panelOpen) {
      if (!countdownTurn || !thread.includes(countdownTurn)) { countdownTurn = { role: 'assistant', text, status: 'done' }; thread.push(countdownTurn); }
      countdownTurn.text = text;
      P.renderThread(false);
    } else api.live(text);
  }
  function endCount() {
    if (countdownTurn) { const i = thread.indexOf(countdownTurn); if (i >= 0) thread.splice(i, 1); countdownTurn = null; P.renderThread(false); }
    api.live(null);
  }

  async function recordOwnVoice(hours = null) {
    if (recordingOwn) return;
    recordingOwn = true;
    P.stopAmbient(); // the recorder takes the microphone
    let stream;
    try { stream = await P.openMicrophone(); } catch {
      recordingOwn = false; P.syncAmbient();
      P.say('Não consegui usar o microfone. Libere em Ajustes do Sistema > Privacidade > Microfone.');
      return;
    }
    const ctx = new AudioContext();
    try {
      tell('Fale por no máximo 10 segundos depois que ouvir o som plim no 3... 2... 1...');
      await waitQuiet(9000);
      const chunks = [];
      let peak = 0, spoke = false, quietSince = 0, floor = 0, frames = 0;
      const source = ctx.createMediaStreamSource(stream);
      const node = ctx.createScriptProcessor(4096, 1, 1);
      const mute = ctx.createGain(); mute.gain.value = 0;
      source.connect(node); node.connect(mute); mute.connect(ctx.destination);
      let capturing = false;
      node.onaudioprocess = (e) => {
        if (!capturing) return;
        const data = new Float32Array(e.inputBuffer.getChannelData(0));
        let sum = 0; for (const v of data) sum += v * v;
        const rms = Math.sqrt(sum / data.length);
        frames += 1; peak = Math.max(peak, rms);
        if (frames <= 3) floor = Math.max(floor, rms);  // the room before the person speaks
        else if (rms > Math.max(0.02, floor * 3)) { spoke = true; quietSince = 0; }
        else if (spoke && !quietSince) quietSince = Date.now();
        chunks.push(data);
      };
      P.chime();
      await sleep(450); // do not record the chime itself
      capturing = true;
      const started = Date.now();
      for (let left = 10; left >= 0; left--) {
        showCount(`${left}...`);
        const until = started + (10 - left + 1) * 1000;
        while (Date.now() < until) {
          await sleep(100);
          if (spoke && quietSince && Date.now() - quietSince > 1600) { left = -1; break; } // finished speaking: do not wait for the rest
        }
      }
      capturing = false;
      node.onaudioprocess = null;
      endCount();
      if (!spoke) { tell('Não ouvi nada. Clique em “Minha fala” para tentar de novo.'); return; }
      const wav = window.Wav.encodeWav(chunks, ctx.sampleRate);
      const res = await api.proposeRecorded(wav, hours);
      lastHours = hours;
      if (!res || res.error) { tell((res && res.error) || 'Não consegui guardar a gravação.'); return; }
      const id = res.action.id;
      const audio = await api.preview(id);
      if (audio && audio.dataUrl) {
        await new Promise((resolve) => {
          const player = new Audio(audio.dataUrl);
          player.onended = player.onerror = resolve;
          player.play().catch(resolve);
        });
        P.quietUntil = Date.now() + 700;
      }
      tell('Ouviu como ficou? Diga sim para confirmar, regravar ou cancelar.', { actionId: id, own: true, sinceState: P.stateVersion });
    } finally {
      endCount();
      releaseMic(stream, ctx);
      recordingOwn = false;
      P.syncAmbient();
    }
  }
  function releaseMic(stream, ctx) { stream.getTracks().forEach((t) => t.stop()); ctx.close().catch(() => {}); }

  async function redoOwnVoice(turn) {
    turn.decision = { text: 'Regravando…' };
    P.renderThread();
    await api.reject(turn.actionId);
    turn.decision = { text: 'Gravação descartada.' };
    P.renderThread();
    recordOwnVoice(lastHours);
  }

  P.inits.push(function () {
    // Automações: nothing to show yet; the button only says what is coming
    $('create-automation').addEventListener('click', () => waGate.run(P.showWhatsAppNotice, () => { $('automation-note').hidden = false; $('input').value = ''; P.startAutomationChips(); $('input').focus(); P.showSuggestions2(); }));
  });

  Object.assign(P, { renderAutomations, previewVoice, tell, recordOwnVoice, redoOwnVoice });

})();
