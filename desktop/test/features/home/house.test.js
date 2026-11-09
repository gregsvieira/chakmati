const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { EngineClient } = require('../../../src/features/engine/client');

const read = (...p) => fs.readFileSync(path.join(__dirname, '..', '..', '..', 'src', ...p), 'utf8');

function recorder(answer) {
  const calls = [];
  return { calls, fetchImpl: async (url, init) => { calls.push({ url, init }); return new Response(JSON.stringify(answer), { status: 200, headers: { 'content-type': 'application/json' } }); } };
}

test('the client reads the players and presses a button with the UI header, checking what it sends', async () => {
  const { fetchImpl, calls } = recorder({ players: [] });
  const c = new EngineClient({ baseUrl: 'http://127.0.0.1:8765', fetchImpl });
  await c.homePlayers();
  await c.homePlayerControl('media_player.echo_dot', 'search', 'Raul Seixas');
  assert.deepEqual(calls.map((x) => [x.init?.method || 'GET', x.url.replace('http://127.0.0.1:8765', '')]), [['GET', '/home/players'], ['POST', '/home/players/control']]);
  assert.deepEqual(JSON.parse(calls[1].init.body), { id: 'media_player.echo_dot', action: 'search', text: 'Raul Seixas' });
  assert.equal(calls[1].init.headers['X-LiteAgent-UI'], '1');
  for (const bad of ['', 'light.sala', 'media_player.', 'media_player.Echo', 'media_player.a b', null, 'media_player.x;y']) await assert.rejects(c.homePlayerControl(bad, 'pause'), /invalid player/);
  for (const bad of ['', 'unlock', 'volume', null]) await assert.rejects(c.homePlayerControl('media_player.echo', bad), /invalid action/);
  await assert.rejects(c.homePlayerControl('media_player.echo', 'search', 'x'.repeat(201)), /invalid text/);
});

test('the main process passes only strings, capped, and answers a problem as a sentence', () => {
  const ipc = read('features', 'home', 'ipc.js');
  assert.match(ipc, /ipcMain\.handle\('panel:home-players'/);
  assert.match(ipc, /ipcMain\.handle\('panel:home-player-control'/);
  assert.match(ipc, /text\(id, 120\), text\(action, 20\), text\(query, 200\)/);
  const preload = read('preload.js');
  for (const c of ['panel:home-players', 'panel:home-player-control']) assert.equal((preload.match(new RegExp(`'${c}'`, 'g')) || []).length, 1, c);
});

test('the section sits above the automations, is hidden until the house is connected, and is one of the foldable topics', () => {
  const html = read('features', 'panel', 'renderer', 'panel.html');
  assert.ok(html.indexOf('<section id="house"') > html.indexOf('<section id="agenda"') && html.indexOf('<section id="house"') < html.indexOf('<section id="automations"'));
  assert.match(html, /<section id="house" hidden>\s*<h2>Casa e Alexa<\/h2>/);
  assert.match(read('features', 'panel', 'renderer', 'layout.js'), /const TOPICS = \['decisions', 'messages', 'agenda', 'house', 'automations'\]/);
  assert.match(read('features', 'panel', 'renderer', 'core.js'), /P\.renderHouse\(\);\s*P\.renderAutomations\(\);/);
  assert.match(html, /<script src="\.\.\/\.\.\/home\/renderer\/house\.js"><\/script>/);
});

test('the page code finds every element it looks up, builds text only with textContent-safe nodes, and has every button of the request', () => {
  const html = read('features', 'panel', 'renderer', 'panel.html');
  const js = read('features', 'home', 'renderer', 'house.js');
  const wanted = [...new Set([...js.matchAll(/\$\('([\w-]+)'\)/g)].map((m) => m[1]))].filter((id) => id !== 'hint-house');
  assert.deepEqual(wanted.filter((id) => !html.includes(`id="${id}"`)), []);
  assert.equal(/innerHTML|outerHTML|insertAdjacentHTML|eval\(/.test(js), false);
  for (const label of ['Música anterior', 'Pausar', 'Continuar tocando', 'Próxima música', 'Diminuir o volume', 'Aumentar o volume', 'Trocar música']) assert.ok(js.includes(`'${label}'`), label);
  for (const action of ['previous', 'pause', 'play', 'next', 'volume_down', 'volume_up', 'search']) assert.ok(js.includes(`'${action}'`), action);
  assert.match(js, /now playing|♪ \$\{p\.title\}/);
});

test('it only asks the engine while it is on screen, open and the house is connected', () => {
  const js = read('features', 'home', 'renderer', 'house.js');
  assert.match(js, /const onScreen = \(\) => connected\(\) && !document\.hidden && P\.state\.panelOpen !== false && !\$\('house'\)\.hidden && !\$\('house'\)\.dataset\.collapsed/);
  assert.match(js, /setInterval\(\(\) => \{ if \(onScreen\(\)\) refresh\(\); \}, 6000\)/);
});

test('what is typed in "Trocar música" survives the redraws (every few seconds the list is rebuilt), keeping the cursor, and goes away when sent or cancelled', () => {
  const js = read('features', 'home', 'renderer', 'house.js');
  assert.match(js, /const drafts = new Map\(\)/);
  assert.match(js, /input\.value = drafts\.get\(p\.id\) \|\| ''/);
  assert.match(js, /input\.addEventListener\('input', \(\) => drafts\.set\(p\.id, input\.value\)\)/);
  assert.match(js, /if \(action === 'search' && res && res\.ok\) \{ searching\.delete\(player\.id\); drafts\.delete\(player\.id\); \}/);
  assert.match(js, /e\.key === 'Escape'\) \{ searching\.delete\(p\.id\); drafts\.delete\(p\.id\); draw\(\); \}/);
  assert.match(js, /setSelectionRange\(keep\.from, keep\.to\)/);                       // the cursor goes back where it was
  assert.match(js, /if \(!drafts\.has\(p\.id\) && !focusedField\(\)\) setTimeout\(\(\) => input\.focus\(\), 0\)/);   // only a field that just opened takes the cursor
  assert.match(js, /houseRefresh: refresh/);
});

test('an Alexa that stopped sending information is said in words, and asking for music is still offered', () => {
  const js = read('features', 'home', 'renderer', 'house.js');
  assert.match(js, /unavailable: 'sem informação agora'/);
  assert.match(js, /unavailable \? 'A Alexa não está mandando informações agora\.' :/);   // one short line...
  assert.doesNotMatch(js.split('\n').find((l) => l.includes('const say =')), /Amazon/);   // ...and the reason only behind the (i)
  assert.match(js, /const UNAVAILABLE_INFO = 'A Amazon limita os pedidos do Home Assistant/);
  assert.match(js, /aria-expanded': String\(moreInfo\)/);
  assert.match(js, /button\('Trocar música', 'Pedir outra música à Alexa', \(\) => \{[^}]*\}, off\)/);   // disabled only while a press is in flight, never because the state is unavailable
});
