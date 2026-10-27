const test = require('node:test');
const assert = require('node:assert/strict');
const { readHardware } = require('../../../src/features/installer/hardware');

const GB = 1024 ** 3;
const fakeOs = (over = {}) => ({
  platform: () => 'linux', arch: () => 'x64', release: () => '6.8.0',
  totalmem: () => 16 * GB, cpus: () => new Array(8).fill({}), homedir: () => '/home/x', ...over,
});
const fakeFs = (free) => ({ statfsSync: () => ({ bavail: free, bsize: 1 }) });

test('reads platform, arch, system version, RAM, free disk and cores', () => {
  const hw = readHardware({ os: fakeOs(), fs: fakeFs(50 * GB), where: '/home/x' });
  assert.deepEqual(hw, { platform: 'linux', arch: 'x64', osRelease: '6.8.0', ramGb: 16, freeDiskGb: 50, cores: 8 });
});

test('exposes nothing beyond those six facts (no user, host or network)', () => {
  const hw = readHardware({ os: fakeOs({ hostname: () => 'meu-pc', userInfo: () => ({ username: 'ana' }) }), fs: fakeFs(GB), where: '/x' });
  assert.deepEqual(Object.keys(hw).sort(), ['arch', 'cores', 'freeDiskGb', 'osRelease', 'platform', 'ramGb']);
  assert.equal(JSON.stringify(hw).includes('meu-pc') || JSON.stringify(hw).includes('ana'), false);
});

test('values are rounded to one decimal', () => {
  const hw = readHardware({ os: fakeOs({ totalmem: () => 7.74 * GB }), fs: fakeFs(12.34 * GB), where: '/x' });
  assert.equal(hw.ramGb, 7.7);
  assert.equal(hw.freeDiskGb, 12.3);
});

test('free disk is null, not zero, when it cannot be measured', () => {
  const broken = { statfsSync: () => { throw new Error('nope'); } };
  assert.equal(readHardware({ os: fakeOs(), fs: broken, where: '/x' }).freeDiskGb, null);
});
