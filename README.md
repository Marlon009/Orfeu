# Lia: agente de atendimento da Empório da Música

Protótipo de um agente de mensagens de texto para a Empório da Música, uma loja fictícia de instrumentos em Campo Grande/MS. A Lia responde sobre o catálogo (preço, promoção, estoque), sobre pedidos (status, rastreio, prazos de troca) e sobre as políticas da loja. Ela sempre consulta os dados por ferramentas e nunca responde de memória.

```
Você: Quanto custa o Takamine GD20?
  🔧 buscar_produtos(termo='Takamine GD20')
Lia: O Takamine GD20 custa R$ 2.199,00. Com o pagamento à vista no PIX, você ganha um desconto de 5%, totalizando R$ 2.089,05. ...
```

## Como rodar

Requisitos: Python 3.10+ e [Ollama](https://ollama.com).

```bash
# 1. Modelo local (o padrão do projeto; ver "Modelo" abaixo para trocar)
ollama pull huihui_ai/qwen2.5-abliterate

# 2. Dependências
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Banco (opcional: é criado sozinho na primeira execução)
python -m emporio.db

# 4. Conversar
python -m emporio.cli                                  # cliente anônimo
python -m emporio.cli --telefone "(67) 99654-7821"     # simula mensagem vinda do WhatsApp de uma cliente cadastrada
python -m emporio.cli --debug                          # mostra as ferramentas chamadas e o tempo de cada resposta
python -m emporio.cli --modo restrito                  # modo para modelos pequenos (ver "Dois modos de execução")

# Outros comandos
python -m emporio.alerts      # relatório para o dono da loja
python -m pytest              # testes das regras e ferramentas (não precisam do LLM)
LLM_MODEL=qwen2.5:1.5b python -m emporio.evaluate   # bateria fechada do intérprete
./examples/gerar.sh           # regera as conversas de exemplo
```

Configuração por variáveis de ambiente (todas opcionais):

| Variável | Padrão | Para quê |
|---|---|---|
| `LLM_BASE_URL` | `http://localhost:11434/v1` | qualquer API compatível com a da OpenAI |
| `LLM_API_KEY` | `ollama` | chave do provedor |
| `LLM_MODEL` | `huihui_ai/qwen2.5-abliterate:latest` | modelo |
| `LLM_TEMPERATURE` | `0` | 0 para respostas estáveis e reprodutíveis |
| `EMPORIO_MODE` | `livre` | `livre` (function calling) ou `restrito` (formulário JSON validado); ver "Dois modos de execução" |
| `EMPORIO_TODAY` | `2026-03-25` | data de referência para os prazos (ver Suposições) |
| `LOW_STOCK_THRESHOLD` | `2` | limite do alerta de estoque baixo |

Para usar um modelo pago, por exemplo: `LLM_BASE_URL=https://api.openai.com/v1 LLM_API_KEY=sk-... LLM_MODEL=gpt-4o-mini python -m emporio.cli`.

> **Desempenho:** em CPU (4 núcleos, sem GPU), cada resposta leva de 1 a 6 minutos. Com GPU ou com um modelo via API, leva poucos segundos. Se o Ollama cortar o contexto, suba o limite com `OLLAMA_CONTEXT_LENGTH=8192 ollama serve`.

## Arquitetura

```
                       ┌───────────── modo livre ─────────────┐
mensagem ─► Agent ─────┤ LLM escolhe as ferramentas em loop   ├─► resposta ─► validador ─► cliente
                       │ (function calling, até 5 passos)     │                 │
                       ├──────────── modo restrito ───────────┤                 │ R$/data/hora fora
                       │ LLM preenche JSON forçado pelo schema│                 │ dos dados: gera de
                       │ → código confere os campos           │                 │ novo; se repetir,
                       │ → código chama as ferramentas        │                 ▼ resposta segura
                       │ → LLM só redige                      │
                       └──────────────────┬───────────────────┘
                                          ▼
                              Toolbox (registro único)
                               ├─ buscar_produtos      ─► SQLite (catálogo, promoções, estoque)
                               ├─ consultar_pedido     ─► SQLite (pedidos, com verificação de identidade)
                               ├─ consultar_politica   ─► data/policies/<tópico>.md
                               ├─ registrar_interesse  ─► customer_interests
                               └─ registrar_reclamacao ─► complaints
```

```
emporio/
  config.py    configuração por variáveis de ambiente
  db.py        CSV → SQLite, com limpeza e flags de qualidade
  rules.py     regras do manual em código: PIX, parcelamento, prazos, disponibilidade
  tools.py     ferramentas do agente e seus schemas (registro único dos dois modos)
  interpreter.py  modo restrito: schema gerado das ferramentas e conferência dos campos
  validator.py confere R$, datas e horários da resposta contra os dados consultados
  prompts.py   persona, regras, prompt de redação e lembretes contextuais
  agent.py     os dois modos, histórico e métricas por resposta
  cli.py       interface de terminal e modo roteiro
  alerts.py    relatório para o dono
data/raw/      dados originais, sem alteração
data/policies/ manual dividido por tópico
examples/      conversas reais geradas pelo agente
tests/         testes das regras e ferramentas
```

## Decisões técnicas

### Abordagem: function calling, com as regras de negócio em Python
O manual exige "nunca fornecer informações sobre preços, estoque ou prazos sem consultar o sistema". Por isso o agente acessa os dados só por ferramentas, e as ferramentas devolvem a resposta já calculada:
- preço final com promoção ativa;
- preço no PIX, que não acumula com promoção;
- parcelamento máximo respeitando a parcela mínima;
- situação do estoque;
- alternativas quando o produto está esgotado;
- prazos de devolução e garantia.

O LLM decide qual ferramenta usar e reescreve o resultado no tom da loja, mas não faz contas. Isso é ainda mais importante com um modelo local de 7B, que erra aritmética e tende a inventar preços. E deixa as regras testáveis: `tests/` cobre tudo sem precisar do LLM.

### Dados: SQLite e consulta na hora, sem RAG vetorial
Dados estruturados (preço, estoque, status) ficam no SQLite e são consultados no momento da pergunta. Se um produto entra, sai do estoque ou é descontinuado, a próxima resposta já reflete a mudança, sem reindexar nada. Num banco de vetores, o agente ficaria respondendo com um retrato antigo do catálogo.

A busca de produtos é por palavras-chave. Ela ignora acentos e plural ("violões" acha "violão"), dá mais peso ao nome e à categoria do que à descrição, e aceita filtro de categoria e de preço máximo.

### Políticas: um arquivo por tópico, sem embeddings
O manual tem 8 páginas e tópicos bem delimitados. Ele virou 7 arquivos Markdown em `data/policies/`. Endereço, contato e horário ficaram juntos porque quase sempre são perguntados juntos, e o modelo escolhe o tópico por um `enum` no schema da ferramenta. Com tão pouco conteúdo, escolher entre tópicos fixos é mais previsível que busca semântica, principalmente com um modelo pequeno. Para incluir um tópico novo, basta criar um `.md`, que a lista de tópicos é gerada a partir dos arquivos.

Com um manual grande, o próximo passo seria separar por seção e buscar com embeddings (o `nomic-embed-text` já roda no Ollama).

### Sem framework (LangChain, LlamaIndex)
O agente (`agent.py`, com os dois modos) e o intérprete somam cerca de 300 linhas sobre o cliente `openai`. Assim não há dependência pesada e cada passo fica visível: os prompts, as chamadas de ferramenta e o tratamento de erros. Como o Ollama expõe uma API compatível com a da OpenAI, trocar de provedor muda só variáveis de ambiente.

### Dois modos de execução

O mesmo registro de ferramentas (`tool_specs`) atende os dois modos. A escolha é por `EMPORIO_MODE`:

- **`livre`:** function calling em loop. O modelo decide quais ferramentas chamar, quantas vezes e em que ordem. Lida bem com pedidos em vários passos ("o violão mais barato dá pra parcelar em 10x?"), mas depende de o modelo seguir as regras.
- **`restrito`:** o modelo só **preenche um formulário JSON**. O servidor força a saída ao schema (`response_format` com `json_schema`), então JSON malformado ou categoria fora do `enum` são impossíveis. O código então:
  1. confere cada campo contra o texto do cliente: número de pedido, contato ou valor que o cliente não escreveu são descartados;
  2. chama as ferramentas, uma por intenção;
  3. responde sozinho a acessório e assunto fora do escopo, com texto fixo e sem chamar o modelo;
  4. registra o interesse do cliente automaticamente;
  5. pede ao modelo apenas a redação da resposta.

**Validador nos dois modos** (`validator.py`): todo `R$`, data e horário da resposta precisa aparecer no retorno das ferramentas, na mensagem do cliente ou no histórico já validado. Se não aparecer, o modelo gera de novo, com o aviso do que inventou; se repetir, sai uma resposta segura que encaminha para a equipe. Ele não pega frases erradas sem número ("o pedido chegou"), só valores.

**Por que isso não trava o crescimento:**
- *Os dados crescem sem código:* o `enum` de categorias vem do banco e os tópicos de política vêm dos arquivos. Categoria nova entra no schema na próxima mensagem.
- *As capacidades crescem pelo registro:* uma ferramenta nova (agendar aula, cotar frete) é uma função mais a descrição dela. O schema do modo restrito é gerado do registro, então ela vale nos dois modos sem mexer no intérprete.
- *O modo acompanha o modelo disponível:* modelo pequeno e local usa `restrito`. Com GPU ou modelo via API, troca-se para `livre` e ganha-se raciocínio em vários passos, sem reescrever ferramentas. O limite real do `restrito` é justamente esse: ele decide tudo antes de ver os resultados.

O padrão do intérprete foi adaptado de um projeto meu anterior (ver "Uso de assistentes de código").

### Modelo
`huihui_ai/qwen2.5-abliterate`: um Qwen2.5 7B (Q4_K_M) local, com suporte a ferramentas no Ollama.
- **Por que local:** custo zero e dados de clientes fora de APIs externas.
- **Por que Qwen2.5 7B:** entre os modelos locais desse porte, é dos mais consistentes em function calling e em português.
- **Por que esta variante:** era a única versão de 7B disponível na máquina de desenvolvimento, sem espaço em disco para baixar outra.

É uma variante "abliterada", ou seja, com o comportamento de recusa removido. Por isso, as restrições de escopo vêm todas do system prompt e das ferramentas, que por construção só leem dados da loja. Em produção, eu usaria o `qwen2.5:7b` original, que é a mesma arquitetura e só pede trocar o `LLM_MODEL`, ou um modelo via API.

### Estratégia de prompt
O system prompt (`emporio/prompts.py`) tem três partes:
- a persona, tirada da seção 7.1 do manual: informal mas profissional, "um amigo que entende de música";
- um guia de quando usar cada ferramenta;
- 10 regras numeradas: não inventar dados, copiar valores sem calcular, mostrar promoção com preço original e percentual, verificar identidade, escopo só de instrumentos, recusar assuntos fora da loja.

Além disso, as ferramentas reforçam o prompt com instruções no próprio retorno. Por exemplo:
- "PREVISÃO VENCIDA: peça desculpas e registre uma reclamação";
- "Não dê nenhum detalhe do pedido";
- "ficha técnica em revisão".

Isso funciona melhor que um prompt longo, porque a instrução chega exatamente na hora em que é relevante.

Pelo mesmo motivo, o agente injeta **lembretes por palavra-chave** (`prompts.reminders`) antes da mensagem do cliente:
- acessório citado: lembra que a loja não vende acessórios;
- assunto fora da loja: lembra de recusar;
- cliente identificado falando de pedido: manda chamar `consultar_pedido` sem argumentos.

A checagem é por palavra inteira, para "acabou" não disparar "cabo".

### Identidade e privacidade (LGPD)
- **Cliente que chega pelo WhatsApp:** o telefone identifica a pessoa, simulado com `--telefone`. A Lia cumprimenta pelo nome e pode consultar os pedidos dela.
- **Cliente anônimo:** precisa informar o número do pedido e o e-mail ou telefone do cadastro.
- **Pedido inexistente e identidade errada recebem a mesma resposta**, para não confirmar que um pedido existe.

### Histórico
As conversas ficam na tabela `messages`, identificadas pelo telefone. Um cliente que volta tem o contexto das últimas 6 trocas. Só as mensagens finais são salvas, não os resultados das ferramentas, para não reaproveitar preço ou estoque antigo.

### Extras para a equipe
- **`registrar_interesse`:** o agente registra em silêncio o que o cliente procura, como "violão nylon para iniciante". É a base para entender a preferência de cada cliente e alimentar um dashboard.
- **`registrar_reclamacao`:** registra a reclamação, gera um protocolo e segue a seção 7.3 do manual (retorno em 24 horas úteis).
- **`python -m emporio.alerts`:** relatório para o dono com estoque baixo, produtos sem estoque, incoerências nos dados, entregas atrasadas, pedidos parados, reclamações abertas e interesses por categoria.

## Iterações com o modelo local

Os exemplos foram gerados três vezes, e o histórico do git guarda cada rodada. Cada falha virou uma correção **no código, não no prompt**, sempre que possível:

| Falha observada (7B abliterado) | Correção |
|---|---|
| Inventou o nome "Ronaldo" para um cliente anônimo | Contexto explícito: "você NÃO sabe o nome dele" |
| Inventou o horário de sábado (10h às 20h) ao responder "endereço e horário" | Endereço e horário no mesmo tópico, mais a regra "consulte os dois assuntos" |
| Respondeu com uma receita de bolo | Exemplos de recusa no prompt e lembrete contextual |
| Disse que "vende cordas, mas..." | Lembrete contextual de acessório |
| Buscou o violão na categoria Guitarras e inventou uma resposta | A busca refaz sem a categoria e avisa o modelo da categoria certa |
| Cliente identificada, mas o modelo pediu o número do pedido | Lembrete e descrição da ferramenta ("chame SEM argumentos") |
| Escreveu a chamada da ferramenta como JSON no texto | O agente interpreta esse JSON e executa a chamada (falha conhecida do Qwen) |
| Leu "garantia dentro do prazo" e prometeu uma troca | A ferramenta entrega a `CONCLUSÃO:` pronta (o que ainda vale) |
| Disse "vou registrar a reclamação" e não registrou | Entrega atrasada abre a reclamação no código, sem duplicar |
| Confundiu a data da compra com a data de entrega | Rótulo "Data da compra" |

A causa mais provável da falha de escopo é a própria variante abliterada, que tem a direção de recusa removida. Por isso, para produção, o README recomenda o `qwen2.5:7b` original.

## Bateria fechada do intérprete

`python -m emporio.evaluate` roda uma bateria de 38 casos ([evals/interpretador.jsonl](evals/interpretador.jsonl)) com nota automática, sem julgamento humano. Mede só o intérprete do modo restrito (intenções e campos do JSON), que é a parte barata o bastante para rodar no CPU (cerca de 5 s por caso com o 1.5B).

**Regras da nota:**
- todas as intenções esperadas precisam aparecer;
- pergunta da loja que vira recusa reprova, e recusa que chama ferramenta também reprova. Assim, nem "recusar tudo" nem "nunca recusar" tiram nota boa, e por isso há um grupo de casos que **não** devem ser recusados ("violão de 7 cordas", "bateria eletrônica");
- os campos esperados precisam bater, e os campos que o cliente não disse precisam estar ausentes.

**Desenvolvimento e reserva:** 27 casos de desenvolvimento, usados para corrigir o sistema, e 11 de reserva, que só rodam com `--reserva` e têm cada uso registrado em `evals/reserva_usos.jsonl`.

**Resultado com `qwen2.5:1.5b`** ([evals/resultados/](evals/resultados/)):

| Rodada | Desenvolvimento | O que mudou |
|---|---|---|
| 1 | 19/27 (70%) | — |
| 2 | 23/27 (85%) | "acessorio" só vale se o texto citar um acessório; "9 mil" vira 9000; exemplos novos |
| 3 | 26/27 (96%) | termo e categoria precisam ter base no texto; categoria inferida do texto |
| **Reserva (uso único)** | **8/11 (73%)** | — |

A distância entre 96% e 73% é o achado principal. Parte da melhora era ajuste aos casos de desenvolvimento: por exemplo, a descrição mais clara do tópico de frete resolveu o caso de Dourados, mas não o de Corumbá na reserva. Com a reserva usada, ela não vale mais para medir as próximas mudanças; a próxima rodada precisa de casos novos de reserva.

A conferência literal descartou de 4 a 6 campos inventados por rodada (números de pedido, preços e contatos que o cliente não escreveu). Sem ela, cada um seria uma falha a mais.

**Como isso escala com GPU:** a mesma bateria vira a função de recompensa para ajuste fino (SFT com as saídas que passam, DPO com pares boa/ruim, ou RL com recompensa verificável), e a reserva continua decidindo se uma versão vai para produção.

## Tratamento de dados e suposições

Os dados originais ficam intocados em `data/raw/`. Os problemas que encontrei, e como tratei cada um:

| Problema encontrado | Tratamento |
|---|---|
| Descrição de 6 produtos (IDs 135, 137, 139, 140, 142, 144) cita outra marca que não a do nome (ex.: "Music Man Bass 1X" descrito como Fender Jazz Bass) | Detecção automática por marca (`description_reliable = 0`). O agente informa preço e estoque, mas não a ficha técnica. Aparece no relatório de alertas. |
| Produto 96 `active` com estoque 0; 136 `discontinued` com 13 unidades; 130 `coming_soon` com pedidos | O status manda: só `active` com estoque > 0 é vendável. Descontinuado e "em breve" não mostram preço. Os casos aparecem nos alertas. |
| Várias promoções por produto, quase todas inativas | Só conta promoção com `is_active = 1`, como manda a seção 7.3. |
| Totais dos pedidos 3 e 20 diferentes da soma dos itens (`order_items` não tem preço unitário) | O agente mostra o total registrado, que é o que o cliente pagou. A divergência vai para os alertas. |
| Clientes 11 e 43 com o mesmo e-mail | A verificação compara o e-mail do dono daquele pedido específico, então não há ambiguidade. |
| Manual: telefone (67) 3341-4444 e WhatsApp (67) 3321-4500 | Assumi o primeiro como telefone fixo e o segundo como WhatsApp, porque a seção 7 é a específica do canal. |
| Manual: e-mail com acento na tabela (`empóriodamusica`) | Usei o da capa, sem acento, já que o acento torna o endereço inválido. |
| Manual: "até 3x sem valor mínimo (exceto abaixo de R$ 50)" | Interpretei como parcela mínima de R$ 50 de 2x a 3x. |
| Manual: frete grátis "acima de R$ 500" e taxa "abaixo de R$ 500" | Considerei exatamente R$ 500 como frete grátis, a leitura mais favorável ao cliente. |
| Manual cita sopro e cordas orquestrais, mas não há produtos nessas categorias | O agente só oferece as categorias que têm produtos ativos. |
| Pedidos não têm data real de entrega | Usei `estimated_delivery` como data de recebimento para os prazos. |
| Pedidos não dizem se a compra foi online ou presencial | O prazo de arrependimento aparece rotulado como "compras online". |
| Os dados terminam em março/2026 | A data de referência é configurável (`EMPORIO_TODAY`, padrão 25/03/2026). Com a data real, todos os prazos estariam vencidos e os pedidos pendentes teriam 7 meses. |
| Significado dos status de pedido | `pending` = aguardando pagamento; `confirmed` = pago e em separação; `shipped` = enviado; `delivered` = entregue. |

## Exemplos de conversa

Gerados pelo próprio agente a partir de `examples/roteiros/`, com `./examples/gerar.sh`. As linhas com 🔧 são as ferramentas chamadas; abaixo de cada resposta ficam o tempo e o que o validador barrou. O cabeçalho de cada arquivo registra o modelo, o modo, a temperatura e o hash do prompt.

**Configuração padrão: 7B, modo livre** (`examples/livre_7b/`). A mesma bateria no 1.5B em modo restrito fica em `examples/restrito_1.5b/`, para comparação.

| Roteiro | Cenário |
|---|---|
| [01_catalogo_violoes](examples/livre_7b/01_catalogo_violoes.md) | Violões até R$ 1.000, depois refinado para nylon/iniciante |
| [02_loja_e_fora_de_escopo](examples/livre_7b/02_loja_e_fora_de_escopo.md) | Endereço e horário, pedido de acessório (cordas) e pergunta fora do escopo |
| [03_devolucao_pedido](examples/livre_7b/03_devolucao_pedido.md) | **Não trivial:** devolução com verificação de identidade e prazos calculados |
| [04_cliente_identificado_atraso](examples/livre_7b/04_cliente_identificado_atraso.md) | **Não trivial:** cliente reconhecida pelo WhatsApp, entrega atrasada e reclamação aberta |
| [05_produto_esgotado](examples/livre_7b/05_produto_esgotado.md) | Produto esgotado com promoções vencidas, oferecendo alternativas |

### Comparação: 7B livre × 1.5B restrito

Mesmos 5 roteiros (9 mensagens), mesma máquina (CPU de 4 núcleos, sem GPU), temperatura 0. Revisão manual de cada resposta.

| | 7B, modo livre | 1.5B, modo restrito |
|---|---|---|
| Roteiros corretos | **4,5 / 5** | 2,5 / 5 |
| Chamadas de ferramenta corretas | 6 de 7 (1 categoria errada, corrigida pela busca tolerante) | **10 de 10** |
| Fora de escopo (bolo) | ❌ inventou "a receita está no site da loja" | ✅ texto fixo, em 4 s |
| Valores inventados que chegaram ao cliente | 0 | 0 (1 barrado pelo validador na 1ª rodada) |
| Tempo médio por resposta | ~235 s (sem contar o carregamento do modelo) | **~73 s** |

**O que os números dizem:**
- **O intérprete pequeno funciona.** Preencher um formulário com schema forçado é uma tarefa estreita o bastante para um modelo de 1.5B: ele acertou todas as ferramentas e todos os campos.
- **O redator pequeno não funciona.** Com dados corretos na mão, o 1.5B ainda ofereceu uma troca que a ferramenta dizia estar fora do prazo (03), escreveu um texto confuso sem o rastreio (04) e vazou um rótulo interno (01). O validador não pega esse tipo de erro, porque não há número errado.
- **O modo livre do 7B erra pouco, mas erra onde o modo restrito é forte:** escopo e argumentos das ferramentas.

Por isso o padrão é **7B livre**, e o próximo passo é a combinação das duas forças (ver "O que eu faria com mais tempo").

## Limitações conhecidas

- **Latência em CPU:** de 1 a 6 minutos por resposta na máquina de desenvolvimento. Não dá para usar com cliente real sem GPU ou API.
- **Modelo de 7B:** pode escolher a ferramenta errada, ignorar uma regra do prompt ou trocar de idioma. As regras críticas ficam no código, mas o texto final ainda é do modelo. Não há uma checagem automática que compare os números da resposta com os números que a ferramenta devolveu.
- **Redação com modelo pequeno:** no modo restrito com 1.5B, a resposta pode contradizer os dados (oferecer troca fora do prazo) sem citar número errado, então o validador não barra.
- **O validador só confere números:** preço, data e horário. Uma frase inventada sem número ("a receita está no site da loja") passa.
- **Perguntas de refinamento:** às vezes o modelo filtra a lista que já mostrou em vez de buscar de novo. No exemplo 01, ele sugeriu 2 violões de nylon quando havia 4 até R$ 1.000.
- **Busca por palavras-chave:** não entende sinônimos ("violão de aço" acha, "violão de cordas metálicas" não) nem pedidos vagos como "algo bom pra rock".
- **Sem horário em tempo real:** o agente informa o horário de funcionamento, mas não sabe se a loja está aberta agora.
- **Avaliação parcial:** a bateria automática cobre só o intérprete, com 38 casos. A redação final foi revisada à mão nos 5 roteiros.
- **Interesse sem consentimento:** `registrar_interesse` guarda interesses sem pedir permissão. Para uso real, é preciso definir a base legal (LGPD) e permitir a exclusão.

## O que eu faria com mais tempo

1. **Ampliar a bateria:** de 38 para 300 a 500 casos (gírias, erros de digitação, vários assuntos por mensagem), com reserva nova a cada ciclo de mudanças, e estender a nota ao redator (validador + consistência com a `CONCLUSÃO` das ferramentas + modelo maior como juiz do tom).
2. **Intérprete pequeno + redator maior:** o 1.5B no modo restrito para entender a mensagem (rápido e acertou 10/10), e o 7B ou um modelo via API só para redigir. Para os casos críticos (prazos de troca, status de pedido), resposta por template preenchido pelo código, sem redação livre.
3. **Integração com o WhatsApp Business API:** um webhook FastAPI chamando o mesmo `Agent.reply()`.
4. **Dashboard para o dono:** Streamlit sobre `customer_interests`, `complaints` e o relatório de alertas, mostrando a inclinação de cada cliente por categoria.
5. **Campanhas com opt-in:**
   - coluna de consentimento por cliente;
   - mensagens de datas especiais (Black Friday, Semana do Músico, Natal) para quem autorizou, usando os interesses registrados;
   - lembretes ligados à garantia e à manutenção do instrumento.
6. **Recomendação:** sugerir produtos a partir do histórico de compras e dos interesses.
7. **Busca híbrida no catálogo:** palavras-chave e embeddings, para pedidos vagos.
8. **Voz e avatar:** transcrição de áudio do WhatsApp e resposta em voz.

## Uso de assistentes de código

Usei o **Claude Code** (modelo Claude Opus) no terminal ao longo de todo o projeto, como par de programação:

1. **Leitura e análise:** pedi para ele ler o enunciado, o manual e os CSVs e listar as inconsistências. Ele escreveu um script que comparou os totais dos pedidos com os itens e encontrou as divergências da tabela acima.
2. **Discussão de arquitetura:** propus uma versão mais ampla, com RAG no catálogo, memória de preferências, campanhas, alertas, voz e avatar. Discutimos o que cabia no prazo. O assistente defendeu SQL em vez de RAG para dados que mudam, e reduzimos o escopo para o núcleo mais os extras baratos (interesses, reclamações, alertas). O resto foi para o roadmap acima.
3. **Implementação incremental:** cada etapa foi testada antes do commit. Primeiro dados, depois ferramentas com testes, depois o agente e por fim os alertas. O histórico do git mostra essa ordem.
4. **Validação:** as ferramentas foram testadas sem LLM antes de conectar o modelo, e as conversas de exemplo são saídas reais do agente.
5. **Iteração guiada pelas falhas:** a cada rodada de exemplos, eu e o assistente revisávamos as respostas, ele propunha a correção (de preferência no código, não no prompt) e eu decidia. As rodadas com falha estão commitadas, então o histórico mostra o antes e o depois (ver "Iterações com o modelo local").
6. **Reaproveitamento de um projeto meu:** pedi para ele ler um projeto anterior meu (um assistente local com Ollama). De lá veio o padrão do modo restrito: o LLM só preenche um JSON com schema forçado, e o código confere cada campo contra o texto do usuário antes de usar. O assistente também apontou o que **não** se aplicava (a camada de decisão probabilística daquele projeto), e isso ficou de fora.
7. **Decisão por medição:** a escolha entre 7B livre e 1.5B restrito saiu da mesma bateria de roteiros rodada nas duas configurações, não de opinião.

<!-- TODO(Marlon): complemente com sua parte do workflow: o que você revisou, mudou ou decidiu diferente do assistente. -->
