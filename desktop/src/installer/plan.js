'use strict';
// Turns "this computer + what the person ticked" into the list of things to do. Pure: it changes nothing and downloads nothing.
const { CORE, ENGINE, MODELS, OPTIONS, extrasSizeMb } = require('./catalog');
const { LIMITS, reasoningFor } = require('./tiers');

const TIGHT_RAM = 0.85; // above this share of the computer's memory the app will feel heavy

function buildPlan({ hw, verdict, selected = [], engine = null }) {
  if (verdict.level === 'unsupported') {
    return { ok: false, blocked: [...verdict.reasons], steps: [], baseline: {}, totals: null, warnings: [], after: [] };
  }
  const chosen = new Set(selected);
  for (const id of chosen) {
    const option = OPTIONS.find((o) => o.id === id);
    if (!option) throw new Error(`Item desconhecido: ${id}`);
    if (!option.platforms.includes(hw.platform) || (engine && option.needsRepo)) throw new Error(`Item indisponível neste sistema: ${id}`);
  }
  const model = MODELS.find((m) => m.id === verdict.model);
  const picked = OPTIONS.filter((o) => chosen.has(o.id));
  const thinker = chosen.has('reasoning') ? reasoningFor(hw) : null;
  if (chosen.has('reasoning') && !thinker) throw new Error('Este computador não tem memória ou espaço para o modelo de raciocínio.');

  const extras = [...new Set(picked.filter((o) => o.extra).map((o) => o.extra))];
  const ollama = { id: 'ollama', kind: 'check-ollama', label: 'Verificar o Ollama', required: true, settings: {} };
  const engineStep = {
    id: 'engine', kind: 'sync-engine', label: 'Preparar o motor do Chakmati', required: true, extras: [],
    approval: { source: 'python.org e pypi.org (pelo uv que vem no instalador)', sizeMb: ENGINE.baseMb }, settings: {},
  };
  const modelStep = {
    id: 'model', kind: 'pull-model', model: model.id, label: `Baixar o ${model.label.toLowerCase()} (${model.id})`, required: true,
    approval: { source: 'ollama.com (pelo Ollama instalado neste computador)', sizeMb: model.diskMb },
    settings: { chatModel: model.id },
  };
  const extrasStep = {
    id: 'extras', kind: 'sync-extras', label: `Instalar os pacotes de ${extras.map((e) => ({ voice: 'voz', listen: 'microfone', laya: 'Laya' }[e])).join(' e ')}`,
    required: false, extras,
    approval: { source: 'pypi.org (pelo uv que vem no instalador)', sizeMb: extrasSizeMb(extras) }, settings: {},
  };
  const steps = [
    ollama,
    ...(engine ? [engineStep] : []),
    modelStep,
    ...(engine && extras.length ? [extrasStep] : []),
    ...(thinker ? [{
      id: 'reasoning', kind: 'pull-model', model: thinker.id, label: `Baixar o ${thinker.label.toLowerCase()} (${thinker.id})`, required: false,
      approval: { source: 'ollama.com (pelo Ollama instalado neste computador)', sizeMb: thinker.diskMb }, settings: {},
    }] : []),
    ...picked.filter((o) => o.id !== 'reasoning').map((o) => ({
      id: o.id, kind: 'setting', label: `Ativar: ${o.label}`, required: false,
      ...(o.approval ? { approval: o.approval } : {}),
      ...(engine && o.extra ? { requires: 'extras' } : {}),
      settings: { ...o.settings },
    })),
  ];

  // The person saw every item and left some out: those are written as off, so nothing optional is on by accident.
  const baseline = {};
  for (const o of OPTIONS) if (!chosen.has(o.id)) Object.assign(baseline, o.offSettings);

  const totals = {
    diskMb: CORE.diskMb + model.diskMb + (thinker ? thinker.diskMb : 0) + picked.reduce((n, o) => n + o.diskMb, 0) + (engine ? extrasSizeMb(extras) : 0),
    ramMb: CORE.ramMb + Math.max(model.ramMb, thinker ? thinker.ramMb : 0) + picked.reduce((n, o) => n + o.ramMb, 0), // the two models are not in memory together
  };

  const blocked = [];
  const warnings = [...verdict.notes];
  if (hw.freeDiskGb !== null && totals.diskMb / 1024 + LIMITS.diskMarginGb > hw.freeDiskGb) {
    blocked.push(`Espaço insuficiente: a instalação precisa de cerca de ${(totals.diskMb / 1024).toFixed(1).replace('.', ',')} GB mais ${LIMITS.diskMarginGb} GB de folga, e há ${hw.freeDiskGb} GB livres.`);
  }
  if (totals.ramMb > hw.ramGb * 1024 * TIGHT_RAM) {
    warnings.push('Com essa escolha a memória fica apertada: o computador pode ficar lento enquanto o Chakmati roda. Desmarque algum item ou aceite o modelo menor.');
  }

  return {
    ok: blocked.length === 0, blocked, steps, baseline, totals, warnings,
    after: picked.filter((o) => o.after).map((o) => o.after),
  };
}

module.exports = { buildPlan };
