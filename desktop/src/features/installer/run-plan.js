'use strict';
// Runs a plan. The rule that matters is here: a step with a download is never started before the person has said yes
// (only a strict `true` counts), and nothing is saved unless the whole install worked.

async function execute(step, runners, onProgress) {
  switch (step.kind) {
    case 'check-ollama': return runners.checkOllama();
    case 'pull-model': return runners.pullModel(step.model, onProgress);
    case 'shortcut': return runners.createDesktopShortcut();
    case 'setting': return undefined; // only changes settings, which are saved at the end
    case 'sync-engine': return runners.syncEngine([], onProgress);
    case 'sync-extras': return runners.syncEngine(step.extras, onProgress);
    default: throw new Error(`Passo desconhecido: ${step.kind}`);
  }
}

async function runPlan(plan, { approve, runners, onProgress = () => {} }) {
  if (!plan.ok) return { status: 'blocked', results: [], settings: null };
  const results = [];
  let settings = { ...plan.baseline };
  const stop = (status) => ({ status, results, settings: null });

  for (const step of plan.steps) {
    if (step.requires && !results.some((r) => r.id === step.requires && r.status === 'done')) {
      results.push({ id: step.id, status: 'skipped' }); // what it needs was declined or failed
      continue;
    }
    if (step.approval) {
      let yes = false;
      try { yes = (await approve(step)) === true; } catch { yes = false; }
      if (!yes) {
        results.push({ id: step.id, status: 'declined' });
        if (step.required) return stop('aborted');
        continue;
      }
    }
    try {
      await execute(step, runners, (p) => onProgress({ id: step.id, ...p }));
      settings = { ...settings, ...step.settings };
      results.push({ id: step.id, status: 'done' });
    } catch (e) {
      results.push({ id: step.id, status: 'failed', error: (e && e.message) || 'erro' });
      if (step.required) return stop('failed');
    }
  }
  await runners.saveSettings(settings);
  return { status: 'done', results, settings };
}

module.exports = { runPlan };
