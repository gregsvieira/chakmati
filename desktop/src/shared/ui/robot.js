// Chakmati: the 3D figure itself, as pictures (src/shared/ui/moods/, Meshy renders with a transparent background), one face for each way he feels:
//   smile (alert, happy) · bored (nothing to do) · thinking (working) · angry (something failed) · drunk (something is off) · sleeping (offline)
// Every picture is aligned on his bow tie, so changing faces never moves his body. Each also has a "-wood" twin with his wooden frame drawn behind him:
// that one is used only when the whole chat is open (setWood). The moods (setMood) and the voice (setTalking) move the whole figure (robot.css).
// Changing faces goes through a blink: the sleeping picture (eyes shut) shows for an instant between the old face and the new one, and he also blinks
// now and then on his own. Built with DOM calls (no innerHTML). setMood(): idle, alert, thinking, happy, offline, angry, drunk, sleeping.
(function () {
  const NS = 'http://www.w3.org/2000/svg';
  const here = document.currentScript && document.currentScript.src;
  const picture = (name) => (here ? new URL(`moods/${name}.png`, here).href : `moods/${name}.png`);
  const SIZE = { w: 472, h: 891 };                                  // every picture's own pixels (one canvas for all)
  const MARGIN = 40;                                                // room around him for the moods that move him (a hop, a sway, a breath)
  const VIEWBOX = `${-MARGIN} ${-MARGIN} ${SIZE.w + 2 * MARGIN} ${SIZE.h + 2 * MARGIN}`;
  const FACES = ['smile', 'bored', 'thinking', 'angry', 'drunk', 'sleeping'];
  const FACE_OF = { idle: 'bored', alert: 'smile', happy: 'smile', thinking: 'thinking', angry: 'angry', drunk: 'drunk', offline: 'sleeping', sleeping: 'sleeping' };
  const BLINK_MS = 120;                                             // how long the eyes stay shut in a blink
  const BLINKS = new Set(['bored', 'smile', 'thinking', 'drunk']);  // the faces that blink on their own (angry stares; sleeping is already shut)

  const el = (name, attrs = {}, parent) => {
    const node = document.createElementNS(NS, name);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
    if (parent) parent.appendChild(node);
    return node;
  };
  const still = () => {
    try {
      if (document.body && document.body.hasAttribute('data-still')) return true;
      return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    } catch { return false; }
  };

  function create(container) {
    const svg = el('svg', { viewBox: VIEWBOX, class: 'robot', 'data-mood': 'idle', 'data-face': 'bored', role: 'img', 'aria-label': 'Chakmati' }, container);
    const fig = el('g', { class: 'fig' }, svg);
    const image = (cls, name) => el('image', { class: cls, href: picture(name), x: 0, y: 0, width: SIZE.w, height: SIZE.h, preserveAspectRatio: 'xMidYMid meet' }, fig);
    for (const face of FACES) image(`f-${face}`, face);
    let woodLoaded = false;
    const loadWood = () => { if (woodLoaded) return; woodLoaded = true; for (const face of FACES) image(`w-${face}`, `${face}-wood`); };   // only when the whole chat opens

    let face = 'bored';
    let timer = null;
    let blinkTimer = null;
    const show = (name) => { face = name; svg.setAttribute('data-face', name); };

    // the eyes shut for an instant, then the face `to`: the blink that joins two faces
    function blinkTo(to) {
      clearTimeout(timer);
      if (to === face) return;
      if (still() || face === 'sleeping' || to === 'sleeping' || typeof setTimeout !== 'function') { show(to); return; }
      show('sleeping');
      timer = setTimeout(() => show(to), BLINK_MS);
    }

    function scheduleBlink() {
      if (typeof setTimeout !== 'function') return;
      clearTimeout(blinkTimer);
      blinkTimer = setTimeout(() => {
        if (!still() && BLINKS.has(face)) {
          const back = face;
          show('sleeping');
          timer = setTimeout(() => { if (face === 'sleeping') show(back); }, BLINK_MS);
        }
        scheduleBlink();
      }, 3500 + Math.random() * 3500);
    }

    scheduleBlink();
    return {
      svg,
      setWood(on) { if (on) loadWood(); svg.setAttribute('data-wood', on ? 'true' : 'false'); },   // the big window: his wooden frame behind him
      setTalking(on) { svg.setAttribute('data-talking', on ? 'true' : 'false'); },
      setMood(mood) {
        const known = Object.prototype.hasOwnProperty.call(FACE_OF, mood) ? mood : 'idle';
        svg.setAttribute('data-mood', known);
        blinkTo(FACE_OF[known]);
      },
    };
  }

  window.Robot = { create, FACES, FACE_OF };
})();
