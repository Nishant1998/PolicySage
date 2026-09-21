import { Link } from "react-router-dom";
import { ArrowLeft, ArrowRight, Github, Globe } from "lucide-react";
import { Header } from "../components/ps/Header";
import { Footer } from "../components/ps/Footer";
import { ArchitectureDiagram } from "../components/ps/ArchitectureDiagram";
import { LINKS } from "../lib/config";

const capabilities = [
  ["Hybrid search", "Semantic and BM25 keyword search retrieve candidate policy passages, which are combined and reranked."],
  ["Evidence before answers", "Retrieved evidence is assessed before a grounded answer is generated. The app can search selected official websites when policy evidence is insufficient."],
  ["Answers you can check", "References include the document, an excerpt and page details when available."],
  ["Admin workflow", "Upload documents and revisions, approve review-required revisions, retry failed jobs and withdraw documents."],
];

const decisions = [
  ["Hybrid search", "Policy wording rarely matches how people ask. Semantic matching finds passages phrased differently from the question, while BM25 still catches exact terms such as “co-payment” or “room rent”."],
  ["PostgreSQL as the publication authority", "PostgreSQL tracks which revisions are published. The knowledge-base search filters Qdrant to eligible revisions, excluding withdrawn and unapproved revisions."],
];

const H2 = ({ children }) => <h2 className="font-display text-lg font-bold tracking-tight text-slate-900 sm:text-xl">{children}</h2>;
const btnPrimary = "inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-blue-700";
const btnSecondary = "inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-800 transition-colors hover:bg-slate-50";

const Links = ({ prefix }) => (
  <div className="flex flex-wrap items-center gap-2">
    <Link to="/" data-testid={`${prefix}-live-demo-button`} className={btnPrimary}>Live Demo <ArrowRight size={15} aria-hidden="true" /></Link>
    <a href={LINKS.github} data-testid={`${prefix}-github-link`} className={btnSecondary}><Github size={15} aria-hidden="true" /> GitHub</a>
    <a href={LINKS.portfolio} data-testid={`${prefix}-portfolio-link`} className="inline-flex items-center gap-1.5 px-2 text-sm font-medium text-slate-700 underline-offset-4 hover:text-slate-900 hover:underline"><Globe size={15} aria-hidden="true" /> Portfolio</a>
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
            PolicySage lets people ask plain-English questions about Indian insurance and inspect the evidence used in supported answers. Policy citations can include an excerpt and page number. When policy evidence is insufficient, the app can search selected public sources or explain that it could not find enough evidence.
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
            An admin can upload a PDF, which is registered in PostgreSQL and stored in object storage. A separate worker parses, chunks and indexes it in Qdrant. FastAPI receives questions and LangGraph coordinates routing, retrieval, evidence assessment and answer generation. If policy evidence is insufficient, the app can search selected public sources.
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

        <section className="mt-14" data-testid="about-evaluation">
          <H2>Evaluation and limitations</H2>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
              <p className="text-sm font-semibold text-amber-900">Evaluation</p>
              <p className="mt-1 text-sm leading-relaxed text-amber-900/90">The workflow has been tested with sample questions and controlled cases. A comprehensive accuracy evaluation is not complete, so no accuracy figure is claimed.</p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <p className="text-sm font-semibold text-slate-900">Limitations</p>
              <p className="mt-1 text-sm leading-relaxed text-slate-600">Answers depend on available policy documents and public sources. Retrieval or generated answers can be incomplete or incorrect. Policy terms vary by insurer, product and revision, so check your own policy wording.</p>
            </div>
          </div>
        </section>

        <section className="mt-14 rounded-2xl border border-slate-200 bg-slate-50 p-5 sm:p-6">
          <p className="font-display text-base font-semibold text-slate-900">Try the live demo, or explore the code on GitHub.</p>
          <div className="mt-4"><Links prefix="about-bottom" /></div>
        </section>
      </main>
      <Footer />
    </div>
  );
}
