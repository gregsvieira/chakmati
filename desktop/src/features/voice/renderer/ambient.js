// Hear and talk: reading answers aloud, the always-on microphone, wake phrases, the chime, hints.

(function () {
  const P = window.Panel;
  const { api, syncTalking, $, input, awaitingSetting } = P;

  // The answer is done. With the panel open it is spoken here; with the panel closed it appears as a bubble by the
  // character (the floating window speaks it if "Ouvir" is on), and nothing opens by itself.
  function deliver(turn) {
    if (!turn.text) return;
    if (P.state && !P.state.panelOpen) { if (!turn.actionId) api.reply(turn.text); return; }
    sayAloud(turn.text);
  }

  function sayAloud(text) {
    if (!P.state || !P.state.settings.hear) return;
    window.Voice.speak(text, { emojis: !!P.state.settings.speakEmojis, enhanced: !!(P.state.settings.enhancedVoice && P.state.voice && P.state.voice.installed), speed: P.state.settings.voiceSpeed, onStart: () => { P.speaking = true; speakingSince = Date.now(); syncTalking(); }, onEnd: () => { P.speaking = false; P.quietUntil = Date.now() + 700; syncTalking(); updateHint(); chimeIfWaiting(); } });
  }

  // "Falar com o Chakmati": the microphone is always listening, with no button to press. It acts only on a wake phrase
  // ("Ôh, Xácmáti") or while it is already waiting for a command, so conversation in the room never reaches the assistant.
  const micButton = $('mic');
  const JUNK = /^(obrigad[oa]\.?|tchau\.?|legendas.*|\.+|…)$/i;
  let ambient = null;
  let starting = false;
  let transcribing = false;
  let speechInProgress = false;
  let ambientWarned = false;
  const diag = (window.__listening = { frames: 0, starts: 0, ends: 0, drops: 0, sent: 0, heard: [], peak: 0, floor: 0, muted: 0, restarts: 0 });
  let speakingSince = 0;
  let queued = null;
  P.otherSpeaking = false;
  let otherSince = 0;
  P.quietUntil = 0;
  const isMuted = () => {
    if (P.speaking && Date.now() - speakingSince > 90000) { P.speaking = false; window.Voice.stop(); } // a voice that never reports its end must not mute the microphone for good
    if (P.otherSpeaking && Date.now() - otherSince > 90000) { P.otherSpeaking = false; diag.unstuck = (diag.unstuck || 0) + 1; } // the same for the floating window: a lost "stopped speaking" must not keep the microphone off for good
    return P.speaking || P.otherSpeaking || Date.now() < P.quietUntil; // not while Chakmati talks: it would hear itself
  };

  function updateHint() {
    if (!P.state) return;
    const talk = P.state.settings.talk;
    const awake = !!(P.state.overview && P.state.overview.awake);
    input.placeholder = P.state.busy ? 'Trabalhando nisso… toque em Parar para interromper' : !talk ? 'Peça algo ao Chakmati…' : awake ? 'Aguardando seu comando… fale agora' : 'Escutando… diga “Ôh, Xácmáti”';
    micButton.classList.toggle('on', talk);
    micButton.classList.toggle('recording', talk && speechInProgress);
    micButton.hidden = !talk;
    micButton.title = talk ? 'Escutando. Clique para desligar.' : 'Falar com o Chakmati';
  }

  // A short "plim": the assistant finished talking and is now waiting for the command.
  let chimeCtx = null;
  function chime() {
    diag.chimes = (diag.chimes || 0) + 1;
    try {
      chimeCtx = chimeCtx || new AudioContext();
      if (chimeCtx.state === 'suspended') chimeCtx.resume();
      const t0 = chimeCtx.currentTime + 0.02;
      [[660, 0], [990, 0.11]].forEach(([freq, offset]) => {
        const osc = chimeCtx.createOscillator();
        const gain = chimeCtx.createGain();
        osc.type = 'sine';
        osc.frequency.value = freq;
        gain.gain.setValueAtTime(0.0001, t0 + offset);
        gain.gain.exponentialRampToValueAtTime(0.18, t0 + offset + 0.015);
        gain.gain.exponentialRampToValueAtTime(0.0001, t0 + offset + 0.16);
        osc.connect(gain);
        gain.connect(chimeCtx.destination);
        osc.start(t0 + offset);
        osc.stop(t0 + offset + 0.18);
      });
      P.quietUntil = Date.now() + 1000; // do not listen to our own chime
    } catch { /* no sound is not a problem */ }
  }

  // Only when the speech that just ended leaves the assistant waiting for a command (not after an ordinary answer).
  function chimeIfWaiting() {
    if (P.state && P.state.settings.talk && ((P.state.overview && P.state.overview.awake) || awaitingSetting())) chime();
  }

  async function handleUtterance(chunks, rate) {
    if (transcribing) return;
    transcribing = true;
    try {
      diag.sent += 1;
      const wait = new Promise((resolve) => setTimeout(() => resolve({ error: 'O reconhecimento de voz demorou demais.' }), 70000));
      const res = await Promise.race([api.transcribe(window.Wav.encodeWav(chunks, rate), 'audio/wav'), wait]);
      diag.heard.push(res && (res.text || res.error)); if (diag.heard.length > 8) diag.heard.shift();
      if (!res || res.error) {
        if (!ambientWarned) { ambientWarned = true; P.say((res && res.error) || 'Não consegui entender o áudio.'); }
        return;
      }
      const text = (res.text || '').trim();
      if (!window.ListenPolicy.shouldAct({ text, wake: res.wake, awake: res.awake || awaitingSetting() })) return;
      if (P.state && P.state.busy) { queued = { text, at: Date.now() }; return; } // still answering the last one: do this next
      P.submit(text, { voice: true });
    } finally {
      transcribing = false;
    }
  }

  // A command heard while the answer to the previous one was still being produced runs as soon as that one ends.
  function runQueued() {
    if (!queued || (P.state && P.state.busy)) return;
    const item = queued;
    queued = null;
    if (Date.now() - item.at < 30000) P.submit(item.text, { voice: true });
  }

  // The computer's own microphone (the built-in one), not whatever virtual or Bluetooth device the system made the default.
  // The names of the devices are only readable after the first permission, hence the second open.
  async function openMicrophone() {
    const base = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };
    let stream = await navigator.mediaDevices.getUserMedia({ audio: base });
    ambientSource = P.state.settings.micSource;
    if (ambientSource !== 'computer') return stream;
    const builtIn = /built-?in|macbook|interno|integrado|internal|imac|studio display/i;
    const devices = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'audioinput' && !['default', 'communications'].includes(d.deviceId));
    const wanted = devices.find((d) => builtIn.test(d.label));
    if (wanted && !builtIn.test(stream.getAudioTracks()[0].label || '')) {
      stream.getTracks().forEach((t) => t.stop());
      stream = await navigator.mediaDevices.getUserMedia({ audio: { ...base, deviceId: { exact: wanted.deviceId } } });
    }
    diag.microphone = stream.getAudioTracks()[0].label;
    return stream;
  }

  async function startAmbient() {
    if (ambient || starting || !P.state || !P.state.settings.talk) return;
    starting = true;
    let stream;
    try {
      stream = await openMicrophone();
    } catch {
      starting = false;
      P.say('Não consegui usar o microfone. Libere em Ajustes do Sistema > Privacidade > Microfone e ligue de novo.');
      api.setSetting('talk', false);
      return;
    }
    starting = false;
    if (!P.state || !P.state.settings.talk) { stream.getTracks().forEach((t) => t.stop()); return; }
    const ctx = new AudioContext();
    const source = ctx.createMediaStreamSource(stream);
    const node = ctx.createScriptProcessor(4096, 1, 1);
    const silent = ctx.createGain();
    silent.gain.value = 0; // the processor must be connected to run, but nothing is played back
    source.connect(node);
    node.connect(silent);
    silent.connect(ctx.destination);
    const detector = window.Vad.createAmbient({});
    const preRoll = [];
    let utterance = null;
    node.onaudioprocess = (e) => {
      if (ambient) ambient.lastFrame = Date.now();
      const data = new Float32Array(e.inputBuffer.getChannelData(0));
      let sum = 0;
      for (const v of data) sum += v * v;
      const rms = Math.sqrt(sum / data.length);
      micButton.style.setProperty('--level', String(Math.min(rms * 6, 0.6)));
      diag.frames += 1; diag.peak = Math.max(diag.peak, rms); diag.floor = detector.floor || 0;
      if (isMuted()) { diag.muted += 1; utterance = null; preRoll.length = 0; if (speechInProgress) { speechInProgress = false; updateHint(); } return; }
      const event = detector.push(rms, (data.length / ctx.sampleRate) * 1000);
      if (utterance) utterance.push(data);
      if (event === 'start') diag.starts += 1;
      if (event === 'end') diag.ends += 1;
      if (event === 'drop') diag.drops += 1;
      if (event === 'start') { utterance = [...preRoll, data]; speechInProgress = true; updateHint(); }
      else if (!utterance) { preRoll.push(data); if (preRoll.length > 8) preRoll.shift(); }
      if (event === 'end' || event === 'drop') {
        const chunks = utterance;
        utterance = null;
        preRoll.length = 0;
        speechInProgress = false;
        updateHint();
        if (event === 'end' && chunks) handleUtterance(chunks, ctx.sampleRate);
      }
    };
    ambient = { ctx, lastFrame: Date.now(), stop() { node.onaudioprocess = null; stream.getTracks().forEach((t) => { t.onended = null; t.stop(); }); ctx.close().catch(() => {}); } };
    // the microphone was taken away (unplugged, another app, the Mac went to sleep): start listening again
    stream.getAudioTracks().forEach((track) => { track.onended = () => { diag.restarts += 1; stopAmbient(); setTimeout(P.syncAmbient, 800); }; });
  }

  function stopAmbient() {
    if (!ambient) return;
    ambient.stop();
    ambient = null;
    speechInProgress = false;
    micButton.style.setProperty('--level', '0');
  }

  let ambientSource = null;

  P.syncAmbient = () => {
    if (ambient && P.state && ambientSource !== P.state.settings.micSource) stopAmbient(); // the person chose another microphone
    if (P.state && P.state.settings.talk) startAmbient(); else stopAmbient();
  };

  P.inits.push(function () {
    diag.chime = chime;

    // Watchdog: if the audio stops flowing (suspended after sleep, device gone) the loop is rebuilt, never left deaf.
    setInterval(() => {
      updateHint();
      if (!ambient || !P.state || !P.state.settings.talk) return;
      if (ambient.ctx.state !== 'running') ambient.ctx.resume().catch(() => {});
      if (Date.now() - ambient.lastFrame > 5000) { diag.restarts += 1; stopAmbient(); startAmbient(); }
    }, 4000);

    micButton.addEventListener('click', () => api.setSetting('talk', !P.state.settings.talk));

    api.onOtherSpeaking((on) => { P.otherSpeaking = on; otherSince = on ? Date.now() : 0; if (!on) { P.quietUntil = Date.now() + 700; chimeIfWaiting(); } });
  });

  Object.assign(P, { deliver, sayAloud, updateHint, chime, runQueued, openMicrophone, stopAmbient });

})();
