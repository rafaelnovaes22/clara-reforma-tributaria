# Aviso de privacidade do piloto Clara

## Escopo permitido

Use somente dados sintéticos. Não informe CNPJ real, nome de cliente, XML real, senha, certificado, token, chave de API ou qualquer dado pessoal, fiscal ou empresarial verdadeiro.

Se um dado real for enviado por engano, interrompa o teste e avise imediatamente o responsável pelo piloto para encerrar a sessão e avaliar a exclusão dos registros operacionais no provedor de hospedagem.

## Processamento pela OpenAI

Perguntas fiscais materiais podem ser enviadas à OpenAI junto com fatos cadastrais sintéticos e até oito turnos recentes. A integração usa `store: false`. Segundo a política padrão da API, o conteúdo não é usado para treinar modelos e logs de monitoramento de abuso podem ser retidos por até 30 dias.

O XML bruto nunca é enviado à OpenAI.

## Memória e auditoria

A memória fica somente no processo do servidor, limitada a 200 sessões e seis pares de mensagens por sessão. Sessões expiram após duas horas de inatividade e são perdidas em reinício ou deploy.

A auditoria registra metadados técnicos, categoria de bloqueio, versões, risco, fontes e identificadores protegidos por HMAC. Não registra pergunta, resposta, XML, credencial ou token. No piloto hospedado, os eventos seguem para stdout e ficam sujeitos à retenção configurada no provedor de hospedagem.

## Decisão profissional

Toda conclusão fiscal é um rascunho. A contadora deve revisar fonte, vigência, contexto e aplicação antes de usar a informação. A triagem XML não valida schema, assinatura, cálculo, autorização ou conformidade.

O aceite na interface confirma ciência destas condições para a sessão atual.
