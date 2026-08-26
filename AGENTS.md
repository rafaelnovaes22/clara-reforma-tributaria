# AGENTS.md

## Objetivo

Piloto privado da Clara para uma contadora. Use somente dados sintéticos. Nenhuma saída autoriza decisão fiscal.

## Setup

```bash
python scripts/setup.py
```

O comando cria ou reutiliza `.venv`, instala dependências travadas, instala o compilador TypeScript e executa `pip check`.

## Executar

```bash
.venv/bin/python backend/server.py
```

No Windows, use `.venv\Scripts\python.exe`.

## Verificar

```bash
.venv/bin/python scripts/verify.py
```

Esse é o único gate local. Ele verifica formato, lint, tipos do frontend, JSON, testes, evals, grafo e artefato compilado.

## Mapa

```text
frontend/runtime.ts + app.ts -> app.js -> HTTP protegido
                                         |
backend/server.py -> clara/http_api.py -> clara/conversation.py -> OpenAI Responses + busca oficial
                                      |                       |
                                      -> clara/documents.py    -> clara/knowledge.py
                                      -> clara/sessions.py     -> memória limitada por ator/cliente/sessão
```

## Regras de segurança

- Nunca reintroduza configuração de chave OpenAI no navegador.
- Toda rota, exceto health e readiness, exige autenticação.
- Toda conclusão fiscal material usa fonte oficial ao vivo ou abstenção.
- Toda conclusão fiscal material exige revisão da contadora.
- XML do piloto é sintético e nunca recebe status de aprovado, válido ou autorizado.
- Não registre pergunta, XML, credencial, token ou identificador em claro.

## Deploy

Siga `PILOT_RUNBOOK.md`. Deploy, domínio, variáveis externas e rollback exigem confirmação explícita do usuário.
