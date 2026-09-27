# FinBot — Registro de Decisões de Arquitetura (ADRs)

Este documento registra de forma simplificada as decisões arquiteturais tomadas no projeto FinBot, seus contextos e justificativas.

---

### D001 — Adoção de Python 3.12
- **Status**: Aceito
- **Data**: FASE 0
- **Contexto**: Escolha da versão base da linguagem para desenvolvimento do bot.
- **Decisão**: Utilizar Python 3.12 (especificamente 3.12.10 disponível no ambiente).
- **Motivo**: Excelente equilíbrio entre estabilidade, alto desempenho nas versões recentes do CPython, suporte pleno do ecossistema quantitativo/financeiro e ampla compatibilidade de bibliotecas.

---

### D002 — Repositório Git Exclusivamente Local Inicialmente
- **Status**: Aceito
- **Data**: FASE 0
- **Contexto**: Controle de versão e colaboração.
- **Decisão**: Manter o repositório Git apenas em ambiente local, sem configurar remotes ou repositórios públicos/privados no GitHub nesta etapa.
- **Motivo**: O usuário não deseja publicar o projeto durante o ciclo inicial de concepção e desenvolvimento.

---

### D003 — Arquitetura Local-first
- **Status**: Aceito
- **Data**: FASE 0
- **Contexto**: Modelo de implantação e hospedagem do bot.
- **Decisão**: O FinBot será executado integralmente em máquina local Windows, sem dependência de serviços cloud, containers Docker ou orquestradores remotos.
- **Motivo**: Reduz custos, simplifica manutenção, garante controle físico dos dados e privacidade operacional.

---

### D004 — Arquitetura Simples e Direta
- **Status**: Aceito
- **Data**: FASE 0
- **Contexto**: Filosofia de design de software.
- **Decisão**: Priorizar simplicidade sobre engenharia excessiva. Não criar microserviços, padrões complexos sem demanda imediata ou abstrações preventivas.
- **Motivo**: Evitar débito técnico de sobre-engenharia, manter facilidade de inspeção pelo operador e garantir que cada linha de código tenha função real demonstrável.

---

### D005 — CCXT como Camada Oficial de Exchange (Adotado)
- **Status**: Aceito (Adotado na FASE 2)
- **Data**: FASE 0 (Planejado) / FASE 2 (Adotado)
- **Contexto**: Acesso a dados públicos de mercado e APIs de exchanges de criptoativos.
- **Decisão**: Adotar a biblioteca CCXT como cliente unificado para consultas públicas de mercado e futuras integrações.
- **Motivo**: Biblioteca padrão da indústria, ativamente mantida, madura, e que oferece interface unificada para centenas de exchanges.

---

### D006 — SQLite Planejado para Armazenamento Local
- **Status**: Aceito (Planejado)
- **Data**: FASE 0
- **Contexto**: Persistência de configurações, trades em paper trading e histórico operacional.
- **Decisão**: Utilizar SQLite como banco de dados local a partir da FASE 5.
- **Motivo**: Banco embutido (zero configuração de servidor externo), transacional (ACID), leve, nativo no Python e altamente confiável para uso em um único processo.

---

### D007 — IA Não Toma Decisões Financeiras
- **Status**: Aceito
- **Data**: FASE 0
- **Contexto**: Aplicação de Inteligência Artificial no projeto.
- **Decisão**: A IA (agentes LLM) é empregada exclusivamente como ferramenta de desenvolvimento, testes e documentação. As estratégias de trading serão puramente determinísticas, baseadas em regras e indicadores objetivos.
- **Motivo**: Eliminar riscos de alucinação, comportamento imprevisível ou não-determinismo em decisões que envolvem risco financeiro.

---

### D008 — Live Trading Bloqueado por Padrão
- **Status**: Aceito
- **Data**: FASE 0
- **Contexto**: Segurança patrimonial e proteção operacional contra acidentes.
- **Decisão**: O envio de ordens reais com capital financeiro permanecerá desativado por padrão no código, exigindo configuração intencional e autorização explícita do operador em fase adequada.
- **Motivo**: Minimização drástica do risco operacional durante desenvolvimento, testes e simulações.

---

### D009 — Estratégia Determinística com Cruzamento de Médias (SMA Crossover)
- **Status**: Aceito
- **Data**: FASE 3
- **Contexto**: Implementação do primeiro motor de estratégia (Strategy Engine) para validação arquitetural.
- **Decisão**: Adotar a estratégia de cruzamento de médias móveis simples (SMA curta vs SMA longa) implementada exclusivamente com a Standard Library do Python, desacoplada de CCXT e de bibliotecas externas pesadas (sem pandas, numpy ou TA-Lib).
- **Motivo**: Determinismo estrito, cálculo matemático simples e transparente, facilidade de testes unitários isolados e preservação do princípio de não adicionar dependências desnecessárias.

---

### D010 — Adoção de Backtesting.py para Simulação Histórica Local
- **Status**: Aceito
- **Data**: FASE 4
- **Contexto**: Necessidade de validar o comportamento histórico e o desempenho da estratégia sobre dados reais de mercado de forma reproduzível e isolada de ordens reais.
- **Decisão**: Adotar a biblioteca `backtesting==0.6.6` (e `pandas==3.0.6` como dependência direta declarada) para execução de simulações locais através de `FractionalBacktest`, integrando o motor oficial `evaluate_sma_crossover` sem duplicar lógica.
- **Licença e Implicações**: A biblioteca Backtesting.py 0.6.6 é distribuída sob licença AGPL-3.0+. A dependência foi adotada nesta fase estritamente para backtesting e simulação local, mantendo o projeto integralmente privado e restrito ao ambiente local do operador. A licença e seus requisitos de compartilhamento de código-fonte devem ser formalmente reavaliados antes de qualquer eventual distribuição pública ou comercialização do projeto.
- **Motivo**: Ferramenta consolidada, de fácil integração com dados tabulares do pandas, semântica transparente de execução no próximo candle (mitigação intrínseca de look-ahead bias) e suporte comprovado a dimensionamento fracionado de contratos para criptoativos.

---

### D011 — Arquitetura de Paper Trading com Persistência SQLite Local
- **Status**: Aceito
- **Data**: FASE 5
- **Contexto**: Necessidade de executar forward testing em tempo real com capital fictício, persistindo saldos e ordens simuladas entre reinicializações sem conexão autenticada com a exchange.
- **Decisão**: Adotar a arquitetura de Paper Trading local com persistência via `sqlite3` da Python Standard Library (`storage.py` e `paper.py`):
  - Carteira simulada mantida integralmente em banco local (`data/finbot_paper.sqlite3`).
  - Nenhuma API key, secret ou chamada a endpoints privados de exchange.
  - Saldo fictício inicial configurável (10000.00 USDT) persistido em tabela única.
  - Modelo operacional Spot LONG exclusivo, limitado a uma única posição aberta por vez.
  - Notional fixo preliminar de 100.00 USDT por operação (a ser aprimorado pelo Risk Engine na FASE 6).
  - Execução one-shot com filtragem estrita de candles ainda em formação e deduplicação pelo timestamp do último candle fechado.
  - Transações atômicas com rollback em caso de falha, garantindo consistência entre carteira, posição e histórico.
- **Motivo**: Atendimento pleno à arquitetura local-first sem dependências externas adicionais (zero novas bibliotecas), confiabilidade transacional garantida pelo SQLite e isolamento completo contra riscos operacionais no mercado real.

---

### D012 — Risk Engine Determinístico e Local
- **Status**: Aceito
- **Data**: FASE 6
- **Contexto**: Necessidade de estabelecer uma camada intermediária explícita e mandatória de gestão e controle de risco entre a geração de sinais da estratégia e a execução de ordens simuladas no Paper Broker.
- **Decisão**: Implementar o motor de risco determinístico exclusivamente na Standard Library do Python (`src/finbot/risk.py`), com as seguintes diretrizes:
  - **Autoridade e Desacoplamento**: A estratégia não define tamanho de posição e o broker não decide se a ordem é permitida. Todo sinal deve receber autorização (`ALLOW`) ou bloqueio (`BLOCK`) com código padronizado (`RiskDecisionCode`).
  - **Isolamento de Rede**: O Risk Engine não importa CCXT nem realiza conexões de rede ou chamadas de IO, operando estritamente sobre estruturas em memória e dados validados.
  - **Precedência Conceitual Estrita**:
    1. *Proteção de Risco / Stop Loss Defensivo*: Se a posição aberta sofrer desvalorização >= 2.0% (`risk_stop_loss_pct`), a saída é disparada imediatamente com motivo `STOP_LOSS`, prevalecendo sobre qualquer sinal da estratégia.
    2. *Sinal SELL da Estratégia*: Se houver posição aberta, o encerramento é autorizado (`STRATEGY_SIGNAL`).
    3. *Sinal HOLD*: Nenhuma alteração patrimonial.
    4. *Sinal BUY da Estratégia*: Submetido à esteira de gates de risco (Posição Aberta / Max Position Notional, Kill Switch, Perda Diária Realizada, Cooldown por candles fechados e Saldo Disponível).
    5. *Sinal SELL sem Posição*: Ignorado sem erro.
  - **Inviolabilidade de Saídas**: Proteções de risco (Kill Switch, Cooldown e Limite de Perda Diária) jamais bloqueiam operações de venda destinadas a reduzir ou encerrar exposição.
  - **Cooldown Baseado em Candles**: O intervalo defensivo pós-encerramento (1 candle fechado) baseia-se em timestamps de candles fechados, sem temporizadores contínuos ou threads em background.
  - **Persistência e Migração Idempotente**: Registro de Kill Switch, último bloqueio de risco e motivo de saída (`exit_reason`) armazenados no SQLite existente via migração incremental que preserva bases anteriores sem destruição de dados.
- **Motivo**: Garantia matemática de contenção de prejuízos, observância de boas práticas quantitativas sem dependências de terceiros, preservação do princípio local-first e preparação estruturada da camada de risco para os futuros modos de operação.

---

### D013 — Adoção de Streamlit para Dashboard Local e Read-Only
- **Status**: Aceito
- **Data**: FASE 7
- **Contexto**: Necessidade de fornecer uma interface visual de fácil entendimento em tempo real para acompanhamento de patrimônio, posições, métricas de risco, sinais da estratégia e histórico de trades, preservando simplicidade local e segurança patrimonial.
- **Decisão**: Adotar a biblioteca `streamlit==1.64.0` para o dashboard visual local (`src/finbot/dashboard.py` e `src/finbot/metrics.py`):
  - **Modo Estritamente Read-Only**: O dashboard atua unicamente como camada de apresentação e leitura do SQLite local (`data/finbot_paper.sqlite3`). Não possui botões, endpoints ou capacidade técnica de emitir ordens de compra/venda, alterar saldos ou contornar o Risk Engine.
  - **Restrição de Rede Local (localhost)**: Vinculado estritamente à interface local `127.0.0.1` (`--server.address=127.0.0.1`), sem exposição para `0.0.0.0`, sem túneis remotos e sem autenticação externa nesta etapa.
  - **Desacoplamento de Métricas**: Módulo puro `metrics.py` para cálculo de win rate, fees, P/L não realizado e evolução patrimonial cumulativa, viabilizando testes unitários automatizados determinísticos sem necessidade de renderização visual.
  - **Responsividade e Prontidão Mobile**: Interface projetada com containers flexíveis e métricas responsivas do Streamlit, permitindo boa ergonomia tanto em monitores desktop quanto em telas menores de smartphones.
  - **Isolamento de Acesso Remoto**: O acesso remoto não foi implementado nesta fase; futuras fases avaliarão opções de distribuição segura (ex: PWA, gateway reverso seguro ou app dedicado).
- **Motivo**: Desenvolvimento rápido em Python, excelente integração nativa com DataFrames/pandas e SQLite, visual moderno e limpo sem necessidade de frameworks web pesados ou acoplamento de servidores adicionais.

---

### D014 — Automação de Ciclos Paper Trading via Windows Task Scheduler
- **Status**: Aceito
- **Data**: FASE 7.5
- **Contexto**: Necessidade de executar o Paper Trading de forma contínua e autônoma ao longo do tempo (intervalo de 1 minuto), preservando a filosofia local-first e sem transformar a aplicação em um serviço de background ou daemon complexo.
- **Decisão**: Adotar a automação externa via Windows Task Scheduler orquestrando scripts PowerShell (`scripts/run_paper.ps1` e `scripts/install_paper_task.ps1`):
  - **Preservação do Modelo One-Shot**: O FinBot não implementa loops infinitos (`while True`), threads permanentes ou bibliotecas externas de agendamento (zero frameworks como APScheduler, Celery ou Redis). O comando `python -m finbot.paper` permanece estritamente one-shot.
  - **Prevenção de Sobreposição Concorrente**: Tarefa configurada com política `MultipleInstances: IgnoreNew`, garantindo que um novo ciclo jamais seja iniciado se uma execução anterior ainda estiver em processamento.
  - **Deduplicação de Candles**: O timestamp do último candle fechado gravado no SQLite continua sendo a salvaguarda primária contra reprocessamento no mesmo minuto.
  - **Observabilidade Persistente**: Gravação do timestamp do último ciclo, último ciclo bem-sucedido, resultado e mensagem de execução em `paper_state`, viabilizando o monitoramento de frescor operacional (`RECENT` vs `STALE`) no dashboard e CLI.
  - **Recuperação Natural**: O agendador nativo do sistema operacional lida com reinicializações e falhas do processo sem risco de estados corrompidos ou threads zumbis.
- **Motivo**: Máxima simplicidade arquitetural, confiabilidade operacional nativa do Windows, separação clara entre motor de cálculo financeiro e agendamento temporal, e conformidade com o princípio de adicionar apenas o estritamente necessário.

---

### D015 — Telemetria Enxuta para Paper Soak Test e Rotação de Logs
- **Status**: Aceito
- **Data**: FASE 7.6
- **Contexto**: Preparação para um período de teste de estresse e estabilidade operacional contínua (*Paper Soak Test*) de 72 horas sem supervisão direta no Windows, exigindo observabilidade de falhas, métricas de execução e controle de espaço em disco.
- **Decisão**:
  - **Telemetria Enxuta em `paper_state`**: Utilizar a tabela existente de chave-valor do SQLite para rastrear contadores atômicos de ciclos (`total_cycles`, `successful_cycles`, `failed_cycles`, `deduplicated_cycles`), além de `soak_start_timestamp`, `last_error` e `last_error_timestamp`. Nenhuma tabela nova ou framework pesado de métricas foi adicionado.
  - **Isolamento de Falhas Transitórias**: Falhas de rede, timeouts ou indisponibilidade temporária de exchange incrementam o contador de falhas e registram o erro, mas jamais alteram ou corrompem o saldo fictício, a posição aberta, os trades executados ou o último candle processado. O próximo ciclo agendado recupera a saúde operacional sem intervenção manual.
  - **Rotação de Arquivos de Log**: Adoção de `RotatingFileHandler` da Standard Library com limite de 5 MB por arquivo e retenção de até 3 backups (`logs/finbot.log`), prevenindo saturação descontrolada de disco ao longo de execuções ininterruptas minuto a minuto.
- **Motivo**: Observabilidade diagnóstica completa, segurança patrimonial inegociável, isolamento contra falhas de infraestrutura e conformidade estrita com o princípio da menor intervenção necessária.

---

### D016 — Adoção de Repositório GitHub Privado para Sincronização e Backup sem CI/CD
- **Status**: Aceito
- **Data**: FASE 7.6 / Transição
- **Contexto**: Necessidade de manter backup privado do código, rastreamento de versões e fluxo de sincronização entre ambientes físicos distintos: Notebook (focado em desenvolvimento e commits) e PC Forte (focado em testes locais completos, Paper Runner, Dashboard e runtime 24/7).
- **Decisão**: Configurar repositório remoto privado no GitHub (`https://github.com/ricobeliko/FinBot.git`) exclusivamente como camada de versionamento e backup do código-fonte:
  - **Papel do Notebook**: Ambiente de desenvolvimento, escrita de código, execução de commits e envio (`git push origin main`).
  - **Papel do PC Forte**: Ambiente de execução local contínua, sincronização (`git pull origin main`), execução de testes automatizados locais (`python -m unittest discover tests`), Paper Runner periódico e visualização de Dashboard.
  - **Ausência Estrita de CI/CD**: Nenhum workflow do GitHub Actions (`.github/workflows/`), pipeline de nuvem, runner remoto ou deploy automático. O repositório é estritamente de armazenamento e transporte de código.
  - **Testes Unitários Versionados (`tests/`)**: A suíte de testes permanece integralmente versionada no Git para ser executada de forma autônoma e offline em cada máquina local.
  - **Isolamento de Estado Operacional (`data/finbot_paper.sqlite3`)**: O banco de dados SQLite local, dados de saldo paper, ordens simuladas, logs e variáveis de ambiente (`.env`) permanecem ignorados no `.gitignore` e restritos à máquina local em que operam.
- **Motivo**: Segurança do patrimônio de código sem dependência de plataformas de automação em nuvem, garantia de execução e testes 100% locais e preservação da integridade da máquina de execução contínua.

---

### D017 — Arquitetura Isolada do FinBot Lab para Backtesting Paralelo e Mitigação de Overfitting
- **Status**: Aceito
- **Data**: FASE 7.7
- **Contexto**: Necessidade de um laboratório quantitativo para testar combinações de parâmetros (grid sweep), utilizar múltiplos núcleos de CPU via paralelismo de processos e avaliar sistematicamente o risco de overfitting com divisão cronológica de dados (Train / Validation / Test).
- **Decisão**: Criar o pacote isolado `src/finbot/lab/` e dashboard dedicado `src/finbot/lab_dashboard.py` (porta 8502):
  - **Isolamento Total do Bot Operacional**: O Lab opera unicamente sobre dados históricos locais, sem jamais acessar, alterar ou criar `data/finbot_paper.sqlite3`, `paper_account`, `paper_position`, `paper_trades` ou o Task Scheduler. O Lab não possui autoridade para promover estratégias automaticamente para o bot operacional.
  - **Divisão Cronológica Estrita**: Particionamento temporal (60% Train, 20% Validation, 20% Test) sem embaralhamento (no-shuffle), evitando qualquer look-ahead bias ou contaminação entre partições.
  - **Reutilização da Lógica Financeira Oficial**: Sem duplicação de cálculo; as simulações reutilizam diretamente `run_backtest` de `finbot.backtest`.
  - **Paralelismo Seguro via Standard Library**: Adoção de `concurrent.futures.ProcessPoolExecutor` com suporte a `--workers auto` (`max(1, cpu_count - 1)`), garantindo determinismo idêntico entre execuções sequenciais e paralelas.
  - **Salvaguarda do Preset FULL**: Presets configuráveis (`smoke`, `standard`, `full`), onde `full` requer confirmação explícita (`--confirm-full`) para prevenir sobrecarga de computação no notebook.
  - **Validade do Dataset Conhecida**: Resultados do snapshot de 500 candles são explicitamente rotulados como `EXPLORATORY / ENGINEERING VALIDATION` e não constituem evidência estatística suficiente de robustez final.
- **Motivo**: Prover infraestrutura quantitativa profissional, reprodutível e determinística mantendo o bot operacional estritamente congelado e protegido.

---

### D018 — Auditoria Metodológica e Ingestão de Dataset Histórico Ampliado (10.000 candles)
- **Status**: Aceito
- **Data**: FASE 7.8
- **Contexto**: Necessidade de auditar rigorosamente o comportamento metodológico do FinBot Lab (isolamento de capital, ausência de transbordo de posições, blindagem do ranking pelo Treino, comportamento de warm-up da SMA) e disponibilizar um dataset histórico substancialmente maior (10.000 candles de 5m da Binance Spot, ~34,7 dias) para viabilizar pesquisas quantitativas robustas sem depender de conexão de rede durante as simulações.
- **Decisão**:
  - **Metodologia de Partições Independentes**: Cada fatia cronológica (Train 60%, Validation 20%, Test 20%) é avaliada de forma estritamente autônoma, iniciando com capital novo (`10000.0 USDT`) e posição zerada. Os primeiros `long_window` candles de cada fatia atuam como aquecimento interno (emitindo `HOLD`), prevenindo que métricas de Buy & Hold ou retornos da partição anterior contaminem a partição subsequente.
  - **Blindagem do Ranqueamento**: O ranking de candidatos é determinado exclusivamente pelo desempenho da partição de Treino (`train.return_pct`, etc.). As métricas de Validação e Teste são puramente diagnósticas (out-of-sample) e não possuem autoridade de seleção.
  - **Dataset Ampliado e Congelado**: Download reproduzível e paginado via script dedicado (`scripts/download_dataset.py`) de 10.000 candles fechados de 5m (`data/backtest/binance_BTCUSDT_5m_10000.json`, 1.7 MB), preservando o snapshot original de 500 candles (`binance_BTCUSDT_5m.json`). Integridade temporal (5m contínuos, ausência de duplicatas e OHLC válido) auditada e aprovada.
  - **Bateria Metodológica Automatizada**: Adição de 10 testes determinísticos em `test_lab_methodology.py` (totalizando 100 testes no projeto).
- **Motivo**: Consolidação de integridade científica e quantitativa prévia a qualquer esforço de força bruta em larga escala, mantendo o bot operacional no PC Forte congelado e protegido.
