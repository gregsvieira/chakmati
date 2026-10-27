// Starts the page: every feature registers its handlers, then the first layout and the "ready" signal.

(function () {
  const P = window.Panel;
  const { api, thread } = P;

  P.inits.push(function () {
    api.onState((s) => { P.state = s; P.stateVersion += 1; P.render(); P.applyLayout(); if (thread.length) P.renderThread(false); P.runQueued(); });
    P.applyLayout();
    api.ready();
  });

  for (const init of P.inits) init();
})();
