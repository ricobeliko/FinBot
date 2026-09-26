# FinBot — Habilidades e Padrões Operacionais (Skills)

Este documento define o conjunto restrito de competências e práticas essenciais para desenvolvimento e manutenção no projeto FinBot.

---

### 1. `safe-code-change`
- **Inspecionar antes**: Ler o arquivo, entender dependências e verificar o contexto antes de editar.
- **Alteração mínima**: Fazer a menor intervenção possível para satisfazer a tarefa atual.
- **Validar depois**: Executar imediatamente o código alterado para garantir ausência de quebras.

---

### 2. `simple-python`
- **Funções pequenas**: Blocos curtos, focados e com responsabilidade única.
- **Nomes claros**: Identificadores descritivos e explícitos em português ou inglês consistente.
- **Type hints quando úteis**: Adicionar anotações de tipo onde facilitarem a leitura e verificação estática.
- **Evitar classes desnecessárias**: Priorizar funções puras e módulos simples; criar classes apenas se houver real gerenciamento de estado encapsulado.

---

### 3. `trading-safety`
- **Strategy nunca chama exchange diretamente**: O fluxo estrito deve ser `Strategy -> Risk Manager -> Broker -> Exchange`.
- **Risk Manager precede Broker**: Nenhuma intenção de ordem pode ser despachada sem validação prévia de risco.
- **Live bloqueado por padrão**: O modo com dinheiro real não pode ser ligado acidentalmente.
- **Nunca habilitar withdrawal**: Chaves de API nunca devem ter permissão de saque.
- **Nenhuma chave no código**: Jamais expor secrets, tokens ou credenciais em repositório ou logs.

---

### 4. `test-before-finish`
- **Executar apenas testes/validações relevantes**: Validar aquilo que foi modificado e as portas de entrada afetadas.
- **Não declarar sucesso sem verificar**: Nunca concluir uma tarefa assumindo que funciona sem ter inspecionado a saída real do terminal.

---

### 5. `documentation-sync`
- **MEMORY acompanha estado atual**: Atualizar fase, checkpoint e pendências a cada marco relevante.
- **DECISIONS acompanha decisões**: Registrar novos direcionamentos ou recuos como ADRs em `DECISIONS.md`.
- **ROADMAP acompanha fases**: Marcar itens concluídos com precisão e manter o foco na fase ativa.
