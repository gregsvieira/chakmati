// Speaking aloud with the voices of the operating system (works offline). Shared by the panel and the floating widget.
(function () {
  let voice = null;
  function pick() {
    const voices = speechSynthesis.getVoices();
    voice = voices.find((v) => /^pt[-_]BR/i.test(v.lang)) || voices.find((v) => /^pt/i.test(v.lang)) || null;
  }
  if ('speechSynthesis' in window) {
    speechSynthesis.addEventListener('voiceschanged', pick);
    pick();
  }

  // onStart/onEnd let the character's mouth follow the speech.
  function speak(text, { onStart, onEnd, emojis = false } = {}) {
    if (!('speechSynthesis' in window)) return;
    const clean = window.SpeechText.speakable(text, { emojis });
    speechSynthesis.cancel();
    if (!clean) return;
    const u = new SpeechSynthesisUtterance(clean);
    u.lang = 'pt-BR';
    if (voice) u.voice = voice;
    u.onstart = () => onStart && onStart();
    u.onend = u.onerror = () => onEnd && onEnd();
    speechSynthesis.speak(u);
  }

  function stop() {
    if ('speechSynthesis' in window) speechSynthesis.cancel();
  }

  window.Voice = { speak, stop };
})();
