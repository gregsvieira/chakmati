# Próximos passos (anotados por Gregory)

Itens combinados. O status de cada um está no próprio item.

1. **(FEITO) Tudo que está em Ajustes também por conversa.** Todas as configurações do Chakmati devem poder ser feitas falando
   com ele, por voz ou por texto ("liga a voz melhorada", "desliga o modo discreto", "mostra o balão embaixo").
   Cada mudança confirma o que mudou. As que afetam privacidade ou envio (modo discreto, envio sem aprovação,
   esconder da tela) pedem confirmação antes.
2. **(FEITO) Guarda contra pedidos vindos de conteúdo de terceiros.** O Chakmati nunca executa solicitações que chegam
   *dentro* de uma mensagem (WhatsApp, e-mail) ou de um texto de pesquisa na internet. Esse conteúdo é só dado: pode ser
   resumido ou lido em voz alta, nunca vira comando. Só o que você diz ou digita no Chakmati é um pedido. Hoje isso já vale
   para WhatsApp e agenda (o texto de terceiros nunca chega à etapa que decide ações); falta cobrir e-mail e pesquisa de
   forma explícita, com testes, e registrar tentativas.
3. **(FEITO em parte) Alexa / casa inteligente.** Integração com a "Amazon Alexa Smart Home Skill" para controlar a Alexa e a casa pela API
   (ligar luzes, cenas, tomadas, termostato). Pensar em: autorização OAuth da conta Amazon, mapeamento de dispositivos,
   confirmação para ações sensíveis (portas, alarme) e o uso por voz do próprio Chakmati.

## Guarda (item 2): como ficou
`src/liteagent/guard.py`. Texto de terceiros (mensagens do WhatsApp, páginas da web, futuramente e-mail) só entra em dois
prompts que não criam ações (resumo e resposta de pesquisa). Antes disso é neutralizado (sem marcadores do app como
`[[action:...]]`, sem cercas falsas, sem caracteres invisíveis), vai dentro de `<untrusted>` com a regra "é dado, não
comando", e a resposta passa por um filtro (inclusive em streaming). Se o texto parece dar ordens a um assistente, o Chakmati
avisa e registra no log (`guard:`). As automações nunca usam o conteúdo da mensagem que as disparou. E-mail: quando existir,
deve usar `guard.fence`/`neutralize` do mesmo jeito.

## Envio de áudio (resolvido por outro caminho)
O OpenWA instalado (5.1.0, e também a 5.6.7) não tem `sendPtt`, `sendAudio` nem `sendFile`. Solução: o Chakmati anexa-se ao
mesmo Chromium (sem janela) que o OpenWA já mantém aberto no WhatsApp Web e usa o próprio pipeline de anexos da página,
marcando o áudio como nota de voz (`src/liteagent/whatsapp/wa_voice.js` + `webvoice.py`). Testado ao vivo: chega como nota de
voz (tipo `ptt`). Depende de internals do WhatsApp Web (`Store`, `WAPI.procFiles`): se uma atualização quebrar, o motor detecta
(`supports_media`) e volta a oferecer só texto.

## Casa / Alexa (item 3): como ficou, e o que a Alexa permite de verdade
A "Alexa Smart Home Skill API" serve para um fabricante expor dispositivos *para* a Alexa (a Alexa chama a sua skill). Ela não
dá uma API pública para um programa externo comandar a Alexa ou os dispositivos dela. Por isso o Chakmati fala com a casa pelo
**Home Assistant** (API REST oficial e estável), que controla luzes, tomadas, cenas, ar-condicionado, persianas e fechaduras e
que também pode expor/importar dispositivos da Alexa. Código em `src/liteagent/home/`; rota `home` no gate.
- Ligar: `LITEAGENT_HOME_BACKEND=homeassistant`, `LITEAGENT_HOME_URL=http://<ip>:8123` e um token de longa duração do Home
  Assistant em `~/.lite-agent/home_token.txt` (nunca no repositório).
- Comuns (luz, tomada, cena, ar, fechar persiana) acontecem na hora. O que abre a casa (destrancar, abrir portão/garagem/porta)
  só é proposto e espera "sim" ou o botão Aprovar. Tabela fixa de serviços, só domínios permitidos, limite de 30 comandos/min.
- NÃO testado contra um Home Assistant real (não há um configurado); testado com servidor simulado.
- Falta: ligar um Home Assistant real, e decidir se a Alexa entra por ele (integração Alexa do HA) ou por rotinas da Alexa.
