const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { EngineClient } = require('../../../src/features/engine/client');

const read = (...p) => fs.readFileSync(path.join(__dirname, '..', '..', '..', 'src', ...p), 'utf8');
const thread = read('features', 'panel', 'renderer', 'thread.js');

test('after "Criar" the buttons go channel, then the hours the automation works, then how it answers', () => {
  assert.match(thread, /\{ label: 'WhatsApp', fill: `\$\{BASE\}: `, next: HOURS_CHIPS \}/);
  for (const label of ["'Sempre'", "'À noite (22:00 às 07:00)'", "'Fora do expediente (18:00 às 08:00)'", "'Madrugada (00:00 às 06:00)'", "'Outro horário'"]) assert.ok(thread.includes(label), label);
  assert.match(thread, /const hoursChip = \(label, h\) => \(\{ label, fill: `\$\{BASE\}\$\{when\(h\)\}`, next: modeChips\(h\) \}\)/);
  assert.match(thread, /const prompt = \(h, tail\) => `\$\{BASE\}\$\{when\(h\)\}, responda\$\{tail\}`/);
  assert.match(thread, /const when = \(h\) => \(h \? ` entre as \$\{h\.from\} e as \$\{h\.to\}` : ''\)/);
});

test('the text the buttons build is the one the engine reads: "entre as 22:00 e as 07:00, responda em áudio: "', () => {
  const BASE = 'Crie uma automação: sempre que alguém me escrever no WhatsApp';
  const when = (h) => (h ? ` entre as ${h.from} e as ${h.to}` : '');
  const prompt = (h, tail) => `${BASE}${when(h)}, responda${tail}`;
  assert.equal(prompt({ from: '22:00', to: '07:00' }, ' em áudio: '), 'Crie uma automação: sempre que alguém me escrever no WhatsApp entre as 22:00 e as 07:00, responda em áudio: ');
  assert.equal(prompt(null, ': '), 'Crie uma automação: sempre que alguém me escrever no WhatsApp, responda: ');
});

test('"Minha fala" carries the chosen hours to the recording, and "regravar" keeps them', () => {
  assert.match(thread, /\{ label: 'Minha fala', media: true, own: true, hours: h \}/);
  assert.match(thread, /P\.recordOwnVoice\(c\.hours \|\| null\)/);
  const auto = read('features', 'automations', 'renderer', 'automations.js');
  assert.match(auto, /async function recordOwnVoice\(hours = null\)/);
  assert.match(auto, /api\.proposeRecorded\(wav, hours\);\s*lastHours = hours;/);
  assert.match(auto, /recordOwnVoice\(lastHours\)/);
});

test('the choices survive clicking elsewhere and coming back to the field, and end when the request is sent or typed by hand', () => {
  assert.match(thread, /if \(!on && !stage\) P\.renderChips\(CHIPS\)/);
  assert.match(thread, /input\.addEventListener\('pointerdown', \(\) => \{ if \(!input\.value\.trim\(\) \|\| stage\) \{ if \(stage\) P\.renderChips\(stage\); showSuggestions\(true\); \} \}\)/);
  assert.match(thread, /input\.addEventListener\('input', \(\) => \{ if \(input\.value\.trim\(\)\) \{ stage = null; showSuggestions\(false\); \} \}\)/);
  assert.match(thread, /async function submit\(text, \{ voice = false \} = \{\}\) \{\s*stage = null;/);
  assert.match(read('features', 'automations', 'renderer', 'automations.js'), /P\.startAutomationChips\(\)/);
});

test('in the small card the strip with the conversation is painted, so the open topics never show through its text, and an opened topic scrolls above it', () => {
  const css = read('features', 'panel', 'renderer', 'panel.css');
  assert.match(css, /#panel\[data-layout="compact"\] #thread-section \{ background: var\(--surface\); box-shadow: 0 -10px 12px -4px var\(--surface\); z-index: 2; \}/);
  assert.match(css, /#panel\[data-layout="compact"\] #content \{ scroll-padding-bottom: 140px; \}/);
  assert.match(read('features', 'panel', 'renderer', 'layout.js'), /section\.scrollIntoView\(\{ block: 'nearest' \}\)/);
});

test('the client sends the hours of a recorded reply only when they are valid HH:MM', async () => {
  const calls = [];
  const fetchImpl = async (url, init) => { calls.push({ url, init }); return new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } }); };
  const c = new EngineClient({ baseUrl: 'http://127.0.0.1:8765', fetchImpl });
  const wav = new Uint8Array([1, 2, 3]);
  await c.proposeRecorded(wav);
  await c.proposeRecorded(wav, { from: '22:00', to: '07:50' });
  assert.equal(calls[0].url.endsWith('/automations/recorded'), true);
  assert.match(calls[1].url, /\/automations\/recorded\?hours_from=22%3A00&hours_to=07%3A50$/);
  for (const bad of [{ from: '25:00', to: '07:00' }, { from: '22:00', to: '7:00' }, { from: '22:00' }, { from: 'noite', to: 'dia' }]) await assert.rejects(c.proposeRecorded(wav, bad), /invalid hours/);
  assert.match(read('features', 'approvals', 'ipc.js'), /panel:propose-recorded', async \(_e, bytes, hours\)/);
  assert.match(read('preload.js'), /proposeRecorded: \(bytes, hours\)/);
});

test('the automations list has only the title and the two buttons; the details open in a window when the title is clicked', () => {
  const js = read('features', 'automations', 'renderer', 'automations.js');
  const html = read('features', 'panel', 'renderer', 'panel.html');
  const card = js.slice(js.indexOf('const card = (a)'), js.indexOf('// One block per channel'));
  assert.match(card, /onclick: \(\) => showDetails\(a\)/);
  assert.equal(/a\.description|decision-body/.test(card), false, 'the long sentence is no longer in the card');
  assert.match(card, /'Pausar'/);
  assert.match(card, /'Apagar'/);
  assert.match(card, /\(pausada\)/);
  const wanted = [...new Set([...js.matchAll(/\$\('([\w-]+)'\)/g)].map((m) => m[1]))].filter((id) => id.startsWith('automation-detail'));
  assert.deepEqual(wanted.filter((id) => !html.includes(`id="${id}"`)), []);
  assert.match(js, /\$\('automation-detail-text'\)\.textContent = a\.description/);
  assert.match(js, /e\.key === 'Escape'\) closeDetails\(\)/);
  assert.equal(/innerHTML/.test(js), false);
  assert.match(html, /<div id="automation-detail" class="modal" role="dialog" aria-modal="true" aria-labelledby="automation-detail-title" hidden>/);
});

test('"Casa e Alexa" replaces the Alexa "em breve": when, then what, and the request it fills is one the engine reads', () => {
  assert.match(thread, /\{ label: 'Casa e Alexa', fill: `\$\{HOUSE_BASE\} `, next: HOUSE_WHEN_CHIPS \}/);
  assert.equal(thread.includes("'Alexa (em breve)'"), false);
  for (const label of ["'Todo dia às 07:00'", "'Dias úteis às 06:30'", "'Fim de semana às 09:00'", "'Todo dia às 22:00'", "'Outro horário'", "'Ligar a luz e abrir a cortina'", "'Fechar a cortina e apagar a luz'", "'Tocar uma música'", "'Outra coisa'"]) assert.ok(thread.includes(label), label);
  const HOUSE_BASE = 'Crie uma automação:';
  const houseWhenChip = (when) => `${HOUSE_BASE} ${when} toque Raul Seixas na Alexa`;
  assert.equal(houseWhenChip('de segunda a sexta às 6h30'), 'Crie uma automação: de segunda a sexta às 6h30 toque Raul Seixas na Alexa');
  assert.match(read('features', 'panel', 'renderer', 'panel.html'), /<dt>Já rodou<\/dt>/);   // the window says "ran", not "answered": it is not always a reply
});

test('inside Automações each channel is folded to its name and how many automations it has, and a click opens it (remembered)', () => {
  const js = read('features', 'automations', 'renderer', 'automations.js');
  const css = read('features', 'panel', 'renderer', 'panel.css');
  assert.match(js, /\['home', 'Casa e Alexa'\]/);
  assert.match(js, /String\(items\.length\)/);                                            // the count is all that shows while folded
  assert.match(js, /open \? items\.map\(card\) : null/);                                   // the cards only exist while the channel is open
  assert.match(js, /'aria-expanded': String\(open\)/);
  assert.match(js, /new Set\(\(P\.store && P\.store\.get\('chakmati\.auto-groups-open', \[\]\)\) \|\| \[\]\)/);   // folded by default
  assert.match(js, /P\.store\.set\('chakmati\.auto-groups-open', \[\.\.\.set\]\)/);
  assert.match(css, /\.group-head \{[^}]*cursor: pointer/);
  assert.match(css, /\.group-count \{/);
  assert.equal(/innerHTML/.test(js), false);
});
