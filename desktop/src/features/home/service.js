'use strict';
// The smart-house assistant, main-process side. The modal in the panel drives it step by step; this part talks to the engine, opens the Home Assistant
// login in the browser, and once something is connected switches the house on. Everything it touches comes in through `deps`, so it can be tested without Electron.
const { isLocalHttpUrl } = require('./lan');

const POLL_MS = 2000;
const GIVE_UP_MS = 3 * 60 * 1000;
const ALEXA_POLL_MS = 2000;
const ALEXA_GIVE_UP_MS = 11 * 60 * 1000;
const CANCELLED_AFTER_MS = 6000;   // pending is gone and nothing got connected: the person said no (or it failed)

const names = (players) => (players || []).slice(0, 3).map((p) => p.name).join(', ');

// One sentence about what is connected (the modal's last page and the notes of the main process).
function summary(status) {
  if (!status || !status.configured) return '';
  if (status.error) return status.error;
  if (!status.connected) return '';
  const players = status.players || [];
  return players.length
    ? `Conectado. Achei: ${names(players)}${players.length > 3 ? ' e mais' : ''}.`
    : 'Conectado ao Home Assistant, mas ainda não vejo nenhuma Alexa ou caixa de som. Falta entrar na sua conta da Amazon dentro do Home Assistant.';
}

// deps: engine (the client), openExternal(url), openLoginWindow(url, { onClosed }) -> { close() }, note(text), afterConnected(status), afterDisconnected(), friendlyError(e), isEngineUp(), sleep(ms), now()
function createHomeService(deps) {
  const { engine, openExternal, note, afterConnected, friendlyError, isEngineUp } = deps;
  const sleep = deps.sleep || ((ms) => new Promise((r) => setTimeout(r, ms)));
  const now = deps.now || Date.now;
  let waiting = 0;   // a counter: starting again cancels the wait of the earlier try
  let lastWait = Promise.resolve();   // the wait in progress, so a test (or a caller) can await it instead of guessing a time

  const down = () => ({ error: 'O motor do Chakmati não está rodando.' });

  async function waitForApproval(mine) {
    const started = now();
    while (mine === waiting && now() - started < GIVE_UP_MS) {
      await sleep(POLL_MS);
      if (mine !== waiting) return;
      let status;
      try { status = await engine().homeStatus(); } catch { continue; }
      if (status.connected && !status.pending) { await afterConnected(status); return; }
      if (!status.pending && now() - started > CANCELLED_AFTER_MS) { note('A conexão não foi concluída. Se foi sem querer, tente de novo.'); return; }
    }
    if (mine === waiting) note('Não vi a aprovação a tempo. Tente de novo.');
  }

  // Looks for a Home Assistant on the network. -> { found: [{ url, name }] } | { error }
  async function discover() {
    if (!isEngineUp()) return down();
    try {
      const { found } = await engine().homeDiscover();
      return { found: Array.isArray(found) ? found.slice(0, 5) : [] };
    } catch (e) { return { error: friendlyError(e) }; }
  }

  // Opens the login of the Home Assistant at `url` in the browser; the person only approves. -> { ok } | { error }
  async function connect(url) {
    if (!isEngineUp()) return down();
    const typed = typeof url === 'string' ? url.trim() : '';
    if (!typed) return { error: 'Faltou o endereço do Home Assistant.' };
    try {
      const { authorize_url: authorize } = await engine().homeConnect(typed);
      if (!isLocalHttpUrl(authorize)) return { error: 'Endereço de conexão inesperado: não abri nada.' };
      const mine = ++waiting;
      await openExternal(authorize);
      lastWait = waitForApproval(mine).catch(() => {});
      return { ok: true };
    } catch (e) { return { error: friendlyError(e) }; }
  }

  // Starts preparing a Home Assistant here (Docker, the image, the Alexa integration). The modal said what would happen and the person pressed "Começar".
  async function startInstall() {
    if (!isEngineUp()) return down();
    try { await engine().homeInstallStart(); return { ok: true }; } catch (e) { return { error: friendlyError(e) }; }
  }

  // The name and the password of the new Home Assistant, once it is up. The password goes to the engine and nowhere else. -> { ok } | { error }
  async function account({ name, password } = {}) {
    if (!isEngineUp()) return down();
    if (typeof password !== 'string' || password.length < 8) return { error: 'Escolha uma senha com pelo menos 8 caracteres.' };
    try {
      await engine().homeAccount(typeof name === 'string' ? name : '', password);
      await afterConnected(await engine().homeStatus());
      return { ok: true };
    } catch (e) { return { error: friendlyError(e) }; }
  }

  // Linking the Alexa: the engine starts Home Assistant's setup with the credentials (which stop there), the sign-in page opens in the app's own window,
  // and the status is read until Home Assistant has finished. -> { ok } | { error }
  let loginWindow = null;
  let alexaRun = 0;
  let loginUrl = '';   // the sign-in page of the setup in progress (checked before it was kept)
  let toBrowser = false;   // the person moved the sign-in to their own browser: closing the app's window then must not cancel the setup
  const closeLogin = () => { const w = loginWindow; loginWindow = null; if (w) { try { w.close(); } catch { /* already closed */ } } };

  async function alexaStart({ region, email, password } = {}) {
    if (!isEngineUp()) return down();
    try {
      const out = await engine().homeAlexaStart(region, email, password);
      const url = out && out.url;
      let path = '';
      try { path = new URL(url).pathname; } catch { /* not a URL */ }
      if (!isLocalHttpUrl(url) || !path.startsWith('/auth/alexamedia/proxy/')) {
        await engine().homeAlexaCancel().catch(() => {});
        return { error: 'Endereço de login inesperado: não abri nada.' };
      }
      const mine = ++alexaRun;
      closeLogin();
      let finished = false;
      loginUrl = url;
      toBrowser = false;
      loginWindow = deps.openLoginWindow(url, { onClosed: () => { loginWindow = null; if (!finished && !toBrowser && mine === alexaRun) engine().homeAlexaCancel().catch(() => {}); } });
      lastWait = (async () => {
        const started = now();
        while (mine === alexaRun && now() - started < ALEXA_GIVE_UP_MS) {
          await sleep(ALEXA_POLL_MS);
          if (mine !== alexaRun) return;
          let status;
          try { status = await engine().homeAlexaStatus(); } catch { continue; }
          if (status.state === 'login') continue;
          finished = true;
          loginUrl = '';
          closeLogin();
          if (status.state === 'done') await deps.afterConnected(await engine().homeStatus());
          return;
        }
        if (mine === alexaRun) { finished = true; closeLogin(); await engine().homeAlexaCancel().catch(() => {}); }
      })().catch(() => {});
      return { ok: true };
    } catch (e) { return { error: friendlyError(e) }; }
  }

  // The person prefers (or needs) to sign in with their own browser: the page is the same one, at the same local address. The wait goes on; the app's window closes
  // without cancelling the setup. Only the address the engine returned and this service checked is ever opened.
  async function alexaOpenBrowser() {
    let path = '';
    try { path = new URL(loginUrl).pathname; } catch { /* nothing in progress */ }
    if (!loginUrl || !isLocalHttpUrl(loginUrl) || !path.startsWith('/auth/alexamedia/proxy/')) return { error: 'Não há um login da Alexa em andamento.' };
    toBrowser = true;
    closeLogin();
    await deps.openExternal(loginUrl);
    return { ok: true };
  }

  async function alexaCancel() {
    alexaRun += 1;
    loginUrl = '';
    closeLogin();
    try { await engine().homeAlexaCancel(); } catch { /* it was already over */ }
    return { ok: true };
  }

  async function disconnect() {
    waiting += 1;
    try { await engine().homeDisconnect(); } catch (e) { return { error: friendlyError(e) }; }
    note('');
    await deps.afterDisconnected();
    return { ok: true };
  }

  return { discover, connect, startInstall, account, alexaStart, alexaOpenBrowser, alexaCancel, disconnect, waitForApproval, idle: () => lastWait, cancel: () => { waiting += 1; } };
}

module.exports = { createHomeService, summary, POLL_MS, GIVE_UP_MS };
