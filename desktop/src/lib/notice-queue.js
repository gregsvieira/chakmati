'use strict';
// What the bubble shows and in which order. Pure logic: the main process feeds it notices and tells it when the bubble
// has finished, and it answers with the next notice to display.

const URGENT = new Set(['approval']);

function present(notice, masked) {
  return masked && notice.masked ? notice.masked : notice.text;
}

function bubbleDuration(text) {
  return Math.min(10000, Math.max(4000, 3000 + text.length * 45));
}

class NoticeQueue {
  constructor({ maxWaiting = 5 } = {}) {
    this.maxWaiting = maxWaiting;
    this.current = null;
    this.waiting = [];
  }

  push(notice) {
    if (!this.current) {
      this.current = notice;
      return { show: notice };
    }
    if (notice.key && notice.key === this.current.key) { // an update about what is already on screen
      this.current = notice;
      return { show: notice };
    }
    const same = notice.key ? this.waiting.findIndex((w) => w.key === notice.key) : -1;
    if (same >= 0) {
      this.waiting[same] = notice;
      return { show: null };
    }
    if (URGENT.has(notice.kind)) {
      const firstOrdinary = this.waiting.findIndex((w) => !URGENT.has(w.kind));
      this.waiting.splice(firstOrdinary === -1 ? this.waiting.length : firstOrdinary, 0, notice);
    } else {
      this.waiting.push(notice);
    }
    while (this.waiting.length > this.maxWaiting) this.waiting.shift(); // the oldest waiting notice is the least relevant
    return { show: null };
  }

  done() {
    this.current = this.waiting.shift() || null;
    return { show: this.current };
  }

  clear() {
    this.current = null;
    this.waiting = [];
  }
}

module.exports = { NoticeQueue, present, bubbleDuration, URGENT };
