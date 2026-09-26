# FinBot — Diretrizes para Agentes de IA

Este é o ponto de partida obrigatório para qualquer agente de IA que atue neste repositório.

## LEITURA OBRIGATÓRIA ANTES DE ALTERAR CÓDIGO

Antes de analisar, planejar ou alterar qualquer arquivo do projeto, leia obrigatoriamente nesta ordem:

1. `AGENTS.md` (este documento)
2. `CONTEXT.md`
3. `MEMORY.md`
4. `ROADMAP.md`
5. `DECISIONS.md`
6. `SKILLS.md`
7. `CONTRIBUTING.md`

---

## Princípio Constitucional

Antes de adicionar qualquer biblioteca, camada, serviço, abstração ou arquivo, faça a si mesmo a pergunta:

> **"Existe necessidade real agora?"**
>
> Se a resposta for **não**: **NÃO IMPLEMENTAR.**

---

## Regras Operacionais do Agente

1. **Entender a fase atual antes de editar**: Consulte sempre `MEMORY.md` e `ROADMAP.md` para saber exatamente em qual fase o projeto está.
2. **Fazer a menor alteração necessária**: Mantenha diffs pequenos, objetivos e focados estritamente na tarefa solicitada.
3. **Não expandir escopo**: Nunca introduza funcionalidades de fases futuras antecipadamente.
4. **Não adicionar dependências sem justificar**: Toda nova dependência deve ter justificativa explícita e aprovação prévia.
5. **Não alterar decisões arquiteturais silenciosamente**: Qualquer mudança de rumo deve ser documentada e formalizada como ADR.
6. **Não implementar funcionalidades futuras antecipadamente**: Se a fase pede estrutura, não implemente conectores; se pede monitor, não implemente trading.
7. **Executar validações pertinentes antes de terminar**: Sempre teste a sintaxe, execução mínima e valide que testes passam antes de dar a tarefa como concluída.
8. **Atualizar MEMORY.md quando houver mudança relevante**: Mantenha o estado operacional e o último checkpoint sempre fidedignos.
9. **Atualizar DECISIONS.md quando houver nova decisão arquitetural**: Registre novas decisões técnicas no formato de ADR simplificado.
10. **Nunca inserir secrets**: Jamais coloque chaves privadas, senhas ou tokens de API no código ou em arquivos versionados.
11. **Nunca habilitar live trading implicitamente**: Live trading é bloqueado por padrão e restrito às fases apropriadas.
12. **Preservar simplicidade**: Local-first, sem microserviços, sem abstrações desnecessárias e sem frameworks pesados.
