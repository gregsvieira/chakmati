'use strict';
// Turns "this computer + what the person ticked" into the list of things to do. Pure: it changes nothing and downloads nothing.
const { CORE, MODELS, OPTIONS } = require('./catalog');
const { LIMITS } = require('./tiers');

const TIGHT_RAM = 0.85; // above this share of the computer's memory the app will feel heavy

function buildPlan({ hw, verdict, selected = [] }) {
  if (verdict.level === 'unsupported') {
    return { ok: false, blocked: [...verdict.reasons], steps: [], baseline: {}, totals: null, warnings: [], after: [] };
  }
  const chosen = new Set(selected);
  for (const id of chosen) {
    const option = OPTIONS.find((o) => o.id === id);
    if (!option) throw new Error(`Item desconhecido: ${id}`);
    if (!option.platforms.includes(hw.platform)) throw new Error(`Item indisponível neste sistema: ${id}`);
  }
  const model = MODELS.find((m) => m.id === verdict.model);
  const picked = OPTIONS.filter((o) => chosen.has(o.id));

  const steps = [
    { id: 'ollama', kind: 'check-ollama', label: 'Verificar o Ollama', required: true, settings: {} },
    {
      id: 'model', kind: 'pull-model', model: model.id, label: `Baixar o ${model.label.toLowerCase()} (${model.id})`, required: true,
      approval: { source: 'ollama.com (pelo Ollama instalado neste computador)', sizeMb: model.diskMb },
      settings: { chatModel: model.id },
    },
    ...picked.map((o) => ({
      id: o.id, kind: 'setting', label: `Ativar: ${o.label}`, required: false,
      ...(o.approval ? { approval: o.approval } : {}), settings: { ...o.settings },
    })),
  ];

  // The person saw every item and left some out: those are written as off, so nothing optional is on by accident.
  const baseline = {};
  for (const o of OPTIONS) if (!chosen.has(o.id)) Object.assign(baseline, o.offSettings);

  const totals = {
    diskMb: CORE.diskMb + model.diskMb + picked.reduce((n, o) => n + o.diskMb, 0),
    ramMb: CORE.ramMb + model.ramMb + picked.reduce((n, o) => n + o.ramMb, 0),
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
