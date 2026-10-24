# Próximos passos (anotados por Gregory)

Itens combinados para criar depois. Não estão implementados.

1. **Tudo que está em Ajustes também por conversa.** Todas as configurações do Chakmati devem poder ser feitas falando
   com ele, por voz ou por texto ("liga a voz melhorada", "desliga o modo discreto", "mostra o balão embaixo").
   Cada mudança confirma o que mudou. As que afetam privacidade ou envio (modo discreto, envio sem aprovação,
   esconder da tela) pedem confirmação antes.
2. **Guarda contra pedidos vindos de conteúdo de terceiros.** O Chakmati nunca executa solicitações que chegam
   *dentro* de uma mensagem (WhatsApp, e-mail) ou de um texto de pesquisa na internet. Esse conteúdo é só dado: pode ser
   resumido ou lido em voz alta, nunca vira comando. Só o que você diz ou digita no Chakmati é um pedido. Hoje isso já vale
   para WhatsApp e agenda (o texto de terceiros nunca chega à etapa que decide ações); falta cobrir e-mail e pesquisa de
   forma explícita, com testes, e registrar tentativas.
3. **Alexa / casa inteligente.** Integração com a "Amazon Alexa Smart Home Skill" para controlar a Alexa e a casa pela API
   (ligar luzes, cenas, tomadas, termostato). Pensar em: autorização OAuth da conta Amazon, mapeamento de dispositivos,
   confirmação para ações sensíveis (portas, alarme) e o uso por voz do próprio Chakmati.
