const test = require('node:test');
const assert = require('node:assert/strict');
const { quip, PRAISE, TEASE } = require('../../../src/features/installer/quips');
const { verdict } = require('../../../src/features/installer/tiers');

const pc = (over = {}) => ({ platform: 'darwin', arch: 'arm64', osRelease: '25.0', ramGb: 15.6, freeDiskGb: 50, cores: 8, ...over });
const say = (hw) => quip(hw, verdict(hw));

test('a weak computer is praised, absurdly', () => {
  const q = say(pc({ ramGb: 5.7, cores: 2 }));
  assert.equal(q.tone, 'praise');
  assert.ok(PRAISE.includes(q.text));
});

test('a very strong computer is teased as if it were a relic', () => {
  const q = say(pc({ ramGb: 31.6, cores: 12 }));
  assert.equal(q.tone, 'tease');
  assert.ok(TEASE.includes(q.text));
});

test('the sentences the owner asked for are among them', () => {
  assert.ok(PRAISE.includes('Nossa, é uma honra ser convidado para essa máquina da NASA!'));
  assert.ok(PRAISE.includes('Então esse é o computador de lançamento da SpaceX?'));
  assert.deepEqual([...TEASE], [
    'É a primeira vez que tentam me rodar no laptop da xuxa.',
    'Esse é o computador do show do milhão?',
    'Ual. Esse pc so nao eh mais potente que minha torradeira jorges formgrill',
  ]);
});

test('a computer in between gets no remark, and neither does one that cannot run the app', () => {
  assert.equal(say(pc({ ramGb: 7.7, cores: 4 })), null);
  assert.equal(say(pc({ ramGb: 15.6, cores: 4 })), null);   // lots of memory but few cores: not "well above"
  assert.equal(say(pc({ ramGb: 2, cores: 2 })), null);      // below the minimum: no joking at a "no"
  assert.equal(quip(null, null), null);
});

test('the same computer always gets the same line; different ones may differ', () => {
  const hw = pc({ ramGb: 5.7, cores: 2 });
  assert.equal(say(hw).text, say({ ...hw }).text);
  const lines = new Set([4, 5, 6, 7].map((gb) => say(pc({ ramGb: gb - 0.3, cores: 2 })).text));
  assert.ok(lines.size >= 2);
});

test('there are few lines, on purpose', () => {
  assert.ok(PRAISE.length <= 5 && TEASE.length <= 5);
});
