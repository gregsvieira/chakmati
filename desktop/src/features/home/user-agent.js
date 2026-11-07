'use strict';
// The sign-in page is Amazon's own, and Amazon may refuse what looks like an embedded browser. Electron adds "Electron/x" and the app's own name to the user agent of the
// window; here they are taken out, so the window introduces itself as the plain Chrome it is built on. (The person is signing in to their own account: nothing else changes.)
function cleanUserAgent(ua, appName = '') {
  let out = String(ua || '').replace(/\s+Electron\/[\d.]+/gi, '');
  if (appName) out = out.replace(new RegExp(`\\s+${appName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\/[\\w.-]+`, 'gi'), '');
  return out.replace(/\s{2,}/g, ' ').trim();
}

module.exports = { cleanUserAgent };
