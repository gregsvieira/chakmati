'use strict';
// Connecting to Home Assistant for someone who has never seen a token: the Chakmati finds it on the network, opens ITS login page in the
// browser, the person taps "Aprovar" there, and the engine receives the answer. This drives that and keeps one plain sentence ("what is
// happening") for Ajustes. Everything it touches comes in through `deps`, so it can be tested without Electron.
const { isLocalHttpUrl } = require('./lan');

const POLL_MS = 2000;
const GIVE_UP_MS = 3 * 60 * 1000;
const INSTALL_GIVE_UP_MS = 40 * 60 * 1000;   // a download plus the first start of Home Assistant
const CANCELLED_AFTER_MS = 6000;   // pending is gone and nothing got connected: the person said no (or it failed)

const names = (players) => (players || []).slice(0, 3).map((p) => p.name).join(', ');

// What Ajustes says once something is connected.
function summary(status) {
  if (!status || !status.configured) return '';
  if (status.error) return status.error;
  if (!status.connected) return '';
  const players = status.players || [];
  return players.length
    ? `Conectado. Achei: ${names(players)}${players.length > 3 ? ' e mais' : ''}.`
    : 'Conectado ao Home Assistant, mas não vejo nenhuma Alexa ou caixa de som. Falta ligar a Alexa lá (veja "Como ligar a Alexa").';
}

// deps: engine (the client), openExternal(url), note(text), afterConnected(status), friendlyError(e), sleep(ms), now()
function createHomeService(deps) {
  const { engine, openExternal, note, afterConnected, friendlyError, isEngineUp } = deps;
  const sleep = deps.sleep || ((ms) => new Promise((r) => setTimeout(r, ms)));
  const now = deps.now || Date.now;
  let waiting = 0;   // a counter: starting again cancels the wait of the earlier try
  let lastWait = Promise.resolve();   // the wait in progress, so a test (or a caller) can await it instead of guessing a time

  async function waitForApproval(mine) {
    const started = now();
    while (mine === waiting && now() - started < GIVE_UP_MS) {
      await sleep(POLL_MS);
      if (mine !== waiting) return;
      let status;
      try { status = await engine().homeStatus(); } catch { continue; }
      if (status.connected && !status.pending) { await afterConnected(status); return; }
      if (!status.pending && now() - started > CANCELLED_AFTER_MS) { note('A conexão não foi concluída. Se foi sem querer, toque em Conectar de novo.'); return; }
    }
    if (mine === waiting) note('Não vi a aprovação a tempo. Toque em Conectar para tentar de novo.');
  }

  // -> { ok, message } | { needAddress, message } | { error }
  async function connect(typed) {
    if (!isEngineUp()) return { error: 'O motor do Chakmati não está rodando.' };
    try {
      let url = typeof typed === 'string' ? typed.trim() : '';
      if (!url) {
        note('Procurando o Home Assistant na sua rede… (leva alguns segundos)');
        const { found } = await engine().homeDiscover();
        if (!found || !found.length) {
          const message = 'Não achei o Home Assistant na sua rede. Se ele estiver ligado, escreva o endereço dele abaixo (por exemplo 192.168.0.10, que aparece em Configurações > Sistema > Rede no próprio Home Assistant, ou na lista de aparelhos do seu roteador). Se você ainda não tem um, toque em "Ainda não tenho o Home Assistant".';
          note(message);
          return { needAddress: true, message };
        }
        url = found[0].url;
      }
      const { authorize_url: authorize } = await engine().homeConnect(url);
      if (!isLocalHttpUrl(authorize)) return { error: 'Endereço de conexão inesperado: não abri nada.' };
      const mine = ++waiting;
      await openExternal(authorize);
      lastWait = waitForApproval(mine).catch(() => {});
      const message = 'Abri o Home Assistant no seu navegador. Entre com a sua conta e toque em Aprovar.';
      note(message);
      return { ok: true, message };
    } catch (e) {
      const message = friendlyError(e);
      note(message);
      return { error: message };
    }
  }

  // Installing a Home Assistant here (Docker). The person is asked first: a download of about 1 GB must never start without a yes.
  async function waitForInstall(mine) {
    const started = now();
    let shown = '';
    while (mine === waiting && now() - started < INSTALL_GIVE_UP_MS) {
      let status;
      try { status = await engine().homeInstallStatus(); } catch { await sleep(POLL_MS); continue; }
      if (status.message && status.message !== shown) { shown = status.message; note(shown); }
      if (status.state === 'done') { await afterConnected(await engine().homeStatus()); return; }
      if (status.state === 'error') return;
      await sleep(POLL_MS);
    }
    if (mine === waiting) note('A instalação está demorando mais do que o normal. Deixe o Chakmati aberto e veja de novo daqui a pouco.');
  }

  // -> { ok, message } | { cancelled, message } | { error, code? }
  async function install({ name, password } = {}) {
    if (!isEngineUp()) return { error: 'O motor do Chakmati não está rodando.' };
    if (typeof password !== 'string' || password.length < 8) return { error: 'Escolha uma senha com pelo menos 8 caracteres.' };
    try {
      const info = await engine().homeInstallStatus();
      if (info.docker === 'no_docker') {
        const message = 'O Docker não está instalado neste computador. Instale o Docker Desktop (é grátis para uso pessoal), abra-o uma vez e toque em Instalar de novo.';
        note(message);
        return { error: message, code: 'docker_missing' };
      }
      const yes = await deps.confirm({
        message: 'Instalar o Home Assistant neste computador?',
        detail: `O Chakmati vai usar o Docker para baixar o Home Assistant (cerca de ${Math.round((info.image_mb || 1000) / 100) / 10} GB, uma estimativa) da internet e deixá-lo rodando só neste computador. Ele usa uns 2 GB de memória enquanto estiver ligado.\n\nNada é baixado sem a sua aprovação.`,
      });
      if (yes !== true) { const message = 'Tudo bem, não instalei nada.'; note(message); return { cancelled: true, message }; }
      const mine = ++waiting;
      await engine().homeInstall(typeof name === 'string' ? name : '', password);
      note('Instalando o Home Assistant… pode levar vários minutos. Deixe o Chakmati aberto.');
      lastWait = waitForInstall(mine).catch(() => {});
      return { ok: true, message: 'Instalando o Home Assistant…' };
    } catch (e) {
      const message = friendlyError(e);
      note(message);
      return { error: message };
    }
  }

  async function disconnect() {
    waiting += 1;
    try { await engine().homeDisconnect(); } catch (e) { return { error: friendlyError(e) }; }
    note('Desconectado do Home Assistant.');
    await deps.afterDisconnected();
    return { ok: true };
  }

  return { connect, install, disconnect, waitForApproval, idle: () => lastWait, cancel: () => { waiting += 1; } };
}

module.exports = { createHomeService, summary, POLL_MS, GIVE_UP_MS };
