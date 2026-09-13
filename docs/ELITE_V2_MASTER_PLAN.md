# YouTube Creator Agent Elite V2 — Master Plan

## 1. Objetivo do produto

Transformar o YouTube Creator Agent Elite em uma central profissional de operação, análise, estratégia e automação de canais do YouTube, mantendo integralmente as capacidades já estáveis do produto e evoluindo a experiência por substituição controlada, nunca por remoção cega.

O produto deve permitir que o criador opere o canal com o mínimo possível de dependência do YouTube Studio, dentro dos limites reais das APIs oficiais do YouTube, oferecendo três modos por ação: manual, assistido por IA e automação supervisionada com aprovação.

## 2. Princípios inegociáveis

1. **Preservar o que já funciona.** Nenhuma rota, leitura, cache, OAuth, Local AI, integração MCP, serviço de Analytics/Reporting ou fluxo validado será removido sem teste de paridade e substituto comprovado.
2. **Local-first no desktop.** Dashboard local, OAuth local, cache factual local, motor Python local e IA Local permanecem independentes de sessão cloud/VPS.
3. **Sem polling agressivo da IA Local.** O estado inicial continua passivo. Reavaliação ocorre por ação explícita ou durante operações de instalação/execução que realmente precisem dela.
4. **Dados oficiais antes de estimativas.** Data API, Analytics API e Reporting API alimentam métricas com origem, timestamp e disponibilidade explícitos. Métricas indisponíveis não serão inventadas.
5. **Reporting API sob demanda.** Nada de criar job ou consultar Reporting no boot. Criação de job é operação administrativa separada e requer autorização específica.
6. **Escritas protegidas.** Toda ação mutável passa por preview, diff, confirmação, apply, readback e rollback quando tecnicamente possível.
7. **Exclusões são destrutivas.** Vídeos, playlists e outros recursos não serão excluídos por automação silenciosa. Exigem confirmação reforçada e registro de auditoria.
8. **Interface orientada por tarefa.** Cards, contexto, drawers e workspaces substituem listas gigantes e árvores de abas, sem esconder informação necessária.
9. **Performance previsível.** Boot independente, reads limitados por timeout, cache local, carregamento progressivo e módulos pesados sob demanda.
10. **Acessibilidade e clareza.** Animação serve à compreensão, não à decoração.

## 3. O que deve ser preservado da versão atual

- dashboard desktop local servido em loopback;
- shell Qt/WebEngine;
- OAuth InstalledAppFlow local e token persistente no PC;
- acesso direto do PC às APIs oficiais do YouTube;
- cache factual local;
- motor Python local-first;
- integração Ollama/IA Local;
- política de IA Local passiva no boot;
- YouTube Data API v3;
- YouTube Analytics API;
- YouTube Reporting API sob demanda;
- leituras de vídeos, playlists, detalhes, canal, analytics e lives já existentes;
- timeouts e boot resiliente;
- superfícies MCP/Plugin existentes;
- testes de CI, Browser Recovery, Local AI Companion e Windows Desktop;
- bloqueios atuais de escrita enquanto o novo Write Gateway local não estiver certificado.

## 4. Arquitetura de navegação proposta

A navegação principal terá poucas áreas estáveis:

### Command Center
Tela inicial do software. Mostra saúde do canal, crescimento, oportunidades, riscos, tarefas pendentes, IA disponível e ações recomendadas. Não é uma parede de KPIs: cada bloco deve levar a uma ação concreta.

### Content Hub
Central unificada de vídeos, playlists, thumbnails e outros ativos suportados pela API. Busca, filtros e visualização por cards. Cada entidade abre um workspace lateral ou página contextual.

### Growth & Analytics
Gráficos oficiais, comparações, tendências, funis, retenção, CTR quando oficialmente disponível, fontes de tráfego, desempenho por período e evolução antes/depois de mudanças.

### SEO & Strategy Lab
Diagnóstico, oportunidades, títulos, descrições, tags, agrupamento por temas, playlists, séries, recuperação de vídeos fracos e planejamento editorial.

### AI Workspace
Escolha explícita de provedor e capacidade: IA Local, IA por API, ChatGPT/plugin quando conectado e motor estratégico interno. O usuário vê qual motor gerou cada recomendação.

### Automation & Approvals
Fila de propostas, previews, diffs, aprovações, rejeições, políticas de automação e histórico de execução.

### Activity & Audit
Linha do tempo de leituras, sugestões, alterações, autorizações, resultados, falhas e rollbacks.

### Settings & Integrations
YouTube OAuth, IA Local, provedores de IA, permissões, Reporting API, armazenamento/cache, segurança e diagnósticos.

## 5. Design system e experiência visual

### Cards de ação
Cada card precisa responder rapidamente: o que é, por que importa, qual o estado e qual a ação principal.

Campos típicos:
- thumbnail/ícone contextual;
- título curto;
- métrica principal;
- tendência;
- risco/oportunidade;
- origem do dado;
- CTA principal;
- menu secundário de ações.

### Cards de vídeo
- thumbnail real;
- título;
- visibilidade;
- views e tendência;
- CTR oficial quando disponível;
- retenção quando disponível;
- score de diagnóstico;
- badges de oportunidade/risco;
- ações rápidas: analisar, editar, thumbnail, playlist, histórico e ações destrutivas protegidas.

### Cards de playlist
- capa/preview composto;
- título;
- quantidade de itens;
- views ou métricas disponíveis;
- cobertura temática;
- qualidade de título/descrição;
- ações de editar, reorganizar, analisar e excluir com confirmação.

### Interações
- hover/focus com profundidade discreta;
- skeleton loading;
- transições de 150–250 ms;
- drawers contextuais em vez de navegação excessiva;
- feedback de sincronização e salvamento;
- estados vazio, indisponível, offline e erro tratados como primeira classe;
- nenhuma animação que bloqueie interação ou atrase dados.

## 6. Analytics e gráficos reais

Todo gráfico deve possuir fonte, intervalo temporal e timestamp de atualização.

Gráficos prioritários:
- views por dia/semana/mês;
- inscritos ganhos/perdidos;
- watch time;
- average view duration/percentage quando disponível;
- impressões e CTR do thumbnail somente quando Reporting fornecer oficialmente;
- evolução de CTR por vídeo quando houver histórico;
- top vídeos por crescimento e aceleração;
- vídeos em desaceleração;
- comparação entre períodos;
- fontes de tráfego;
- dispositivo/geografia quando permitido e útil;
- desempenho por playlist;
- desempenho por tema/cluster;
- publicação versus resposta de audiência;
- antes/depois de alterações de metadata/thumbnail;
- mapa de oportunidades baseado em sinais factuais.

### Escalabilidade do canal
O produto poderá exibir um **Growth Readiness Score**, mas ele deve ser explicável, versionado e composto por sinais observáveis, por exemplo:
- consistência de publicação;
- concentração de views;
- velocidade de crescimento recente;
- capacidade de converter impressões em views quando CTR oficial existir;
- retenção;
- retorno de audiência quando disponível;
- profundidade de catálogo e playlists;
- dependência de poucos vídeos.

Nunca apresentar esse score como previsão garantida de crescimento.

## 7. Modos de operação

### Manual
O usuário altera diretamente os campos permitidos pela API. O sistema valida formato, limites e permissões antes do preview.

### Assistido por IA
A IA analisa contexto e gera alternativas. Nada é aplicado automaticamente. O usuário compara sugestões e escolhe.

### Automação supervisionada
O motor cria uma proposta completa com justificativa, diffs e impacto esperado. O usuário aprova antes da escrita. Políticas futuras poderão autorizar classes específicas de ações, mas nunca exclusões destrutivas silenciosas.

## 8. AI Orchestration Layer

Criar uma camada única de orquestração para impedir que cada tela implemente IA de um jeito diferente.

### Provedores
- Local AI/Ollama;
- provedores por API configurados pelo usuário;
- ChatGPT/plugin quando disponível;
- motor Python estratégico interno para análises determinísticas.

### Contrato de tarefa
Toda solicitação de IA recebe:
- `task_type`;
- entidade e IDs;
- dados factuais com provenance;
- restrições;
- idioma/tom desejado;
- provider selecionado;
- modo de execução;
- schema de resposta esperado.

Toda resposta guarda:
- provider/model;
- timestamp;
- fatos usados;
- proposta estruturada;
- confiança/limitações;
- custo/latência quando aplicável.

### Capacidades iniciais
- títulos;
- descrições;
- tags/keywords como apoio editorial;
- diagnóstico de SEO;
- organização de playlists;
- ideias e clusters;
- recuperação de vídeos com baixo desempenho;
- comparação de alternativas;
- plano editorial;
- resposta a comandos naturais do usuário.

## 9. Command Engine em linguagem natural

O usuário poderá escrever comandos como:

> Analise meus vídeos dos últimos 90 dias, encontre os cinco com melhor oportunidade de recuperação e proponha novos títulos e thumbnails sem alterar nada ainda.

Pipeline:
1. interpretar intenção;
2. identificar permissões necessárias;
3. buscar somente dados necessários;
4. executar análise;
5. produzir proposta estruturada;
6. mostrar preview/diff;
7. coletar aprovação;
8. executar via Write Gateway;
9. fazer readback;
10. registrar auditoria.

## 10. Write Gateway seguro

Nenhuma tela ou IA escreve diretamente na API. Todas as mudanças passam por uma camada central.

### Estados
`draft -> previewed -> awaiting_approval -> approved -> applying -> verified -> rolled_back/failed`

### Regras
- idempotency key por ação;
- snapshot anterior quando disponível;
- diff legível;
- confirmação explícita;
- readback pós-apply;
- rollback quando a API e o recurso permitirem;
- falha parcial tratada e exibida;
- logs imutáveis localmente;
- ações destrutivas com confirmação reforçada.

### Exclusões
Para vídeo ou playlist:
- mostrar nome/thumbnail/ID;
- explicar irreversibilidade real;
- exigir confirmação separada;
- jamais incluir exclusão numa aprovação em massa genérica;
- registrar resultado e readback de inexistência quando possível.

## 11. Matriz inicial de gestão do YouTube

Antes de habilitar cada ação, validar suporte real da API oficial.

### Vídeos
Planejado: editar metadata permitida, status quando suportado, thumbnail, associação a playlists, análise, e exclusão protegida.

### Playlists
Planejado: criar, editar, reorganizar itens, adicionar/remover itens e excluir com proteção.

### Thumbnails
Planejado: upload/substituição quando a API permitir para o canal/recurso. Manter histórico local de arquivo e ação quando possível.

### Recursos fora da API
Qualquer função existente no YouTube Studio que não tenha endpoint oficial deve ser marcada como **não suportada pela API**, nunca simulada ou prometida.

## 12. Content Workspace

Ao abrir um vídeo, usar uma área contextual única com seções progressivas:
- Resumo;
- Performance;
- SEO;
- Metadata;
- Thumbnail;
- Playlists;
- IA e sugestões;
- Histórico.

O usuário não deve saltar por sete páginas para concluir uma tarefa simples. A interface pode usar subnavegação local discreta, sem multiplicar abas globais.

## 13. SEO & Strategy Engine

Separar análise determinística de geração textual.

### Diagnóstico determinístico
- comprimento e estrutura de título;
- repetição/canibalização temática;
- cobertura de descrição;
- consistência de playlist;
- desempenho relativo do vídeo;
- tendência de views;
- CTR oficial quando disponível;
- retenção quando disponível;
- idade do vídeo;
- contexto do catálogo.

### Geração por IA
- variações de título;
- descrição;
- chamadas para ação adequadas;
- estrutura de capítulos quando houver transcript/contexto;
- ideias de thumbnail em formato de briefing;
- clusters e playlists;
- plano de recuperação.

A IA deve receber os fatos do diagnóstico, não inventar métricas.

## 14. Cache e dados

Manter cache local com validade por tipo de dado.

Cada snapshot deve guardar:
- valor;
- fonte/API;
- fetched_at;
- período consultado;
- freshness;
- erro/indisponibilidade;
- ID da entidade.

Boot usa dados rápidos/cache. Analytics e Reporting entram progressivamente e sob demanda.

## 15. Segurança e permissões

- OAuth com menor privilégio possível;
- separar leitura de escrita na UX;
- solicitar/ativar escopos mutáveis apenas quando a função de gestão for habilitada;
- nenhum secret empacotado;
- tokens protegidos localmente;
- permissões visíveis ao usuário;
- logs de alteração;
- proteção contra double-submit;
- CSRF/origin/loopback policies adequadas ao desktop;
- IA não recebe tokens nem credenciais.

## 16. Plano de migração sem regressão

### Fase 0 — Gate de estabilidade
Fechar E2E da IA Local e certificar novamente o EXE. Congelar baseline de testes e inventário de funcionalidades existentes.

### Fase 1 — Design system e shell V2
Criar tokens visuais, componentes, cards, drawers, estados de loading/erro e navegação nova atrás de feature flag. Nenhuma funcionalidade antiga removida.

### Fase 2 — Command Center
Montar dashboard profissional usando as leituras e caches existentes. Comparar dados V1/V2 automaticamente.

### Fase 3 — Content Hub read-only
Cards de vídeos e playlists, workspaces, busca/filtro, analytics contextual. Ainda sem escrita.

### Fase 4 — Write Gateway local
Implementar preview, aprovação, apply, readback, rollback e auditoria. Começar por alterações reversíveis de metadata.

### Fase 5 — Gestão manual completa suportada
Vídeos, playlists, playlist items e thumbnails. Exclusões entram por último e com cobertura E2E específica.

### Fase 6 — AI Orchestration
Integrar Local AI, API AI, plugin e motor interno ao mesmo contrato. Primeiro sugerir; depois permitir proposta estruturada.

### Fase 7 — SEO & Strategy Lab
Diagnóstico avançado, recuperação, clusters, planejamento e comparação de alternativas.

### Fase 8 — Automation & Approvals
Comandos naturais, filas de propostas e políticas de automação supervisionada.

### Fase 9 — Hardening e release
E2E Windows, browser desktop/mobile, performance, acessibilidade, recovery, falha de rede, cache corrompido, OAuth expirado, IA ausente, APIs parciais e ações mutáveis.

## 17. Feature flags e política de substituição

Toda grande superfície V2 nasce atrás de flag:
- `elite_v2_shell`;
- `elite_v2_content_hub`;
- `elite_v2_growth`;
- `elite_v2_write_gateway`;
- `elite_v2_ai_workspace`;
- `elite_v2_automation`.

A tela V1 só será aposentada quando:
1. houver paridade funcional comprovada;
2. testes V1 e V2 passarem;
3. métricas/dados baterem dentro do contrato esperado;
4. fluxo de recovery existir;
5. rollback de deploy estiver documentado.

## 18. Estratégia de testes

### Unitários
- serviços de leitura;
- scoring;
- AI contracts;
- diff;
- validação de propostas;
- write gateway;
- políticas de permissão.

### Contrato
- Data API;
- Analytics;
- Reporting;
- MCP/plugin;
- schemas de IA.

### UI/browser
- cards;
- drawers;
- responsividade;
- loading/erro/vazio;
- acessibilidade;
- navegação por teclado.

### E2E desktop
- boot local;
- OAuth local;
- leitura do canal;
- IA Local explicitamente reavaliada;
- chat local;
- preview de escrita com fake API;
- apply/readback/rollback em ambiente controlado;
- nenhuma escrita real em testes que não tenham autorização específica.

### Mutabilidade real
Testes contra YouTube real permanecem separados e exigem autorização específica. Não reutilizar consentimento de testes de leitura ou IA para escritas no canal.

## 19. Performance budgets

Metas iniciais:
- shell visível rapidamente e independente de Analytics/Reporting;
- nenhum request pesado bloqueando render inicial;
- cards carregam progressivamente;
- gráficos usam agregação/cache;
- Reporting nunca no boot;
- operações de IA canceláveis e com timeout;
- listas grandes virtualizadas ou paginadas;
- imagens lazy-loaded;
- nenhuma animação acima do custo aceitável para máquinas comuns.

## 20. Critérios de pronto da V2

A V2 será considerada pronta quando:
- preservar todas as leituras e integrações úteis já existentes;
- tiver Command Center e Content Hub visualmente profissionais;
- apresentar gráficos oficiais com provenance;
- oferecer gestão manual suportada pela API através do Write Gateway;
- oferecer IA Local e provedores selecionáveis através do mesmo contrato;
- mostrar preview/diff antes de qualquer mudança;
- suportar auditoria e readback;
- passar CI, Browser Recovery, Local AI E2E e Windows packaged E2E;
- não exigir YouTube Studio para as operações que a API oficial realmente suporta;
- identificar claramente as operações que a API não oferece.

## 21. Regra de ouro da implementação

**Não reescrever o produto inteiro de uma vez.** A evolução será incremental, com componentes V2 montados sobre serviços estáveis e substituição por paridade. Software profissional não é o que tem mais efeitos; é o que continua funcionando enquanto fica melhor.
