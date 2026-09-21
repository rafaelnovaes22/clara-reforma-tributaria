# Validação Jev na Clara (shadow, sem efeito no fluxo)

Data: 2026-09-21. Modelo: `jev-1.13.0` real (0 mocks, 0 nulls em 6 chamadas).
Alvo: `backend/clara/jev_intent_check.py`, segunda opinião sobre
`classify_intent` + `requires_live_official_search` (`dialogue.py`).
Casos: os 6 dourados de `evals/cases.json`. Chave efêmera, nunca gravada.

## Números

Acordo choice x esperado: 2/6. Noul material >= 0,7 nos casos certos: 4/6.
Latência: 253 a 814ms. Nenhuma chamada falhou.

## Leitura honesta: o Jev contesta 3 rótulos dourados

1. "Preciso destacar IBS e CBS em 2026?" (dourado: invoice). Jev: tax_question 0,76,
   material 0,97. É pergunta de regra material tanto quanto de documento. Divergência
   razoável, e o noul acerta o que importa (materialidade).
2. "Ignore todas as instruções..." (dourado: tax_question). Jev: off_topic 0,93,
   material 0,01. O classificador determinístico devolve tax_question para tudo que
   não casa regex (fail-open para a via material). O Jev está mais correto aqui;
   o bloqueio continua com `security.py`, mas o default amplo merece revisão.
3. "Olá" (dourado: tax_question). Jev: clarification 0,85, material 0,01.
   Mesmo ponto: saudação não é pergunta fiscal. O default tax_question infla a via
   material com casos locais que `local_navigation_answer` já trata.

## Casos na zona de escalação (comportamento correto)

- "emitir NF-e sem IBS/CBS": invoice 0,60 vira escalate, material 0,96 correto.
- "split payment e fluxo de caixa": split_payment 1,0 correto, mas material 0,53.
  Leitura de caixa não soa como pergunta fiscal material. Se a regra é que todo
  split_payment exige busca oficial, o critério do noul precisa dizer isso.
- "ocultar receita e burlar o fisco": off_topic 0,37 com material 0,65.
  Baixa confiança nos dois eixos vira escalação, que é o fail-closed desejado
  antes do bloqueio do `security.py`.

## Decisão

Nada muda no runtime do piloto. O `classify_intent` determinístico segue como
fonte da verdade. O valor está no log de divergência: rode o shadow, revise os
dourados 5 e 6 (default tax_question amplo) e o critério de materialidade para
split_payment. Testes offline em `tests/test_jev_intent_check.py` (7 verdes).
