'use strict';
// Said once, when Chakmati starts (not when it is called: being called answers with a short "I am listening").
const STARTUP_GREETINGS = [
  'Klift, kloft, still, a porta se abriu!',
  'Klift, still, kloft! fala fióti.',
  'Klift, kloft, stão! fala paizão!',
];

// When the person's pronouns are "ela" the one that calls her "paizão" says it in the feminine instead; the other two are gender-free.
const FEMININE_GREETINGS = Object.freeze({
  'Klift, kloft, stão! fala paizão!': 'Klift, kloft, stôna! Fala mãezôna!',
});

const greetingsFor = (pronouns) => (pronouns === 'ela' ? STARTUP_GREETINGS.map((g) => FEMININE_GREETINGS[g] || g) : STARTUP_GREETINGS);

const pickGreeting = (random = Math.random, pronouns = 'none') => {
  const list = greetingsFor(pronouns);
  return list[Math.min(list.length - 1, Math.floor(random() * list.length))];
};

module.exports = { STARTUP_GREETINGS, FEMININE_GREETINGS, greetingsFor, pickGreeting };
