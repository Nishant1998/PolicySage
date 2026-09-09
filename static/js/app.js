const $ = selector => document.querySelector(selector);
const messages = $("#messages");
const question = $("#question");
let busy = false;
let failedQuestion = "";
let chatHistory = [];
let conversationId = crypto.randomUUID?.();

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function sourceUrl(value) {
  try {
    if (/^\/api\/kb\/revisions\/[0-9a-f]{32}(?:[0-9a-f]{32})?\.pdf$/.test(value)) {
      return new URL(value, window.location.origin).href;
    }
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) ? url.href : null;
  } catch { return null; }
}

function citationUrl(citation) {
  const value = sourceUrl(citation.url);
  if (!value) return null;
  const url = new URL(value);
  if (citation.type === "kb" && /\.pdf$/i.test(url.pathname) && Number.isInteger(citation.page_start) && citation.page_start > 0 && !url.hash) {
    url.hash = `page=${citation.page_start}`;
  }
  return url.href;
}

function sourceDetail(citation) {
  const pages = Number.isInteger(citation.page_start) && citation.page_start > 0
    ? (Number.isInteger(citation.page_end) && citation.page_end > citation.page_start
      ? ` · Pages ${citation.page_start}–${citation.page_end}` : ` · Page ${citation.page_start}`) : "";
  return `${citation.type === "web" ? "Web source" : "Knowledge-base document"}${pages}`;
}

function updateInsights(data) {
  const labels = { kb: "Knowledge base", web: "Official web sources", kb_and_web: "Knowledge base + official web", direct: "Direct response", none: "No cited source" };
  $("#insightOrigin").textContent = labels[data.source_used] || "Source not specified";
  const sources = $("#insightSources");
  sources.replaceChildren();
  const citations = Array.isArray(data.citations) ? data.citations.filter(c => c && typeof c.id === "string") : [];
  for (const citation of citations) {
    const url = citationUrl(citation);
    const card = element("div", "insight-source");
    const name = element(url ? "a" : "span", "insight-source-name", `[${citation.id}] ${citation.title || "Source"}`);
    if (url) { name.href = url; name.target = "_blank"; name.rel = "noopener noreferrer"; }
    card.append(name, element("small", "", `${sourceDetail(citation)}${url ? " · Open source ↗" : " · Link unavailable"}`));
    sources.append(card);
  }
  if (!citations.length) sources.append(element("p", "insight-empty", "No sources returned for this answer."));
  const list = $("#insightTrace");
  list.replaceChildren();
  const steps = Array.isArray(data.trace) ? data.trace.filter(step => typeof step === "string") : [];
  for (const step of steps) list.append(element("li", "", step));
  if (!steps.length) list.append(element("li", "insight-empty", "No trace returned."));
}

function resetInsights(message = "Ask a question to see the source.") {
  $("#insightOrigin").textContent = message;
  $("#insightSources").replaceChildren(element("p", "insight-empty", "No sources yet."));
  $("#insightTrace").replaceChildren(element("li", "insight-empty", "No activity yet."));
}

function addUser(text) {
  const article = element("article", "message user", text);
  messages.append(article);
  return article;
}

function describeStep(step) {
  if (/^Router: kb$/.test(step)) return "Chose to search policy documents";
  if (/^Router: direct$/.test(step)) return "Chose a direct response";
  if (/^Decomposition skipped$/.test(step)) return "Kept the question as one search";
  if (/^Decomposed into \d+ queries$/.test(step)) return "Split the question into focused searches";
  if (/^KB retrieval: \d+ chunks$/.test(step)) return "Searched policy documents";
  if (/^KB grade: good$/.test(step)) return "Checked the policy evidence: sufficient";
  if (/^KB grade: weak$/.test(step)) return "Checked the policy evidence: incomplete";
  if (/^Web search: \d+ sources$/.test(step)) return "Searched official websites";
  if (step === "Web search unavailable") return "Official web search was unavailable";
  if (/^Web and KB grade: (good|weak)$/.test(step)) return step.endsWith("good") ? "Checked the combined evidence: sufficient" : "Checked the combined evidence: incomplete";
  if (step === "Query rewritten") return "Refined the search question";
  if (step === "Token budget reached") return "Stopped at the request's research limit";
  if (/^Answer: /.test(step)) return "Prepared an answer";
  if (/^General answer: /.test(step)) return "Prepared a response";
  if (step === "Workflow error") return "The search could not be completed";
  return step;
}

function addAnswer(data) {
  const article = element("article", "message assistant");
  article.append(element("div", "assistant-label", "✧ POLICYSAGE"));
  const text = element("div", "answer-text");
  const citations = Array.isArray(data.citations) ? data.citations : [];
  const sourceIds = new Map(citations.filter(c => c && typeof c.id === "string").map(c => [c.id, c]));
  for (const part of data.answer.split(/(\[[KW]\d+\])/g)) {
    const id = part.slice(1, -1);
    const source = sourceIds.get(id);
    if (!source) { text.append(document.createTextNode(part)); continue; }
    const marker = element("a", "cite", part);
    marker.href = `#source-${messages.children.length}-${id}`;
    marker.setAttribute("aria-label", `View source ${id}`);
    text.append(marker);
  }
  article.append(text);
  const sourceLabels = { kb: "Policy documents", web: "Official web sources", kb_and_web: "Policy documents and official web sources" };
  if (sourceLabels[data.source_used]) {
    const sourceLabel = element("p", "answer-origin", `Answer based on: ${sourceLabels[data.source_used]}`);
    article.append(sourceLabel);
  }
  if (citations.length) {
    const details = element("details", "sources");
    details.append(element("summary", "", `Sources (${citations.length})`));
    for (const citation of citations) {
      if (!citation || typeof citation.id !== "string") continue;
      const url = citationUrl(citation);
      const card = element("div", "source-card");
      card.id = `source-${messages.children.length}-${citation.id}`;
      card.append(element("strong", "", `[${citation.id}] ${citation.title || "Policy document"}`));
      const pages = citation.page_start ? (citation.page_end && citation.page_end !== citation.page_start ? ` · Pages ${citation.page_start}–${citation.page_end}` : ` · Page ${citation.page_start}`) : "";
      card.append(element("small", "", `${citation.type === "web" ? "Web source" : "Policy document"}${pages}`));
      if (typeof citation.excerpt === "string" && citation.excerpt) {
        card.append(element("blockquote", "source-excerpt", citation.excerpt));
      }
      if (url) {
        const link = element("a", "", citation.type === "kb" ? "Open original document ↗" : "Open website ↗");
        link.href = url; link.target = "_blank"; link.rel = "noopener noreferrer";
        card.append(link);
      } else {
        card.append(element("small", "", "Source excerpt available; no public document link provided."));
      }
      details.append(card);
    }
    article.append(details);
    text.addEventListener("click", event => {
      if (event.target.closest(".cite")) details.open = true;
    });
  }
  if (Array.isArray(data.limitations) && data.limitations.length) {
    const list = element("ul", "answer-limitations");
    list.setAttribute("aria-label", "Answer limitations");
    for (const item of data.limitations) if (typeof item === "string") list.append(element("li", "", item));
    article.append(list);
  }
  if (Array.isArray(data.trace) && data.trace.length) {
    const details = element("details", "activity");
    details.append(element("summary", "", "How this answer was found"));
    const list = element("ul");
    for (const step of data.trace) if (typeof step === "string") list.append(element("li", "", describeStep(step)));
    details.append(list);
    article.append(details);
  }
  messages.append(article);
  updateInsights(data);
}

function resize() {
  question.style.height = "auto";
  question.style.height = `${Math.min(question.scrollHeight, 200)}px`;
}

function setBusy(value) {
  busy = value;
  $("#send").disabled = value;
  $("#newChat").disabled = value;
  question.disabled = value;
  messages.setAttribute("aria-busy", String(value));
}

async function ask(text, retry = false) {
  const value = text.trim();
  if (busy || value.length < 2 || value.length > 3000) return;
  if (!retry && failedQuestion) {
    messages.lastElementChild?.remove();
    failedQuestion = "";
  }
  $("#error").hidden = true;
  $("#welcome").hidden = true;
  if (!retry) addUser(value);
  question.value = "";
  resize();
  setBusy(true);
  $("#status").textContent = "Finding an answer…";
  resetInsights("Finding an answer…");
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 120000);
    let response;
    try {
      response = await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json",
        ...(conversationId ? { "X-Conversation-ID": conversationId } : {}) },
      body: JSON.stringify({ question: value, history: chatHistory, allow_web: $("#allowWeb").checked }),
        signal: controller.signal,
      });
    } finally { clearTimeout(timeout); }
    if (!response.ok) {
      const messages = {
        429: "Too many requests. Please wait before trying again.",
        503: "The demo is busy or temporarily unavailable. Please try again shortly.",
        413: "This conversation is too large. Start a new chat and shorten your question.",
      };
      const error = new Error("unavailable");
      if (messages[response.status]) {
        const data = await response.json().catch(() => ({}));
        error.userMessage = typeof data.detail === "string" ? data.detail : messages[response.status];
      }
      throw error;
    }
    const data = await response.json();
    if (typeof data.answer !== "string" || !data.answer.trim()) throw new Error("invalid");
    addAnswer(data);
    chatHistory = [...chatHistory, { question: value, answer: data.answer.slice(0, 4000) }].slice(-4);
    failedQuestion = "";
  } catch (error) {
    failedQuestion = value;
    resetInsights("Request did not complete.");
    $("#errorText").textContent = error.name === "AbortError"
      ? "The request is taking too long. It may still be running on the server. Please wait before retrying."
      : error.userMessage || "Could not get an answer. Please try again or edit your question.";
    $("#error").hidden = false;
  } finally {
    $("#status").textContent = "";
    setBusy(false);
    question.focus();
  }
}

$("#chatForm").addEventListener("submit", event => { event.preventDefault(); ask(question.value); });
question.addEventListener("input", resize);
question.addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); $("#chatForm").requestSubmit(); }
});
document.querySelectorAll(".examples button").forEach(button => button.addEventListener("click", () => {
  question.value = button.textContent;
  resize();
  question.focus();
}));
$("#retry").addEventListener("click", () => { if (failedQuestion) ask(failedQuestion, true); });
$("#edit").addEventListener("click", () => {
  if (!failedQuestion) return;
  messages.lastElementChild?.remove();
  question.value = failedQuestion;
  failedQuestion = "";
  $("#error").hidden = true;
  resize();
  question.focus();
});
$("#newChat").addEventListener("click", () => {
  if (busy) return;
  chatHistory = [];
  conversationId = crypto.randomUUID?.();
  messages.replaceChildren();
  resetInsights();
  $("#welcome").hidden = false;
  $("#error").hidden = true;
  failedQuestion = "";
  question.value = "";
  resize();
  question.focus();
});

const helpDialog = $("#helpDialog");
document.querySelectorAll("[data-open-help]").forEach(button => {
  button.addEventListener("click", () => helpDialog.showModal());
});
$("#closeHelp").addEventListener("click", () => helpDialog.close());

