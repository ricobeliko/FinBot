# FinBot — Templates de Prompts para Agentes

Templates padronizados e concisos para guiar intervenções de agentes de IA ao longo das fases do FinBot.

---

### 1. Auditoria de Fase
```text
Revise o estado atual do FinBot em relação aos objetivos da FASE [X] definidos no ROADMAP.md.
Inspecione os arquivos criados/alterados, verifique a conformidade com as regras em AGENTS.md e DECISIONS.md, e confirme se há código desnecessário, dependências não justificadas ou violações de fluxo de risco.
Apresente um resumo com status, validações executadas e pendências antes do fechamento da fase.
```

---

### 2. Implementação da Próxima Fase
```text
Inicie a implementação da FASE [X] do FinBot conforme o ROADMAP.md.
Antes de escrever código:
1. Leia AGENTS.md, CONTEXT.md, MEMORY.md e DECISIONS.md.
2. Identifique os requisitos mínimos estritos desta fase.
3. Não adicione dependências sem justificar nem crie abstrações prematuras.
4. Execute as validações locais pertinentes e atualize MEMORY.md com o novo checkpoint.
```

---

### 3. Investigação de Bug
```text
Investigue o problema relatado no FinBot: [DESCREVER COMPORTAMENTO OBSERVADO].
Siga a skill safe-code-change:
1. Isole a causa raiz inspecionando o código e os logs locais.
2. Formule uma solução com a menor alteração de código necessária.
3. Valide a correção no terminal local.
4. Explique a causa e o ajuste realizado.
```

---

### 4. Revisão de Segurança Financeira
```text
Realize uma auditoria estrita de segurança no fluxo de ordens e dados:
1. Verifique se Strategy chama Broker ou Exchange diretamente (violação arquitetural grave).
2. Confirme se Risk Manager intercepta e valida 100% das intenções de ordem.
3. Certifique-se de que o modo LIVE está bloqueado por padrão e nenhuma chave de API real está exposta.
4. Valide a integridade do Kill Switch e das salvaguardas operacionais.
```

---

### 5. Preparação para Release Local
```text
Prepare o FinBot para transferência e execução no PC de produção local (Windows):
1. Verifique dependências estritamente necessárias em pyproject.toml / requirements.txt.
2. Valide os scripts de inicialização e ativação local em RUNBOOK.md.
3. Assegure que nenhum dado sensível, log pessoal ou cache seja versionado.
4. Confirme que o sistema inicializa de forma estável e autônoma.
```
