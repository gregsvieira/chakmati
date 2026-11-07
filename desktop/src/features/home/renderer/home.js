// The smart-house assistant: one button in Ajustes, and a modal that finds a Home Assistant or installs one (Docker, Home Assistant, the Alexa integration),
// and at the end asks for a name and a password. The sentences and the choice of page come from modal-logic.js; this only shows them.

(function () {
  const P = window.Panel;
  const { $, api } = P;
  const M = window.HomeModal;
  const PAGES = ['search', 'found', 'intro', 'progress', 'approving', 'account', 'alexa', 'alexa-wait', 'done'];
  let page = 'closed';
  let timer = null;
  let foundUrl = '';
  let fromInstall = false;   // the Home Assistant is the one this app installed (so "Abrir o Home Assistant" goes to it)
  let startedAt = 0;

  const stopPolling = () => { if (timer) { clearInterval(timer); timer = null; } };
  const poll = (fn, ms = 2000) => { stopPolling(); timer = setInterval(fn, ms); };
  const error = (text) => { $('hm-error').textContent = text || ''; $('hm-error').hidden = !text; };

  function buttons(primary, secondary, cancel) {
    const set = (id, spec) => { $(id).hidden = !spec; if (spec) { $(id).textContent = spec.text; $(id).disabled = !!spec.disabled; } };
    set('hm-primary', primary);
    set('hm-secondary', secondary);
    set('hm-cancel', cancel);
  }

  function show(name, text) {
    page = name;
    for (const p of PAGES) $('hm-' + p).hidden = p !== name;
    if (name !== 'progress' && name !== 'approving' && name !== 'alexa-wait') stopPolling();
    if (name === 'search') buttons(null, null, { text: 'Cancelar' });
    if (name === 'found') buttons({ text: 'Conectar' }, null, { text: 'Cancelar' });
    if (name === 'progress') buttons(null, null, { text: 'Fechar (continua em segundo plano)' });
    if (name === 'approving') buttons(null, null, { text: 'Cancelar' });
    if (name === 'account') buttons({ text: 'Conectar' }, null, { text: 'Cancelar' });
    if (name === 'alexa') buttons({ text: 'Conectar a Alexa' }, null, { text: 'Agora não' });
    if (name === 'alexa-wait') buttons(null, null, { text: 'Cancelar' });
    if (name === 'done') buttons({ text: 'Fechar' }, fromInstall ? { text: 'Abrir o Home Assistant' } : null, null);
    if (text !== undefined) {
      if (name === 'progress') $('hm-progress-text').textContent = text;
      if (name === 'account') $('hm-account-text').textContent = text;
      if (name === 'done') $('hm-done-text').textContent = text;
    }
  }

  function fail(text, retry = true) {
    error(text);
    stopPolling();
    buttons(retry ? { text: 'Tentar de novo' } : null, null, { text: 'Fechar' });
    page = 'error';
  }

  function close() {
    stopPolling();
    for (const id of ['hm-password', 'hm-alexa-password', 'hm-email']) $(id).value = '';   // neither the passwords nor the e-mail stay on the page
    $('home-modal').hidden = true;
    page = 'closed';
    error('');
  }

  function renderIntro(info) {
    $('hm-steps').replaceChildren(...M.introSteps(info).map((t) => Object.assign(document.createElement('li'), { textContent: t })));
    show('intro');
    buttons({ text: 'Começar', disabled: !M.canStart(info) }, null, { text: 'Agora não' });
  }

  function watchInstall() {
    show('progress', 'Verificando o Docker…');
    poll(async () => {
      const next = M.stageFor(await api.homeInstallInfo());
      if (page === 'closed') return stopPolling();
      if (next.stage === 'progress') { $('hm-progress-text').textContent = next.text; return; }
      stopPolling();
      if (next.stage === 'account') { fromInstall = true; show('account', next.text); $('hm-name').focus(); }
      else if (next.stage === 'found') { foundUrl = 'http://localhost:8123'; fromInstall = true; $('hm-found-text').textContent = next.text; show('found'); }
      else if (next.stage === 'done') { fromInstall = true; await afterConnected(); }
      else fail(next.text, next.code !== 'reboot');
    });
  }

  async function open() {
    $('home-modal').hidden = false;
    error('');
    show('search');
    const current = await api.homeInstallInfo();
    if (current && !current.error && (current.state === 'running' || (current.state === 'ready' && current.code === 'needs_account'))) { fromInstall = true; return resume(current); }
    const found = await api.homeDiscover();
    if (page === 'closed') return undefined;
    if (found.error) return fail(found.error);
    if (found.found.length) {
      foundUrl = found.found[0].url;
      fromInstall = false;
      $('hm-found-text').textContent = `Encontrei o Home Assistant da sua casa (${found.found[0].name}, em ${foundUrl}).`;
      return show('found');
    }
    if (current.error) return fail(current.error);
    fromInstall = false;
    return renderIntro(current);
  }

  function resume(info) {
    const next = M.stageFor(info);
    if (next.stage === 'progress') return watchInstall();
    return show('account', next.text);
  }

  // Connected: if a speaker is already there we are done; otherwise it is time to link the Alexa.
  async function afterConnected() {
    const status = await api.homeStatus();
    if (M.afterConnected(status) === 'done') return show('done', M.doneText(status));
    return openAlexa();
  }

  async function openAlexa() {
    $('home-modal').hidden = false;
    const info = await api.homeAlexaStatus();
    const regions = (info && info.regions) || {};
    $('hm-region').replaceChildren(...Object.entries(regions).map(([id, name]) => Object.assign(document.createElement('option'), { value: id, textContent: `${name} (${id})` })));
    $('hm-region').value = M.regionFor(navigator.language, regions);
    for (const id of ['hm-email', 'hm-alexa-password']) $(id).value = '';
    show('alexa');
    $('hm-email').focus();
  }

  async function startAlexa() {
    const region = $('hm-region').value;
    const email = $('hm-email').value;
    const password = $('hm-alexa-password').value;
    $('hm-alexa-password').value = '';   // gone from the page the moment it is sent
    const res = await api.homeAlexaStart(region, email, password);
    if (res.error) return error(res.error);
    show('alexa-wait');
    return poll(async () => {
      const out = M.alexaWait(await api.homeAlexaStatus());
      if (page !== 'alexa-wait') return;
      if (out.stage === 'alexa-wait') return;
      stopPolling();
      if (out.stage === 'done') {   // the speakers show up a few seconds after the configuration is loaded
        let status = await api.homeStatus();
        for (let i = 0; i < 10 && !(status.players || []).length; i += 1) { await new Promise((r) => setTimeout(r, 2000)); status = await api.homeStatus(); }
        return show('done', M.doneText(status));
      }
      show('alexa');
      return error(out.text);
    });
  }

  async function primary() {
    error('');
    if (page === 'error') return open();
    if (page === 'done') return close();
    if (page === 'intro') {
      const res = await api.homeInstallStart();
      if (res.error) return fail(res.error);
      fromInstall = true;
      return watchInstall();
    }
    if (page === 'found') {
      const res = await api.homeConnect(foundUrl);
      if (res.error) return fail(res.error);
      show('approving');
      startedAt = Date.now();
      return poll(async () => {
        const out = M.approval(await api.homeStatus(), Date.now() - startedAt);
        if (out.stage === 'done') await afterConnected();
        else if (out.stage === 'error') fail(out.text);
      });
    }
    if (page === 'account') {
      const res = await api.homeAccount($('hm-name').value, $('hm-password').value);
      if (res.error) return error(res.error);
      $('hm-password').value = '';
      return afterConnected();
    }
    if (page === 'alexa') return startAlexa();
    return undefined;
  }

  // The section in Ajustes: one button, or "connected" with a way to disconnect.
  function renderHome() {
    const home = (P.state && P.state.overview && P.state.overview.home) || {};
    $('home-open').hidden = !!home.connected;
    $('home-on').hidden = !home.connected;
    $('home-alexa').hidden = !(home.connected && !(home.players || []).length);   // connected, but no speaker yet: the way to link the Alexa
  }

  $('home-open').addEventListener('click', open);
  $('home-alexa').addEventListener('click', openAlexa);
  $('home-disconnect').addEventListener('click', async () => { await api.homeDisconnect(); renderHome(); });
  $('hm-primary').addEventListener('click', primary);
  $('hm-secondary').addEventListener('click', () => api.homeOpenHa());
  $('hm-cancel').addEventListener('click', async () => {
    if (page === 'alexa-wait') { await api.homeAlexaCancel(); show('alexa'); return; }
    if (page === 'alexa') { await api.homeAlexaCancel(); show('done', M.doneText(await api.homeStatus())); return; }
    close();
  });
  $('hm-password').addEventListener('keydown', (e) => { if (e.key === 'Enter') primary(); });
  $('hm-alexa-password').addEventListener('keydown', (e) => { if (e.key === 'Enter') primary(); });
  $('home-modal').addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });
  Object.assign(P, { renderHome });
})();
