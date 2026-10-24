// Speaking aloud. Two voices, one interface: the voice of the operating system (default, works offline, costs nothing) and,
// when the person turned it on and it has been downloaded, a small neural voice synthesised on this computer. If the
// enhanced voice fails for any reason, the system voice speaks instead, so Chakmati is never silent. Shared by the panel
// and the floating widget.
(function () {
  let voice = null;
  let token = 0;       // a newer sentence replaces an older one, even if the older audio arrives late
  let playing = null;  // the <audio> element of the enhanced voice, if one is playing
  let ownSystemSpeech = false; // this window started speech with the system voice. The speech queue is shared by every window of
                               // the app, so a window must never cancel speech that another window started.

  function pick() {
    const voices = speechSynthesis.getVoices();
    voice = voices.find((v) => /^pt[-_]BR/i.test(v.lang)) || voices.find((v) => /^pt/i.test(v.lang)) || null;
  }
  if ('speechSynthesis' in window) {
    speechSynthesis.addEventListener('voiceschanged', pick);
    pick();
  }

  function systemSpeak(clean, my, { onStart, onEnd }) {
    if (!('speechSynthesis' in window) || my !== token) return;
    const u = new SpeechSynthesisUtterance(clean);
    u.lang = 'pt-BR';
    if (voice) u.voice = voice;
    u.onstart = () => onStart && onStart();
    u.onend = u.onerror = () => { if (my === token) ownSystemSpeech = false; onEnd && onEnd(); };
    ownSystemSpeech = true;
    speechSynthesis.speak(u);
  }

  // onStart/onEnd let the character's mouth follow the speech and mute the microphone meanwhile.
  function speak(text, { onStart, onEnd, emojis = false, enhanced = false, speed = 'normal' } = {}) {
    const clean = window.SpeechText.speakable(text, { emojis });
    stop();
    if (!clean) return;
    const my = token;
    if (enhanced && window.assistant && window.assistant.voice) {
      window.assistant.voice.synthesize(clean, speed).then((res) => {
        if (my !== token) return;
        if (!res || res.error || !res.dataUrl) { systemSpeak(clean, my, { onStart, onEnd }); return; }
        const audio = new Audio(res.dataUrl);
        playing = audio;
        let ended = false;
        const finish = () => { if (ended) return; ended = true; if (playing === audio) playing = null; onEnd && onEnd(); };
        audio.onplaying = () => onStart && onStart();
        audio.onended = finish;
        audio.onerror = () => { if (!ended && my === token) { ended = true; playing = null; systemSpeak(clean, my, { onStart, onEnd }); } };
        audio.play().catch(() => { if (!ended && my === token) { ended = true; playing = null; systemSpeak(clean, my, { onStart, onEnd }); } });
      }).catch(() => systemSpeak(clean, my, { onStart, onEnd }));
      return;
    }
    systemSpeak(clean, my, { onStart, onEnd });
  }

  function stop() {
    token += 1;
    if (playing) { playing.pause(); playing = null; }
    if (ownSystemSpeech && 'speechSynthesis' in window) { speechSynthesis.cancel(); ownSystemSpeech = false; }
  }

  window.Voice = { speak, stop };
})();
