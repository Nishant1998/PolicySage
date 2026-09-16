import { ArrowDown, ArrowRight } from "lucide-react";

const Node = ({ title, role, accent }) => (
  <div className={`rounded-lg border bg-white px-3 py-2.5 ${accent ? "border-blue-300 ring-2 ring-blue-50" : "border-slate-200"}`}>
    <p className="text-sm font-semibold text-slate-900">{title}</p>
    {role && <p className="mt-0.5 text-xs leading-snug text-slate-600">{role}</p>}
  </div>
);

const Arrow = () => (
  <div className="flex items-center justify-center text-slate-400" aria-hidden="true">
    <ArrowDown size={16} className="md:hidden" /><ArrowRight size={16} className="hidden md:block" />
  </div>
);

const Lane = ({ label, steps, testid }) => (
  <div data-testid={testid}>
    <p className="mb-2 font-mono text-[11px] uppercase tracking-wider text-slate-500">{label}</p>
    <div className="grid gap-2 md:grid-cols-[1fr_auto_1fr_auto_1fr] md:items-stretch">
      {steps.flatMap((s, i) => [<Node key={s.title} {...s} />, i < steps.length - 1 && <Arrow key={`a${i}`} />]).filter(Boolean)}
    </div>
  </div>
);

export const ArchitectureDiagram = () => (
  <figure data-testid="architecture-diagram" className="rounded-2xl border border-slate-200 bg-slate-50 p-4 sm:p-6">
    <div className="space-y-5">
      <Lane label="Ingestion · background" testid="diagram-ingestion-lane" steps={[
        { title: "Policy PDFs", role: "Original files kept in object storage" },
        { title: "Parse and chunk", role: "Separate ingestion worker processes queued documents" },
        { title: "Index in Qdrant", role: "Searchable chunks for dense and BM25 retrieval" },
      ]} />
      <div className="flex items-center gap-3 rounded-lg border border-dashed border-slate-300 bg-white px-3 py-2.5" data-testid="diagram-postgres">
        <span className="shrink-0 rounded-md bg-slate-900 px-2 py-1 font-mono text-[11px] font-semibold text-white">PostgreSQL</span>
        <p className="text-xs leading-snug text-slate-700">Tracks revisions and publication status, and decides which revisions may be searched.</p>
      </div>
      <Lane label="Question answering · live" testid="diagram-question-lane" steps={[
        { title: "User question", role: "Received by FastAPI; LangGraph coordinates the workflow" },
        { title: "Retrieve and select evidence", role: "Hybrid search over eligible revisions, then reranking" },
        { title: "Answer with citations", role: "References with excerpts and pages when available", accent: true },
      ]} />
    </div>
    <figcaption className="mt-4 text-xs text-slate-500">High-level view. Modules, graph nodes and API routes are left out.</figcaption>
  </figure>
);
