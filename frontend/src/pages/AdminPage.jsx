import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, LogOut, Upload } from "lucide-react";
import { toast } from "sonner";
import { Header } from "../components/ps/Header";
import { Footer } from "../components/ps/Footer";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { DocumentsTable, JobsList } from "../components/admin/AdminTables";
import { UploadDialog } from "../components/admin/UploadDialog";
import { adminApi } from "../lib/api";

const TokenBar = ({ credentials, setCredentials }) => {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  if (credentials) return (
    <div className="flex items-center justify-between rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900" data-testid="admin-auth-status">
      <span className="flex items-center gap-2"><KeyRound size={15} /> Signed in as {credentials.username} for this session.</span>
      <button onClick={() => setCredentials(null)} data-testid="admin-signout-button" className="inline-flex items-center gap-1 text-xs font-semibold hover:underline"><LogOut size={13} /> Sign out</button>
    </div>
  );
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (username.trim() && password) setCredentials({ username: username.trim(), password }); }} className="flex flex-col gap-2 rounded-xl border border-slate-200 bg-white p-4 sm:flex-row sm:items-center">
      <KeyRound size={16} className="hidden text-slate-500 sm:block" />
      <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="Admin username" autoComplete="username" data-testid="admin-username-input"
        className="h-10 flex-1 rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-100" />
      <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Admin password" autoComplete="current-password" data-testid="admin-password-input"
        className="h-10 flex-1 rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-100" />
      <button type="submit" data-testid="admin-token-submit" className="h-10 rounded-lg bg-slate-900 px-4 text-sm font-semibold text-white hover:bg-slate-700">Sign in</button>
    </form>
  );
};

export default function AdminPage() {
  const qc = useQueryClient();
  const [credentials, setCredentialsState] = useState(null);
  const [dialog, setDialog] = useState({ open: false, doc: null });
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const live = Boolean(credentials);

  const setCredentials = (value) => {
    setCredentialsState(value);
  };
  const docsQ = useQuery({ queryKey: ["docs", credentials], queryFn: () => adminApi.documents(credentials), enabled: live, refetchInterval: 10000 });
  const jobsQ = useQuery({ queryKey: ["jobs", credentials], queryFn: () => adminApi.jobs(credentials), enabled: live, refetchInterval: 10000 });

  const act = useMutation({
    mutationFn: ({ fn }) => fn(),
    onSuccess: (result, { msg }) => { toast.success(result?.status === "unchanged" ? "This revision is already registered." : msg); setDialog({ open: false, doc: null }); qc.invalidateQueries(); },
    onError: (e) => toast.error(e.message),
  });
  const run = (fn, msg) => act.mutate({ fn, msg });

  const docs = live ? docsQ.data ?? [] : [];
  const query = search.trim().toLocaleLowerCase();
  const filteredDocs = docs.filter((doc) =>
    (statusFilter === "all" || doc.status === statusFilter) &&
    (!query || [doc.title, doc.filename, doc.insurer, doc.category, doc.docType, doc.id]
      .some((value) => String(value ?? "").toLocaleLowerCase().includes(query)))
  ).sort((a, b) => {
    const dateA = Date.parse(a.updatedAt) || 0;
    const dateB = Date.parse(b.updatedAt) || 0;
    return dateB - dateA || a.title.localeCompare(b.title) || a.id.localeCompare(b.id);
  });
  const statuses = [...new Set(docs.map((doc) => doc.status))].sort();
  const jobs = live ? jobsQ.data ?? [] : [];
  const error = docsQ.error || jobsQ.error;

  const actions = {
    preview: (d) => { const tab = window.open("about:blank", "_blank"); if (!tab) return toast.error("Allow pop-ups to preview the PDF."); tab.opener = null; run(async () => { const r = await adminApi.preview(credentials, d.revisionId); if (!r?.url) throw new Error("No preview link was returned."); tab.location.replace(r.url); }, "Preview opened"); },
    revision: (d) => setDialog({ open: true, doc: d }),
    approve: (d) => run(() => adminApi.approve(credentials, d.revisionId), "Revision approved"),
    withdraw: (d) => run(() => adminApi.withdraw(credentials, d.id), "Document withdrawn"),
  };
  const submitUpload = (fd) => (dialog.doc ? run(() => adminApi.revision(credentials, dialog.doc.id, fd), "Revision uploaded and queued") : run(() => adminApi.upload(credentials, fd), "Document uploaded and queued"));

  return (
    <div className="flex min-h-[100dvh] flex-col bg-slate-50">
      <Header />
      <main className="mx-auto w-full max-w-6xl flex-1 space-y-5 px-4 py-8">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight text-slate-900">Document management</h1>
            <p className="mt-1 text-sm text-slate-600">Authorized admins only. Only published revisions are searchable by the public assistant.</p>
          </div>
          <button onClick={() => setDialog({ open: true, doc: null })} disabled={!live} data-testid="upload-document-button"
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300">
            <Upload size={15} /> Upload PDF
          </button>
        </div>
        <TokenBar credentials={live ? credentials : null} setCredentials={setCredentials} />
        {error && <p className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800" data-testid="admin-error">{error.message}</p>}
        <Tabs defaultValue="documents">
          <TabsList>
            <TabsTrigger value="documents" data-testid="admin-tab-documents">Documents ({docs.length})</TabsTrigger>
            <TabsTrigger value="jobs" data-testid="admin-tab-jobs">Ingestion jobs ({jobs.length})</TabsTrigger>
          </TabsList>
          <TabsContent value="documents" className="mt-4 space-y-3">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
              <label className="flex-1 text-xs font-semibold text-slate-700">
                Search documents
                <input type="search" value={search} onChange={(e) => setSearch(e.target.value)}
                  placeholder="Name, filename, insurer, category, type or ID"
                  data-testid="document-search"
                  className="mt-1 block h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm font-normal outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-100" />
              </label>
              <label className="text-xs font-semibold text-slate-700">
                Status
                <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} data-testid="document-status-filter"
                  className="mt-1 block h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm font-normal sm:w-44">
                  <option value="all">All statuses</option>
                  {statuses.map((status) => <option key={status} value={status}>{status.replace(/_/g, " ")}</option>)}
                </select>
              </label>
            </div>
            <p className="text-xs text-slate-500">Showing {filteredDocs.length} of {docs.length} documents · Most recently updated first</p>
            <DocumentsTable docs={filteredDocs} disabled={!live || act.isPending} actions={actions} filtered={Boolean(query) || statusFilter !== "all"} />
          </TabsContent>
          <TabsContent value="jobs" className="mt-4"><JobsList jobs={jobs} disabled={!live || act.isPending} onRetry={(j) => run(() => adminApi.retry(credentials, j.id), "Job queued for retry")} /></TabsContent>
        </Tabs>
      </main>
      <Footer />
      <UploadDialog key={dialog.doc?.id ?? "new"} open={dialog.open} doc={dialog.doc} busy={act.isPending} onSubmit={submitUpload} onOpenChange={(o) => setDialog((d) => ({ ...d, open: o }))} />
    </div>
  );
}
