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
  if (!defaultsApplied) { defaultsApplied = true; for (const id of DEFAULT_ON) if (scan.options.some((o) => o.id === id)) chosen.add(id); }
  buildScreens();
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

// A few short screens, each with boxes to flag: nothing is installed until the summary. The first is the basics (the engine, and how the chat model runs: the local one,
// the person's paid AI, or both), then one screen per group of extras. The screens are built from the scan, so the list is the main process's.
const GROUPS = [
  { title: 'Voz', ids: ['voice', 'talk'] },
  { title: 'Modelos extras', ids: ['reasoning', 'laya'] },
  { title: 'Integrações', ids: ['whatsapp', 'homeInstall'] },   // 'home' (I already have a Home Assistant) is not offered: the house step finds the one on the network first
  { title: 'Aparência e privacidade', ids: ['animations', 'glass', 'hideShare'] },
];
// What comes flagged: the recommended integrations. They are the person's to unflag; WhatsApp still asks for the notice about the number being blocked first.
const DEFAULT_ON = ['whatsapp', 'homeInstall'];
const boxes = {};   // the checkbox of each item on the screen being shown
let whatsappAsked = false;
let defaultsApplied = false;
const model = { local: true, cloud: false, connected: false, provider: '', name: '' };   // how the chat model runs
const modelOut = () => ({ local: model.local, cloud: model.cloud && model.connected });
let ollamaWarn = null;   // the warning on the first screen (only for the local model, and only when the Ollama is not there)
let screens = [];   // 'basics' then the groups that have something on this computer
let step = 0;

function buildScreens() {
  const known = new Set(GROUPS.flatMap((g) => g.ids));
  const present = scan.options.map((o) => o.id);
  const groups = GROUPS.map((g) => ({ ...g, ids: g.ids.filter((id) => present.includes(id)) }));
  const rest = present.filter((id) => !known.has(id));
  if (rest.length) groups.push({ title: 'Outros', ids: rest });
  screens = [{ kind: 'basics' }, ...groups.filter((g) => g.ids.length).map((g) => ({ kind: 'group', ...g }))];
}

function flagRow(box, title, lines) {
  return el('label', { className: 'flag' }, box, el('span', {}, title, ...lines.flatMap((l) => [el('br'), l])));
}

function modelFlags() {
  const local = el('input', { type: 'checkbox', checked: model.local });
  local.addEventListener('change', () => { model.local = local.checked; if (ollamaWarn) ollamaWarn.hidden = scan.ollamaUp || !model.local; });
  const cloud = el('input', { type: 'checkbox', checked: model.cloud });
  cloud.addEventListener('change', () => { model.cloud = cloud.checked; });
  return [
    flagRow(local, el('span', { className: 'name', textContent: `Rodar com o modelo local: ${scan.model.label} (${scan.model.id}, ${scan.model.sizeText})` }),
      [el('span', { textContent: 'Funciona sem internet e sem gastar nada. É baixado neste computador.' })]),
    flagRow(cloud, el('span', { className: 'name', textContent: 'Quero rodar com a minha assinatura de IA paga' }),
      [el('span', { textContent: 'Claude, OpenAI… O Chakmati usa a sua IA primeiro; quando o limite dela acabar, usa o modelo local. Se você marcar só esta, não baixa o modelo local.' })]),
  ];
}

function groupFlags(ids) {
  return ids.map((id) => {
    const opt = scan.options.find((o) => o.id === id);
    const box = el('input', { type: 'checkbox', checked: chosen.has(id) });
    boxes[id] = box;
    box.addEventListener('change', () => {
      if (box.checked && id === 'whatsapp') {
        box.checked = false;   // flagged only after the notice was acknowledged
        waGate.run(showWhatsAppNotice, () => { box.checked = true; chosen.add(id); });
        return;
      }
      if (box.checked) chosen.add(id); else chosen.delete(id);
    });
    const title = el('span', { className: 'name', textContent: opt.label });
    if (scan.suggested[id] || DEFAULT_ON.includes(id)) title.append(el('span', { className: 'badge', textContent: 'Recomendado' }));
    const lines = [el('span', { textContent: opt.description })];
    if (opt.advice) lines.push(el('span', { className: 'advice', textContent: opt.advice }));
    lines.push(el('span', { className: 'cost', textContent: opt.costText }));
    return flagRow(box, title, lines);
  });
}

function renderOptions() { goStep(0); }

function goStep(n) {
  step = n;
  const sc = screens[n];
  $('opt-error').hidden = true;
  $('opt-progress').textContent = n === 0 ? '' : `Extras ${n} de ${screens.length - 1}`;
  if (sc.kind === 'basics') {
    $('opt-title').textContent = 'O que será instalado';
    $('opt-body').replaceChildren(
      el('p', { className: 'card', textContent: `Obrigatório: ${scan.engineText ? `o motor do Chakmati (cerca de ${scan.engineText}).` : 'o Chakmati.'} O resto você marca abaixo e só é instalado no fim, tudo de uma vez.` }),
      el('h3', { textContent: 'Modelo de conversa' }),
      ...modelFlags(),
      (ollamaWarn = el('p', { className: 'muted', hidden: scan.ollamaUp || !model.local, textContent: 'O Ollama não foi encontrado neste computador. O modelo local precisa dele: instale e abra o Ollama antes de instalar, ou use só a sua IA paga.' })),
    );
  } else {
    $('opt-title').textContent = sc.title;
    $('opt-body').replaceChildren(el('p', { className: 'muted', textContent: 'Marque o que quiser: os recomendados já vêm marcados. Nada é instalado agora; tudo é instalado de uma vez no fim.' }), ...groupFlags(sc.ids));
  }
  $('opt-yes').textContent = n === screens.length - 1 ? 'Ver o resumo' : 'Continuar';
  show('options');
  askWhatsappNotice();
}

// WhatsApp comes flagged, but the notice about the number being blocked has to be read before it counts: asked once, when its screen first shows.
function askWhatsappNotice() {
  if (whatsappAsked || !boxes.whatsapp || !document.body.contains(boxes.whatsapp) || !chosen.has('whatsapp') || waGate.acknowledged()) return;
  whatsappAsked = true;
  waGate.run(showWhatsAppNotice, () => {}, () => { chosen.delete('whatsapp'); boxes.whatsapp.checked = false; });
}

function nextStep() {
  if (step === 0) {
    if (!model.local && !model.cloud) { $('opt-error').textContent = 'Marque o modelo local, a sua assinatura de IA paga, ou os dois.'; $('opt-error').hidden = false; return; }
    if (!model.cloud && model.connected) { api.cloudClear(); model.connected = false; }   // unflagged after connecting: the stored key goes too
    if (model.cloud && !model.connected) { renderCloud(); return; }
  }
  if (step >= screens.length - 1) renderSummary(); else goStep(step + 1);
}

// The paid AI: provider, key and model. The main process checks the key with the provider and stores it encrypted; the page keeps nothing of it.
function renderCloud() {
  const pick = $('cloud-provider');
  pick.replaceChildren(...scan.providers.map((p) => el('option', { value: p.id, textContent: p.label })));
  pick.value = model.provider || scan.providers[0].id;
  const sync = () => {
    const p = scan.providers.find((x) => x.id === pick.value);
    $('cloud-model').value = model.name && model.provider === pick.value ? model.name : p.defaultModel;
    $('cloud-help').textContent = `Crie a chave em ${p.keyHelp}.`;
  };
  pick.onchange = sync;
  sync();
  $('cloud-key').value = '';
  $('cloud-error').hidden = true;
  show('cloud');
  $('cloud-key').focus();
}

async function saveCloud() {
  const provider = $('cloud-provider').value;
  const name = $('cloud-model').value.trim();
  const key = $('cloud-key').value.trim();
  $('cloud-key').value = '';   // gone from the page the moment it is sent
  $('cloud-save').disabled = true;
  $('cloud-save').textContent = 'Conferindo com o provedor…';
  const res = await api.cloudCheck(provider, key, name);
  $('cloud-save').disabled = false;
  $('cloud-save').textContent = 'Testar e guardar';
  if (res.error) { $('cloud-error').textContent = res.error; $('cloud-error').hidden = false; return; }
  Object.assign(model, { connected: true, provider, name });
  step = 0;
  nextStep();
}

$('opt-back').addEventListener('click', () => { if (step === 0) renderProfile(); else goStep(step - 1); });
$('opt-yes').addEventListener('click', nextStep);
$('cloud-back').addEventListener('click', () => { $('cloud-key').value = ''; goStep(0); });
$('cloud-save').addEventListener('click', saveCloud);

async function renderSummary() {
  const plan = await api.plan([...chosen], profileOut(), modelOut());
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
  const result = await api.run([...chosen], profileOut(), modelOut());
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
$('back-options').addEventListener('click', () => goStep(screens.length - 1));
$('install').addEventListener('click', install);
$('finish').addEventListener('click', () => api.finish());
$('done-finish').addEventListener('click', () => api.finish());
$('open-ollama').addEventListener('click', () => api.ollamaPage());
$('recheck').addEventListener('click', start);

start();
