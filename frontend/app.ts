function requirePilotConsent(): boolean {
  const accepted = selectElement<HTMLInputElement>("#pilotConsent").checked;
  if (!accepted)
    showToast(
      "Confirme o uso exclusivo de dados sintéticos antes de continuar.",
    );
  return accepted;
}

function addUserMessage(text: string): void {
  const article = document.createElement("article");
  article.className = "message user-message";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  bubble.appendChild(paragraph);
  article.appendChild(bubble);
  selectElement<HTMLElement>("#conversation").appendChild(article);
  article.scrollIntoView({ behavior: "smooth", block: "end" });
}

function addThinkingMessage(): HTMLElement {
  const article = document.createElement("article");
  article.className = "message assistant thinking";
  article.innerHTML =
    '<div class="bot-avatar">C</div><div class="bubble"><div class="dots"><i></i><i></i><i></i></div></div>';
  selectElement<HTMLElement>("#conversation").appendChild(article);
  article.scrollIntoView({ behavior: "smooth", block: "end" });
  return article;
}

function officialSourceUrl(rawUrl: string): string | null {
  try {
    const url = new URL(rawUrl);
    const trusted = OFFICIAL_DOMAINS.some(
      (domain) =>
        url.hostname === domain || url.hostname.endsWith(`.${domain}`),
    );
    return url.protocol === "https:" && trusted ? url.href : null;
  } catch {
    return null;
  }
}

function buildSourceLink(source: OfficialSource): HTMLAnchorElement | null {
  const trustedUrl = officialSourceUrl(source.url);
  if (!trustedUrl) return null;
  const anchor = document.createElement("a");
  anchor.className = "source-link";
  anchor.href = trustedUrl;
  anchor.target = "_blank";
  anchor.rel = "noreferrer";
  const badge = document.createElement("span");
  badge.textContent = source.live ? "AO VIVO" : source.id;
  const title = document.createElement("strong");
  title.textContent = source.title;
  const arrow = document.createElement("b");
  arrow.textContent = "↗";
  anchor.append(badge, title, arrow);
  return anchor;
}

function renderAnswer(result: ChatResult, placeholder: HTMLElement): void {
  placeholder.className = "message assistant";
  placeholder.replaceChildren();
  const avatar = document.createElement("div");
  avatar.className = "bot-avatar";
  avatar.textContent = "C";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  const paragraph = document.createElement("p");
  paragraph.innerHTML = formatAnswer(result.answer);
  bubble.append(paragraph, buildAnswerMetadata(result));
  const sourceBlock = buildSourceBlock(result.sources);
  if (sourceBlock) bubble.appendChild(sourceBlock);
  placeholder.append(avatar, bubble);
  placeholder.scrollIntoView({ behavior: "smooth", block: "end" });
}

function buildAnswerMetadata(result: ChatResult): HTMLDivElement {
  const metadata = document.createElement("div");
  metadata.className = "answer-meta";
  const mode = document.createElement("span");
  mode.textContent =
    result.generation_mode === "openai_live"
      ? "✦ Busca oficial ao vivo"
      : "◌ Modo seguro";
  const gates = document.createElement("span");
  gates.textContent = result.evals.passed
    ? "✓ Hard gates aprovados"
    : "◉ Gate pendente";
  const review = document.createElement("span");
  review.className = result.needs_human_review ? "review" : "";
  review.textContent = result.needs_human_review
    ? "◉ Revisão obrigatória"
    : "✓ Sem conclusão fiscal";
  metadata.append(mode, gates, review);
  return metadata;
}

function buildSourceBlock(sources: OfficialSource[]): HTMLDivElement | null {
  const links = sources
    .map(buildSourceLink)
    .filter((link): link is HTMLAnchorElement => link !== null);
  if (!links.length) return null;
  const block = document.createElement("div");
  block.className = "sources";
  const label = document.createElement("span");
  label.textContent = "FONTES OFICIAIS CONSULTADAS";
  block.append(label, ...links);
  return block;
}

function resetAgentFlow(): void {
  selectElements<HTMLElement>(".agent").forEach((element) =>
    element.classList.remove("active", "done"),
  );
  selectElement<HTMLElement>("#runStatus").textContent = "Processando pergunta";
  selectElement<HTMLElement>("#evalScore").textContent = "Pendente";
}

async function animateTrace(trace: TraceStep[]): Promise<void> {
  for (const step of trace) {
    const node = document.querySelector<HTMLElement>(
      `.agent[data-agent="${CSS.escape(step.agent)}"]`,
    );
    if (!node) continue;
    node.classList.add("active");
    selectElement<HTMLElement>("#runStatus").textContent = step.detail;
    await new Promise<void>((resolve) => setTimeout(resolve, 220));
    node.classList.remove("active");
    node.classList.add("done");
  }
}

async function sendQuestion(forcedText?: string): Promise<void> {
  if (!requirePilotConsent()) return;
  const input = selectElement<HTMLTextAreaElement>("#question");
  const text = (forcedText || input.value).trim();
  if (!text) return;
  switchView("chat");
  input.value = "";
  addUserMessage(text);
  const placeholder = addThinkingMessage();
  const button = selectElement<HTMLButtonElement>("#sendButton");
  button.disabled = true;
  resetAgentFlow();
  await executeQuestion(text, placeholder, button, input);
}

async function executeQuestion(
  text: string,
  placeholder: HTMLElement,
  button: HTMLButtonElement,
  input: HTMLTextAreaElement,
): Promise<void> {
  try {
    const result = await postApi<ChatResult>("/api/chat", { message: text });
    await animateTrace(result.trace);
    renderAnswer(result, placeholder);
    updateRunSummary(result);
  } catch (error) {
    selectElement<HTMLElement>(".bubble", placeholder).textContent =
      `Não consegui concluir: ${errorMessage(error)}`;
    showToast(errorMessage(error));
  } finally {
    button.disabled = false;
    input.focus();
  }
}

function updateRunSummary(result: ChatResult): void {
  selectElement<HTMLElement>("#evalScore").textContent = result.evals.passed
    ? "Aprovados"
    : "Revisão";
  selectElement<HTMLElement>("#sourceCount").textContent = String(
    result.sources.length,
  );
  selectElement<HTMLElement>("#reviewText").textContent =
    result.needs_human_review
      ? `Revisão obrigatória, risco ${result.risk}`
      : "Sem conclusão fiscal neste turno";
  selectElement<HTMLElement>("#runStatus").textContent = result.evals.passed
    ? "Hard gates aprovados"
    : "Revisão necessária";
}

function renderXmlTriage(result: XmlTriageResult): void {
  const resultCard = selectElement<HTMLElement>("#xmlResult");
  resultCard.replaceChildren();
  const heading = document.createElement("div");
  heading.className = "score-line";
  heading.innerHTML = `<div><span class="kicker">TRIAGEM PENDENTE · ${escapeHtml(result.filename)}</span><h3>Revisão e validação oficial obrigatórias</h3></div>`;
  resultCard.appendChild(heading);
  for (const item of result.findings)
    resultCard.appendChild(buildFinding(item));
  const note = document.createElement("p");
  note.className = "source-link";
  note.textContent = result.note;
  resultCard.appendChild(note);
  resultCard.classList.remove("hidden");
  resultCard.scrollIntoView({ behavior: "smooth", block: "center" });
}

function buildFinding(item: XmlFinding): HTMLDivElement {
  const row = document.createElement("div");
  row.classList.add("finding", item.severity);
  const marker = document.createElement("i");
  const content = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = item.title;
  const detail = document.createElement("span");
  detail.textContent = item.detail;
  const severity = document.createElement("em");
  severity.textContent = item.severity.toUpperCase();
  content.append(title, detail);
  row.append(marker, content, severity);
  return row;
}

async function analyzeFile(file: File): Promise<void> {
  if (!requirePilotConsent()) return;
  if (file.size > 524_288) {
    showToast("O XML excede o limite de 512 KiB do piloto.");
    return;
  }
  try {
    const result = await postApi<XmlTriageResult>("/api/analyze-xml", {
      filename: file.name,
      content: await file.text(),
      synthetic: true,
    });
    renderXmlTriage(result);
  } catch (error) {
    showToast(errorMessage(error));
  }
}

const sampleXml = `<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe"><NFe><infNFe Id="NFe12345678901234567890123456789012345678901234"><emit><CNPJ>12345678000195</CNPJ><xNome>Empresa Sintética</xNome></emit><det nItem="1"><prod><cProd>001</cProd><xProd>Produto sintético</xProd><NCM>09012100</NCM><vProd>1250.00</vProd></prod><IBSCBS><vIBS>1.25</vIBS><vCBS>11.25</vCBS></IBSCBS></det><total><ICMSTot><vProd>1250.00</vProd><vNF>1250.00</vNF></ICMSTot></total></infNFe></NFe></nfeProc>`;

async function resetSession(): Promise<void> {
  try {
    const result = await postApi<PilotSessionResult>("/api/session/reset", {});
    csrfToken = result.csrf_token;
    selectElements<HTMLElement>(".message:not(.welcome)").forEach((element) =>
      element.remove(),
    );
    resetAgentFlow();
    selectElement<HTMLElement>("#runStatus").textContent =
      "Nova sessão iniciada";
    showToast("Nova sessão com memória limpa");
    switchView("chat");
  } catch (error) {
    showToast(errorMessage(error));
  }
}

function bindNavigationEvents(): void {
  bindWorkspaceNavigation();
  bindViewTargets();
  bindQuestionShortcuts();
  selectElement<HTMLButtonElement>("#showGov").addEventListener("click", () =>
    switchView("governance"),
  );
}

function bindWorkspaceNavigation(): void {
  selectElements<HTMLButtonElement>(".nav-item").forEach((button) => {
    button.addEventListener("click", () =>
      switchView(button.dataset.view as ViewName),
    );
  });
}

function bindViewTargets(): void {
  selectElements<HTMLButtonElement>("[data-view-target]").forEach((button) => {
    button.addEventListener("click", () =>
      switchView(button.dataset.viewTarget as ViewName),
    );
  });
}

function bindQuestionShortcuts(): void {
  selectElements<HTMLButtonElement>("[data-question]").forEach((button) => {
    button.addEventListener(
      "click",
      () => void sendQuestion(button.dataset.question),
    );
  });
}

function bindChatEvents(): void {
  selectElement<HTMLButtonElement>("#sendButton").addEventListener(
    "click",
    () => void sendQuestion(),
  );
  selectElement<HTMLTextAreaElement>("#question").addEventListener(
    "keydown",
    (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        void sendQuestion();
      }
    },
  );
  selectElement<HTMLButtonElement>("#newChat").addEventListener(
    "click",
    () => void resetSession(),
  );
}

function bindXmlEvents(): void {
  const fileInput = selectElement<HTMLInputElement>("#xmlFile");
  const dropZone = selectElement<HTMLElement>("#dropZone");
  fileInput.addEventListener(
    "change",
    () => fileInput.files?.[0] && void analyzeFile(fileInput.files[0]),
  );
  selectElement<HTMLButtonElement>("#sampleXml").addEventListener(
    "click",
    () => {
      void analyzeFile(
        new File([sampleXml], "nfe_sintetica_demo.xml", { type: "text/xml" }),
      );
    },
  );
  bindDropZoneEvents(dropZone);
}

function bindDropZoneEvents(dropZone: HTMLElement): void {
  ["dragenter", "dragover"].forEach((name) =>
    dropZone.addEventListener(name, (event) => {
      event.preventDefault();
      dropZone.classList.add("drag");
    }),
  );
  ["dragleave", "drop"].forEach((name) =>
    dropZone.addEventListener(name, (event) => {
      event.preventDefault();
      dropZone.classList.remove("drag");
    }),
  );
  dropZone.addEventListener("drop", (event) => {
    const file = (event as DragEvent).dataTransfer?.files[0];
    if (file) void analyzeFile(file);
  });
}

function bindSplitEvent(): void {
  selectElement<HTMLFormElement>("#splitForm").addEventListener(
    "submit",
    async (event) => {
      event.preventDefault();
      if (!requirePilotConsent()) return;
      try {
        const result = await postApi<SplitResult>("/api/split", {
          gross: Number(selectElement<HTMLInputElement>("#gross").value),
          ibs_rate: Number(selectElement<HTMLInputElement>("#ibsRate").value),
          cbs_rate: Number(selectElement<HTMLInputElement>("#cbsRate").value),
        });
        selectElement<HTMLElement>("#splitResult").innerHTML =
          buildSplitMarkup(result);
      } catch (error) {
        showToast(errorMessage(error));
      }
    },
  );
}

function buildSplitMarkup(result: SplitResult): string {
  return `<span>RESULTADO MATEMÁTICO</span><h3>Valores calculados com as taxas informadas</h3><div class="cash-flow"><div class="cash-row"><span>Venda bruta</span><strong>${formatMoney(result.gross)}</strong></div><div class="cash-row tax"><span>IBS informado (${result.rates.ibs}%)</span><strong>${formatMoney(result.ibs)}</strong></div><div class="cash-row tax"><span>CBS informada (${result.rates.cbs}%)</span><strong>${formatMoney(result.cbs)}</strong></div><div class="cash-row net"><span>Diferença matemática</span><strong>${formatMoney(result.net)}</strong></div></div><p>${escapeHtml(result.note)}</p>`;
}

async function initializeApplication(): Promise<void> {
  const session = await getApi<PilotSessionResult>("/api/session");
  csrfToken = session.csrf_token;
  const demonstration = await getApi<DemoResult>("/api/demo-data");
  renderRuntimeStatus(demonstration);
}

function renderRuntimeStatus(demonstration: DemoResult): void {
  selectElement<HTMLElement>("#engineMode").classList.add("ready");
  selectElement<HTMLElement>("#engineMode").innerHTML =
    "<i></i> Piloto privado · fonte oficial ao vivo";
  selectElement<HTMLElement>("#sourceCount").textContent = String(
    demonstration.sources.length,
  );
  selectElement<HTMLElement>("#soulVersion").textContent =
    demonstration.governance.soul;
  selectElement<HTMLElement>("#promptOrchestrator").textContent =
    demonstration.governance.prompts.orchestrator;
  selectElement<HTMLElement>("#promptSpecialist").textContent =
    demonstration.governance.prompts.tax_specialist;
  selectElement<HTMLElement>("#promptReviewer").textContent =
    demonstration.governance.prompts.reviewer;
  selectElement<HTMLElement>("#policyVersion").textContent =
    demonstration.governance.policy;
  selectElement<HTMLElement>("#suiteStatus").textContent =
    demonstration.governance.evals;
}

bindNavigationEvents();
bindChatEvents();
bindXmlEvents();
bindSplitEvent();
const initializationPromise = initializeApplication().catch(
  (error: unknown) => {
    selectElement<HTMLElement>("#engineMode").innerHTML =
      "<i></i> Backend indisponível";
    showToast(errorMessage(error));
    throw error;
  },
);
