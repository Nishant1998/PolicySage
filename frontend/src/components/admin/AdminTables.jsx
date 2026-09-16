import { CheckCheck, Eye, FilePlus2, RotateCcw, Archive } from "lucide-react";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from "../ui/alert-dialog";
import { StatusBadge } from "./StatusBadge";

const btn = "inline-flex items-center gap-1 rounded-md border border-slate-200 px-2 py-1 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50";

const Withdraw = ({ doc, disabled, onConfirm }) => (
  <AlertDialog>
    <AlertDialogTrigger asChild>
      <button className={`${btn} text-red-700`} disabled={disabled} data-testid={`withdraw-document-button-${doc.id}`}><Archive size={13} /> Withdraw</button>
    </AlertDialogTrigger>
    <AlertDialogContent>
      <AlertDialogHeader>
        <AlertDialogTitle>Withdraw “{doc.title}”?</AlertDialogTitle>
        <AlertDialogDescription>The public assistant will stop searching this document. Existing revisions are kept.</AlertDialogDescription>
      </AlertDialogHeader>
      <AlertDialogFooter>
        <AlertDialogCancel>Cancel</AlertDialogCancel>
        <AlertDialogAction onClick={onConfirm} className="bg-red-700 hover:bg-red-800" data-testid={`withdraw-confirm-${doc.id}`}>Withdraw</AlertDialogAction>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>
);

export const DocumentsTable = ({ docs, disabled, actions, filtered = false }) => (
  <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white" data-testid="admin-documents-table">
    <table className="w-full min-w-[760px] text-sm">
      <thead className="border-b border-slate-200 bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
        <tr><th className="px-4 py-3">Document</th><th className="px-4">Revision</th><th className="px-4">Status</th><th className="px-4">Updated</th><th className="px-4 text-right">Actions</th></tr>
      </thead>
      <tbody>
        {docs.length === 0 && <tr><td colSpan={5} className="px-4 py-10 text-center text-slate-500" data-testid="documents-empty">{filtered ? "No documents match your filters." : "No documents to show."}</td></tr>}
        {docs.map((d) => (
          <tr key={d.id} className="border-b border-slate-100 last:border-0" data-testid={`document-row-${d.id}`}>
            <td className="px-4 py-3">
              <p className="font-semibold text-slate-900">{d.title}</p>
              <p className="text-xs text-slate-500">{[d.insurer, d.docType].filter(Boolean).join(" · ") || "No details"}</p>
            </td>
            <td className="px-4 font-mono text-xs text-slate-600">{d.revision ? `r${d.revision}` : "–"}</td>
            <td className="px-4"><StatusBadge status={d.status} testid={`document-status-${d.id}`} /></td>
            <td className="px-4 text-xs text-slate-500">{d.updatedAt ?? "–"}</td>
            <td className="px-4">
              <div className="flex justify-end gap-1.5">
                <button className={btn} disabled={disabled || !d.revisionId} onClick={() => actions.preview(d)} data-testid={`preview-document-button-${d.id}`}><Eye size={13} /> Preview</button>
                <button className={btn} disabled={disabled || d.status === "withdrawn"} onClick={() => actions.revision(d)} data-testid={`new-revision-button-${d.id}`}><FilePlus2 size={13} /> New revision</button>
                {d.status === "pending_approval" && <button className={`${btn} border-emerald-300 text-emerald-800`} disabled={disabled} onClick={() => actions.approve(d)} data-testid={`approve-revision-button-${d.id}`}><CheckCheck size={13} /> Approve</button>}
                {d.status === "published" && <Withdraw doc={d} disabled={disabled} onConfirm={() => actions.withdraw(d)} />}
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

export const JobsList = ({ jobs, disabled, onRetry }) => (
  <ul className="divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-200 bg-white" data-testid="admin-jobs-list">
    {jobs.length === 0 && <li className="px-4 py-10 text-center text-sm text-slate-500" data-testid="jobs-empty">No ingestion jobs to show.</li>}
    {jobs.map((j) => (
      <li key={j.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3" data-testid={`job-row-${j.id}`}>
        <span className="font-mono text-xs text-slate-500">{j.id}</span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-slate-900">{j.document}</p>
          <p className="text-xs text-slate-500">{j.stage ? `Stage: ${j.stage}` : "Stage not reported"}{j.updatedAt ? ` · ${j.updatedAt}` : ""}</p>
          {j.error && <p className="mt-1 text-xs text-red-700">{j.error}</p>}
        </div>
        <StatusBadge status={j.status} testid={`job-status-${j.id}`} />
        {["failed", "cleanup_failed"].includes(j.status) && !j.error?.startsWith("Upload ") && <button className={btn} disabled={disabled} onClick={() => onRetry(j)} data-testid={`retry-job-button-${j.id}`}><RotateCcw size={13} /> Retry</button>}
      </li>
    ))}
  </ul>
);
