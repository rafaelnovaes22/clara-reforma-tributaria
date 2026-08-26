type ViewName = "chat" | "invoice" | "split" | "portfolio" | "governance";

interface OfficialSource {
  id: string;
  title: string;
  url: string;
  live: boolean;
}

interface ExecutionEvaluation {
  passed: boolean;
  overall: number;
  grounding_status: string;
}

interface TraceStep {
  agent: string;
  detail: string;
}

interface ChatResult {
  answer: string;
  generation_mode: string;
  needs_human_review: boolean;
  risk: string;
  sources: OfficialSource[];
  trace: TraceStep[];
  evals: ExecutionEvaluation;
}

interface XmlFinding {
  code: string;
  severity: string;
  title: string;
  detail: string;
}

interface XmlTriageResult {
  filename: string;
  status: "triagem_pendente";
  findings: XmlFinding[];
  note: string;
}

interface SplitResult {
  gross: number;
  ibs: number;
  cbs: number;
  net: number;
  rates: { ibs: number; cbs: number };
  note: string;
}

interface PilotSessionResult {
  csrf_token: string;
  client_id?: string;
  message?: string;
}

interface DemoResult {
  sources: OfficialSource[];
  governance: {
    prompts: Record<string, string>;
    soul: string;
    policy: string;
    evals: string;
  };
}

interface ApiErrorPayload {
  error?: string;
  code?: string;
}

const VIEW_LABELS: Record<ViewName, [string, string]> = {
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

function selectElement<ElementType extends Element>(
  selector: string,
  root: ParentNode = document,
): ElementType {
  const element = root.querySelector<ElementType>(selector);
  if (!element)
    throw new Error(`Elemento obrigatório não encontrado: ${selector}.`);
  return element;
}

function selectElements<ElementType extends Element>(
  selector: string,
  root: ParentNode = document,
): ElementType[] {
  return Array.from(root.querySelectorAll<ElementType>(selector));
}

function switchView(viewName: ViewName): void {
  selectElements<HTMLElement>(".view").forEach((element) =>
    element.classList.remove("active"),
  );
  selectElement<HTMLElement>(`#view-${viewName}`).classList.add("active");
  selectElements<HTMLButtonElement>(".nav-item").forEach((element) => {
    element.classList.toggle("active", element.dataset.view === viewName);
  });
  selectElement<HTMLElement>("#viewTitle").textContent =
    VIEW_LABELS[viewName][0];
  selectElement<HTMLElement>("#viewSubtitle").textContent =
    VIEW_LABELS[viewName][1];
  if (innerWidth < 720) scrollTo({ top: 0, behavior: "smooth" });
}

function formatMoney(value: number): string {
  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL",
  }).format(value);
}

function escapeHtml(value: string): string {
  const container = document.createElement("div");
  container.textContent = value;
  return container.innerHTML;
}

function formatAnswer(value: string): string {
  return escapeHtml(value)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replaceAll("\n", "<br>");
}

function showToast(message: string): void {
  const toast = selectElement<HTMLElement>("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 2500);
}

function errorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Não foi possível completar a operação.";
}

async function readJson<ResponseType>(
  response: Response,
): Promise<ResponseType> {
  const payload = (await response.json()) as ResponseType & ApiErrorPayload;
  if (!response.ok)
    throw new Error(payload.error || "Não foi possível completar a operação.");
  return payload;
}

async function getApi<ResponseType>(path: string): Promise<ResponseType> {
  return readJson<ResponseType>(
    await fetch(path, { credentials: "same-origin" }),
  );
}

async function postApi<ResponseType>(
  path: string,
  body: Record<string, unknown>,
): Promise<ResponseType> {
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
  return readJson<ResponseType>(response);
}
