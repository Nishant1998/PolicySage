import { Link } from "react-router-dom";
import { ArrowLeft, ArrowRight, Github, Globe } from "lucide-react";
import { Header } from "../components/ps/Header";
import { Footer } from "../components/ps/Footer";
import { ArchitectureDiagram } from "../components/ps/ArchitectureDiagram";
import { LINKS } from "../lib/config";

const capabilities = [
  ["Hybrid search", "Semantic search finds policy information by meaning, while BM25 helps match specific insurance terms and policy identifiers. Results are combined and reranked to find relevant passages."],
  ["Evidence-aware answers", "The system assesses retrieved evidence before generating an answer. If policy evidence is insufficient, it can search selected official websites or explain that reliable information is unavailable."],
  ["Source citations", "Answers include references with document titles, excerpts, and page numbers when available. Accessible source links let users inspect the original documents."],
  ["Document management", "Admins can upload and replace policy PDFs, review and approve revisions, retry failed processing jobs, and withdraw outdated documents."],
];

const decisions = [
  ["Hybrid search", "Semantic search finds relevant policy information even when the user's question uses different wording. BM25 complements it by prioritizing specific keywords, insurance terms, and policy identifiers that semantic search might miss. Both results are combined and reranked to improve retrieval."],
  ["Controlled document publication", "PostgreSQL tracks active and review-required revisions. Retrieval is restricted to eligible revisions, so new questions do not use withdrawn or unapproved policy versions."],
  ["Practical safeguards", "Request and token limits control resource use. External web queries use best-effort redaction of common personal identifiers, and cached answers are checked against document revision context."],
];

const H2 = ({ children }) => <h2 className="font-display text-lg font-bold tracking-tight text-slate-900 sm:text-xl">{children}</h2>;
const btnPrimary = "inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-blue-700";
const btnSecondary = "inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-800 transition-colors hover:bg-slate-50";

const Links = ({ prefix }) => (
  <div className="flex flex-wrap items-center gap-2">
    <Link to="/" data-testid={`${prefix}-live-demo-button`} className={btnPrimary}>Live Demo <ArrowRight size={15} aria-hidden="true" /></Link>
    {LINKS.github && <a href={LINKS.github} data-testid={`${prefix}-github-link`} className={btnSecondary}><Github size={15} aria-hidden="true" /> GitHub</a>}
    {LINKS.portfolio && <a href={LINKS.portfolio} data-testid={`${prefix}-portfolio-link`} className="inline-flex items-center gap-1.5 px-2 text-sm font-medium text-slate-700 underline-offset-4 hover:text-slate-900 hover:underline"><Globe size={15} aria-hidden="true" /> Portfolio</a>}
  </div>
);

export default function AboutPage() {
  return (
    <div className="flex min-h-[100dvh] flex-col bg-white">
      <Header />
      <main className="mx-auto w-full max-w-4xl flex-1 px-4 pb-16 pt-8 sm:pt-12" data-testid="about-page">
        <Link to="/" data-testid="about-back-link" className="inline-flex items-center gap-1.5 text-sm font-medium text-slate-600 hover:text-slate-900">
          <ArrowLeft size={15} aria-hidden="true" /> Back to the live demo
        </Link>

        <section className="mt-6">
          <p className="font-mono text-xs uppercase tracking-wider text-blue-700">About Project</p>
          <h1 className="font-display mt-2 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">PolicySage</h1>
          <p className="mt-4 max-w-2xl text-base leading-relaxed text-slate-700 sm:text-lg" data-testid="about-overview">
            Insurance policy documents can be lengthy and difficult to understand. <strong>PolicySage is an Agentic RAG application</strong> that helps users ask questions about Indian insurance policies in plain English and verify answers against supporting sources.
          </p>
          <p className="mt-3 max-w-2xl text-base leading-relaxed text-slate-700 sm:text-lg">
            Built with LangGraph, it adapts its workflow based on the question and available evidence. It can break complex questions into smaller searches, combine semantic and keyword retrieval, rerank relevant passages, and assess evidence quality. When policy information is insufficient, it can search selected official websites, refine queries, or explain that reliable evidence is unavailable.
          </p>
          <div className="mt-6"><Links prefix="about-top" /></div>
        </section>

        <section className="mt-14">
          <H2>Key capabilities</H2>
          <div className="mt-4 grid gap-3 sm:grid-cols-2" data-testid="about-capabilities">
            {capabilities.map(([t, d]) => (
              <div key={t} className="rounded-xl border border-slate-200 p-4">
                <h3 className="text-sm font-semibold text-slate-900">{t}</h3>
                <p className="mt-1 text-sm leading-relaxed text-slate-600">{d}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="mt-14">
          <H2>How it works</H2>
          <p className="mt-3 max-w-2xl text-[15px] leading-relaxed text-slate-700">
            PolicySage separates document ingestion from live question answering. A background worker processes insurance PDFs and indexes them for retrieval, while LangGraph coordinates an adaptive workflow that retrieves, evaluates and refines evidence before generating an answer.
          </p>
          <div className="mt-5"><ArchitectureDiagram /></div>
        </section>

        <section className="mt-14">
          <H2>Engineering decisions</H2>
          <div className="mt-4 space-y-4" data-testid="about-decisions">
            {decisions.map(([t, d]) => (
              <div key={t} className="border-l-2 border-blue-600 pl-4">
                <h3 className="text-sm font-semibold text-slate-900">{t}</h3>
                <p className="mt-1 text-sm leading-relaxed text-slate-600">{d}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="mt-14" data-testid="about-limitations">
          <H2>Limitations</H2>
          <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
            <p className="text-sm leading-relaxed text-slate-600">Answers depend on the available insurance documents and selected official sources. Information may be incomplete or incorrect, so users should verify important details against the applicable original policy.</p>
          </div>
        </section>

        <section className="mt-14 rounded-2xl border border-slate-200 bg-slate-50 p-5 sm:p-6">
          <p className="font-display text-base font-semibold text-slate-900">Try the live demo{LINKS.github && ", or explore the code on GitHub"}.</p>
          <div className="mt-4"><Links prefix="about-bottom" /></div>
        </section>
      </main>
      <Footer />
    </div>
  );
}
