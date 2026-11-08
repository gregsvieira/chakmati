// Ajustes: the settings page, the voice settings, and settings changed by speaking ("desligue o som").

(function () {
  const P = window.Panel;
  const { $, thread, api } = P;

  const PERSONALITY_NAMES = { padrao: 'Padrão', carioca: 'Carioca', paulista: 'Paulista', gaucho: 'Gaúcho', nordestino: 'Nordestino', mineiro: 'Mineiro' };

  // The select lists the installed personalities; the checkboxes install or remove the others (Padrão and the one in use stay).
  function renderPersonalities() {
    const s = P.state.settings;
    const installed = s.personalities || Object.keys(PERSONALITY_NAMES);
    const active = s.personality || 'padrao';
    $('set-personality').replaceChildren(...installed.map((id) => Object.assign(document.createElement('option'), { value: id, textContent: PERSONALITY_NAMES[id] || id })));
    $('set-personality').value = active;
    $('personality-list').replaceChildren(...Object.keys(PERSONALITY_NAMES).map((id) => {
      const box = Object.assign(document.createElement('input'), { type: 'checkbox', checked: installed.includes(id), disabled: id === 'padrao' || id === active });
      box.addEventListener('change', () => api.setSetting('personalities', Object.keys(PERSONALITY_NAMES).filter((p) => (p === id ? box.checked : installed.includes(p)))));
      const label = document.createElement('label');
      label.append(box, ` ${PERSONALITY_NAMES[id]}`);
      return label;
    }));
  }

  function renderSettings() {
    $('set-protect').checked = !!P.state.settings.protect;
    $('set-masked').checked = !!P.state.settings.masked;
    $('set-side').value = P.state.settings.bubbleSide;
    $('set-mood').value = P.state.settings.mood;
    renderPersonalities();
    $('set-pronouns').value = P.state.settings.pronouns || 'none';
    $('set-still').checked = !!P.state.settings.still;
    $('set-hear').checked = !!P.state.settings.hear;
    $('set-talk').checked = !!P.state.settings.talk;
    $('set-emojis').checked = !!P.state.settings.speakEmojis;
    renderVoiceSettings();
    $('set-mic').value = P.state.settings.micSource;
    $('set-autosend').checked = !!P.state.settings.autoSend;
    $('set-keepawake').checked = !!P.state.settings.keepAwake;
    $('set-autorun').checked = !!P.state.settings.autoRunSafe;
    if (!P.state.settings.hear) { window.Voice.stop(); P.speaking = false; }
    P.syncAmbient();
    P.updateHint();
    document.body.toggleAttribute('data-still', !!P.state.settings.still);
    $('set-glass').checked = !!P.state.settings.glass;
    document.body.toggleAttribute('data-flat', !P.state.settings.glass);   // glass off: flat panes (the CSS drops every blur)
    $('set-whatsapp').checked = !!P.state.settings.whatsapp;
    $('set-calendar').checked = !!P.state.settings.calendar;
    $('set-research').checked = !!P.state.settings.research;
    if (P.renderCloud) P.renderCloud();   // the paid-AI section lives in features/cloud/renderer/cloud.js
    if (P.renderHome) P.renderHome();   // the smart-house section lives in features/home/renderer/home.js
    const wa = (P.state.overview && P.state.overview.whatsapp) || { enabled: false };
    $('wa-status').textContent = !wa.enabled ? 'Ler, resumir e enviar mensagens (sempre com a sua aprovação).'
      : wa.error ? 'O OpenWA está ligado, mas deu erro ao ler o WhatsApp. Reinicie o OpenWA abaixo.'
      : wa.connected ? 'Conectado.' : 'Ligado, mas sem conexão. Conecte abaixo.';
    $('wa-connect').hidden = !(P.state.settings.whatsapp && P.state.canOpenWa && wa.enabled && !wa.connected);  // an error also shows it: restarting OpenWA is the cure
    const hint = $('engine-hint');
    hint.hidden = P.state.ownsEngine || !P.state.engineUp;
    hint.textContent = 'O motor foi iniciado por fora do Chakmati: reinicie-o para aplicar estas opções.';
    $('hotkeys').textContent = `Atalhos: abrir ou fechar ${P.state.hotkeys.toggle}; ocultar tudo ${P.state.hotkeys.panic}.`;
  }

  // Ajustes > Voz melhorada: off by default (the voice of the system); turning it on downloads the voice the first time.
  function renderVoiceSettings() {
    const v = P.state.voice;
    const on = !!P.state.settings.enhancedVoice;
    $('set-enhanced').checked = on;
    $('set-voicespeed').value = P.state.settings.voiceSpeed;
    const downloading = !!(v && v.downloading);
    let text = `Usa a voz do sistema. Ligando, o Chakmati baixa uma voz neural em português do Brasil (cerca de ${v ? Math.round(v.size_mb) : 63} MB, uma única vez) e fala com ela, no seu computador.`;
    if (downloading) text = `Baixando a voz melhorada… ${Math.round((v.progress || 0) * 100)}%`;
    else if (on && v && v.installed) text = 'Voz melhorada ligada. Funciona sem internet.';
    else if (v && v.error) text = `Não consegui baixar: ${v.error}`;
    $('enhanced-status').textContent = text;
    $('voice-progress').hidden = !downloading;
    $('voice-progress').value = downloading ? Math.round((v.progress || 0) * 100) : 0;
    $('remove-voice').hidden = !(v && v.installed) || downloading;
    $('set-voicespeed').closest('.field').hidden = !on;
  }

  // Settings by conversation: "liga a voz melhorada". Rules on the person's own words, so it never reaches the engine.
  let pendingSetting = null;
  const awaitingSetting = () => !!(pendingSetting && Date.now() < pendingSetting.until);
  function trySettings(clean) {
    const SI = window.SettingsIntent;
    let result = null;
    if (awaitingSetting()) {
      const answer = SI.verdict(clean);
      if (answer) { result = { answer, change: pendingSetting }; pendingSetting = null; }
      else pendingSetting = null; // anything else cancels the question
    }
    if (result) {
      thread.push({ role: 'user', text: clean, status: 'done' });
      if (result.answer === 'yes') applyIntent(result.change); else P.tell('Certo, não mudei nada.');
      return true;
    }
    const intent = SI.parse(clean);
    if (!intent) return false;
    thread.push({ role: 'user', text: clean, status: 'done' });
    if (intent.sensitive) { pendingSetting = { ...intent, until: Date.now() + 30000 }; P.tell(intent.ask); } else applyIntent(intent);
    return true;
  }
  async function applyIntent(intent) {
    const res = await api.setSetting(intent.key, intent.value);
    P.tell(res && res.ok ? intent.done : 'Não consegui mudar essa configuração.');
  }

  P.inits.push(function () {
    $('set-protect').addEventListener('change', (e) => api.setSetting('protect', e.target.checked));
    $('set-masked').addEventListener('change', (e) => api.setSetting('masked', e.target.checked));

    $('set-research').addEventListener('change', (e) => api.setSetting('research', e.target.checked));
    $('set-calendar').addEventListener('change', (e) => api.setSetting('calendar', e.target.checked));

    $('set-autosend').addEventListener('change', (e) => api.setSetting('autoSend', e.target.checked));
    $('set-keepawake').addEventListener('change', (e) => api.setSetting('keepAwake', e.target.checked));
    $('set-autorun').addEventListener('change', (e) => api.setSetting('autoRunSafe', e.target.checked));
    $('set-enhanced').addEventListener('change', (e) => api.setSetting('enhancedVoice', e.target.checked));
    $('set-voicespeed').addEventListener('change', (e) => api.setSetting('voiceSpeed', e.target.value));
    $('remove-voice').addEventListener('click', async () => { await api.removeVoice(); });
    $('set-emojis').addEventListener('change', (e) => api.setSetting('speakEmojis', e.target.checked));
    $('set-mic').addEventListener('change', (e) => api.setSetting('micSource', e.target.value));
    $('set-hear').addEventListener('change', (e) => api.setSetting('hear', e.target.checked));
    $('set-talk').addEventListener('change', (e) => api.setSetting('talk', e.target.checked));

    $('set-still').addEventListener('change', (e) => api.setSetting('still', e.target.checked));
    $('set-glass').addEventListener('change', (e) => api.setSetting('glass', e.target.checked));
    $('set-mood').addEventListener('change', (e) => api.setSetting('mood', e.target.value));
    $('set-personality').addEventListener('change', (e) => api.setSetting('personality', e.target.value));
    $('set-pronouns').addEventListener('change', (e) => api.setSetting('pronouns', e.target.value));
    $('set-side').addEventListener('change', (e) => api.setSetting('bubbleSide', e.target.value));
  });

  Object.assign(P, { renderSettings, awaitingSetting, trySettings });

})();
