const test = require('node:test');
const assert = require('node:assert/strict');
const { EXTRA_NAMES, extrasFromSettings, venvPython, uvPath, toolPath, engineLaunch, syncCommand } = require('../src/lib/engine-launch');

test('extras follow the settings that need them', () => {
  assert.deepEqual(EXTRA_NAMES, ['voice', 'listen']);
  assert.deepEqual(extrasFromSettings({ enhancedVoice: false, talk: false }), []);
  assert.deepEqual(extrasFromSettings({ enhancedVoice: true, talk: false }), ['voice']);
  assert.deepEqual(extrasFromSettings({ enhancedVoice: true, talk: true }), ['voice', 'listen']);
  assert.deepEqual(extrasFromSettings({ enhancedVoice: false, talk: true }), ['listen']);
});

test('paths are built for the target system, whatever system runs the test', () => {
  assert.equal(venvPython({ dataDir: '/d', platform: 'darwin' }), '/d/engine-venv/bin/python');
  assert.equal(venvPython({ dataDir: '/d', platform: 'linux' }), '/d/engine-venv/bin/python');
  assert.equal(venvPython({ dataDir: 'C:\\d', platform: 'win32' }), 'C:\\d\\engine-venv\\Scripts\\python.exe');
  assert.equal(uvPath({ resourcesPath: '/r', platform: 'darwin' }), '/r/bin/uv');
  assert.equal(uvPath({ resourcesPath: 'C:\\r', platform: 'win32' }), 'C:\\r\\bin\\uv.exe');
});

test('the tool PATH uses the separator of the system and keeps what was there first', () => {
  assert.equal(toolPath({ platform: 'darwin', base: '/a', home: '/h' }), '/a:/h/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin');
  assert.equal(toolPath({ platform: 'linux', base: '/a', home: '/h' }), '/a:/h/.local/bin:/usr/local/bin:/usr/bin:/bin');
  assert.equal(toolPath({ platform: 'win32', base: 'C:\\x;C:\\y', home: 'C:\\h' }), 'C:\\x;C:\\y');
  assert.equal(toolPath({ platform: 'linux', base: '', home: '/h' }), '/h/.local/bin:/usr/local/bin:/usr/bin:/bin');
});

test('in development the engine starts as before, in the checkout', () => {
  assert.deepEqual(engineLaunch({ packaged: false, repoRoot: '/repo', platform: 'darwin' }),
    { command: 'uv', args: ['run', 'python', '-m', 'liteagent.main'], cwd: '/repo', env: {} });
  assert.equal(engineLaunch({ packaged: false, repoRoot: null, platform: 'darwin' }), null);
});

test('installed, the engine runs from the data folder with its files kept out of the read-only app', () => {
  const l = engineLaunch({ packaged: true, resourcesPath: '/app/resources', dataDir: '/data', platform: 'darwin' });
  assert.equal(l.command, '/data/engine-venv/bin/python');
  assert.deepEqual(l.args, ['-m', 'liteagent.main']);
  assert.equal(l.cwd, '/data/engine-data');
  assert.deepEqual(l.env, { CHAKMATI_DB_PATH: '/data/engine-data/liteagent.db', CHAKMATI_CALENDAR_ICS_PATH: '/data/engine-data/agenda.ics' });
  const w = engineLaunch({ packaged: true, resourcesPath: 'C:\\app\\resources', dataDir: 'C:\\data', platform: 'win32' });
  assert.equal(w.command, 'C:\\data\\engine-venv\\Scripts\\python.exe');
  assert.equal(w.cwd, 'C:\\data\\engine-data');
  assert.equal(w.env.CHAKMATI_DB_PATH, 'C:\\data\\engine-data\\liteagent.db');
});

test('the sync command installs the engine as a copy, with the managed Python, inside the data folder', () => {
  const s = syncCommand({ resourcesPath: '/app/resources', dataDir: '/data', platform: 'darwin', extras: [] });
  assert.equal(s.command, '/app/resources/bin/uv');
  assert.deepEqual(s.args, ['sync', '--frozen', '--no-dev', '--no-editable', '--managed-python', '--python', '3.13', '--project', '/app/resources/engine']);
  assert.deepEqual(s.env, { UV_PROJECT_ENVIRONMENT: '/data/engine-venv', UV_PYTHON_INSTALL_DIR: '/data/python' });
  const e = syncCommand({ resourcesPath: '/r', dataDir: '/d', platform: 'linux', extras: ['voice', 'listen'] });
  assert.deepEqual(e.args.slice(-4), ['--extra', 'voice', '--extra', 'listen']);
  assert.equal(syncCommand({ resourcesPath: 'C:\\r', dataDir: 'C:\\d', platform: 'win32', extras: [] }).command, 'C:\\r\\bin\\uv.exe');
});

test('an extra that is not on the list never reaches the command line', () => {
  for (const bad of ['evil', '--index-url=http://x', 'voice; rm', '']) {
    assert.throws(() => syncCommand({ resourcesPath: '/r', dataDir: '/d', platform: 'linux', extras: [bad] }), /extra/i);
  }
});
