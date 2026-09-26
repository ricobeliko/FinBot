# Diretrizes para Agentes de IA e GitHub Copilot

Este arquivo orienta agentes de IA trabalhando no repositório **FinBot**.

## Leitura Obrigatória Antes de Alterar Qualquer Código

Antes de propor ou executar qualquer modificação, consulte obrigatoriamente:
1. `AGENTS.md` (regras fundamentais de conduta do agente)
2. `CONTEXT.md` (domínio, propósito e fluxo do sistema)
3. `MEMORY.md` (estado operacional atual, fase ativa e checkpoint)
4. `ROADMAP.md` (fases de desenvolvimento e escopo permitido)
5. `DECISIONS.md` (registro de decisões de arquitetura - ADRs)
6. `SKILLS.md` (padrões de segurança e práticas de código)
7. `CONTRIBUTING.md` (convenções de estilo, fluxo e commits)

## Princípio Constitucional

> Antes de adicionar biblioteca, camada, serviço, abstração ou arquivo, pergunte:
> **"Existe necessidade real agora?"**
> Se a resposta for não: **NÃO IMPLEMENTAR.**

## Regras Fundamentais

- **Fase Atual**: Respeite rigorosamente a fase documentada em `MEMORY.md`. Não implemente nada além da fase ativa.
- **Local-first**: O bot é desenvolvido e executado exclusivamente em ambiente local Windows.
- **Segurança Operacional**:
  - Live Trading deve permanecer desativado por padrão.
  - A estratégia nunca fala diretamente com a exchange (`Strategy -> Risk Manager -> Broker -> Exchange`).
  - Nunca commite nem utilize secrets/chaves reais no código.
- **Simplicidade**: Mantenha o código limpo, legível (PEP 8) e sem abstrações preventivas ou dependências não justificadas.
- **Sincronização**: Atualize `MEMORY.md` e `DECISIONS.md` sempre que houver evolução de fase ou novas decisões arquiteturais.
