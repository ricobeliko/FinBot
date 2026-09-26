# FinBot — Guia de Contribuição e Estilo de Código

Este guia estabelece os padrões técnicos e o fluxo de trabalho para manter a qualidade e a simplicidade do FinBot.

---

## Padrões de Código

- **Python Legível e Idiomático**: Escreva código simples e direto, priorizando legibilidade para humanos.
- **PEP 8**: Respeite os padrões de formatação padrão do Python (espaçamento, nomenclatura, quebra de linhas).
- **Nomes Explícitos**: Variáveis, funções e arquivos devem revelar claramente seu propósito (evite siglas crípticas ou abreviações obscuras).
- **Módulos Pequenos**: Divida responsabilidades em arquivos enxutos e coesos.
- **Evitar Duplicação Óbvia**: Reutilize lógica existente quando direto e limpo, sem criar dependências circulares.
- **Evitar Abstração Prematura**: Não crie interfaces, fábricas ou padrões de projeto antes de haver três casos de uso reais e idênticos.
- **Documentação Onde Agrega Valor**: Use docstrings concisas em funções e módulos públicos. Não comente o óbvio.
- **Testes Focados em Comportamento Importante**: Priorize testes que garantam o cálculo correto de sinais, integridade do gerenciador de risco e fluxo de dados, evitando testes triviais de boilerplate.

---

## Fluxo de Mudança Padrão

Ao implementar qualquer funcionalidade ou ajuste, siga rigorosamente as etapas:

1. **Entender contexto**: Ler a fase ativa em `MEMORY.md`, o roadmap em `ROADMAP.md` e as diretrizes em `AGENTS.md`.
2. **Alterar**: Fazer a menor intervenção necessária para cumprir o objetivo estrito da tarefa.
3. **Validar**: Executar a aplicação, verificar sintaxe e rodar testes pertinentes no terminal.
4. **Revisar diff**: Inspecionar com `git diff` e `git status` para certificar-se de que nada acidental foi incluído.
5. **Atualizar memória se necessário**: Refletir mudanças de fase ou checkpoints em `MEMORY.md` e ADRs em `DECISIONS.md`.
6. **Commit local**: Registrar a alteração em commit claro e coeso no Git local (sem push para remotes).
