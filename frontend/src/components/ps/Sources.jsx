import { useEffect, useId, useRef, useState } from "react";
import { ExternalLink, FileX, Lock, FileQuestion, Info } from "lucide-react";
import { pageText } from "./Bits";

const Note = ({ icon: Icon, children, testid }) => (
  <p data-testid={testid} className="flex items-start gap-1.5 text-xs text-slate-600"><Icon size={14} className="mt-px shrink-0 text-slate-500" />{children}</p>
);

const isPdfUrl = (url) => {
  if (!url) return false;
  try {
    return /\.pdf$/i.test(decodeURIComponent(new URL(url, window.location.origin).pathname));
  } catch {
    return false;
  }
};

const SourceAction = ({ c, pdf, testid }) => {
  const page = c.pageStart;
  if (c.access === "restricted") return <Note icon={Lock} testid={testid}>Public access to this PDF is disabled.</Note>;
  if (c.access === "unavailable") return <Note icon={FileX} testid={testid}>The source file is currently unavailable.</Note>;
  if (!c.sourceUrl) return <Note icon={FileQuestion} testid={testid}>No source link available{page ? `. Cited on page ${page}.` : "."}</Note>;
  const jump = pdf && c.pageNav !== false && page;
  return (
    <div className="space-y-1.5">
      <a href={jump ? `${c.sourceUrl.split("#")[0]}#page=${page}` : c.sourceUrl} target="_blank" rel="noopener noreferrer" data-testid={testid}
        onClick={(e) => e.stopPropagation()}
        className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-slate-700">
        <ExternalLink size={13} /> {pdf ? "Open source PDF" : "Open website"}{jump ? ` at page ${page}` : ""}
      </a>
      {pdf && c.pageNav === false && page && <Note icon={Info}>Opens at the start of the PDF. Go to page {page}.</Note>}
    </div>
  );
};

export const SourceCard = ({ c, active, onSelect, scope }) => {
  const ref = useRef(null);
  useEffect(() => {
    if (active) ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [active]);
  const pages = pageText(c);
  const pdf = isPdfUrl(c.sourceUrl);
  const [expanded, setExpanded] = useState(false);
  const excerptId = useId();
  const excerpt = c.excerpt?.trim();
  const preview = excerpt?.replace(/\s+/g, " ");
  const longExcerpt = preview?.length > 220;
  const visibleText = longExcerpt && !expanded ? preview.slice(0, 220).trimEnd() + "…" : excerpt;
  return (
    <article ref={ref} onClick={onSelect} data-testid={`source-card-${scope}-${c.id}`}
      className={`cursor-pointer rounded-xl border bg-white p-4 transition-colors ${active ? "border-blue-500 ring-4 ring-blue-100" : "border-slate-200 hover:border-slate-400"}`}>
      <div className="flex items-start gap-2.5">
        <span className={`flex h-6 min-w-[24px] items-center justify-center rounded-md font-mono text-xs font-semibold ${active ? "bg-blue-600 text-white" : "bg-blue-50 text-blue-700"}`}>{c.id}</span>
        <h4 className="flex-1 text-sm font-semibold leading-snug text-slate-900">{c.title ?? "Untitled source"}</h4>
        {(pages || c.sourceUrl) && <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-700">{c.sourceUrl && !pdf ? "Website" : pages ?? "PDF"}</span>}
      </div>
      {excerpt
        ? <blockquote id={excerptId} className={`mt-3 whitespace-pre-wrap break-words border-l-2 pl-3 text-[13px] leading-relaxed text-slate-700 ${active ? "border-blue-500 bg-blue-50/60 py-1" : "border-slate-200"}`}>“{visibleText}”</blockquote>
        : <p className="mt-3 text-xs italic text-slate-500">No excerpt was returned for this source.</p>}
      {longExcerpt && (
        <button type="button" aria-expanded={expanded} aria-controls={excerptId}
          onClick={(event) => { event.stopPropagation(); setExpanded(!expanded); }}
          className="mt-2 rounded px-1 text-xs font-semibold text-blue-700 hover:underline">
          {expanded ? "Collapse" : "Expand"}
        </button>
      )}
      <div className="mt-3"><SourceAction c={c} pdf={pdf} testid={`open-source-button-${scope}-${c.id}`} /></div>
    </article>
  );
};

export const SourcesList = ({ citations, activeId, onSelect, scope }) => (
  <div className="space-y-3">
    {citations.map((c) => <SourceCard key={c.id} c={c} scope={scope} active={activeId === c.id} onSelect={() => onSelect(c.id)} />)}
  </div>
);
