'use strict';
// "Manter o PC acordado para as automações": while the person asked for it AND some automation is on, the system is kept from
// sleeping by idleness on macOS, Windows and Linux (Electron's powerSaveBlocker; the screen may still turn off and lock). Without automations, or with the option off, nothing is held.

// Pure: should the computer be kept awake right now?
function wanted(settings, overview) {
  if (!settings || settings.keepAwake !== true) return false;
  const list = overview && Array.isArray(overview.automations) ? overview.automations : [];
  return list.some((a) => a && a.enabled === true);
}

// Holds at most one blocker; `power` is Electron's powerSaveBlocker (injected so it can be tested).
function createKeepAwake(power) {
  let id = null;
  const held = () => id !== null && power.isStarted(id);
  return {
    sync(settings, overview) {
      const want = wanted(settings, overview);
      if (want && !held()) id = power.start('prevent-app-suspension');
      else if (!want && id !== null) { if (power.isStarted(id)) power.stop(id); id = null; }
      return held();
    },
    release() { if (id !== null && power.isStarted(id)) power.stop(id); id = null; },
    get active() { return held(); },
  };
}

Object.assign(module.exports, { wanted, createKeepAwake });
