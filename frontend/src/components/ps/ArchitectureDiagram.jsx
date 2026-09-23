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
        { title: "Upload PDFs", role: "Store originals in object storage and register revisions" },
        { title: "Process documents", role: "Background worker parses, chunks and embeds PDFs" },
        { title: "Index in Qdrant", role: "Store passages for semantic and BM25 search" },
      ]} />
      <div className="flex items-center gap-3 rounded-lg border border-dashed border-slate-300 bg-white px-3 py-2.5" data-testid="diagram-postgres">
        <span className="shrink-0 rounded-md bg-slate-900 px-2 py-1 font-mono text-[11px] font-semibold text-white">PostgreSQL</span>
        <p className="text-xs leading-snug text-slate-700">Tracks document revisions and publication status; retrieval is restricted to eligible revisions.</p>
      </div>
      <Lane label="Question answering · live" testid="diagram-question-lane" steps={[
        { title: "Route question", role: "FastAPI receives the question; LangGraph selects a path and can decompose it" },
        { title: "Retrieve and assess evidence", role: "Hybrid search, fusion, reranking and evidence grading" },
        { title: "Generate response", role: "Provide available references or explain missing evidence", accent: true },
      ]} />
      <div className="flex items-center justify-center gap-1 text-xs font-medium text-slate-600">
        <ArrowDown size={14} aria-hidden="true" /> Conditional paths
      </div>
      <div className="grid gap-3 md:grid-cols-2" aria-label="Conditional question-answering paths">
        <div className="rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-xs leading-snug text-slate-700">
          <span className="font-semibold text-slate-900">Direct path:</span> Some questions receive a direct answer or clarification without document retrieval.
        </div>
        <div className="rounded-lg border border-dashed border-blue-300 bg-blue-50 px-3 py-2.5 text-xs leading-snug text-slate-700">
          <span className="font-semibold text-blue-900">If evidence is insufficient:</span> Search selected official websites when permitted and assess the results. Within retry limits and budgets, rewrite the query and repeat research through the knowledge base and web. Disclose limitations if evidence remains insufficient.
        </div>
      </div>
    </div>
    <figcaption className="mt-4 text-xs text-slate-500">High-level view. Modules, graph nodes and API routes are left out.</figcaption>
  </figure>
);
