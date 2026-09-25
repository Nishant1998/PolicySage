import { API_BASE, ENDPOINTS } from "./config";

const STAGE_LABELS = {
  route_question: "Understanding the question",
  decompose_question: "Preparing search queries",
  retrieve_kb: "Searching policy documents",
  grade_kb: "Checking policy evidence",
  search_web: "Searching official websites",
  grade_web: "Checking web and policy evidence",
  rewrite_query: "Refining the search query",
  generate_from_kb: "Writing an answer from policy documents",
  generate_from_web: "Writing an answer using web evidence",
  general_answer: "Preparing a reply",
};

export const stageLabel = (s) => {
  const key = String(s ?? "").toLowerCase();
  return STAGE_LABELS[key] ?? key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
};

const absolute = (url) => (url && url.startsWith("/") ? `${API_BASE}${url}` : url);

const normalizeCitation = (c, i) => ({
  id: String(c?.id ?? i + 1),
  title: c?.title ?? null,
  pageStart: c?.page_start ?? null,
  pageEnd: c?.page_end ?? null,
  excerpt: c?.excerpt ?? null,
  sourceUrl: absolute(c?.url),
  access: c?.access ?? (c?.url ? null : "unavailable"),
  pageNav: c?.supports_page_navigation ?? true,
});

const normalizeTrace = (t) =>
  typeof t === "string" ? { label: t, detail: null } : { label: stageLabel(t?.step ?? t?.name ?? t?.stage), detail: t?.detail ?? t?.summary ?? null };

export function normalizeResponse(raw) {
  const citations = (Array.isArray(raw?.citations) ? raw.citations : []).map(normalizeCitation);
  const status = raw?.status ?? (citations.length ? "answered" : "conversational");
  return {
    status: status === "insufficient_evidence" ? "no_evidence" : status,
    answer: raw?.answer ?? "",
    citations,
    trace: (Array.isArray(raw?.trace) ? raw.trace : []).map(normalizeTrace),
    limitations: Array.isArray(raw?.limitations) ? raw.limitations : [],
  };
}

const parseEvent = (block) => {
  let event = "message";
  let data = "";
  block.split("\n").forEach((line) => {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  });
  if (!data) return null;
  try { return { event, data: JSON.parse(data) }; } catch { return { event, data }; }
};

export async function askQuestion({ question, history, onStage, signal }) {
  const res = await fetch(`${API_BASE}${ENDPOINTS.chat}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ question, history, allow_web: true }),
    signal,
  });
  if (!res.ok) throw new Error(`The server responded with status ${res.status}.`);
  if (!(res.headers.get("content-type") ?? "").includes("text/event-stream")) return normalizeResponse(await res.json());

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let final = null;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop();
    for (const block of blocks) {
      const ev = parseEvent(block);
      const type = ev?.data?.type ?? ev?.event;
      if (type === "stage") onStage?.(stageLabel(ev.data?.stage ?? ev.data?.name ?? ev.data));
      else if (type === "error") throw new Error(ev.data?.message ?? "The backend reported an error.");
      else if (type === "final" || type === "result") final = normalizeResponse(ev.data?.result ?? ev.data);
    }
  }
  if (!final) throw new Error("The response ended before an answer arrived.");
  return final;
}

const adminFetch = async (path, credentials, opts = {}) => {
  const isForm = opts.body instanceof FormData;
  const encoded = btoa(String.fromCharCode(...new TextEncoder().encode(`${credentials.username}:${credentials.password}`)));
  const res = await fetch(`${API_BASE}${path}`, {
    ...opts,
    headers: { Authorization: `Basic ${encoded}`, ...(isForm ? {} : { "Content-Type": "application/json" }) },
  });
  if (res.status === 401 || res.status === 403) throw new Error("Not authorized. Check the admin username and password.");
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `Request failed with status ${res.status}.`);
  }
  return res.status === 204 ? null : res.json();
};

const list = (d, key) => (Array.isArray(d) ? d : Array.isArray(d?.[key]) ? d[key] : []);

export const normalizeDoc = (d) => ({
  id: String(d?.id ?? d?.document_id),
  title: d?.title ?? "Untitled document",
  insurer: d?.insurer ?? null,
  category: d?.category ?? null,
  filename: d?.filename ?? null,
  docType: d?.document_type ?? d?.doc_type ?? null,
  revision: d?.version ?? null,
  revisionId: d?.latest_revision ?? d?.active_revision ?? null,
  status: d?.withdrawn_at ? "withdrawn" : d?.index_status === "active" ? "published" : d?.index_status === "verifying" && d?.review_required ? "pending_approval" : ["parsing", "chunking", "indexing", "verifying"].includes(d?.index_status) ? "processing" : d?.index_status ?? "unknown",
  updatedAt: d?.updated_at ?? null,
});

export const normalizeJob = (j) => ({
  id: String(j?.id ?? j?.job_id),
  document: j?.name ?? j?.document_title ?? j?.document_id ?? "Unknown document",
  stage: j?.stage ?? null,
  status: j?.status === "active" ? "completed" : j?.status ?? "unknown",
  error: j?.last_error ?? j?.error ?? null,
  updatedAt: j?.updated_at ?? null,
});

export const adminApi = {
  documents: async (t) => list(await adminFetch(ENDPOINTS.documents, t), "documents").map(normalizeDoc),
  jobs: async (t) => list(await adminFetch(ENDPOINTS.jobs, t), "jobs").map(normalizeJob),
  upload: (t, form) => adminFetch(ENDPOINTS.documents, t, { method: "POST", body: form }),
  revision: (t, docId, form) => adminFetch(ENDPOINTS.revisions(docId), t, { method: "POST", body: form }),
  approve: (t, revisionId) => adminFetch(ENDPOINTS.approve(revisionId), t, { method: "POST" }),
  retry: (t, jobId) => adminFetch(ENDPOINTS.retry(jobId), t, { method: "POST" }),
  withdraw: (t, docId) => adminFetch(ENDPOINTS.withdraw(docId), t, { method: "DELETE" }),
  preview: (t, revisionId) => adminFetch(ENDPOINTS.preview(revisionId), t),
};
