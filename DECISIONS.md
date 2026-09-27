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
