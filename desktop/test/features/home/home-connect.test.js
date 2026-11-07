const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { isLocalHttpUrl } = require('../../../src/features/home/lan');
const { createHomeService, summary, POLL_MS, GIVE_UP_MS } = require('../../../src/features/home/service');
const modal = require('../../../src/features/home/modal-logic');
const { EngineClient } = require('../../../src/features/engine/client');

const read = (...p) => fs.readFileSync(path.join(__dirname, '..', '..', '..', 'src', ...p), 'utf8');

// --- which addresses may be opened ----------------------------------------------------------------------------------------------------
test('only addresses of the own network are opened', () => {
  for (const ok of ['http://homeassistant.local:8123/auth/authorize?x=1', 'http://192.168.0.10:8123', 'http://10.1.2.3:8123', 'http://172.16.0.9:8123', 'http://172.31.255.1',
    'http://localhost:8123', 'http://homeassistant:8123', 'https://ha.local', 'http://[::1]:8123', 'http://169.254.1.1']) assert.equal(isLocalHttpUrl(ok), true, ok);
  for (const bad of ['https://example.com/auth', 'http://8.8.8.8', 'http://172.32.0.1', 'http://192.169.0.1', 'http://ha.nabu.casa', 'ftp://192.168.0.1', 'file:///etc/passwd',
    'javascript:alert(1)', 'http://user:pw@192.168.0.1', 'http://evil.com@192.168.0.1.evil.com', '', 'nonsense', null, undefined]) assert.equal(isLocalHttpUrl(bad), false, String(bad));
});

// --- the service the modal talks to --------------------------------------------------------------------------------------------------------
function harness({ found = [{ url: 'http://homeassistant.local:8123', name: 'Casa' }], statuses = [], engineUp = true, authorize = 'http://homeassistant.local:8123/auth/authorize?state=s', fails = {} } = {}) {
  const log = { notes: [], opened: [], connected: [], calls: [], accounts: [], disconnects: 0 };
  let clock = 0;
  const queue = [...statuses];
  const maybeFail = (name) => { if (fails[name]) throw fails[name]; };
  const engine = {
    homeDiscover: async () => { log.calls.push('discover'); maybeFail('discover'); return { found }; },
    homeConnect: async (url) => { log.calls.push(`connect:${url}`); maybeFail('connect'); return { authorize_url: authorize }; },
    homeStatus: async () => { log.calls.push('status'); const s = queue.length > 1 ? queue.shift() : queue[0]; if (s instanceof Error) throw s; return s || { configured: true, connected: true, pending: false, players: [] }; },
    homeInstallStart: async () => { log.calls.push('install-start'); maybeFail('start'); return {}; },
    homeAccount: async (name, password) => { log.accounts.push([name, password]); maybeFail('account'); return {}; },
    homeDisconnect: async () => { log.disconnects += 1; return {}; },
  };
  const service = createHomeService({
    engine: () => engine, isEngineUp: () => engineUp, openExternal: async (u) => { log.opened.push(u); }, note: (t) => log.notes.push(t),
    afterConnected: async (s) => { log.connected.push(s); }, afterDisconnected: async () => {}, friendlyError: (e) => `ERRO: ${e.message}`,
    sleep: async (ms) => { clock += ms; await new Promise((r) => setImmediate(r)); }, now: () => clock,
  });
  return { service, log };
}

test('every action says in words that the engine is down, and does nothing', async () => {
  const { service, log } = harness({ engineUp: false });
  const down = { error: 'O motor do Chakmati não está rodando.' };
  assert.deepEqual(await service.discover(), down);
  assert.deepEqual(await service.connect('192.168.0.10'), down);
  assert.deepEqual(await service.startInstall(), down);
  assert.deepEqual(await service.account({ name: 'M', password: 'senha-forte-1' }), down);
  assert.deepEqual(log.calls, []);
});

test('discover lists what was found (at most 5), or says what went wrong', async () => {
  const many = Array.from({ length: 8 }, (_, i) => ({ url: `http://192.168.0.${i + 1}:8123`, name: 'Casa' }));
  assert.equal((await harness({ found: many }).service.discover()).found.length, 5);
  assert.deepEqual(await harness({ found: [] }).service.discover(), { found: [] });
  assert.deepEqual(await harness({ fails: { discover: new Error('caiu') } }).service.discover(), { error: 'ERRO: caiu' });
});

test('connect opens the login of the Home Assistant in the browser, and nothing else', async () => {
  const { service, log } = harness({ statuses: [{ pending: true }] });
  assert.deepEqual(await service.connect('  http://homeassistant.local:8123 '), { ok: true });
  assert.deepEqual(log.calls.slice(0, 1), ['connect:http://homeassistant.local:8123']);
  assert.deepEqual(log.opened, ['http://homeassistant.local:8123/auth/authorize?state=s']);
  service.cancel();
});

test('connect needs an address, and never opens one that is not on the own network', async () => {
  const empty = harness();
  assert.deepEqual(await empty.service.connect('   '), { error: 'Faltou o endereço do Home Assistant.' });
  assert.deepEqual(empty.log.calls, []);
  const strange = harness({ authorize: 'https://evil.example/auth/authorize' });
  assert.match((await strange.service.connect('192.168.0.10')).error, /não abri nada/);
  assert.deepEqual(strange.log.opened, []);
  assert.deepEqual(await harness({ fails: { connect: new Error('só aceito um Home Assistant da sua rede') } }).service.connect('8.8.8.8'), { error: 'ERRO: só aceito um Home Assistant da sua rede' });
});

test('when the approval arrives the house is switched on', async () => {
  const connected = { configured: true, connected: true, pending: false, players: [{ name: 'Echo Dot da sala', state: 'idle' }] };
  const { service, log } = harness({ statuses: [{ pending: true }, { pending: true }, connected] });
  await service.connect('192.168.0.10');
  await service.idle();
  assert.equal(log.connected.length, 1);
  assert.equal(summary(log.connected[0]), 'Conectado. Achei: Echo Dot da sala.');
});

test('saying no in Home Assistant, a hiccup, a wait that is too long, and starting again', async () => {
  const no = harness({ statuses: [{ pending: true }, { pending: false, connected: false, configured: false }] });
  await no.service.connect('192.168.0.10');
  await no.service.idle();
  assert.match(no.log.notes.at(-1), /não foi concluída/);
  assert.equal(no.log.connected.length, 0);
  const hiccup = harness({ statuses: [new Error('rede'), { pending: true }, { configured: true, connected: true, pending: false, players: [] }] });
  await hiccup.service.connect('192.168.0.10');
  await hiccup.service.idle();
  assert.equal(hiccup.log.connected.length, 1);
  const forever = harness({ statuses: [{ pending: true }] });
  await forever.service.connect('192.168.0.10');
  await forever.service.idle();                       // the clock is fake: three minutes pass at once
  assert.equal(forever.log.notes.at(-1), 'Não vi a aprovação a tempo. Tente de novo.');
  assert.ok(GIVE_UP_MS / POLL_MS > 10);
});

test('disconnecting cancels the wait and says so', async () => {
  const { service, log } = harness({ statuses: [{ pending: true }, { pending: true }, { configured: true, connected: true, pending: false, players: [] }] });
  await service.connect('192.168.0.10');
  await service.disconnect();
  await service.idle();
  assert.equal(log.connected.length, 0);
  assert.equal(log.disconnects, 1);
});

test('starting the install is one call; an engine that refuses is a sentence', async () => {
  const ok = harness();
  assert.deepEqual(await ok.service.startInstall(), { ok: true });
  assert.deepEqual(ok.log.calls, ['install-start']);
  assert.deepEqual(await harness({ fails: { start: new Error('a instalação já está em andamento') } }).service.startInstall(), { error: 'ERRO: a instalação já está em andamento' });
});

test('the account needs a real password, goes to the engine once, and then switches the house on', async () => {
  const short = harness();
  assert.deepEqual(await short.service.account({ name: 'Maria', password: 'curta' }), { error: 'Escolha uma senha com pelo menos 8 caracteres.' });
  assert.deepEqual(short.log.accounts, []);
  const { service, log } = harness({ statuses: [{ configured: true, connected: true, pending: false, players: [] }] });
  assert.deepEqual(await service.account({ name: 'Maria', password: 'senha-forte-1' }), { ok: true });
  assert.deepEqual(log.accounts, [['Maria', 'senha-forte-1']]);
  assert.equal(log.connected.length, 1);
  assert.equal(log.notes.some((n) => n.includes('senha-forte-1')), false);          // never in a sentence shown to the person
  const refused = harness({ fails: { account: new Error('o Home Assistant não aceitou criar a conta') } });
  assert.deepEqual(await refused.service.account({ name: 'M', password: 'senha-forte-1' }), { error: 'ERRO: o Home Assistant não aceitou criar a conta' });
  assert.equal(refused.log.connected.length, 0);
});

test('the sentence about what is connected says what was found or what is missing', () => {
  const base = { configured: true, connected: true };
  assert.equal(summary({ ...base, players: [{ name: 'A' }, { name: 'B' }] }), 'Conectado. Achei: A, B.');
  assert.equal(summary({ ...base, players: [{ name: 'A' }, { name: 'B' }, { name: 'C' }, { name: 'D' }] }), 'Conectado. Achei: A, B, C e mais.');
  assert.match(summary({ ...base, players: [] }), /conta da Amazon/);
  assert.equal(summary({ configured: true, connected: false, error: 'o Home Assistant recusou o acesso' }), 'o Home Assistant recusou o acesso');
  assert.equal(summary({ configured: false }), '');
  assert.equal(summary(null), '');
});

// --- what the modal says -----------------------------------------------------------------------------------------------------------------------
const ready = { docker: 'ready', container: 'none', image_mb: 1000, alexa_ready: false, docker_installable: true, docker_mb: 700, can_open_docker: true, platform: 'darwin' };

test('the list before "Começar" is exactly what will happen on this computer', () => {
  assert.deepEqual(modal.introSteps(ready), [
    'Usar o Docker, que já está ligado.', 'Baixar e instalar o Home Assistant (cerca de 1 GB de download).',
    'Baixar a integração da Alexa (alexa_media_player) para dentro do Home Assistant.', 'Ligar tudo e conferir que está funcionando.']);
  const noDocker = modal.introSteps({ ...ready, docker: 'no_docker' });
  assert.match(noDocker[0], /^Instalar o Docker Desktop \(cerca de 700 MB\)\. O computador vai pedir a sua senha de administrador\.$/);
  assert.match(modal.introSteps({ ...ready, docker: 'no_docker', platform: 'win32' })[0], /pode pedir para reiniciar/);
  assert.match(modal.introSteps({ ...ready, docker: 'no_docker', docker_installable: false })[0], /gerenciador de pacotes/);
  assert.match(modal.introSteps({ ...ready, docker: 'daemon_off' })[0], /Ligar o Docker \(o Chakmati abre o programa para você\)/);
  assert.match(modal.introSteps({ ...ready, docker: 'daemon_off', can_open_docker: false })[0], /ligue o serviço do Docker/);
  assert.match(modal.introSteps({ ...ready, container: 'stopped' })[1], /Ligar o Home Assistant que já foi instalado/);
  assert.match(modal.introSteps({ ...ready, alexa_ready: true })[2], /que já está no Home Assistant/);
});

test('"Começar" is off only when Docker is missing and this system cannot install it', () => {
  assert.equal(modal.canStart(ready), true);
  assert.equal(modal.canStart({ ...ready, docker: 'no_docker' }), true);
  assert.equal(modal.canStart({ ...ready, docker: 'no_docker', docker_installable: false }), false);
  assert.equal(modal.canStart({ error: 'sem motor' }), false);
  assert.equal(modal.canStart(null), false);
});

test('each state of the install shows its own page', () => {
  assert.deepEqual(modal.stageFor({ state: 'running', message: 'Baixando…' }), { stage: 'progress', text: 'Baixando…' });
  assert.deepEqual(modal.stageFor({ state: 'ready', code: 'needs_account', message: 'Tudo pronto' }), { stage: 'account', text: 'Tudo pronto' });
  assert.equal(modal.stageFor({ state: 'ready', code: 'has_owner', message: 'Já tem conta' }).stage, 'found');
  assert.equal(modal.stageFor({ state: 'done', message: 'Pronto' }).stage, 'done');
  assert.deepEqual(modal.stageFor({ state: 'error', message: 'O Docker não ficou pronto', code: 'docker_slow' }), { stage: 'error', text: 'O Docker não ficou pronto', code: 'docker_slow' });
  assert.deepEqual(modal.stageFor({ state: 'idle' }), { stage: 'intro', text: '' });
  assert.equal(modal.stageFor({ error: 'sem motor' }).stage, 'error');
  assert.equal(modal.stageFor(null).stage, 'error');
});

test('waiting for the approval: keeps waiting, finishes, or gives up with a sentence', () => {
  assert.equal(modal.approval({ pending: true }, 1000).stage, 'approving');
  assert.equal(modal.approval({ connected: true, pending: false }, 1000).stage, 'done');
  assert.equal(modal.approval({ pending: false, connected: false }, 2000).stage, 'approving');        // too early to say it failed
  assert.match(modal.approval({ pending: false, connected: false }, 7000).text, /não foi concluída/);
  assert.match(modal.approval({ pending: true }, 4 * 60 * 1000).text, /a tempo/);
});

test('the last page says what was found, or what is still missing for the Alexa', () => {
  assert.match(modal.doneText({ players: [{ name: 'Echo Dot da sala' }] }), /Achei: Echo Dot da sala\. Já dá para dizer "próxima música"/);
  const missing = modal.doneText({ players: [] });
  assert.match(missing, /Alexa Media Player/);
  assert.match(missing, /conta da Amazon/);
  assert.match(modal.doneText(null), /Abrir o Home Assistant/);
});

// --- the client and the wiring ------------------------------------------------------------------------------------------------------------------
function recorder(answer) {
  const calls = [];
  return { calls, fetchImpl: async (url, init) => { calls.push({ url, init }); return new Response(JSON.stringify(answer), { status: 200, headers: { 'content-type': 'application/json' } }); } };
}

test('the client reaches every route of the assistant, with the UI header on the ones that change something', async () => {
  const { fetchImpl, calls } = recorder({ ok: true });
  const c = new EngineClient({ baseUrl: 'http://127.0.0.1:8765', fetchImpl });
  await c.homeDiscover();
  await c.homeStatus();
  await c.homeConnect('  192.168.0.10 ');
  await c.homeInstallStatus();
  await c.homeInstallStart();
  await c.homeAccount('Maria', 'senha-forte-1');
  await c.homeDisconnect();
  assert.deepEqual(calls.map((x) => [x.init?.method || 'GET', x.url.replace('http://127.0.0.1:8765', '')]), [
    ['GET', '/home/discover'], ['GET', '/home/status'], ['POST', '/home/connect'], ['GET', '/home/install'], ['POST', '/home/install'], ['POST', '/home/install/account'], ['DELETE', '/home']]);
  for (const i of [2, 4, 5, 6]) assert.equal(calls[i].init.headers['X-LiteAgent-UI'], '1');
  assert.deepEqual(JSON.parse(calls[2].init.body), { url: '192.168.0.10' });
  assert.deepEqual(JSON.parse(calls[4].init.body), { confirm: true });
  assert.deepEqual(JSON.parse(calls[5].init.body), { name: 'Maria', password: 'senha-forte-1' });
  for (const bad of ['', '   ', 'a'.repeat(201), null, 7]) await assert.rejects(c.homeConnect(bad), /invalid address/);
  for (const bad of ['', 'curta', 'a'.repeat(129), null, 12345678]) await assert.rejects(c.homeAccount('M', bad), /invalid password/);
});

test('Ajustes has one section with one button, and nothing of the old controls is left in it', () => {
  const html = read('features', 'panel', 'renderer', 'panel.html');
  const section = html.slice(html.indexOf('<section class="cat" id="home-section">'), html.indexOf('</section>', html.indexOf('id="home-section"')));
  assert.match(section, /<h3>Assistente de Casa e Alexa<\/h3>/);
  assert.match(section, /<button type="button" id="home-open" class="ghost">Conectar Home Assistant<\/button>/);
  assert.deepEqual((section.match(/<input/g) || []).length, 0);                     // no address, no password in the page of Ajustes
  assert.deepEqual((section.match(/<button/g) || []).length, 2);                    // "Conectar Home Assistant" and, once connected, "Desconectar"
  for (const gone of ['home-address', 'home-install-password', 'home-install-go', 'home-note', 'home-status', 'set-home', 'home-install-help']) assert.equal(html.includes(`id="${gone}"`), false, gone);
  assert.equal(/id="home-/.test(read('features', 'settings', 'renderer', 'settings.js')), false);
});

test('the modal has the pages, the name and the password only at the end, and every element the code looks up', () => {
  const html = read('features', 'panel', 'renderer', 'panel.html');
  const js = read('features', 'home', 'renderer', 'home.js');
  const modalHtml = html.slice(html.indexOf('<div id="home-modal"'), html.indexOf('<div id="notice-modal"'));
  for (const id of ['hm-search', 'hm-found', 'hm-intro', 'hm-progress', 'hm-approving', 'hm-account', 'hm-done']) assert.ok(modalHtml.includes(`id="${id}"`), id);
  const account = modalHtml.slice(modalHtml.indexOf('id="hm-account"'), modalHtml.indexOf('id="hm-done"'));
  assert.ok(account.includes('id="hm-name"') && /<input type="password" id="hm-password"/.test(account) && /autocomplete="new-password"/.test(account));
  assert.equal(modalHtml.replace(account, '').includes('<input'), false, 'the inputs live only on the account page');
  const wanted = [...new Set([...js.matchAll(/\$\('([\w-]+)'\)/g)].map((m) => m[1]))];
  assert.deepEqual(wanted.filter((id) => !html.includes(`id="${id}"`)), []);
  assert.match(js, /\$\('hm-password'\)\.value = ''/);                              // the password never stays on the page
  assert.match(html, /<script src="\.\.\/\.\.\/home\/modal-logic\.js"><\/script>\s*<script src="\.\.\/\.\.\/home\/renderer\/home\.js"><\/script>/);
});

test('the main process opens only the checked login or the fixed address of the own Home Assistant, and caps what the page sends', () => {
  const ipc = read('features', 'home', 'ipc.js');
  assert.match(ipc, /shell\.openExternal\('http:\/\/localhost:8123'\)/);
  assert.equal((ipc.match(/openExternal\(/g) || []).length, 2);
  assert.match(ipc, /text\(name, 60\)/);
  assert.match(ipc, /text\(password, 128\)/);
  for (const channel of ['discover', 'connect', 'status', 'install-info', 'install-start', 'account', 'open-ha', 'disconnect']) assert.ok(read('preload.js').includes(`'panel:home-${channel}'`), channel);
  const service = read('features', 'home', 'service.js');
  assert.ok(service.indexOf('isLocalHttpUrl(authorize)') < service.indexOf('await openExternal(authorize)'));
  assert.equal((service.match(/await openExternal\(/g) || []).length, 1);
});
