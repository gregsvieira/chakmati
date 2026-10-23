'use strict';
// The sentence the robot says about itself in the panel header, and the mood of its face.

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

function describe({ engineUp, overview, busy = false } = {}) {
  if (!engineUp) {
    return { title: 'Não consigo falar com o motor.', detail: 'Inicie o lite-agent e eu volto sozinho.', mood: 'offline' };
  }
  if (busy) return { title: 'Pensando…', detail: 'Já volto com a resposta.', mood: 'thinking' };

  const o = overview || {};
  const pending = (o.pending || []).length;
  if (pending > 0) {
    const what = pending === 1 ? 'Há 1 ação aguardando' : `Há ${pending} ações aguardando`;
    return { title: 'Preciso da sua decisão.', detail: `${what} a sua aprovação.`, mood: 'alert' };
  }

  const wa = o.whatsapp || {};
  const parts = [];
  const unread = (wa.unread || []).length;
  if (unread > 0) parts.push(`${plural(unread, 'conversa', 'conversas')} com mensagens não lidas`);
  const events = ((o.calendar || {}).today || []).length;
  if (events > 0) parts.push(`${plural(events, 'compromisso', 'compromissos')} hoje`);

  const notes = [];
  if (wa.enabled && (wa.error || wa.connected === false)) notes.push('O WhatsApp está desconectado.');
  if (parts.length) notes.push(`Você tem ${parts.join(' e ')}.`);
  return { title: 'Tudo certo por aqui.', detail: notes.length ? notes.join(' ') : 'Nada novo por enquanto.', mood: 'idle' };
}

module.exports = { describe, plural };
