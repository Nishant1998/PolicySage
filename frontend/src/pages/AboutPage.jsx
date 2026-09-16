import { Link } from "react-router-dom";
import { ArrowLeft, ArrowRight, Github, Globe } from "lucide-react";
import { Header } from "../components/ps/Header";
import { Footer } from "../components/ps/Footer";
import { ArchitectureDiagram } from "../components/ps/ArchitectureDiagram";
import { LINKS } from "../lib/config";

const capabilities = [
  ["Hybrid search", "Semantic and BM25 keyword search find relevant policy passages, even when the wording differs from the question."],
  ["Evidence before answers", "Passages are reranked and the evidence is assessed before an answer is generated."],
  ["Answers you can check", "References include the document, an excerpt and page details when available."],
  ["Admin workflow", "Upload documents and revisions, review and publish them, retry failed jobs and withdraw documents."],
];

const decisions = [
  ["Hybrid search", "Policy wording rarely matches how people ask. Semantic matching finds passages phrased differently from the question, while BM25 still catches exact terms such as “co-payment” or “room rent”."],
  ["PostgreSQL as the publication authority", "Qdrant can hold chunks from many revisions, but PostgreSQL decides which are published. Retrieval only considers eligible revisions, so withdrawn or unapproved documents stay out of answers."],
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
            PolicySage lets people ask plain-English questions about Indian insurance policy documents and inspect the passages behind each answer. Answers come with references to the document, excerpt and page. They depend on the documents available to the application, and it says so when evidence is missing.
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
            Documents and questions follow two paths. An admin's PDF is stored in object storage and registered in PostgreSQL. A separate ingestion worker then parses, chunks and indexes it in Qdrant. When someone asks a question, FastAPI receives it and LangGraph coordinates retrieval, evidence selection and answer generation. PostgreSQL decides which revisions are published, so only eligible chunks are searched.
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
              <p className="text-sm font-semibold text-amber-900">Evaluation in progress</p>
              <p className="mt-1 text-sm leading-relaxed text-amber-900/90">Formal evaluation is not complete, so no accuracy figures are claimed. Results and the method will be published in the GitHub repository.</p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <p className="text-sm font-semibold text-slate-900">Limitations</p>
              <p className="mt-1 text-sm leading-relaxed text-slate-600">Answers are limited to the available documents. Policy terms vary by insurer, product and revision, so check your own policy wording.</p>
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
