'use strict';
// Turns "this computer + what the person ticked" into the list of things to do. Pure: it changes nothing and downloads nothing.
const { CORE, ENGINE, MODELS, OPTIONS, extrasSizeMb } = require('./catalog');
const { LIMITS, reasoningFor } = require('./tiers');
const { PERSONALITIES, PERSONALITY_NAMES, PRONOUNS, PRONOUN_NAMES } = require('../settings').settings; // the pure part of the feature: the plan never needs electron

const { PROVIDERS, validProvider, validModel } = require('../engine').cloudKey;

const TIGHT_RAM = 0.85; // above this share of the computer's memory the app will feel heavy

// How the Chakmati speaks: the personality chosen as the default, the others the person wants in Ajustes, and the pronouns. Free (a few lines of text):
// no download, no approval. Null when the wizard did not ask (the plan is then only what was ticked).
function profileStep(profile) {
  if (!profile) return null;
  const { personality = 'padrao', personalities = [], pronouns = 'none' } = profile;
  if (!PERSONALITIES.includes(personality)) throw new Error(`Personalidade desconhecida: ${personality}`);
  if (!PRONOUNS.includes(pronouns)) throw new Error(`Pronomes desconhecidos: ${pronouns}`);
  if (!Array.isArray(personalities) || personalities.some((p) => !PERSONALITIES.includes(p))) throw new Error('Personalidade desconhecida na lista.');
  const installed = PERSONALITIES.filter((p) => p === 'padrao' || p === personality || personalities.includes(p));
  const more = installed.filter((p) => p !== 'padrao' && p !== personality).map((p) => PERSONALITY_NAMES[p]);
  return {
    id: 'profile', kind: 'setting', required: false,
    label: `Jeito de falar: ${PERSONALITY_NAMES[personality]}${more.length ? ` (e mais: ${more.join(', ')})` : ''}; pronomes: ${PRONOUN_NAMES[pronouns]}`,
    settings: { personality, personalities: installed, pronouns },
  };
}

// The paid AI the person connected (the key itself was checked and stored by the main process; the plan only knows which one). `local: false` = no local model.
function cloudStep(cloud) {
  if (!cloud) return null;
  if (!validProvider(cloud.provider) || !validModel(cloud.model)) throw new Error('A conexão com a sua IA paga está incompleta.');
  const local = cloud.local !== false;
  return {
    id: 'cloud', kind: 'setting', required: false, local,
    label: `Usar a sua assinatura de IA: ${PROVIDERS[cloud.provider].label} (${cloud.model})${local ? ', com o modelo local de reserva' : ''}`,
    settings: { cloudProvider: cloud.provider, cloudModel: cloud.model, localModel: local },
  };
}

function buildPlan({ hw, verdict, selected = [], engine = null, profile = null, cloud = null }) {
  if (verdict.level === 'unsupported') {
    return { ok: false, blocked: [...verdict.reasons], steps: [], baseline: {}, totals: null, warnings: [], after: [] };
  }
  const chosen = new Set(selected);
  for (const id of chosen) {
    const option = OPTIONS.find((o) => o.id === id);
    if (!option) throw new Error(`Item desconhecido: ${id}`);
    if (!option.platforms.includes(hw.platform) || (engine && option.needsRepo) || (!engine && option.needsPackaged)) throw new Error(`Item indisponível neste sistema: ${id}`);
  }
  const cloudLine = cloudStep(cloud);
  const useLocal = !cloudLine || cloudLine.local;   // the local model is installed unless the person chose to run only on the paid AI
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
    id: 'extras', kind: 'sync-extras', label: `Instalar os pacotes de ${extras.map((e) => ({ voice: 'voz', listen: 'microfone', laya: 'Laya', documents: 'leitura de arquivos' }[e])).join(' e ')}`,
    required: false, extras,
    approval: { source: 'pypi.org (pelo uv que vem no instalador)', sizeMb: extrasSizeMb(extras) }, settings: {},
  };
  const profileLine = profileStep(profile);
  const steps = [
    ...(useLocal || chosen.has('reasoning') ? [ollama] : []),
    ...(engine ? [engineStep] : []),
    ...(useLocal ? [modelStep] : []),
    ...(cloudLine ? [cloudLine] : []),
    ...(profileLine ? [profileLine] : []),
    ...(engine && extras.length ? [extrasStep] : []),
    ...(thinker ? [{
      id: 'reasoning', kind: 'pull-model', model: thinker.id, label: `Baixar o ${thinker.label.toLowerCase()} (${thinker.id})`, required: false,
      approval: { source: 'ollama.com (pelo Ollama instalado neste computador)', sizeMb: thinker.diskMb }, settings: {},
    }] : []),
    ...picked.filter((o) => o.id !== 'reasoning').map((o) => ({
      id: o.id, kind: o.action || 'setting', label: o.action ? o.label : `Ativar: ${o.label}`, required: false,
      ...(o.approval ? { approval: o.approval } : {}),
      ...(engine && o.extra ? { requires: 'extras' } : {}),
      settings: { ...o.settings },
    })),
  ];

  // The person saw every item and left some out: those are written as off, so nothing optional is on by accident.
  const baseline = cloudLine ? {} : { cloudProvider: '', cloudModel: '', localModel: true };   // no paid AI chosen: written as off
  for (const o of OPTIONS) if (!chosen.has(o.id)) Object.assign(baseline, o.offSettings);

  const totals = {
    diskMb: CORE.diskMb + (useLocal ? model.diskMb : 0) + (thinker ? thinker.diskMb : 0) + picked.reduce((n, o) => n + o.diskMb, 0) + (engine ? extrasSizeMb(extras) : 0),
    ramMb: CORE.ramMb + Math.max(useLocal ? model.ramMb : 0, thinker ? thinker.ramMb : 0) + picked.reduce((n, o) => n + o.ramMb, 0), // the two models are not in memory together
  };

  const blocked = [];
  const warnings = [...verdict.notes];
  if (!useLocal) warnings.push('Sem o modelo local, quando o limite da sua assinatura de IA acabar o Chakmati não consegue responder até ele renovar.');
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
