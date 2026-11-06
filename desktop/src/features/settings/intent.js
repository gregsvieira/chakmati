'use strict';
// Everything in Ajustes can also be asked for by talking or typing: "liga a voz melhorada", "desliga o modo discreto",
// "balão embaixo". This is plain rules on the person's own words (no model, nothing from the outside world reaches it), so
// it is predictable and cannot be steered by a message or a web page.
(function (root) {
  const plain = (s) => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9\s]/g, ' ').replace(/\s+/g, ' ').trim();

  const ON = /\b(liga|ligue|ligar|ativa|ative|ativar|habilita|habilite|habilitar|coloca|coloque|colocar|quero|permite|permita)\b/;
  const OFF = /\b(desliga|desligue|desligar|desativa|desative|desativar|desabilita|desabilite|desabilitar|tira|tire|tirar|remove|remova|para de|pare de|nao quero|bloqueia|bloqueie)\b/;
  const QUESTION = /^(como|o que|qual|quais|por que|porque|quando|onde|quem|voce|tem como|da pra|posso)\b/;

  // key, the words that name it, how it is called when answering, and whether changing it asks for a confirmation first.
  const SWITCHES = [
    { key: 'enhancedVoice', re: /\bvoz (melhorada|neural|natural)\b/, name: 'a voz melhorada' },
    { key: 'speakEmojis', re: /\bemojis?\b/, name: 'a leitura dos emojis' },
    { key: 'autoSend', re: /\b(envio automatico|envio sem (pedir )?aprovacao|enviar sem (pedir )?aprovacao|enviar sem aprovar|aprovar (automaticamente|sempre|as proximas)|aprovacao automatica)\b/, name: 'o envio sem pedir aprovação', sensitive: true },
    { key: 'autoRunSafe', re: /\b(manter (os )?comandos (seguros )?aprovados|aprovar (os )?comandos (seguros )?(automaticamente|sempre)|comandos seguros)\b/, name: 'a aprovação automática dos comandos seguros', sensitive: true },
    { key: 'masked', re: /\b(modo discreto|discreto|esconder (os )?nomes|ocultar (os )?nomes)\b/, name: 'o modo discreto', sensitive: true },
    { key: 'protect', re: /\b(protecao de tela|proteger a tela|esconder (da|na|das|nas) (tela|gravac\w+|compartilh\w+)|ficar invisivel)\b/, name: 'a proteção contra gravação de tela', sensitive: true },
    { key: 'still', re: /\b(animacoes?|animado|ficar parado|estatico)\b/, name: 'as animações', invert: true },
    { key: 'talk', re: /\b(falar com (o )?(chakmati|xacmati)|escutar|me ouvir|ouvir (a )?minha voz|microfone|modo de escuta)\b/, name: 'o falar com o Chakmati' },
    { key: 'hear', re: /\b(ouvir (o )?(chakmati|xacmati)|falar em voz alta|ler em voz alta|voz alta|responder falando|falar as respostas)\b/, name: 'o ouvir o Chakmati' },
    { key: 'whatsapp', re: /\bwhats\w*|\bzap\w*|\bwpp\b/, name: 'o WhatsApp' },
    { key: 'calendar', re: /\b(agenda|calendario)\b/, name: 'a agenda' },
    { key: 'research', re: /\b(pesquisa|pesquisar|buscar) (na )?(internet|web)\b|\bpesquisa na internet\b/, name: 'a pesquisa na internet' },
  ];

  // Values with several choices.
  const CHOICES = [
    { key: 'bubbleSide', re: /\b(balao|bolha|aviso)\b/, name: 'o balão', options: [
      [/\b(embaixo|em baixo|abaixo|parte de baixo)\b/, 'bottom', 'embaixo'], [/\b(em cima|acima|parte de cima|topo)\b/, 'top', 'em cima'],
      [/\besquerda\b/, 'left', 'à esquerda'], [/\bdireita\b/, 'right', 'à direita'], [/\bautomatic\w*\b/, 'auto', 'no automático']] },
    { key: 'mood', re: /\bhumor\b|\bcara\b|\bexpressao\b/, name: 'o humor', options: [
      [/\bfeliz|alegre|contente\b/, 'happy', 'feliz'], [/\bcalm[oa]|tranquil[oa]\b/, 'idle', 'calmo'], [/\balerta\b/, 'alert', 'alerta'],
      [/\bpensativ[oa]\b/, 'thinking', 'pensativo'], [/\bautomatic\w*\b/, 'auto', 'automático']] },
    { key: 'personality', re: /\b(personalidade|sotaque|jeito de falar|modo de falar)\b/, name: 'a personalidade', options: [
      [/\bcarioc\w*\b/, 'carioca', 'carioca'], [/\bpaulist\w*\b/, 'paulista', 'paulista'], [/\bgauch\w*\b|\bsulista\b/, 'gaucho', 'gaúcha'],
      [/\bnordestin\w*\b/, 'nordestino', 'nordestina'], [/\bmineir\w*\b/, 'mineiro', 'mineira'],
      [/\b(padrao|normal|neutr\w*|sem sotaque)\b/, 'padrao', 'padrão']] },
    { key: 'pronouns', re: /\bpronomes?\b/, name: 'os pronomes', options: [
      [/\belu\b/, 'elu', 'elu/delu'], [/\bela\b/, 'ela', 'ela/dela'], [/\bele\b/, 'ele', 'ele/dele'],
      [/\b(nao informar|nenhum|sem pronome|prefiro nao)\b/, 'none', 'sem informar']] },
    { key: 'voiceSpeed', re: /\b(velocidade|voz)\b/, name: 'a velocidade da voz', options: [
      [/\b(mais rapid[ao]|rapid[ao]|acelera\w*)\b/, 'fast', 'mais rápida'], [/\b(normal|mais devagar|devagar|lent[ao])\b/, 'normal', 'normal']] },
    { key: 'micSource', re: /\bmicrofone\b/, name: 'o microfone', options: [
      [/\b(do computador|do mac|interno|do proprio)\b/, 'computer', 'do próprio computador'], [/\b(padrao|do sistema)\b/, 'system', 'padrão do sistema']] },
  ];

  // -> null (not a settings request) or { key, value, sensitive, done, ask }
  function parse(text) {
    const t = plain(text);
    if (!t || t.split(' ').length > 14 || QUESTION.test(t)) return null;

    for (const c of CHOICES) {
      if (!c.re.test(t)) continue;
      // "microfone" alone with on/off belongs to the talk switch; a choice needs one of its own words
      const hit = c.options.find(([re]) => re.test(t));
      if (hit) return { key: c.key, value: hit[1], sensitive: false, done: `Pronto: ${c.name} ${hit[2]}.`, ask: '' };
    }

    const off = OFF.test(t);
    const on = !off && ON.test(t);
    if (!off && !on) return null;
    const wantsOn = on;
    for (const s of SWITCHES) {
      if (!s.re.test(t)) continue;
      const value = s.invert ? !wantsOn : wantsOn;
      const shown = s.invert ? wantsOn : value; // "desligar animações" reads as turning animations off
      const sensitive = !!s.sensitive;
      const done = `Pronto: ${s.name} ${shown ? 'ligad' : 'desligad'}${/^(a|as)\b/.test(s.name) ? 'a' : 'o'}${/^(as|os)\b/.test(s.name) ? 's' : ''}.`;
      return { key: s.key, value, sensitive, done, ask: sensitive ? `Isso mexe em privacidade ou envio: vou ${shown ? 'ligar' : 'desligar'} ${s.name}. Confirma? Diga sim ou não.` : '' };
    }
    return null;
  }

  const YES = new Set(['sim', 'confirmo', 'confirma', 'pode', 'pode sim', 'isso', 'isso mesmo', 'claro', 'ok', 'certo', 'faz', 'pode fazer', 'manda ver']);
  const NO = new Set(['nao', 'cancela', 'cancele', 'deixa', 'deixa pra la', 'esquece', 'nao quero', 'melhor nao', 'para']);
  function verdict(text) {
    const t = plain(text);
    if (NO.has(t) || /^nao\b/.test(t) && t.split(' ').length <= 3) return 'no';
    if (YES.has(t)) return 'yes';
    return null;
  }

  const api = { parse, verdict, plain };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.SettingsIntent = api;
})(typeof window !== 'undefined' ? window : globalThis);
