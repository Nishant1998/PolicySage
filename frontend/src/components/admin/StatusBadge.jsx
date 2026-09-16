const STYLES = {
  published: "bg-emerald-50 text-emerald-800 border-emerald-200",
  completed: "bg-emerald-50 text-emerald-800 border-emerald-200",
  pending_approval: "bg-amber-50 text-amber-800 border-amber-200",
  processing: "bg-blue-50 text-blue-800 border-blue-200",
  parsing: "bg-blue-50 text-blue-800 border-blue-200",
  chunking: "bg-blue-50 text-blue-800 border-blue-200",
  indexing: "bg-blue-50 text-blue-800 border-blue-200",
  verifying: "bg-blue-50 text-blue-800 border-blue-200",
  queued: "bg-blue-50 text-blue-800 border-blue-200",
  failed: "bg-red-50 text-red-800 border-red-200",
  withdrawn: "bg-slate-100 text-slate-700 border-slate-200",
};

export const StatusBadge = ({ status, testid }) => (
  <span data-testid={testid} className={`inline-flex whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-semibold ${STYLES[status] ?? "bg-slate-100 text-slate-700 border-slate-200"}`}>
    {String(status).replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase())}
  </span>
);
