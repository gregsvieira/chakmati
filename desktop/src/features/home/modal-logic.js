'use strict';
// What the smart-house modal says and which page it shows, decided from what the engine reports. Pure, so it is tested without a window.
(function (root) {
  const GB = (mb) => `${Math.round(mb / 100) / 10} GB`.replace('.', ',');

  // The list the person reads before pressing "Começar": exactly what will happen on THIS computer.
  function introSteps(info) {
    const steps = [];
    if (info.docker === 'no_docker') {
      steps.push(info.docker_installable
        ? `Instalar o Docker Desktop (cerca de ${info.docker_mb} MB). O computador vai pedir a sua senha de administrador${info.platform === 'win32' ? ' e pode pedir para reiniciar' : ''}.`
        : 'O Docker precisa ser instalado por você: neste sistema ele vem do gerenciador de pacotes (docs.docker.com/engine/install).');
    } else if (info.docker === 'daemon_off') {
      steps.push(info.can_open_docker ? 'Ligar o Docker (o Chakmati abre o programa para você).' : 'O Docker está desligado: ligue o serviço do Docker.');
    } else {
      steps.push('Usar o Docker, que já está ligado.');
    }
    steps.push(info.container === 'none' || info.container === 'unknown'
      ? `Baixar e instalar o Home Assistant (cerca de ${GB(info.image_mb || 1000)} de download).`
      : 'Ligar o Home Assistant que já foi instalado.');
    steps.push(info.alexa_ready ? 'Usar a integração da Alexa (alexa_media_player), que já está no Home Assistant.' : 'Baixar a integração da Alexa (alexa_media_player) para dentro do Home Assistant.');
    steps.push('Ligar tudo e conferir que está funcionando.');
    return steps;
  }

  // Can the person press "Começar"? Not when Docker is missing and this system cannot install it for them.
  function canStart(info) {
    return !!info && !info.error && !(info.docker === 'no_docker' && !info.docker_installable);
  }

  // From the engine's report of the install: which page, and the sentence to show.
  function stageFor(info) {
    if (!info || info.error) return { stage: 'error', text: (info && info.error) || 'Não consegui falar com o motor do Chakmati.' };
    if (info.state === 'running') return { stage: 'progress', text: info.message || 'Preparando…' };
    if (info.state === 'ready' && info.code === 'needs_account') return { stage: 'account', text: info.message };
    if (info.state === 'ready' && info.code === 'has_owner') return { stage: 'found', text: info.message };
    if (info.state === 'done') return { stage: 'done', text: info.message };
    if (info.state === 'error') return { stage: 'error', text: info.message, code: info.code };
    return { stage: 'intro', text: '' };
  }

  // While waiting for the approval in the browser: keep waiting, done, or give up with a sentence.
  function approval(status, elapsedMs) {
    if (status && status.connected && !status.pending) return { stage: 'done' };
    if (status && !status.pending && elapsedMs > 6000) return { stage: 'error', text: 'A conexão não foi concluída. Se foi sem querer, tente de novo.' };
    if (elapsedMs > 3 * 60 * 1000) return { stage: 'error', text: 'Não vi a aprovação a tempo. Tente de novo.' };
    return { stage: 'approving' };
  }

  // The last page: what was found, and what is still missing for the Alexa.
  function doneText(status) {
    const players = (status && status.players) || [];
    if (players.length) return `Achei: ${players.slice(0, 3).map((p) => p.name).join(', ')}${players.length > 3 ? ' e mais' : ''}. Já dá para dizer "próxima música".`;
    return 'Falta só uma coisa para a Alexa aparecer: entrar na sua conta da Amazon dentro do Home Assistant. Toque em "Abrir o Home Assistant", vá em Configurações > Dispositivos e serviços > Adicionar integração, procure "Alexa Media Player" e entre com a sua conta da Amazon.';
  }

  const api = { introSteps, canStart, stageFor, approval, doneText };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.HomeModal = api;
})(typeof window !== 'undefined' ? window : globalThis);
