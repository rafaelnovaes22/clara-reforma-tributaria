# Runbook do piloto privado

## 1. Gates antes do deploy

```bash
.venv/bin/python scripts/verify.py
.venv/bin/python scripts/check_sources.py
```

Exija 100% dos hard gates críticos e zero retry para obter aprovação. A contadora deve revisar e aprovar o conjunto de casos fiscais em `evals/cases.json`.

## 2. Variáveis Railway

Configure como secrets ou variáveis do serviço:

- `CLARA_ENV=pilot`
- `CLARA_PUBLIC_ORIGIN=https://DOMINIO-DO-SERVICO`
- `CLARA_REQUIRE_AUTH=true`
- `CLARA_PILOT_USERNAME=contadora`
- `CLARA_PILOT_PASSWORD` com valor aleatório de pelo menos 24 caracteres
- `CLARA_PILOT_CLIENT_ID=piloto-contadora`
- `CLARA_AUDIT_HASH_KEY` com valor aleatório de pelo menos 32 caracteres
- `CLARA_DISABLE_AUDIT=false`
- `CLARA_ALLOW_REAL_XML=false`
- `OPENAI_API_KEY` como secret do projeto OpenAI
- `OPENAI_MODEL=gpt-5.6-luna`
- `RAILPACK_PYTHON_VERSION=3.12`

Não configure `PORT`. A Railway injeta essa variável. O processo usa `0.0.0.0` quando `PORT` existe.

## 3. Contrato operacional

`railway.json` fixa uma réplica, start command, readiness e política de restart. Uma réplica é obrigatória enquanto memória e sessões forem locais ao processo.

TLS termina no edge da Railway. O app exige Origin e Host iguais a `CLARA_PUBLIC_ORIGIN` e envia HSTS no modo piloto.

Deploy ou restart apaga todas as sessões. Avise a contadora antes de cada mudança.

## 4. Deploy manual

Execute somente após confirmação explícita do usuário:

```bash
railway status --json
railway up --detach --project PROJECT_ID --service SERVICE --environment production --message "Piloto privado Clara"
railway deployment list --json --service SERVICE --environment production
```

Substitua `PROJECT_ID` e `SERVICE` pelos identificadores conferidos no primeiro comando. Só declare sucesso quando o deployment estiver `SUCCESS`. Registre o deployment ID e o Git SHA como last-known-good.

## 5. Smoke pós-deploy

Defina localmente, sem gravar no repositório:

- `CLARA_SMOKE_ORIGIN`
- `CLARA_PILOT_USERNAME`
- `CLARA_PILOT_PASSWORD`

Execute:

```bash
.venv/bin/python scripts/smoke_pilot.py
```

O smoke confirma liveness, readiness, autenticação, sessão, CSRF e o cálculo `gross=100`, `tax=1`, `net=99`. Ele não chama a OpenAI e não consome créditos.

Depois, faça um teste manual com uma saudação, uma pergunta fiscal sintética e o XML demonstrativo. Confirme que a pergunta fiscal aparece como rascunho revisável e que o XML permanece em `triagem_pendente`.

## 6. Monitoramento inicial

Nos primeiros 10 minutos, acompanhe logs JSON e procure:

- `status` 500 ou 503
- `audit_write_failed`
- crescimento de 401, 403 ou 429
- `source_registry_stale` no readiness

Os logs não devem conter pergunta, resposta, XML, senha, token, chave ou identificador em claro.

## 7. Rollback

`railway redeploy` recria o deployment mais recente e não é rollback.

Para reverter, reative o deployment anterior no dashboard ou promova novamente o Git SHA last-known-good. Repita o smoke completo antes de liberar a URL.

## 8. Critérios de parada

Encerre o piloto imediatamente se ocorrer qualquer um destes eventos:

- entrada de dado real
- resposta fiscal sem fonte oficial ao vivo e sem abstenção
- resposta material sem aviso de revisão obrigatória
- XML apresentado como válido, aprovado, consistente ou autorizado
- vazamento de contexto entre sessões
- exposição de credencial, token ou conteúdo em log

Basic Auth é temporário e adequado apenas para uma contadora. Antes de múltiplos usuários ou clientes reais, migre para IdP, autorização tenant-aware, armazenamento durável e processo formal de LGPD.
