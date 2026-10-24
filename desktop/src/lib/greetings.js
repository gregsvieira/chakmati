'use strict';
// Said once, when Chakmati starts (not when it is called: being called answers with a short "I am listening").
const STARTUP_GREETINGS = [
  'Klift, kloft, still, a porta se abriu!',
  'Klift, still, kloft! fala fióti.',
  'Klift, kloft, stão! fala paizão!',
];

const pickGreeting = (random = Math.random) => STARTUP_GREETINGS[Math.min(STARTUP_GREETINGS.length - 1, Math.floor(random() * STARTUP_GREETINGS.length))];

module.exports = { STARTUP_GREETINGS, pickGreeting };
