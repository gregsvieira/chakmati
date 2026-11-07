// The smart-house flow: finds a Home Assistant or installs one (Docker, Home Assistant, the Alexa integration), asks for a name and a password, links the Alexa.
// One controller for both places it lives: the modal of the panel (Ajustes) and the last screen of the setup wizard. The sentences and the choice of page come
// from modal-logic.js; this only shows them. `$` finds an element by id, `api` is the set of calls (the panel's or the wizard's), `rootId` the element to show.

(function (root) {
  function create({ $, api, M = root.HomeModal, locale = '', rootId = 'home-modal', labels = {}, onClose = () => {} }) {
    const L = { cancel: 'Cancelar', close: 'Fechar', skip: 'Agora não', ...labels };
    const PAGES = ['search', 'found', 'intro', 'progress', 'approving', 'account', 'alexa', 'alexa-wait', 'done'];
    let page = 'closed';
    let timer = null;
    let foundUrl = '';
    let fromInstall = false;   // the Home Assistant is the one this app installed (so "Abrir o Home Assistant" goes to it)
    let startedAt = 0;

    const setRoot = (visible) => { $(rootId).hidden = !visible; };
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
      if (name === 'search') buttons(null, null, { text: L.cancel });
      if (name === 'found') buttons({ text: 'Conectar' }, null, { text: L.cancel });
      if (name === 'progress') buttons(null, null, { text: `${L.close} (continua em segundo plano)` });
      if (name === 'approving') buttons(null, null, { text: L.cancel });
      if (name === 'account') buttons({ text: 'Conectar' }, null, { text: L.cancel });
      if (name === 'alexa') buttons({ text: 'Conectar a Alexa' }, null, { text: L.skip });
      if (name === 'alexa-wait') buttons(null, { text: 'Abrir no meu navegador' }, { text: L.cancel });
      if (name === 'done') buttons({ text: L.close }, fromInstall ? { text: 'Abrir o Home Assistant' } : null, null);
      if (text !== undefined) {
        if (name === 'progress') $('hm-progress-text').textContent = text;
        if (name === 'account') $('hm-account-text').textContent = text;
        if (name === 'done') $('hm-done-text').textContent = text;
      }
    }

    function fail(text, retry = true) {
      error(text);
      stopPolling();
      buttons(retry ? { text: 'Tentar de novo' } : null, null, { text: L.close });
      page = 'error';
    }

    function close() {
      stopPolling();
      for (const id of ['hm-password', 'hm-alexa-password', 'hm-email']) $(id).value = '';   // neither the passwords nor the e-mail stay on the page
      setRoot(false);
      page = 'closed';
      error('');
      onClose();
    }

    function renderIntro(info) {
      $('hm-steps').replaceChildren(...M.introSteps(info).map((t) => Object.assign(document.createElement('li'), { textContent: t })));
      show('intro');
      buttons({ text: 'Começar', disabled: !M.canStart(info) }, null, { text: L.skip });
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
      setRoot(true);
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
      setRoot(true);
      const info = await api.homeAlexaStatus();
      const regions = (info && info.regions) || {};
      $('hm-region').replaceChildren(...Object.entries(regions).map(([id, name]) => Object.assign(document.createElement('option'), { value: id, textContent: `${name} (${id})` })));
      $('hm-region').value = M.regionFor(locale, regions);
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

    // Wires the buttons of the markup once.
    function bind() {
      $('hm-primary').addEventListener('click', primary);
      $('hm-secondary').addEventListener('click', () => (page === 'alexa-wait' ? api.homeAlexaBrowser() : api.homeOpenHa()));
      $('hm-cancel').addEventListener('click', async () => {
        if (page === 'alexa-wait') { await api.homeAlexaCancel(); show('alexa'); return; }
        if (page === 'alexa') { await api.homeAlexaCancel(); show('done', M.doneText(await api.homeStatus())); return; }
        close();
      });
      $('hm-password').addEventListener('keydown', (e) => { if (e.key === 'Enter') primary(); });
      $('hm-alexa-password').addEventListener('keydown', (e) => { if (e.key === 'Enter') primary(); });
      $(rootId).addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });
    }

    return { open, openAlexa, close, bind };
  }

  root.HomeFlow = { create };
})(window);
