// The smart-house assistant in Ajustes: one button, or "connected" with a way to disconnect, and the modal that does the work (the flow is in flow.js).

(function () {
  const P = window.Panel;
  const { $, api } = P;
  const flow = window.HomeFlow.create({ $, api, locale: navigator.language, rootId: 'home-modal' });

  // The section in Ajustes: one button, or "connected" with a way to disconnect.
  function renderHome() {
    const home = (P.state && P.state.overview && P.state.overview.home) || {};
    $('home-open').hidden = !!home.connected;
    $('home-on').hidden = !home.connected;
    $('home-alexa').hidden = !(home.connected && !(home.players || []).length);   // connected, but no speaker yet: the way to link the Alexa
  }

  flow.bind();
  $('home-open').addEventListener('click', flow.open);
  $('home-alexa').addEventListener('click', flow.openAlexa);
  $('home-disconnect').addEventListener('click', async () => { await api.homeDisconnect(); renderHome(); });
  Object.assign(P, { renderHome });
})();
