const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const read = (...p) => fs.readFileSync(path.join(__dirname, '..', '..', '..', 'src', ...p), 'utf8');

test('the wizard page keeps the strict CSP and loads only its own files', () => {
  const html = read('features', 'installer', 'renderer', 'installer.html');
  assert.match(html, /Content-Security-Policy" content="default-src 'none'; img-src 'self' data:; style-src 'self'; script-src 'self'"/);
  assert.equal(/<script(?![^>]*\bsrc=)/.test(html), false, 'no inline script');
  assert.equal(/\bstyle=/.test(html), false, 'no inline style');
  assert.equal(/https?:\/\//.test(html), false, 'no remote address');
});

test('the wizard script never writes data as HTML and nothing starts ticked', () => {
  const js = read('features', 'installer', 'renderer', 'installer.js');
  assert.equal(/innerHTML|outerHTML|insertAdjacentHTML|eval\(|new Function/.test(js), false);
  assert.equal(/setAttribute\(\s*['"]checked/.test(js), false);
  // the only place a box is ticked by the script: after the person ticked WhatsApp AND acknowledged the notice about the number being blocked
  const ticks = js.match(/\bchecked\s*=\s*true/g) || [];
  assert.ok(ticks.length <= 1);
  if (ticks.length) assert.ok(js.includes('waGate.run(showWhatsAppNotice, () => { box.checked = true;'));
  assert.equal(/\bchecked\b/.test(read('features', 'installer', 'renderer', 'installer.html')), false);
});

test('the preload exposes exactly the installer calls, each as invoke/send of a fixed channel', () => {
  const src = read('preload.js');
  const block = src.slice(src.indexOf('installer: {'));
  for (const channel of ['installer:scan', 'installer:plan', 'installer:run', 'installer:ollama-page', 'installer:progress', 'installer:finish']) {
    assert.ok(block.includes(`'${channel}'`), channel);
  }
});

test('the download dialog defaults to "Pular" and the only external page is the Ollama download', () => {
  const src = read('features', 'installer', 'wizard.js');
  assert.match(src, /buttons: step\.required \? \['Aprovar', 'Cancelar a instalação'\] : \['Aprovar', 'Pular'\]/);   // optional downloads: "Pular"; mandatory ones: cancel the install
  assert.match(src, /defaultId: 1/);
  assert.match(src, /cancelId: 1/);
  assert.equal((src.match(/openExternal\(/g) || []).length, 1);
  assert.match(src, /const OLLAMA_DOWNLOAD = 'https:\/\/ollama\.com\/download'/);
});

test('the app starts the wizard only on --setup, and downloads the chosen voice at the next start', () => {
  const start = read('app', 'start.js');
  assert.match(read('shared', 'constants.js'), /process\.argv\.includes\('--setup'\)/);
  assert.match(start, /ctx\.settings\.enhancedVoice && ctx\.state\.voice && !ctx\.state\.voice\.installed/);
});

test('the installed app opens the wizard on its own, and starts the engine from the data folder', () => {
  const start = read('app', 'start.js');
  const service = read('features', 'engine', 'service.js');
  assert.match(start, /needsSetup\(\{ packaged: app\.isPackaged/);
  assert.match(service, /engineLaunch\(\{ packaged: app\.isPackaged/);
  assert.match(service, /windowsHide: true/);
  assert.equal(/spawn\('uv'/.test(start + service), false, 'the engine is no longer started with a hard-coded uv');
});

test('the wizard writes the marker only after a finished install, and runs uv without a shell', () => {
  const index = read('features', 'installer', 'wizard.js');
  assert.match(index, /writeSetupDone\(/);
  assert.match(index, /result\.status === 'done'/);
  assert.match(index, /optionsFor\(hw\.platform, \{ packaged: !!engine \}\)/);
  const sync = read('features', 'installer', 'engine-sync.js');
  assert.equal(/shell:\s*true|exec\(|execSync|child_process'\)\.exec\b/.test(sync), false);
});

test('every element the wizard script looks up exists in the page, profile screen included', () => {
  const html = read('features', 'installer', 'renderer', 'installer.html');
  const js = read('features', 'installer', 'renderer', 'installer.js');
  const wanted = [...new Set([...js.matchAll(/\$\('([\w-]+)'\)/g)].map((m) => m[1]))];
  const missing = wanted.filter((id) => !html.includes(`id="${id}"`));
  assert.deepEqual(missing, []);
  assert.ok(wanted.includes('profile-personality') && wanted.includes('profile-more') && wanted.includes('profile-pronouns'));
});

test('the wizard sends the personality and pronouns choice with both the plan and the run, and the main process rebuilds the plan from it', () => {
  const js = read('features', 'installer', 'renderer', 'installer.js');
  assert.match(js, /api\.plan\(\[\.\.\.chosen\], profileOut\(\)\)/);
  assert.match(js, /api\.run\(\[\.\.\.chosen\], profileOut\(\)\)/);
  const wizard = read('features', 'installer', 'wizard.js');
  assert.match(wizard, /ipcMain\.handle\('installer:plan', \(_e, selected, profile\)/);
  assert.match(wizard, /ipcMain\.handle\('installer:run', async \(_e, selected, profile\)/);
  assert.match(read('preload.js'), /plan: \(selected, profile\) => ipcRenderer\.invoke\('installer:plan', selected, profile\)/);
});

test('a mandatory download has no "Pular": only approving it or cancelling the install, and the page says it is mandatory', () => {
  const wizard = read('features', 'installer', 'wizard.js');
  assert.match(wizard, /step\.required \? \['Aprovar', 'Cancelar a instalação'\] : \['Aprovar', 'Pular'\]/);
  assert.match(wizard, /Obrigatório: sem isso o Chakmati não funciona/);
  assert.match(wizard, /defaultId: 1/);   // the default button is still the one that downloads nothing
  const js = read('features', 'installer', 'renderer', 'installer.js');
  assert.match(js, /Obrigatórios: /);
  assert.match(js, /obrigatório/);
  assert.match(js, /result\.status === 'aborted'/);
});
