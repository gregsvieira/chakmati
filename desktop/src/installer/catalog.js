'use strict';
// What the installer can put on a computer. Plain data: the numbers are the sizes of the downloads; RAM figures are
// estimates (the file size plus working memory), not measurements, and the wizard says "cerca de".
const CORE = Object.freeze({ diskMb: 1500, ramMb: 400 }); // the app and the engine, without any optional piece

const model = (id, label, diskMb) => Object.freeze({ id, label, diskMb, ramMb: diskMb + 500 });
const MODELS = Object.freeze([
  model('qwen3.5:0.8b', 'Modelo leve', 1200),
  model('qwen3.5:4b', 'Modelo intermediário', 4000),
  model('qwen3.5:latest', 'Modelo completo', 6600),
]);

// Measured on macOS arm64 with `uv sync --frozen --no-dev --no-editable` (MB installed; the downloads are smaller):
// base 124 + uv's managed Python 65; each extra on top of the base (the two together share packages).
const ENGINE = Object.freeze({ baseMb: 189, extraMb: Object.freeze({ voice: 198, listen: 183, both: 228 }) });

function extrasSizeMb(extras) {
  if (!extras.length) return 0;
  if (extras.includes('voice') && extras.includes('listen')) return ENGINE.extraMb.both;
  return ENGINE.extraMb[extras[0]];
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
    id: 'whatsapp', label: 'WhatsApp', platforms: ['darwin', 'linux'], needsRepo: true, diskMb: 1200, ramMb: 800,
    description: 'Ler e responder mensagens, sempre com a sua aprovação para enviar.',
    settings: {}, offSettings: {},
    after: 'WhatsApp: depois da instalação, conecte em Ajustes > Integrações (isso instala o OpenWA e mostra o QR code).',
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

module.exports = { CORE, ENGINE, MODELS, OPTIONS, extrasSizeMb, optionsFor };
