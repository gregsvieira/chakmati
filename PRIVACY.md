# Privacidade / Privacy

**Português.** O Chakmati é local por padrão: as conversas, os arquivos anexados, as automações e as chaves ficam no seu computador (pasta de dados `~/.chakmati-agent` e a pasta de dados do app). Ele **não tem telemetria, análise de uso nem conta**, e o autor não recebe nada.

**O que pode sair do seu computador, e só quando você usa:**

| O quê | Para onde | Quando |
|---|---|---|
| O texto da conversa | o provedor da **IA paga** que você escolheu, possivelmente no exterior | só se você ligar a IA paga e informar a sua chave de API. A chave fica cifrada no seu computador |
| A pergunta de pesquisa e as páginas lidas | o buscador (DuckDuckGo ou o SearXNG que você mantém) e os sites visitados | quando você pede uma pesquisa ou usa o navegador |
| As mensagens do WhatsApp | o WhatsApp/Meta, como já acontece no seu aparelho; o OpenWA roda no seu computador | só se você ligar a integração (leia o `DISCLAIMER.md`) |
| Downloads de modelos, voz e pacotes | Hugging Face, Ollama, PyPI, GitHub e o site do Docker | só depois da sua aprovação, mostrando origem e tamanho |
| Login da Alexa | Amazon, pela integração do Home Assistant que roda no seu computador | só se você conectar a Alexa |

Dados de outras pessoas (mensagens, provas de alunos) que você pedir ao Chakmati para processar são **sob a sua responsabilidade** como controlador, nos termos da LGPD. Com o modelo local, eles não saem do computador.

**English.** Chakmati is local by default: conversations, attached files, automations and keys stay on your computer. It has **no telemetry, usage analytics or accounts**, and the author receives nothing. Data leaves your computer only when you use a feature that needs it: the paid AI you chose (text goes to its provider, possibly abroad), web search and the pages visited, WhatsApp (if you turn it on), downloads you approved, and the Alexa sign-in. Other people's data you ask it to process is your responsibility as controller under the LGPD; with the local model it does not leave the computer.
