"use strict";
const VIEW_LABELS = {
    chat: [
        "Copiloto tributário",
        "Fontes oficiais ao vivo, abstenção segura e revisão humana",
    ],
    invoice: ["Triagem de NF-e", "Inspeção estrutural limitada de XML sintético"],
    split: [
        "Split payment",
        "Cálculo matemático com taxas informadas pelo usuário",
    ],
    portfolio: [
        "Carteira sintética",
        "Priorização demonstrativa sem dados reais",
    ],
    governance: ["Governança da IA", "Hard gates, guardrails e versões"],
};
const OFFICIAL_DOMAINS = ["gov.br", "planalto.gov.br", "cgibs.gov.br"];
let csrfToken = "";
function selectElement(selector, root = document) {
    const element = root.querySelector(selector);
    if (!element)
        throw new Error(`Elemento obrigatório não encontrado: ${selector}.`);
    return element;
}
function selectElements(selector, root = document) {
    return Array.from(root.querySelectorAll(selector));
}
function switchView(viewName) {
    selectElements(".view").forEach((element) => element.classList.remove("active"));
    selectElement(`#view-${viewName}`).classList.add("active");
    selectElements(".nav-item").forEach((element) => {
        element.classList.toggle("active", element.dataset.view === viewName);
    });
    selectElement("#viewTitle").textContent =
        VIEW_LABELS[viewName][0];
    selectElement("#viewSubtitle").textContent =
        VIEW_LABELS[viewName][1];
    if (innerWidth < 720)
        scrollTo({ top: 0, behavior: "smooth" });
}
function formatMoney(value) {
    return new Intl.NumberFormat("pt-BR", {
        style: "currency",
        currency: "BRL",
    }).format(value);
}
function escapeHtml(value) {
    const container = document.createElement("div");
    container.textContent = value;
    return container.innerHTML;
}
function formatAnswer(value) {
    return escapeHtml(value)
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replaceAll("\n", "<br>");
}
function showToast(message) {
    const toast = selectElement("#toast");
    toast.textContent = message;
    toast.classList.add("show");
    setTimeout(() => toast.classList.remove("show"), 2500);
}
function errorMessage(error) {
    return error instanceof Error
        ? error.message
        : "Não foi possível completar a operação.";
}
async function readJson(response) {
    const payload = (await response.json());
    if (!response.ok)
        throw new Error(payload.error || "Não foi possível completar a operação.");
    return payload;
}
async function getApi(path) {
    return readJson(await fetch(path, { credentials: "same-origin" }));
}
async function postApi(path, body) {
    await initializationPromise;
    const response = await fetch(path, {
        method: "POST",
        credentials: "same-origin",
        headers: {
            "Content-Type": "application/json",
            "X-Clara-Request": "1",
            "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify(body),
    });
    return readJson(response);
}
function requirePilotConsent() {
    const accepted = selectElement("#pilotConsent").checked;
    if (!accepted)
        showToast("Confirme o uso exclusivo de dados sintéticos antes de continuar.");
    return accepted;
}
function addUserMessage(text) {
    const article = document.createElement("article");
    article.className = "message user-message";
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    const paragraph = document.createElement("p");
    paragraph.textContent = text;
    bubble.appendChild(paragraph);
    article.appendChild(bubble);
    selectElement("#conversation").appendChild(article);
    article.scrollIntoView({ behavior: "smooth", block: "end" });
}
function addThinkingMessage() {
    const article = document.createElement("article");
    article.className = "message assistant thinking";
    article.innerHTML =
        '<div class="bot-avatar">C</div><div class="bubble"><div class="dots"><i></i><i></i><i></i></div></div>';
    selectElement("#conversation").appendChild(article);
    article.scrollIntoView({ behavior: "smooth", block: "end" });
    return article;
}
function officialSourceUrl(rawUrl) {
    try {
        const url = new URL(rawUrl);
        const trusted = OFFICIAL_DOMAINS.some((domain) => url.hostname === domain || url.hostname.endsWith(`.${domain}`));
        return url.protocol === "https:" && trusted ? url.href : null;
    }
    catch {
        return null;
    }
}
function buildSourceLink(source) {
    const trustedUrl = officialSourceUrl(source.url);
    if (!trustedUrl)
        return null;
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
function renderAnswer(result, placeholder) {
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
    if (sourceBlock)
        bubble.appendChild(sourceBlock);
    placeholder.append(avatar, bubble);
    placeholder.scrollIntoView({ behavior: "smooth", block: "end" });
}
function buildAnswerMetadata(result) {
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
function buildSourceBlock(sources) {
    const links = sources
        .map(buildSourceLink)
        .filter((link) => link !== null);
    if (!links.length)
        return null;
    const block = document.createElement("div");
    block.className = "sources";
    const label = document.createElement("span");
    label.textContent = "FONTES OFICIAIS CONSULTADAS";
    block.append(label, ...links);
    return block;
}
function resetAgentFlow() {
    selectElements(".agent").forEach((element) => element.classList.remove("active", "done"));
    selectElement("#runStatus").textContent = "Processando pergunta";
    selectElement("#evalScore").textContent = "Pendente";
}
async function animateTrace(trace) {
    for (const step of trace) {
        const node = document.querySelector(`.agent[data-agent="${CSS.escape(step.agent)}"]`);
        if (!node)
            continue;
        node.classList.add("active");
        selectElement("#runStatus").textContent = step.detail;
        await new Promise((resolve) => setTimeout(resolve, 220));
        node.classList.remove("active");
        node.classList.add("done");
    }
}
async function sendQuestion(forcedText) {
    if (!requirePilotConsent())
        return;
    const input = selectElement("#question");
    const text = (forcedText || input.value).trim();
    if (!text)
        return;
    switchView("chat");
    input.value = "";
    addUserMessage(text);
    const placeholder = addThinkingMessage();
    const button = selectElement("#sendButton");
    button.disabled = true;
    resetAgentFlow();
    await executeQuestion(text, placeholder, button, input);
}
async function executeQuestion(text, placeholder, button, input) {
    try {
        const result = await postApi("/api/chat", { message: text });
        await animateTrace(result.trace);
        renderAnswer(result, placeholder);
        updateRunSummary(result);
    }
    catch (error) {
        selectElement(".bubble", placeholder).textContent =
            `Não consegui concluir: ${errorMessage(error)}`;
        showToast(errorMessage(error));
    }
    finally {
        button.disabled = false;
        input.focus();
    }
}
function updateRunSummary(result) {
    selectElement("#evalScore").textContent = result.evals.passed
        ? "Aprovados"
        : "Revisão";
    selectElement("#sourceCount").textContent = String(result.sources.length);
    selectElement("#reviewText").textContent =
        result.needs_human_review
            ? `Revisão obrigatória, risco ${result.risk}`
            : "Sem conclusão fiscal neste turno";
    selectElement("#runStatus").textContent = result.evals.passed
        ? "Hard gates aprovados"
        : "Revisão necessária";
}
function renderXmlTriage(result) {
    const resultCard = selectElement("#xmlResult");
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
function buildFinding(item) {
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
async function analyzeFile(file) {
    if (!requirePilotConsent())
        return;
    if (file.size > 524_288) {
        showToast("O XML excede o limite de 512 KiB do piloto.");
        return;
    }
    try {
        const result = await postApi("/api/analyze-xml", {
            filename: file.name,
            content: await file.text(),
            synthetic: true,
        });
        renderXmlTriage(result);
    }
    catch (error) {
        showToast(errorMessage(error));
    }
}
const sampleXml = `<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe"><NFe><infNFe Id="NFe12345678901234567890123456789012345678901234"><emit><CNPJ>12345678000195</CNPJ><xNome>Empresa Sintética</xNome></emit><det nItem="1"><prod><cProd>001</cProd><xProd>Produto sintético</xProd><NCM>09012100</NCM><vProd>1250.00</vProd></prod><IBSCBS><vIBS>1.25</vIBS><vCBS>11.25</vCBS></IBSCBS></det><total><ICMSTot><vProd>1250.00</vProd><vNF>1250.00</vNF></ICMSTot></total></infNFe></NFe></nfeProc>`;
async function resetSession() {
    try {
        const result = await postApi("/api/session/reset", {});
        csrfToken = result.csrf_token;
        selectElements(".message:not(.welcome)").forEach((element) => element.remove());
        resetAgentFlow();
        selectElement("#runStatus").textContent =
            "Nova sessão iniciada";
        showToast("Nova sessão com memória limpa");
        switchView("chat");
    }
    catch (error) {
        showToast(errorMessage(error));
    }
}
function bindNavigationEvents() {
    bindWorkspaceNavigation();
    bindViewTargets();
    bindQuestionShortcuts();
    selectElement("#showGov").addEventListener("click", () => switchView("governance"));
}
function bindWorkspaceNavigation() {
    selectElements(".nav-item").forEach((button) => {
        button.addEventListener("click", () => switchView(button.dataset.view));
    });
}
function bindViewTargets() {
    selectElements("[data-view-target]").forEach((button) => {
        button.addEventListener("click", () => switchView(button.dataset.viewTarget));
    });
}
function bindQuestionShortcuts() {
    selectElements("[data-question]").forEach((button) => {
        button.addEventListener("click", () => void sendQuestion(button.dataset.question));
    });
}
function bindChatEvents() {
    selectElement("#sendButton").addEventListener("click", () => void sendQuestion());
    selectElement("#question").addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            void sendQuestion();
        }
    });
    selectElement("#newChat").addEventListener("click", () => void resetSession());
}
function bindXmlEvents() {
    const fileInput = selectElement("#xmlFile");
    const dropZone = selectElement("#dropZone");
    fileInput.addEventListener("change", () => fileInput.files?.[0] && void analyzeFile(fileInput.files[0]));
    selectElement("#sampleXml").addEventListener("click", () => {
        void analyzeFile(new File([sampleXml], "nfe_sintetica_demo.xml", { type: "text/xml" }));
    });
    bindDropZoneEvents(dropZone);
}
function bindDropZoneEvents(dropZone) {
    ["dragenter", "dragover"].forEach((name) => dropZone.addEventListener(name, (event) => {
        event.preventDefault();
        dropZone.classList.add("drag");
    }));
    ["dragleave", "drop"].forEach((name) => dropZone.addEventListener(name, (event) => {
        event.preventDefault();
        dropZone.classList.remove("drag");
    }));
    dropZone.addEventListener("drop", (event) => {
        const file = event.dataTransfer?.files[0];
        if (file)
            void analyzeFile(file);
    });
}
function bindSplitEvent() {
    selectElement("#splitForm").addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!requirePilotConsent())
            return;
        try {
            const result = await postApi("/api/split", {
                gross: Number(selectElement("#gross").value),
                ibs_rate: Number(selectElement("#ibsRate").value),
                cbs_rate: Number(selectElement("#cbsRate").value),
            });
            selectElement("#splitResult").innerHTML =
                buildSplitMarkup(result);
        }
        catch (error) {
            showToast(errorMessage(error));
        }
    });
}
function buildSplitMarkup(result) {
    return `<span>RESULTADO MATEMÁTICO</span><h3>Valores calculados com as taxas informadas</h3><div class="cash-flow"><div class="cash-row"><span>Venda bruta</span><strong>${formatMoney(result.gross)}</strong></div><div class="cash-row tax"><span>IBS informado (${result.rates.ibs}%)</span><strong>${formatMoney(result.ibs)}</strong></div><div class="cash-row tax"><span>CBS informada (${result.rates.cbs}%)</span><strong>${formatMoney(result.cbs)}</strong></div><div class="cash-row net"><span>Diferença matemática</span><strong>${formatMoney(result.net)}</strong></div></div><p>${escapeHtml(result.note)}</p>`;
}
async function initializeApplication() {
    const session = await getApi("/api/session");
    csrfToken = session.csrf_token;
    const demonstration = await getApi("/api/demo-data");
    renderRuntimeStatus(demonstration);
}
function renderRuntimeStatus(demonstration) {
    selectElement("#engineMode").classList.add("ready");
    selectElement("#engineMode").innerHTML =
        "<i></i> Piloto privado · fonte oficial ao vivo";
    selectElement("#sourceCount").textContent = String(demonstration.sources.length);
    selectElement("#soulVersion").textContent =
        demonstration.governance.soul;
    selectElement("#promptOrchestrator").textContent =
        demonstration.governance.prompts.orchestrator;
    selectElement("#promptSpecialist").textContent =
        demonstration.governance.prompts.tax_specialist;
    selectElement("#promptReviewer").textContent =
        demonstration.governance.prompts.reviewer;
    selectElement("#policyVersion").textContent =
        demonstration.governance.policy;
    selectElement("#suiteStatus").textContent =
        demonstration.governance.evals;
}
bindNavigationEvents();
bindChatEvents();
bindXmlEvents();
bindSplitEvent();
const initializationPromise = initializeApplication().catch((error) => {
    selectElement("#engineMode").innerHTML =
        "<i></i> Backend indisponível";
    showToast(errorMessage(error));
    throw error;
});
