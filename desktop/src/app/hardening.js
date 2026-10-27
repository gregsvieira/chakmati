'use strict';
// Locks every window down: no navigation, no new windows, every permission denied but the microphone (and that only for the panel, while talking is on).
const { app } = require('electron');
const ctx = require('../shared/context');

app.on('web-contents-created', (_event, contents) => {
  contents.on('will-navigate', (e) => e.preventDefault());
  contents.setWindowOpenHandler(() => ({ action: 'deny' }));
  // Everything is denied except the microphone, and only for the panel and only while "Ouvir e falar" is on.
  const micAllowed = (wc, permission, details) => permission === 'media' && !!ctx.settings && ctx.settings.talk === true
    && !!wc && wc.getURL().endsWith('panel.html') && (!details || !details.mediaTypes || details.mediaTypes.every((t) => t === 'audio'));
  contents.session.setPermissionRequestHandler((wc, permission, callback, details) => callback(micAllowed(wc, permission, details)));
  contents.session.setPermissionCheckHandler((wc, permission, _origin, details) => micAllowed(wc, permission, details));
});
