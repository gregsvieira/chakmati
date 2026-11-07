'use strict';
// The wizard's screens. It only shows what the main process computed and sends back the ids the person ticked;
// the main process recomputes the plan itself, so nothing here can change what gets installed.
const api = window.assistant.installer;
const $ = (id) => document.getElementById(id);

function el(tag, props, ...kids) {
  const node = document.createElement(tag);
  Object.assign(node, props || {});
  node.append(...kids);
  return node;
}
const items = (list, texts) => list.replaceChildren(...texts.map((t) => el('li', { textContent: t })));
const show = (name) => { for (const s of document.querySelectorAll('main > section')) s.hidden = s.id !== `s-${name}`; };

let scan;
let face = null;   // the tiny Chakmati that says the remark about the computer
const chosen = new Set();
const profile = { personality: 'padrao', personalities: new Set(), pronouns: 'none' };   // how the Chakmati speaks: the default, the ones to install too, the pronouns
const profileOut = () => ({ personality: profile.personality, personalities: [...profile.personalities], pronouns: profile.pronouns });

// WhatsApp: the first time it is ticked, a notice about not getting the number blocked has to be read ("Compreendi e estou ciente!").
// Esc or a click outside closes it without ticking the box.
const waGate = window.NoticeGate.createGate((() => { try { return window.localStorage; } catch { return { getItem: () => null, setItem: () => {} }; } })(), 'chakmati.whatsapp-notice');
function showWhatsAppNotice(onAck, onCancel) {
  const modal = $('notice-modal');
  const finish = (fn) => { modal.hidden = true; document.removeEventListener('keydown', onKey, true); modal.removeEventListener('mousedown', onOutside); fn(); };
  const onKey = (e) => {
    if (e.key === 'Escape') { e.preventDefault(); finish(onCancel); } else if (e.key === 'Tab') { e.preventDefault(); $('notice-ok').focus(); }
  };
  const onOutside = (e) => { if (e.target === modal) finish(onCancel); };
  $('notice-ok').onclick = () => finish(onAck);
  modal.hidden = false;
  document.addEventListener('keydown', onKey, true);
  modal.addEventListener('mousedown', onOutside);
  $('notice-ok').focus();
}

async function start() {
  scan = await api.scan();
  const rows = [['Sistema', scan.hwText.system], ['Memória RAM', scan.hwText.ram], ['Espaço livre', scan.hwText.disk], ['Núcleos', scan.hwText.cores]];
  $('hw').replaceChildren(...rows.map(([k, v]) => el('div', { className: 'row' }, el('span', { textContent: k }), el('strong', { textContent: v }))));
  $('quip-row').hidden = !scan.quip;
  if (scan.quip) {
    $('quip').textContent = scan.quip.text;
    if (!face) { face = window.Robot.create($('quip-face')); face.svg.setAttribute('viewBox', '26 4 42 54'); }   // only his head, tiny
    face.setMood(scan.quip.tone === 'praise' ? 'happy' : 'idle');
  }
  $('verdict').textContent = scan.levelText;
  $('verdict').dataset.level = scan.verdict.level;
  items($('reasons'), [...scan.verdict.reasons, ...scan.verdict.notes]);
  const usable = scan.verdict.level !== 'unsupported';
  $('ollama-help').hidden = !usable || scan.ollamaUp;
  $('to-options').hidden = !usable;
  $('to-options').disabled = !scan.ollamaUp;
  show('check');
}

function renderProfile() {
  const radios = (host, name, list, current, onPick) => host.replaceChildren(...list.map((o) => {
    const input = el('input', { type: 'radio', name, value: o.id, checked: o.id === current });
    input.addEventListener('change', () => onPick(o.id));
    return el('label', {}, input, o.name);
  }));
  const more = () => {
    profile.personalities.delete(profile.personality);   // the default is installed anyway
    $('profile-more').replaceChildren(...scan.profile.personalities.filter((o) => o.id !== 'padrao' && o.id !== profile.personality).map((o) => {
      const box = el('input', { type: 'checkbox', checked: profile.personalities.has(o.id) });
      box.addEventListener('change', () => { if (box.checked) profile.personalities.add(o.id); else profile.personalities.delete(o.id); });
      return el('label', {}, box, o.name);
    }));
  };
  radios($('profile-personality'), 'personality', scan.profile.personalities, profile.personality, (id) => { profile.personality = id; more(); });
  radios($('profile-pronouns'), 'pronouns', scan.profile.pronouns, profile.pronouns, (id) => { profile.pronouns = id; });
  more();
  show('profile');
}

function renderOptions() {
  $('model-line').textContent = `Obrigatórios: ${scan.engineText ? `o motor do Chakmati (cerca de ${scan.engineText}) e ` : ''}o modelo de conversa para este computador, ${scan.model.label} (${scan.model.id}, ${scan.model.sizeText}). Sem eles o Chakmati não funciona.`;
  $('options').replaceChildren(...scan.options.map((o) => {
    const box = el('input', { type: 'checkbox', id: `opt-${o.id}` });
    box.addEventListener('change', () => {
      if (box.checked && o.id === 'whatsapp') {
        box.checked = false;  // ticked only after the notice was acknowledged
        waGate.run(showWhatsAppNotice, () => { box.checked = true; chosen.add(o.id); });
        return;
      }
      if (box.checked) chosen.add(o.id); else chosen.delete(o.id);
    });
    const title = el('span', { className: 'name', textContent: o.label });
    if (scan.suggested[o.id]) title.append(el('span', { className: 'badge', textContent: 'Recomendado para este PC' }));
    const text = el('span', {}, title, el('br'), el('span', { textContent: o.description }), el('br'), ...(o.advice ? [el('span', { className: 'advice', textContent: o.advice }), el('br')] : []), el('span', { className: 'cost', textContent: o.costText }));
    return el('li', {}, el('label', {}, box, text));
  }));
  show('options');
}

async function renderSummary() {
  const plan = await api.plan([...chosen], profileOut());
  if (!plan.ok) {
    items($('steps'), plan.blocked);
    $('totals').textContent = '';
    $('install').disabled = true;
  } else {
    items($('steps'), plan.steps.map((s) => `${s.label}${s.required ? ' — obrigatório' : ''}${s.approval ? ' — vai pedir sua aprovação' : ''}`));
    $('totals').textContent = plan.totalsText;
    $('install').disabled = false;
  }
  items($('warnings'), plan.warnings);
  show('summary');
}

async function install() {
  show('run');
  $('bar').value = 0;
  $('run-title').textContent = 'Instalando…';
  $('run-details').hidden = true;
  $('finish').hidden = true;
  const off = api.onProgress((p) => {
    $('run-status').textContent = p.total ? `${p.status} (${Math.round((p.completed / p.total) * 100)}%)` : p.status;
    if (p.total) $('bar').value = Math.round((p.completed / p.total) * 100);
  });
  const result = await api.run([...chosen], profileOut());
  off();
  const titles = { done: 'Pronto!', aborted: 'Instalação cancelada', failed: 'A instalação falhou', blocked: 'Não foi possível instalar' };
  $('run-title').textContent = titles[result.status] || 'Fim';
  $('bar').value = result.status === 'done' ? 100 : $('bar').value;
  $('run-status').textContent = result.status === 'aborted' ? 'O motor e o modelo de conversa são obrigatórios: sem eles o Chakmati não funciona. Abra o instalador de novo quando quiser.' : '';
  const names = { done: 'feito', declined: 'pulado por você', failed: 'falhou' };
  items($('results'), result.results.map((r) => `${r.id}: ${names[r.status]}${r.error ? ` — ${r.error}` : ''}`));
  items($('after'), result.after || []);
  $('after-details').hidden = !(result.after || []).length;
  if (result.status === 'done') return showDone(true);   // one short screen of its own, with the optional house step
  $('run-details').hidden = false;
  $('finish').hidden = false;
  return undefined;
}

// The end: "installed" and the one optional thing left. After the house step (or without it) the same screen only says it is over.
function showDone(offerHome) {
  $('done-title').textContent = offerHome ? 'O Chakmati está instalado' : 'Tudo pronto!';
  $('done-lead').hidden = !offerHome;
  $('home-setup').hidden = !offerHome;
  $('done-finish').textContent = offerHome ? 'Agora não' : 'Concluir';
  $('done-finish').className = offerHome ? '' : 'primary';
  show('done');
}

// The smart house and the Alexa: the same flow as Ajustes (home/renderer/flow.js), shown as one more screen. It needs the engine, which the main process starts for it.
const homeFlow = window.HomeFlow.create({
  $, api, locale: navigator.language, rootId: 's-home',
  labels: { cancel: 'Voltar', close: 'Concluir', skip: 'Agora não' },
  onClose: () => showDone(false),
});
homeFlow.bind();
$('home-setup').addEventListener('click', async () => {
  $('home-setup').disabled = true;
  const ready = await api.homePrepare();
  $('home-setup').disabled = false;
  if (ready && ready.error) { items($('after'), [`Casa e Alexa: ${ready.error} Você pode fazer isso depois em Ajustes.`]); return; }
  show('home');
  try { await homeFlow.open(); } catch { showDone(true); $('done-lead').textContent = 'Não consegui abrir a conexão da casa agora. Você pode fazer isso depois, em Ajustes.'; $('home-setup').hidden = true; }   // never an empty screen
});

$('to-options').addEventListener('click', renderProfile);
$('back-check2').addEventListener('click', () => show('check'));
$('to-options2').addEventListener('click', renderOptions);
$('back-profile').addEventListener('click', renderProfile);
$('to-summary').addEventListener('click', renderSummary);
$('back-options').addEventListener('click', () => show('options'));
$('install').addEventListener('click', install);
$('finish').addEventListener('click', () => api.finish());
$('done-finish').addEventListener('click', () => api.finish());
$('open-ollama').addEventListener('click', () => api.ollamaPage());
$('recheck').addEventListener('click', start);

start();
