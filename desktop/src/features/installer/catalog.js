'use strict';
// What the installer can put on a computer. Plain data: the numbers are the sizes of the downloads; RAM figures are
// estimates (the file size plus working memory), not measurements, and the wizard says "cerca de".
const CORE = Object.freeze({ diskMb: 1500, ramMb: 400 }); // the app and the engine, without any optional piece

const model = (id, label, diskMb) => Object.freeze({ id, label, diskMb, ramMb: diskMb + 500 });
const MODELS = Object.freeze([
  model('qwen3.5:0.8b', 'Modelo leve', 1200),
  model('granite4:3b', 'Modelo compacto', 2100), // 3B, Apache 2.0, 24/24 on scripts/bench_loose_requests.py (qwen3.5:0.8b: 22/24)
  model('qwen3.5:4b', 'Modelo intermediário', 4000),
  model('qwen3.5:latest', 'Modelo completo', 6600),
]);

// Models that think before they answer: the engine uses one (when it is installed and the computer has the memory) to work out the
// questions of an exam and explain what a student got wrong. `minRamGb` is what the computer must report for it to run without swapping.
const reasoning = (id, label, diskMb, minRamGb) => Object.freeze({ id, label, diskMb, ramMb: Math.round(diskMb * 1.25), minRamGb });
const REASONING = Object.freeze([
  reasoning('deepseek-r1:14b', 'Modelo de raciocínio', 9000, 15),
  reasoning('deepseek-r1:8b', 'Modelo de raciocínio compacto', 5200, 11),
]);

// Measured on macOS arm64 with `uv sync --frozen --no-dev --no-editable` (MB installed; the downloads are smaller):
// base 124 + uv's managed Python 65; each extra on top of the base (the two together share packages).
// Laya (not measured: an estimate, it brings PyTorch and transformers; its own weights are fetched on first use).
const ENGINE = Object.freeze({ baseMb: 189, extraMb: Object.freeze({ voice: 198, listen: 183, both: 228, laya: 1500 }) });

function extrasSizeMb(extras) {
  const speech = extras.filter((e) => e === 'voice' || e === 'listen');
  const speechMb = !speech.length ? 0 : speech.length === 2 ? ENGINE.extraMb.both : ENGINE.extraMb[speech[0]];
  return speechMb + (extras.includes('laya') ? ENGINE.extraMb.laya : 0);
}

const ALL = ['darwin', 'win32', 'linux'];
const OPTIONS = Object.freeze([
  {
    id: 'voice', label: 'Voz melhorada', platforms: ALL, extra: 'voice', diskMb: 63, ramMb: 300,
    description: 'Voz neural em português do Brasil, falada no próprio computador.',
    settings: { enhancedVoice: true }, offSettings: { enhancedVoice: false },
    approval: { source: 'huggingface.co/rhasspy/piper-voices (voz Piper "jeff", conferida por SHA-256)', sizeMb: 63 },
  },
  {
    id: 'talk', label: 'Falar com o Chakmati (microfone)', platforms: ALL, extra: 'listen', diskMb: 140, ramMb: 500,
    description: 'O microfone fica ouvindo as frases de chamada e os comandos. Reconhecimento de voz local.',
    settings: { talk: true, hear: true }, offSettings: { talk: false },
    approval: { source: 'Hugging Face (modelo Whisper "base", baixado no primeiro uso)', sizeMb: 140 },
  },
  {
    id: 'reasoning', label: 'Modelo de raciocínio (corrigir provas e explicar os erros)', platforms: ALL, diskMb: 0, ramMb: 0, dynamic: true,
    description: 'Um segundo modelo, que pensa antes de responder, para resolver as questões de uma prova e explicar o erro de cada aluno. Só é usado nesses pedidos e só aparece em computadores com memória para ele.',
    settings: {}, offSettings: {},
    approval: { source: 'ollama.com (pelo Ollama instalado neste computador)', sizeMb: 0 },
  },
  {
    id: 'whatsapp', label: 'WhatsApp', platforms: ['darwin', 'linux'], needsRepo: true, diskMb: 1200, ramMb: 800,
    description: 'Ler e responder mensagens, sempre com a sua aprovação para enviar.',
    settings: {}, offSettings: {},
    after: 'WhatsApp: depois da instalação, conecte em Ajustes > Integrações (isso instala o OpenWA e mostra o QR code).',
  },
  {
    id: 'home', label: 'Casa inteligente e Alexa (Home Assistant)', platforms: ALL, diskMb: 0, ramMb: 0,
    description: 'Controlar luzes, tomadas e a música da Alexa pelo Home Assistant da sua casa. Só faz sentido se você já usa o Home Assistant.',
    settings: { home: true }, offSettings: { home: false },
    after: 'Casa inteligente: depois da instalação, abra Ajustes > Integrações e toque em "Conectar ao Home Assistant". O Chakmati procura o seu na rede e você só precisa aprovar o acesso, sem copiar nenhum código.',
  },
  {
    id: 'laya', label: 'Laya (filtro de relevância da pesquisa)', platforms: ALL, extra: 'laya', diskMb: 1500, ramMb: 800,
    advice: 'Não recomendado. Possui baixa eficácia neste projeto até o momento.',
    description: 'Um modelo extra que descarta trechos pouco relevantes das páginas da pesquisa antes de responder.',
    settings: { laya: true }, offSettings: { laya: false },
    approval: { source: 'pypi.org e huggingface.co (PyTorch e o modelo Laya, pelo uv que vem no instalador)', sizeMb: 1500 },
  },
  {
    id: 'animations', label: 'Animações do personagem', platforms: ALL, diskMb: 0, ramMb: 0,
    description: 'O Chakmati pisca, olha e se mexe. Desligado, ele fica parado.',
    settings: { still: false }, offSettings: { still: true },
  },
  {
    id: 'hideShare', label: 'Ocultar a janela no compartilhamento de tela', platforms: ALL, diskMb: 0, ramMb: 0,
    description: 'Pede ao sistema que as janelas do Chakmati não apareçam em compartilhamentos e gravações.',
    settings: { protect: true }, offSettings: { protect: false },
  },
]);

const optionsFor = (platform, { packaged = false } = {}) => OPTIONS.filter((o) => o.platforms.includes(platform) && !(packaged && o.needsRepo));

module.exports = { CORE, ENGINE, MODELS, REASONING, OPTIONS, extrasSizeMb, optionsFor };
