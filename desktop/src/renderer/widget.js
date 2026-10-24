(function () {
  const api = window.assistant.widget;
  const stage = document.getElementById('stage');
  const robotButton = document.getElementById('robot');
  const bubble = document.getElementById('bubble');
  const bubbleText = document.getElementById('bubble-text');
  const robot = window.Robot.create(robotButton);
  const badge = document.getElementById('mic-badge');
  api.onListening((on) => badge.classList.toggle('hidden', !on));
  let layout = null;

  function placeBubble() {
    if (!layout) return;
    const { side, alignRight, size, iconOffset: o, gap } = layout;
    const W = window.innerWidth;
    const H = window.innerHeight;
    badge.style.left = `${o.x + size / 2 - 58}px`; // beside the head, which is narrow and centred in its box
    badge.style.top = `${o.y + 6}px`;
    robotButton.style.left = `${o.x}px`;
    robotButton.style.top = `${o.y}px`;
    robotButton.style.width = robotButton.style.height = `${size}px`;
    for (const s of ['top', 'bottom', 'left', 'right']) bubble.classList.remove(`side-${s}`);
    bubble.classList.remove('align-right');
    bubble.classList.add(`side-${side}`);
    if (alignRight) bubble.classList.add('align-right');
    bubble.style.maxWidth = `${layout.bubble.w}px`;
    for (const k of ['top', 'bottom', 'left', 'right']) bubble.style[k] = 'auto';
    bubble.style.transform = 'none';
    if (side === 'top' || side === 'bottom') {
      if (side === 'top') bubble.style.bottom = `${H - o.y + gap}px`;
      else bubble.style.top = `${o.y + size + gap}px`;
      if (alignRight) bubble.style.right = '0px'; else bubble.style.left = '0px';
    } else {
      if (side === 'left') bubble.style.right = `${W - o.x + gap}px`;
      else bubble.style.left = `${o.x + size + gap}px`;
      bubble.style.top = '50%';
      bubble.style.transform = 'translateY(-50%)';
    }
  }

  api.onLayout((l) => { layout = l; placeBubble(); });
  let voiceOn = false;
  let voiceEmojis = false;
  let voiceEnhanced = false;
  let voiceSpeed = 'normal';
  api.onVoice((v) => { voiceOn = !!(v && v.hear); voiceEmojis = !!(v && v.emojis); voiceEnhanced = !!(v && v.enhanced); voiceSpeed = (v && v.speed) || 'normal'; if (!voiceOn) window.Voice.stop(); });
  api.onStill((on) => document.body.toggleAttribute('data-still', !!on));
  api.onMood((m) => robot.setMood(m));
  api.onBackdrop((on) => document.body.classList.toggle('backdrop', !!on));
  api.onBubble((b) => {
    robot.setTalking(!!b);
    if (!b) { bubble.classList.add('hidden'); window.Voice.stop(); return; }
    if (voiceOn && !b.silent) window.Voice.speak(b.text, { emojis: voiceEmojis, enhanced: voiceEnhanced, speed: voiceSpeed, onStart: () => api.speaking(true), onEnd: () => api.speaking(false) });
    bubbleText.textContent = b.text;
    bubble.dataset.kind = b.kind || 'system';
    bubble.classList.remove('hidden', 'enter');
    void bubble.offsetWidth; // restart the entrance animation
    bubble.classList.add('enter');
  });

  // The window is click-through except over the robot and the bubble: tell the app when the pointer is over them.
  for (const target of [robotButton, bubble]) {
    target.addEventListener('mouseenter', () => api.hover(true));
    target.addEventListener('mouseleave', () => { if (!dragging) api.hover(false); });
  }
  bubble.addEventListener('click', () => api.bubbleClick());

  // Click opens the panel, dragging moves the robot: the same gesture, told apart by how far the pointer travelled.
  let dragging = false;
  let origin = null;
  robotButton.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    origin = { x: e.screenX, y: e.screenY };
    dragging = false;
    robotButton.setPointerCapture(e.pointerId);
    api.dragStart();
  });
  robotButton.addEventListener('pointermove', (e) => {
    if (!origin) return;
    const dx = e.screenX - origin.x;
    const dy = e.screenY - origin.y;
    if (!dragging && Math.hypot(dx, dy) > 4) dragging = true;
    if (dragging) api.dragMove(dx, dy);
  });
  const finish = (e) => {
    if (!origin) return;
    const moved = dragging;
    origin = null;
    dragging = false;
    if (robotButton.hasPointerCapture?.(e.pointerId)) robotButton.releasePointerCapture(e.pointerId);
    api.dragEnd(moved);
    if (!moved) api.toggle();
  };
  robotButton.addEventListener('pointerup', finish);
  robotButton.addEventListener('pointercancel', finish);
  robotButton.addEventListener('contextmenu', (e) => { e.preventDefault(); api.menu(); });

  api.ready();
})();
