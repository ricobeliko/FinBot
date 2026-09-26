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
