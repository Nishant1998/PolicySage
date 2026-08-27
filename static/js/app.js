const chatForm = document.getElementById("chatForm");
const question = document.getElementById("question");
const scopeForm = document.getElementById("scopeForm");
const messages = document.getElementById("messages");
const conversation = document.getElementById("conversation");
const welcome = document.getElementById("welcome");
const requestStatus = document.getElementById("requestStatus");
const serviceStatus = document.getElementById("serviceStatus");
const newQuestion = document.getElementById("newQuestion");
const uploadDialog = document.getElementById("uploadDialog");
const uploadForm = document.getElementById("uploadForm");
const uploadStatus = document.getElementById("uploadStatus");
const adminKey = document.getElementById("adminKey");
const closeUpload = document.getElementById("closeUpload");
let requestRunning = false;
let uploadRunning = false;

const sourceNames = {
  kb: "Knowledge base", web: "Official web sources",
  kb_and_web: "Knowledge base + official web", direct: "General response", none: "No verified source",
};

function escapeHtml(text = "") {
  return String(text).replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

function formatText(text) {
  // Escape source text before adding the small amount of supported formatting.
  return escapeHtml(text).replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`\n]+)`/g, "<code>$1</code>")
    .replace(/^#{1,3}\s+(.+)$/gm, "<strong>$1</strong>");
}

function addMessage(role, text) {
  const element = document.createElement("article");
  element.className = `message ${role}`;
  const label = document.createElement("div");
  label.className = "message-label";
  label.textContent = role === "user" ? "YOU" : "POLICYSAGE";
  const body = document.createElement("div");
  body.className = "message-body";
  const content = document.createElement("div");
  content.className = "message-text";
  content.innerHTML = formatText(text);
  body.appendChild(content);
  element.append(label, body);
  messages.appendChild(element);
  conversation.scrollTop = conversation.scrollHeight;
  return { element, body, content };
}

function renderCitations(body, citations) {
  if (!citations.length) return;
  const section = document.createElement("section");
  section.className = "sources";
  const heading = document.createElement("h2");
  heading.textContent = "Sources behind this answer";
  const list = document.createElement("div");
  list.className = "source-list";
  for (const citation of citations) {
    let url;
    try {
      const parsed = new URL(citation.url);
      if (["http:", "https:"].includes(parsed.protocol)) url = parsed;
    } catch { /* Documents without a public URL still have a source card. */ }
    const card = document.createElement(url ? "a" : "div");
    card.className = "source-card";
    if (url) {
      card.href = url.href;
      card.target = "_blank";
      card.rel = "noopener noreferrer";
    }
    const title = document.createElement("span");
    title.className = "source-title";
    title.textContent = `[${citation.id}] ${citation.title || "Policy document"}`;
    const detail = document.createElement("span");
    detail.className = "source-detail";
    const parts = [citation.type === "web" ? "Official website" : "Policy document"];
    if (citation.page_start) {
      parts.push(citation.page_end && citation.page_end !== citation.page_start
        ? `Pages ${citation.page_start}–${citation.page_end}` : `Page ${citation.page_start}`);
    }
    if (url) parts.push(url.hostname);
    detail.textContent = parts.join(" · ");
    card.append(title, detail);
    list.appendChild(card);
  }
  section.append(heading, list);
  body.appendChild(section);
}

function renderAnswer(message, data, originalQuestion) {
  message.element.classList.remove("loading");
  message.content.innerHTML = formatText(data.answer);
  const meta = document.createElement("div");
  meta.className = "answer-meta";
  const source = document.createElement("span");
  source.className = "source-label";
  source.textContent = sourceNames[data.source_used] || "Source not specified";
  meta.appendChild(source);
  const outcomes = { clarification_required: "A few details needed", insufficient_evidence: "Evidence incomplete" };
  if (outcomes[data.status]) {
    const outcome = document.createElement("span");
    outcome.className = "outcome-label";
    outcome.textContent = outcomes[data.status];
    meta.appendChild(outcome);
  }
  message.body.appendChild(meta);
  renderCitations(message.body, data.citations || []);
  if (data.limitations?.length) {
    const limitations = document.createElement("ul");
    limitations.className = "limitations";
    limitations.setAttribute("aria-label", "Answer limitations");
    for (const text of data.limitations) {
      const item = document.createElement("li");
      item.textContent = text;
      limitations.appendChild(item);
    }
    message.body.appendChild(limitations);
  }
  if (data.trace?.length) {
    const details = document.createElement("details");
    details.className = "answer-trace";
    const summary = document.createElement("summary");
    summary.textContent = "How this answer was found";
    const steps = document.createElement("ol");
    for (const step of data.trace) {
      const item = document.createElement("li");
      item.textContent = step;
      steps.appendChild(item);
    }
    details.append(summary, steps);
    if (data.rewritten_query && data.rewritten_query !== originalQuestion) {
      const query = document.createElement("p");
      query.className = "query-detail";
      query.textContent = `Refined search: ${data.rewritten_query}`;
      details.appendChild(query);
    }
    message.body.appendChild(details);
  }
}

function updateCharacterCount() {
  document.getElementById("characterCount").textContent = `${question.value.length} / 3000`;
}

function setBusy(busy) {
  requestRunning = busy;
  chatForm.setAttribute("aria-busy", String(busy));
  document.querySelectorAll("#chatForm button, #chatForm textarea, #scopeForm input, #scopeForm select, #scopeForm button, .example")
    .forEach(control => { control.disabled = busy; });
  newQuestion.disabled = busy;
  document.getElementById("sendButton").textContent = busy ? "Finding an answer…" : "Ask PolicySage ↑";
}

function apiError(data, fallback) {
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) return data.detail.map(item => item.msg).join(" ");
  return fallback;
}

async function askAgent(text) {
  const value = text.trim();
  if (requestRunning) return;
  if (value.length < 2 || value.length > 3000) {
    requestStatus.textContent = "Please enter a question between 2 and 3,000 characters.";
    question.focus();
    return;
  }
  const filters = Object.fromEntries([...new FormData(scopeForm)].filter(([, value]) => value.trim()));
  const payload = { question: value, filters, allow_web: document.getElementById("allowWeb").checked };
  setBusy(true);
  welcome.hidden = true;
  addMessage("user", value);
  question.value = "";
  updateCharacterCount();
  const pending = addMessage("assistant", "Looking for supporting policy documents…");
  pending.element.classList.add("loading");
  requestStatus.textContent = "Checking the evidence. This can take a moment.";
  try {
    const response = await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(apiError(data, "Could not process the question. Please try again."));
    renderAnswer(pending, data, value);
    requestStatus.textContent = "Response ready.";
  } catch (error) {
    pending.element.classList.remove("loading");
    pending.element.classList.add("error");
    pending.content.textContent = error.message === "Failed to fetch"
      ? "Could not connect to the server. Please check your connection and try again." : error.message;
    question.value = value;
    updateCharacterCount();
    requestStatus.textContent = "Your question is back in the box so you can retry.";
  } finally {
    setBusy(false);
    conversation.scrollTop = conversation.scrollHeight;
    question.focus();
  }
}

chatForm.addEventListener("submit", event => { event.preventDefault(); askAgent(question.value); });
question.addEventListener("input", updateCharacterCount);
question.addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});
scopeForm.addEventListener("submit", event => event.preventDefault());
document.querySelectorAll(".example").forEach(button => {
  button.addEventListener("click", () => askAgent(button.dataset.question));
});
document.getElementById("resetFilters").addEventListener("click", () => scopeForm.reset());
newQuestion.addEventListener("click", () => {
  messages.replaceChildren();
  welcome.hidden = false;
  question.value = "";
  updateCharacterCount();
  requestStatus.textContent = "";
  conversation.scrollTop = 0;
  question.focus();
});
document.getElementById("scopeToggle").addEventListener("click", event => {
  const open = document.getElementById("sidebar").classList.toggle("is-open");
  event.currentTarget.setAttribute("aria-expanded", String(open));
});

document.getElementById("openUpload").addEventListener("click", () => {
  uploadStatus.textContent = "";
  uploadStatus.classList.remove("error");
  uploadDialog.showModal();
  adminKey.focus();
});
closeUpload.addEventListener("click", () => uploadDialog.close());
uploadDialog.addEventListener("cancel", event => { if (uploadRunning) event.preventDefault(); });
uploadDialog.addEventListener("close", () => { adminKey.value = ""; });
uploadForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (uploadRunning) return;
  const file = document.getElementById("fileInput").files[0];
  uploadStatus.classList.remove("error");
  if (!file || file.size === 0 || file.size > 20 * 1024 * 1024) {
    uploadStatus.textContent = "Choose a non-empty document no larger than 20 MB.";
    uploadStatus.classList.add("error");
    return;
  }
  const key = adminKey.value;
  const body = new FormData();
  body.append("file", file);
  uploadRunning = true;
  uploadForm.querySelectorAll("input, button").forEach(control => { control.disabled = true; });
  closeUpload.disabled = true;
  uploadStatus.textContent = "Reading and indexing the document. Please keep this dialog open…";
  try {
    const response = await fetch("/api/ingest", { method: "POST", headers: { "X-Admin-Key": key }, body });
    const data = await response.json();
    if (!response.ok) throw new Error(apiError(data, "Could not index the document. Please try again."));
    uploadStatus.textContent = `${data.file} is available in the knowledge base (${data.chunks} chunks).`;
    document.getElementById("fileInput").value = "";
  } catch (error) {
    uploadStatus.classList.add("error");
    uploadStatus.textContent = error.message === "Failed to fetch" ? "Could not connect to the server. Please try again." : error.message;
  } finally {
    uploadRunning = false;
    uploadForm.querySelectorAll("input, button").forEach(control => { control.disabled = false; });
    closeUpload.disabled = false;
    adminKey.value = "";
  }
});

fetch("/api/health").then(response => {
  if (!response.ok) throw new Error("Server unavailable");
  serviceStatus.textContent = "Server connected";
  serviceStatus.classList.add("ready");
}).catch(() => {
  serviceStatus.textContent = "Connection unavailable";
  serviceStatus.classList.add("offline");
});
