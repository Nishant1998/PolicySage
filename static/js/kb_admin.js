const get = id => document.getElementById(id);
const login = get("loginForm");
const upload = get("documentForm");
const panel = get("adminPanel");
const status = get("adminStatus");
const prefix = "/api/admin/kb";
let authorization = "";
let replacement = null;
let documents = [];
let loading = false;

function node(tag, text) {
  const item = document.createElement(tag);
  item.textContent = text;
  return item;
}

async function api(path, options = {}) {
  const response = await fetch(prefix + path, {
    ...options,
    headers: { Authorization: authorization },
  });
  if (!response.ok) {
    const result = await response.json().catch(() => ({}));
    if (response.status === 401) signOut();
    throw new Error(typeof result.detail === "string" ? result.detail : "Request failed. Please try again.");
  }
  return response.json();
}

function signOut() {
  authorization = "";
  panel.hidden = true;
  login.hidden = false;
  login.reset();
  selectReplacement(null);
  documents = [];
  get("documentList").replaceChildren();
  get("jobList").replaceChildren();
  status.textContent = "";
}

function button(text, action) {
  const item = node("button", text);
  item.type = "button";
  item.addEventListener("click", () => perform(action, item));
  return item;
}

async function perform(action, button) {
  if (button) button.disabled = true;
  try {
    await action();
  } catch (error) {
    status.textContent = error.message;
  } finally {
    if (button) button.disabled = false;
  }
}

function selectReplacement(doc) {
  replacement = doc;
  get("uploadTitle").textContent = doc ? `Replace ${doc.title}` : "Add a PDF";
  get("cancelReplace").hidden = !doc;
  upload.reset();
  if (doc) {
    upload.elements.title.value = doc.title;
    upload.elements.source_url.value = doc.source_url || "";
    upload.elements.file.focus();
  }
}

async function previewPdf(revisionId) {
  const tab = window.open("about:blank", "_blank");
  if (!tab) throw new Error("Allow pop-ups to preview the PDF.");
  tab.opener = null;
  try {
    const {url} = await api(`/revisions/${revisionId}/preview`);
    tab.location.replace(url);
  } catch (error) {
    tab.close();
    throw error;
  }
}

function renderDocuments() {
  const list = get("documentList");
  const query = get("findDocument").value.trim().toLowerCase();
  const matches = documents.filter(doc =>
    `${doc.title} ${doc.filename || ""} ${doc.source || ""}`.toLowerCase().includes(query));
  list.replaceChildren();
  if (!matches.length) list.append(node("p", query ? "No matching documents." : "No documents yet."));
  for (const doc of matches) {
    const card = node("article", "");
    card.className = "kb-item";
    const state = doc.withdrawn_at ? "Withdrawn" : doc.active_revision ? "Searchable" : "Awaiting publication";
    const stage = !doc.withdrawn_at && doc.index_status && doc.index_status !== "active"
      ? ` · Latest upload: ${doc.index_status.replaceAll("_", " ")}` : "";
    card.append(node("h3", doc.title), node("p", state + stage));
    card.append(node("p", `Updated ${new Date(doc.updated_at).toLocaleString()}`));
    if (!doc.withdrawn_at) {
      const actions = node("div", "");
      actions.className = "kb-actions";
      if (doc.active_revision) {
        actions.append(button("Open PDF", () => previewPdf(doc.active_revision)));
      }
      actions.append(button("Replace PDF", () => selectReplacement(doc)));
      actions.append(button("Withdraw", async () => {
        if (!window.confirm(`Withdraw ${doc.title} from search? The original PDF will be retained privately.`)) return;
        await api(`/documents/${doc.id}`, { method: "DELETE" });
        if (replacement?.id === doc.id) selectReplacement(null);
        status.textContent = "Document withdrawn. Vector cleanup is queued.";
        await refresh();
      }));
      card.append(actions);
    }
    list.append(card);
  }
}

function renderJobs(jobs) {
  const list = get("jobList");
  list.replaceChildren();
  if (!jobs.length) list.append(node("p", "No jobs yet."));
  for (const job of jobs) {
    const card = node("article", "");
    card.className = "kb-item";
    const waitingForReview = job.status === "verifying" && job.review_required;
    const stage = waitingForReview ? "Awaiting review" : job.status.replaceAll("_", " ");
    card.append(node("h3", job.name),
      node("p", `${stage} · Indexing attempts: ${job.attempts}`));
    if (job.last_error) card.append(node("p", job.last_error));
    if (waitingForReview) {
      card.append(button("Preview PDF", () => previewPdf(job.id)));
      card.append(button("Approve publication", async () => {
        await api(`/revisions/${job.id}/approve`, { method: "POST" });
        status.textContent = "Approved. The worker will publish this revision.";
        await refresh();
      }));
    }
    if (["failed", "cleanup_failed"].includes(job.status)) card.append(button("Retry", async () => {
      await api(`/jobs/${job.id}/retry`, { method: "POST" });
      status.textContent = "Retry queued.";
      await refresh();
    }));
    list.append(card);
  }
}

async function refresh() {
  if (loading || !authorization) return;
  loading = true;
  const session = authorization;
  try {
    const [docs, jobs] = await Promise.all([api("/documents"), api("/jobs")]);
    if (session !== authorization) return;
    documents = docs;
    renderDocuments();
    renderJobs(jobs);
  } finally {
    loading = false;
  }
}

login.addEventListener("submit", event => {
  event.preventDefault();
  perform(async () => {
    const values = new FormData(login);
    const username = values.get("username");
    const password = values.get("password");
    if (!/^[!-~]+$/.test(username) || username.includes(":") || !/^[ -~]+$/.test(password)) {
      throw new Error("Use the configured username and password with standard ASCII characters.");
    }
    authorization = "Basic " + btoa(`${username}:${password}`);
    status.textContent = "Signing in…";
    await refresh();
    login.reset();
    login.hidden = true;
    panel.hidden = false;
    status.textContent = "Signed in.";
    upload.elements.file.focus();
  }, login.querySelector("button"));
});

upload.addEventListener("submit", event => {
  event.preventDefault();
  perform(async () => {
    const data = new FormData(upload);
    const target = replacement;
    status.textContent = "Uploading PDF…";
    const result = await api(target ? `/documents/${target.id}/revisions` : "/documents",
      { method: "POST", body: data });
    selectReplacement(null);
    status.textContent = result.status === "unchanged"
      ? "This PDF is already registered for this document. Check its activity below."
      : "PDF saved. Indexing is queued.";
    await refresh();
  }, upload.querySelector("button[type=submit]"));
});

get("signOut").addEventListener("click", () => { signOut(); login.elements.username.focus(); });
get("cancelReplace").addEventListener("click", () => selectReplacement(null));
get("refresh").addEventListener("click", () => perform(refresh, get("refresh")));
get("findDocument").addEventListener("input", renderDocuments);
setInterval(() => {
  if (!document.hidden && !panel.hidden) perform(refresh);
}, 10000);
