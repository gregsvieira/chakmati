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
const chosen = new Set();

async function start() {
  scan = await api.scan();
  const rows = [['Sistema', scan.hwText.system], ['Memória RAM', scan.hwText.ram], ['Espaço livre', scan.hwText.disk], ['Núcleos', scan.hwText.cores]];
  $('hw').replaceChildren(...rows.map(([k, v]) => el('div', { className: 'row' }, el('span', { textContent: k }), el('strong', { textContent: v }))));
  $('verdict').textContent = scan.levelText;
  $('verdict').dataset.level = scan.verdict.level;
  items($('reasons'), [...scan.verdict.reasons, ...scan.verdict.notes]);
  const usable = scan.verdict.level !== 'unsupported';
  $('ollama-help').hidden = !usable || scan.ollamaUp;
  $('to-options').hidden = !usable;
  $('to-options').disabled = !scan.ollamaUp;
  show('check');
}

function renderOptions() {
  $('model-line').textContent = `Modelo de conversa para este computador: ${scan.model.label} (${scan.model.id}, ${scan.model.sizeText}). Sempre instalado.`;
  $('options').replaceChildren(...scan.options.map((o) => {
    const box = el('input', { type: 'checkbox', id: `opt-${o.id}` });
    box.addEventListener('change', () => (box.checked ? chosen.add(o.id) : chosen.delete(o.id)));
    const title = el('span', { className: 'name', textContent: o.label });
    if (scan.suggested[o.id]) title.append(el('span', { className: 'badge', textContent: 'Recomendado para este PC' }));
    const text = el('span', {}, title, el('br'), el('span', { textContent: o.description }), el('br'), el('span', { className: 'cost', textContent: o.costText }));
    return el('li', {}, el('label', {}, box, text));
  }));
  show('options');
}

async function renderSummary() {
  const plan = await api.plan([...chosen]);
  if (!plan.ok) {
    items($('steps'), plan.blocked);
    $('totals').textContent = '';
    $('install').disabled = true;
  } else {
    items($('steps'), plan.steps.map((s) => (s.approval ? `${s.label} — vai pedir sua aprovação` : s.label)));
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
  const off = api.onProgress((p) => {
    $('run-status').textContent = p.total ? `${p.status} (${Math.round((p.completed / p.total) * 100)}%)` : p.status;
    if (p.total) $('bar').value = Math.round((p.completed / p.total) * 100);
  });
  const result = await api.run([...chosen]);
  off();
  const titles = { done: 'Pronto!', aborted: 'Instalação cancelada', failed: 'A instalação falhou', blocked: 'Não foi possível instalar' };
  $('run-title').textContent = titles[result.status] || 'Fim';
  $('bar').value = result.status === 'done' ? 100 : $('bar').value;
  $('run-status').textContent = '';
  const names = { done: 'feito', declined: 'pulado por você', failed: 'falhou' };
  items($('results'), result.results.map((r) => `${r.id}: ${names[r.status]}${r.error ? ` — ${r.error}` : ''}`));
  items($('after'), result.after || []);
  $('finish').hidden = false;
  $('finish').textContent = result.status === 'done' ? 'Concluir' : 'Fechar';
}

$('to-options').addEventListener('click', renderOptions);
$('back-check').addEventListener('click', () => show('check'));
$('to-summary').addEventListener('click', renderSummary);
$('back-options').addEventListener('click', () => show('options'));
$('install').addEventListener('click', install);
$('finish').addEventListener('click', () => api.finish());
$('open-ollama').addEventListener('click', () => api.ollamaPage());
$('recheck').addEventListener('click', start);

start();
