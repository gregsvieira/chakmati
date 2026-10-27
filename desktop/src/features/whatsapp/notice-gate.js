'use strict';
// A notice that must be read once before an action, and never again after it was acknowledged ("Compreendi e estou ciente!").
// The memory is whatever `storage` is (localStorage in the panel); if it cannot be read or written, the notice simply shows each time.
(function (root) {
  function createGate(storage, key) {
    const read = () => { try { return storage.getItem(key) === '1'; } catch { return false; } };
    const write = () => { try { storage.setItem(key, '1'); } catch { /* not remembered: it will show again */ } };
    return {
      acknowledged: read,
      // Does the action now if the notice was already read; otherwise shows it, and does the action only after it is acknowledged.
      // `show(onAck, onCancel)` draws the notice. Returns true when the action ran at once.
      run(show, action, onCancel = () => {}) {
        if (read()) { action(); return true; }
        show(() => { write(); action(); }, onCancel);
        return false;
      },
    };
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = { createGate };
  else root.NoticeGate = { createGate };
})(typeof window !== 'undefined' ? window : globalThis);
