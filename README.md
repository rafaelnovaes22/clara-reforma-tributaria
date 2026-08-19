# Clara — Copiloto da Reforma Tributária

Demo local e portátil de um copiloto para profissionais contábeis. A Clara responde dúvidas sobre a Reforma Tributária do Consumo, mantém contexto por cliente, faz uma pré-análise demonstrativa de XML de NF-e e simula split payment.

## Requisitos

- Python 3.10 ou superior
- Acesso à internet apenas para instalar dependências e, opcionalmente, usar a OpenAI API

## Instalação

Crie um ambiente virtual e instale a dependência do grafo:

```bash
python -m venv .venv
```

No Windows:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

No macOS ou Linux:

```bash
. .venv/bin/activate
python -m pip install -r requirements.txt
```

## Executar

Windows:

```text
INICIAR_DEMO.bat
```

macOS ou Linux:

```bash
./scripts/iniciar-demo.sh
```

Ou diretamente:

```bash
python backend/server.py
```

Depois, abra [http://127.0.0.1:8765](http://127.0.0.1:8765). Use `Ctrl+C` no terminal para encerrar.

A demo funciona sem chave, em modo determinístico. Para habilitar respostas da OpenAI, defina `OPENAI_API_KEY` no ambiente antes de iniciar. O modelo pode ser selecionado por `OPENAI_MODEL`.

Por padrão, a trilha operacional local é gravada em `data/audit.jsonl` e permanece fora do Git. Use `CLARA_AUDIT_PATH` para escolher outro destino ou `CLARA_DISABLE_AUDIT=1` para desativá-la.

## Executar as avaliações

Windows:

```text
EXECUTAR_EVALS.bat
```

macOS ou Linux:

```bash
./scripts/executar-evals.sh
```

Os resultados são gravados localmente em `evals/latest_results.json` e `evals/latest_conversation_results.json`; esses arquivos são gerados e não são versionados.

Os arquivos `baseline_results.json` e `baseline_conversation_results.json` registram a execução aprovada que acompanhou o commit inicial.

## Estrutura

- `backend/server.py`: servidor HTTP, grafo de agentes, memória, fontes, controles e integrações opcionais.
- `frontend/`: interface web estática servida pelo backend.
- `data/prompt_registry.json`: registro das versões de prompts.
- `data/risk_register.json`: registro demonstrativo de riscos e controles.
- `evals/`: casos e suítes determinísticas de avaliação.
- `SOUL.md`: princípios de comportamento e comunicação da Clara.

## Escopo e limites

- O projeto é uma demonstração; não substitui revisão profissional, schema oficial ou autorização fiscal.
- As referências normativas são um recorte com data de corte indicada no código e precisam de manutenção contínua em produção.
- A simulação de split payment é didática e não constitui apuração tributária definitiva.
- Não envie senhas, certificados digitais ou dados fiscais reais à demo.
