const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
let sessionId = localStorage.getItem('clara_session') || crypto.randomUUID();
localStorage.setItem('clara_session', sessionId);

const views = {
  chat: ['Copiloto tributário', 'Respostas fundamentadas, com memória e supervisão humana'],
  invoice: ['Análise de NF-e', 'Pré-validação demonstrativa do XML'],
  split: ['Split payment', 'Simulação do impacto no fluxo de caixa'],
  portfolio: ['Carteira de clientes', 'Priorização por impacto e prontidão'],
  governance: ['Governança da IA', 'ISO/IEC 42001, evals, guardrails e versões'],
};

function switchView(name) {
  $$('.view').forEach((el) => el.classList.remove('active'));
  $(`#view-${name}`).classList.add('active');
  $$('.nav-item').forEach((el) => el.classList.toggle('active', el.dataset.view === name));
  $('#viewTitle').textContent = views[name][0];
  $('#viewSubtitle').textContent = views[name][1];
  if (innerWidth < 720) scrollTo({ top: 0, behavior: 'smooth' });
}

function money(value) {
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value);
}

function escapeHtml(value) {
  const div = document.createElement('div');
  div.textContent = value;
  return div.innerHTML;
}

function formatAnswer(value) {
  return escapeHtml(value)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replaceAll('\n', '<br>');
}

function toast(message) {
  const el = $('#toast');
  el.textContent = message;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 2500);
}

async function api(path, body) {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || 'Não foi possível completar a operação.');
  return payload;
}

function userMessage(text) {
  const article = document.createElement('article');
  article.className = 'message user-message';
  article.innerHTML = `<div class="bubble"><p>${escapeHtml(text)}</p></div>`;
  $('#conversation').appendChild(article);
  article.scrollIntoView({ behavior: 'smooth', block: 'end' });
}

function thinkingMessage() {
  const article = document.createElement('article');
  article.className = 'message assistant thinking';
  article.innerHTML = '<div class="bot-avatar">C</div><div class="bubble"><div class="dots"><i></i><i></i><i></i></div></div>';
  $('#conversation').appendChild(article);
  article.scrollIntoView({ behavior: 'smooth', block: 'end' });
  return article;
}

function answerMessage(data, placeholder) {
  const sources = data.sources.map((source) =>
    `<a class="source-link" href="${source.url}" target="_blank" rel="noreferrer"><span>${source.id}</span><strong>${escapeHtml(source.title)}</strong><b>↗</b></a>`
  ).join('');
  const review = data.needs_human_review ? '<span class="review">◉ Revisão humana recomendada</span>' : '<span>✓ Baixo risco</span>';
  const engine = data.generation_mode === 'openai' ? '<span>✦ OpenAI + busca oficial</span>' : '<span>◌ Modo contingência</span>';
  const sourceBlock = data.sources.length ? `<div class="sources"><span>EVIDÊNCIAS CONSULTADAS</span>${sources}</div>` : '';
  placeholder.className = 'message assistant';
  placeholder.innerHTML = `
    <div class="bot-avatar">C</div>
    <div class="bubble">
      <p>${formatAnswer(data.answer)}</p>
      <div class="answer-meta">${engine}<span>✓ ${Math.round(data.evals.overall * 100)}% eval</span><span>✓ ${data.sources.length} fontes</span>${review}</div>
      ${sourceBlock}
    </div>`;
  placeholder.scrollIntoView({ behavior: 'smooth', block: 'end' });
}

function resetFlow() {
  $$('.agent').forEach((el) => el.classList.remove('active', 'done'));
  $('#runStatus').textContent = 'Processando pergunta';
  $('#evalScore').textContent = '—';
}

async function animateTrace(trace) {
  for (const step of trace) {
    const node = $(`.agent[data-agent="${step.agent}"]`);
    if (!node) continue;
    node.classList.add('active');
    $('#runStatus').textContent = step.detail;
    await new Promise((resolve) => setTimeout(resolve, 270));
    node.classList.remove('active');
    node.classList.add('done');
  }
}

async function sendQuestion(forcedText) {
  const input = $('#question');
  const text = (forcedText || input.value).trim();
  if (!text) return;
  switchView('chat');
  input.value = '';
  input.style.height = 'auto';
  userMessage(text);
  const placeholder = thinkingMessage();
  const button = $('#sendButton');
  button.disabled = true;
  resetFlow();
  try {
    const data = await api('/api/chat', {
      message: text,
      session_id: sessionId,
      client_id: 'mercearia-bom-preco',
    });
    await animateTrace(data.trace);
    answerMessage(data, placeholder);
    $('#evalScore').textContent = `${Math.round(data.evals.overall * 100)}%`;
    $('#sourceCount').textContent = data.sources.length;
    $('#reviewText').textContent = data.needs_human_review ? `Requer revisão · risco ${data.risk}` : 'Aprovada automaticamente';
    $('#runStatus').textContent = `Execução ${data.evals.passed ? 'aprovada' : 'em revisão'}`;
  } catch (error) {
    placeholder.querySelector('.bubble').innerHTML = `<p>Não consegui concluir: ${escapeHtml(error.message)}</p>`;
    toast(error.message);
  } finally {
    button.disabled = false;
    input.focus();
  }
}

function renderXml(result) {
  const findings = result.findings.map((finding) => `
    <div class="finding ${finding.severity}"><i></i><div><strong>${escapeHtml(finding.title)}</strong><span>${escapeHtml(finding.detail)}</span></div><em>${finding.severity.toUpperCase()}</em></div>`).join('');
  const el = $('#xmlResult');
  el.innerHTML = `<div class="score-line"><div><span class="kicker">RESULTADO · ${escapeHtml(result.filename)}</span><h3>${result.status === 'revisar' ? 'Revisão recomendada antes do envio' : 'Estrutura básica consistente'}</h3></div><div class="score-ring" style="--score:${result.score}"><strong>${result.score}</strong></div></div>${findings}<p class="source-link"><span>RFB2026</span><strong>${escapeHtml(result.note)}</strong></p>`;
  el.classList.remove('hidden');
  el.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

async function analyzeFile(file) {
  try {
    const result = await api('/api/analyze-xml', { filename: file.name, content: await file.text(), session_id: sessionId, client_id: 'mercearia-bom-preco' });
    renderXml(result);
  } catch (error) { toast(error.message); }
}

const sampleXml = `<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe"><NFe><infNFe Id="NFeDemo"><emit><CNPJ>12345678000190</CNPJ><xNome>Mercearia Bom Preço</xNome></emit><det nItem="1"><prod><cProd>001</cProd><xProd>Café 500g</xProd><vProd>1250.00</vProd></prod></det><total><ICMSTot><vProd>1250.00</vProd><vNF>1250.00</vNF></ICMSTot></total></infNFe></NFe></nfeProc>`;

$$('.nav-item').forEach((button) => button.addEventListener('click', () => switchView(button.dataset.view)));
$$('[data-view-target]').forEach((button) => button.addEventListener('click', () => switchView(button.dataset.viewTarget)));
$$('[data-question]').forEach((button) => button.addEventListener('click', () => sendQuestion(button.dataset.question)));
$('#showGov').addEventListener('click', () => switchView('governance'));
$('#sendButton').addEventListener('click', () => sendQuestion());
$('#question').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendQuestion(); }
});
$('#question').addEventListener('input', (event) => {
  event.target.style.height = 'auto';
  event.target.style.height = `${Math.min(event.target.scrollHeight, 100)}px`;
});
$('#newChat').addEventListener('click', () => {
  sessionId = crypto.randomUUID();
  localStorage.setItem('clara_session', sessionId);
  $$('.message:not(.welcome)').forEach((el) => el.remove());
  resetFlow();
  $('#runStatus').textContent = 'Nova conversa iniciada';
  toast('Nova conversa com memória limpa');
  switchView('chat');
});
$('#xmlFile').addEventListener('change', (event) => event.target.files[0] && analyzeFile(event.target.files[0]));
$('#sampleXml').addEventListener('click', () => analyzeFile(new File([sampleXml], 'nfe_mercearia_demo.xml', { type: 'text/xml' })));
['dragenter', 'dragover'].forEach((name) => $('#dropZone').addEventListener(name, (event) => { event.preventDefault(); $('#dropZone').classList.add('drag'); }));
['dragleave', 'drop'].forEach((name) => $('#dropZone').addEventListener(name, (event) => { event.preventDefault(); $('#dropZone').classList.remove('drag'); }));
$('#dropZone').addEventListener('drop', (event) => event.dataTransfer.files[0] && analyzeFile(event.dataTransfer.files[0]));
$('#splitForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    const result = await api('/api/split', { gross: +$('#gross').value, ibs_rate: +$('#ibsRate').value, cbs_rate: +$('#cbsRate').value });
    $('#splitResult').innerHTML = `<span>RESULTADO DA SIMULAÇÃO</span><h3>A empresa recebe o valor líquido</h3><div class="cash-flow"><div class="cash-row"><span>Venda bruta</span><strong>${money(result.gross)}</strong></div><div class="cash-row tax"><span>IBS segregado (${result.rates.ibs}%)</span><strong>− ${money(result.ibs)}</strong></div><div class="cash-row tax"><span>CBS segregada (${result.rates.cbs}%)</span><strong>− ${money(result.cbs)}</strong></div><div class="cash-row net"><span>Recebimento líquido</span><strong>${money(result.net)}</strong></div></div><p>${escapeHtml(result.note)}</p>`;
  } catch (error) { toast(error.message); }
});

async function refreshHealth() {
  try {
    const health = await fetch('/api/health').then((res) => res.json());
    const mode = $('#engineMode');
    const connect = $('#connectOpenAI');
    mode.classList.add('ready');
    mode.innerHTML = `<i></i> ${health.langgraph ? 'LangGraph ativo' : 'Fluxo demo'} · ${health.openai ? health.model : 'respostas locais'}`;
    connect.textContent = health.openai ? 'OpenAI conectada' : 'Conectar OpenAI';
    connect.classList.toggle('connected', health.openai);
    $('#disconnectOpenAI').classList.toggle('hidden', !health.openai);
    $('#sourceCount').textContent = health.sources;
    $('#soulVersion').textContent = health.soul;
    $('#promptOrchestrator').textContent = health.prompts.orchestrator;
    $('#promptSpecialist').textContent = health.prompts.tax_specialist;
    $('#promptReviewer').textContent = health.prompts.reviewer;
    $('#policyVersion').textContent = health.policy;
    $('#suiteStatus').textContent = health.evals;
    return health;
  } catch {
    $('#engineMode').innerHTML = '<i></i> Backend desconectado';
    return null;
  }
}

function openOpenAIModal() {
  $('#openaiStatus').classList.add('hidden');
  $('#openaiModal').classList.remove('hidden');
  setTimeout(() => $('#openaiKey').focus(), 50);
}

$('#connectOpenAI').addEventListener('click', openOpenAIModal);
$('#closeOpenAI').addEventListener('click', () => $('#openaiModal').classList.add('hidden'));
$('#openaiModal').addEventListener('click', (event) => {
  if (event.target === $('#openaiModal')) $('#openaiModal').classList.add('hidden');
});
$('#saveOpenAI').addEventListener('click', async () => {
  const button = $('#saveOpenAI');
  const status = $('#openaiStatus');
  button.disabled = true;
  button.textContent = 'Validando conexão…';
  status.classList.remove('hidden', 'error');
  status.textContent = 'A OpenAI está validando a chave e o modelo.';
  try {
    const result = await api('/api/openai/configure', { api_key: $('#openaiKey').value, model: $('#openaiModel').value });
    $('#openaiKey').value = '';
    status.textContent = result.message;
    await refreshHealth();
    toast('OpenAI conectada com sucesso');
  } catch (error) {
    status.classList.add('error');
    status.textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = 'Validar e conectar';
  }
});
$('#disconnectOpenAI').addEventListener('click', async () => {
  const result = await api('/api/openai/configure', { disconnect: true, model: $('#openaiModel').value });
  $('#openaiStatus').classList.remove('hidden', 'error');
  $('#openaiStatus').textContent = result.message;
  await refreshHealth();
});

refreshHealth();
