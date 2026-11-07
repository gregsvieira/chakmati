const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { isLocalHttpUrl } = require('../../../src/features/home/lan');
const { createHomeService, summary, POLL_MS, GIVE_UP_MS } = require('../../../src/features/home/service');
const { EngineClient } = require('../../../src/features/engine/client');

const read = (...p) => fs.readFileSync(path.join(__dirname, '..', '..', '..', 'src', ...p), 'utf8');

// --- which addresses may be opened ----------------------------------------------------------------------------------------------------
test('only addresses of the own network are opened', () => {
  for (const ok of ['http://homeassistant.local:8123/auth/authorize?x=1', 'http://192.168.0.10:8123', 'http://10.1.2.3:8123', 'http://172.16.0.9:8123', 'http://172.31.255.1',
    'http://localhost:8123', 'http://homeassistant:8123', 'https://ha.local', 'http://[::1]:8123', 'http://169.254.1.1']) assert.equal(isLocalHttpUrl(ok), true, ok);
  for (const bad of ['https://example.com/auth', 'http://8.8.8.8', 'http://172.32.0.1', 'http://192.169.0.1', 'http://ha.nabu.casa', 'ftp://192.168.0.1', 'file:///etc/passwd',
    'javascript:alert(1)', 'http://user:pw@192.168.0.1', 'http://evil.com@192.168.0.1.evil.com', '', 'nonsense', null, undefined]) assert.equal(isLocalHttpUrl(bad), false, String(bad));
});

// --- the flow -------------------------------------------------------------------------------------------------------------------------
function harness({ found = [{ url: 'http://homeassistant.local:8123', name: 'Casa' }], statuses = [], engineUp = true, authorize = 'http://homeassistant.local:8123/auth/authorize?state=s', connectFails = null } = {}) {
  const log = { notes: [], opened: [], connected: [], disconnects: 0, calls: [] };
  let clock = 0;
  const queue = [...statuses];
  const engine = {
    homeDiscover: async () => { log.calls.push('discover'); return { found }; },
    homeConnect: async (url) => { log.calls.push(`connect:${url}`); if (connectFails) throw connectFails; return { authorize_url: authorize }; },
    homeStatus: async () => { log.calls.push('status'); const s = queue.length > 1 ? queue.shift() : queue[0]; if (s instanceof Error) throw s; return s; },
    homeDisconnect: async () => { log.disconnects += 1; return {}; },
  };
  const service = createHomeService({
    engine: () => engine, isEngineUp: () => engineUp, openExternal: async (u) => { log.opened.push(u); }, note: (t) => log.notes.push(t),
    afterConnected: async (s) => { log.connected.push(s); }, afterDisconnected: async () => {}, friendlyError: (e) => `ERRO: ${e.message}`,
    sleep: async (ms) => { clock += ms; await new Promise((r) => setImmediate(r)); }, now: () => clock,
  });
  return { service, log };
}

test('the engine being down is said in words and nothing is tried', async () => {
  const { service, log } = harness({ engineUp: false });
  assert.deepEqual(await service.connect(''), { error: 'O motor do Chakmati não está rodando.' });
  assert.deepEqual(log.calls, []);
});

test('with no Home Assistant found, it asks for the address instead of failing', async () => {
  const { service, log } = harness({ found: [] });
  const res = await service.connect('');
  assert.equal(res.needAddress, true);
  assert.match(res.message, /escreva o endereço dele abaixo/);
  assert.match(res.message, /Ainda não tenho o Home Assistant/);   // and says what to do if there is none
  assert.deepEqual(log.notes, ['Procurando o Home Assistant na sua rede… (leva alguns segundos)', res.message]);   // first the search is announced, then the answer reaches Ajustes
  assert.deepEqual(log.opened, []);
});

test('a found Home Assistant is used without asking anything, and its login opens in the browser', async () => {
  const { service, log } = harness({ statuses: [{ pending: true }] });
  const res = await service.connect('');
  assert.equal(res.ok, true);
  assert.deepEqual(log.calls.slice(0, 2), ['discover', 'connect:http://homeassistant.local:8123']);
  assert.deepEqual(log.opened, ['http://homeassistant.local:8123/auth/authorize?state=s']);
  assert.match(res.message, /toque em Aprovar/);
  service.cancel();
});

test('a typed address skips the search', async () => {
  const { service, log } = harness({ statuses: [{ pending: true }] });
  await service.connect('  192.168.0.10  ');
  assert.deepEqual(log.calls.slice(0, 1), ['connect:192.168.0.10']);
  assert.equal(log.calls.includes('discover'), false);
  service.cancel();
});

test('an address the engine gives that is not on the own network is never opened', async () => {
  const { service, log } = harness({ authorize: 'https://evil.example/auth/authorize' });
  const res = await service.connect('');
  assert.match(res.error, /não abri nada/);
  assert.deepEqual(log.opened, []);
});

test('an engine error becomes a sentence for the person', async () => {
  const { service, log } = harness({ connectFails: new Error('só aceito um Home Assistant da sua rede') });
  const res = await service.connect('8.8.8.8');
  assert.deepEqual(res, { error: 'ERRO: só aceito um Home Assistant da sua rede' });
  assert.deepEqual(log.notes, [res.error]);
});

test('when the approval arrives the connection is announced and the house switched on', async () => {
  const connected = { configured: true, connected: true, pending: false, players: [{ name: 'Echo Dot da sala', state: 'idle' }] };
  const { service, log } = harness({ statuses: [{ pending: true }, { pending: true }, connected] });
  await service.connect('');
  await service.idle();
  assert.equal(log.connected.length, 1);
  assert.equal(summary(log.connected[0]), 'Conectado. Achei: Echo Dot da sala.');
});

test('saying no in Home Assistant is noticed and said kindly', async () => {
  const { service, log } = harness({ statuses: [{ pending: true }, { pending: false, connected: false, configured: false }] });
  await service.connect('');
  await service.idle();
  assert.match(log.notes.at(-1), /não foi concluída/);
  assert.equal(log.connected.length, 0);
});

test('a short hiccup while waiting does not end the wait', async () => {
  const connected = { configured: true, connected: true, pending: false, players: [] };
  const { service, log } = harness({ statuses: [new Error('rede'), { pending: true }, connected] });
  await service.connect('');
  await service.idle();
  assert.equal(log.connected.length, 1);
});

test('waiting is not forever: it gives up with a sentence', async () => {
  const { service, log } = harness({ statuses: [{ pending: true }] });
  await service.connect('');
  await service.idle();                              // the clock is fake: three minutes pass at once
  assert.equal(log.notes.at(-1), 'Não vi a aprovação a tempo. Toque em Conectar para tentar de novo.');
  assert.equal(log.connected.length, 0);
  assert.ok(GIVE_UP_MS / POLL_MS > 10);
});

test('starting again cancels the earlier wait, and disconnecting cancels it too', async () => {
  const connected = { configured: true, connected: true, pending: false, players: [] };
  const { service, log } = harness({ statuses: [{ pending: true }, { pending: true }, connected] });
  await service.connect('');
  await service.disconnect();
  await service.idle();
  assert.equal(log.connected.length, 0);          // the first wait ended when the person disconnected
  assert.equal(log.disconnects, 1);
  assert.match(log.notes.at(-1), /Desconectado/);
});

// --- what Ajustes says ---------------------------------------------------------------------------------------------------------------------
test('the sentence after connecting says what was found, or what is missing', () => {
  const base = { configured: true, connected: true };
  assert.equal(summary({ ...base, players: [{ name: 'A' }, { name: 'B' }] }), 'Conectado. Achei: A, B.');
  assert.equal(summary({ ...base, players: [{ name: 'A' }, { name: 'B' }, { name: 'C' }, { name: 'D' }] }), 'Conectado. Achei: A, B, C e mais.');
  assert.match(summary({ ...base, players: [] }), /não vejo nenhuma Alexa/);
  assert.equal(summary({ configured: true, connected: false, error: 'o Home Assistant recusou o acesso' }), 'o Home Assistant recusou o acesso');
  assert.equal(summary({ configured: false }), '');
  assert.equal(summary(null), '');
});

// --- the client and the wiring ---------------------------------------------------------------------------------------------------------------
function recorder(answer) {
  const calls = [];
  return { calls, fetchImpl: async (url, init) => { calls.push({ url, init }); return new Response(JSON.stringify(answer), { status: 200, headers: { 'content-type': 'application/json' } }); } };
}

test('the client reaches the connect routes, with the UI header on the ones that change something', async () => {
  const { fetchImpl, calls } = recorder({ ok: true });
  const c = new EngineClient({ baseUrl: 'http://127.0.0.1:8765', fetchImpl });
  await c.homeDiscover();
  await c.homeStatus();
  await c.homeConnect('  192.168.0.10 ');
  await c.homeDisconnect();
  assert.deepEqual(calls.map((x) => [x.init?.method || 'GET', x.url.replace('http://127.0.0.1:8765', '')]), [['GET', '/home/discover'], ['GET', '/home/status'], ['POST', '/home/connect'], ['DELETE', '/home']]);
  assert.equal(calls[2].init.headers['X-LiteAgent-UI'], '1');
  assert.deepEqual(JSON.parse(calls[2].init.body), { url: '192.168.0.10' });
  assert.equal(calls[3].init.headers['X-LiteAgent-UI'], '1');
  for (const bad of ['', '   ', 'a'.repeat(201), null, 7]) await assert.rejects(c.homeConnect(bad), /invalid address/);
});

test('the page has every element the connect code looks up, and the switch starts the house in the engine', () => {
  const html = read('features', 'panel', 'renderer', 'panel.html');
  const js = read('features', 'settings', 'renderer', 'settings.js');
  const ids = [...new Set([...js.matchAll(/\$\('(home-[\w-]+|set-home)'\)/g)].map((m) => m[1]))];
  assert.ok(ids.length >= 8);
  assert.deepEqual(ids.filter((id) => !html.includes(`id="${id}"`)), []);
  assert.match(read('features', 'settings', 'service.js'), /key === 'research' \|\| key === 'home'/);
  assert.match(read('preload.js'), /homeConnect: \(url\) => ipcRenderer\.invoke\('panel:home-connect'/);
  assert.match(read('app', 'ipc.js'), /homeIpc\.register\(\)/);
});

test('the browser is only ever opened through the own-network check', () => {
  const service = read('features', 'home', 'service.js');
  assert.ok(service.indexOf('isLocalHttpUrl(authorize)') < service.indexOf('await openExternal(authorize)'));
  assert.equal((service.match(/await openExternal\(/g) || []).length, 1);
});

test('searching is announced at once, and a typed address skips the announcement', async () => {
  const a = harness({ statuses: [{ pending: true }] });
  await a.service.connect('');
  assert.match(a.log.notes[0], /^Procurando o Home Assistant/);
  a.service.cancel();
  const b = harness({ statuses: [{ pending: true }] });
  await b.service.connect('192.168.0.10');
  assert.equal(b.log.notes.some((n) => /^Procurando/.test(n)), false);
  b.service.cancel();
});

test('for someone with no Home Assistant the page offers to install one, and the note is a visible paragraph', () => {
  const html = read('features', 'panel', 'renderer', 'panel.html');
  const js = read('features', 'settings', 'renderer', 'settings.js');
  assert.ok(html.includes('id="home-install-help"') && /<p id="home-note" class="note"/.test(html));
  assert.match(html, /id="home-install-password" maxlength="128"[^>]*autocomplete="new-password"/);
  assert.match(html, /<input type="password" id="home-install-password"/);                         // the password is never shown
  assert.match(js, /home-install-help'\)\.addEventListener\('click', async \(\) => \{ showInstall = true; renderHome\(\); await loadInstallInfo\(\); \}\)/);
  assert.match(js, /\$\('home-note'\)\.hidden = !P\.state\.homeNote/);
  assert.match(js, /\$\('home-install-password'\)\.value = ''/);                                  // and it does not stay on the page once sent
  assert.match(js, /home-docker-download'\)\.addEventListener\('click', \(\) => api\.homeDockerPage\(\)\)/);
});

// --- installing a Home Assistant (Docker) ------------------------------------------------------------------------------------------------------
function installHarness({ info = { docker: 'ready', container: 'none', image_mb: 1000 }, statuses = [], confirms = true, installFails = null, engineUp = true } = {}) {
  const log = { notes: [], confirmed: [], installs: [], connected: [], calls: [] };
  let clock = 0;
  const queue = [...statuses];
  const engine = {
    homeInstallStatus: async () => { log.calls.push('info'); return queue.length ? (queue.length > 1 ? queue.shift() : queue[0]) : info; },
    homeInstall: async (name, password) => { if (installFails) throw installFails; log.installs.push([name, password]); queue.length || queue.push({ state: 'running', message: 'Verificando o Docker…' }); return {}; },
    homeStatus: async () => ({ configured: true, connected: true, pending: false, players: [] }),
  };
  const firstInfo = info;
  const wrapped = { ...engine, homeInstallStatus: async () => (log.installs.length ? engine.homeInstallStatus() : firstInfo) };
  const service = createHomeService({
    engine: () => wrapped, isEngineUp: () => engineUp, openExternal: async () => {}, note: (t) => log.notes.push(t),
    afterConnected: async (s) => { log.connected.push(s); }, afterDisconnected: async () => {}, friendlyError: (e) => `ERRO: ${e.message}`,
    confirm: async (c) => { log.confirmed.push(c); return confirms; },
    sleep: async (ms) => { clock += ms; await new Promise((r) => setImmediate(r)); }, now: () => clock,
  });
  return { service, log };
}

test('a short password is refused before anything is asked or sent', async () => {
  const { service, log } = installHarness();
  assert.deepEqual(await service.install({ name: 'Maria', password: 'curta' }), { error: 'Escolha uma senha com pelo menos 8 caracteres.' });
  assert.deepEqual(log.confirmed, []);
  assert.deepEqual(log.installs, []);
  assert.deepEqual(await installHarness({ engineUp: false }).service.install({ name: 'M', password: 'senha-forte-1' }), { error: 'O motor do Chakmati não está rodando.' });
});

test('without Docker it says what to do and does not even ask for the download', async () => {
  const { service, log } = installHarness({ info: { docker: 'no_docker' } });
  const res = await service.install({ name: 'Maria', password: 'senha-forte-1' });
  assert.equal(res.code, 'docker_missing');
  assert.match(res.error, /Instale o Docker Desktop/);
  assert.deepEqual(log.confirmed, []);
  assert.deepEqual(log.installs, []);
  assert.deepEqual(log.notes, [res.error]);
});

test('the download is asked first, with its size, its memory and the promise that nothing is downloaded without a yes', async () => {
  const { service, log } = installHarness({ statuses: [{ state: 'done', message: 'Pronto!' }] });
  await service.install({ name: 'Maria', password: 'senha-forte-1' });
  assert.equal(log.confirmed.length, 1);
  assert.match(log.confirmed[0].message, /Instalar o Home Assistant neste computador\?/);
  assert.match(log.confirmed[0].detail, /cerca de 1 GB/);
  assert.match(log.confirmed[0].detail, /uns 2 GB de memória/);
  assert.match(log.confirmed[0].detail, /Nada é baixado sem a sua aprovação/);
  assert.ok(log.calls.length >= 1);
  await service.idle();
});

test('saying no installs nothing', async () => {
  const { service, log } = installHarness({ confirms: false });
  const res = await service.install({ name: 'Maria', password: 'senha-forte-1' });
  assert.deepEqual(res, { cancelled: true, message: 'Tudo bem, não instalei nada.' });
  assert.deepEqual(log.installs, []);
  assert.deepEqual(log.notes, ['Tudo bem, não instalei nada.']);
});

test('a yes starts the install with the name and the password, and the progress reaches Ajustes in plain words', async () => {
  const { service, log } = installHarness({ statuses: [
    { state: 'running', message: 'Abrindo o Docker… (pode levar um minuto)' },
    { state: 'running', message: 'Baixando o Home Assistant… 12MB/100MB' },
    { state: 'running', message: 'Baixando o Home Assistant… 12MB/100MB' },
    { state: 'done', message: 'Pronto! O Home Assistant está instalado e conectado.' },
  ] });
  const res = await service.install({ name: 'Maria', password: 'senha-forte-1' });
  assert.equal(res.ok, true);
  assert.deepEqual(log.installs, [['Maria', 'senha-forte-1']]);
  await service.idle();
  assert.deepEqual(log.notes.filter((n) => !/^Instalando o Home Assistant…/.test(n)), [
    'Abrindo o Docker… (pode levar um minuto)', 'Baixando o Home Assistant… 12MB/100MB', 'Pronto! O Home Assistant está instalado e conectado.']);   // no repeats
  assert.equal(log.connected.length, 1);                                    // and when it is done, the house is switched on and refreshed
  assert.equal(JSON.stringify(log).includes('senha-forte-1'), true);       // (only the engine call received it)
  assert.equal(log.notes.some((n) => n.includes('senha-forte-1')), false);  // never in a sentence shown to the person
});

test('an install that ends in an error shows the sentence and connects nothing', async () => {
  const { service, log } = installHarness({ statuses: [{ state: 'running', message: 'Verificando o Docker…' }, { state: 'error', message: 'O Docker não ficou pronto a tempo.', code: 'docker_slow' }] });
  await service.install({ name: 'Maria', password: 'senha-forte-1' });
  await service.idle();
  assert.equal(log.notes.at(-1), 'O Docker não ficou pronto a tempo.');
  assert.equal(log.connected.length, 0);
});

test('an engine that refuses to start the install is a sentence', async () => {
  const { service, log } = installHarness({ installFails: new Error('a instalação já está em andamento') });
  const res = await service.install({ name: 'Maria', password: 'senha-forte-1' });
  assert.deepEqual(res, { error: 'ERRO: a instalação já está em andamento' });
  assert.equal(log.notes.at(-1), res.error);
});

test('the client reads what is there and starts the install with the confirmation and the UI header', async () => {
  const { fetchImpl, calls } = recorder({ ok: true });
  const c = new EngineClient({ baseUrl: 'http://127.0.0.1:8765', fetchImpl });
  await c.homeInstallStatus();
  await c.homeInstall('Maria', 'senha-forte-1');
  assert.deepEqual(calls.map((x) => [x.init?.method || 'GET', x.url.replace('http://127.0.0.1:8765', '')]), [['GET', '/home/install'], ['POST', '/home/install']]);
  assert.equal(calls[1].init.headers['X-LiteAgent-UI'], '1');
  assert.deepEqual(JSON.parse(calls[1].init.body), { name: 'Maria', password: 'senha-forte-1', confirm: true });
  for (const bad of ['', 'curta', 'a'.repeat(129), null, 12345678]) await assert.rejects(c.homeInstall('M', bad), /invalid password/);
});

test('the main process asks with a dialog whose default is "Agora não", opens only a fixed Docker address, and caps what the page sends', () => {
  const ipc = read('features', 'home', 'ipc.js');
  assert.match(ipc, /buttons: \['Instalar', 'Agora não'\], defaultId: 1, cancelId: 1/);
  assert.match(ipc, /shell\.openExternal\('https:\/\/www\.docker\.com\/products\/docker-desktop\/'\)/);
  assert.equal((ipc.match(/openExternal\(/g) || []).length, 2);               // the Home Assistant login (checked) and the fixed Docker page
  assert.match(ipc, /name\.slice\(0, 60\)/);
  assert.match(ipc, /password\.slice\(0, 128\)/);
  assert.match(read('preload.js'), /homeInstall: \(name, password\) => ipcRenderer\.invoke\('panel:home-install'/);
});
