import { motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, ChevronDown, FileSearch, Loader2, MessageCircle, RotateCcw, SearchX, Unplug } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../ui/collapsible";
import { AnswerText } from "./AnswerText";

const STATES = {
  no_evidence: { icon: SearchX, tone: "amber", title: "No relevant policy evidence found", text: "The published documents don't appear to cover this question, so no answer was given.", next: "Try naming the type of policy, or use words from the policy such as “exclusions” or “room rent”." },
  insufficient_evidence: { icon: FileSearch, tone: "amber", title: "Not enough evidence to answer reliably", text: "Some passages were found, but they don't clearly answer the question.", next: "Ask a narrower question, for example about one benefit or one exclusion." },
  conversational: { icon: MessageCircle, tone: "slate", title: "General reply", text: "This reply didn't use policy documents, so it has no citations." },
  offline: { icon: Unplug, tone: "slate", title: "The assistant can't answer this right now", text: "Live answers are temporarily unavailable.", next: "Try one of the suggested questions, or come back a little later." },
};
const tones = { amber: "border-amber-200 bg-amber-50 text-amber-900", slate: "border-slate-200 bg-slate-50 text-slate-800", red: "border-red-200 bg-red-50 text-red-900" };

const StateBox = ({ s, testid, children }) => (
  <div data-testid={testid} className={`rounded-xl border p-4 ${tones[s.tone]}`}>
    <p className="flex items-center gap-2 text-sm font-semibold"><s.icon size={16} /> {s.title}</p>
    <p className="mt-1 text-sm opacity-90">{s.text}</p>
    {s.next && <p className="mt-2 text-sm"><span className="font-semibold">Next: </span>{s.next}</p>}
    {children}
  </div>
);

const Progress = ({ stages }) => (
  <div data-testid="reasoning-progress-stepper" className="rounded-xl border border-blue-100 bg-blue-50/60 p-4" aria-live="polite">
    <p className="flex items-center gap-2 text-sm font-semibold text-blue-900"><Loader2 size={16} className="animate-spin" />
      Working on your answer. This can take a little while.
    </p>
    {stages.length > 0 && (
      <ol className="mt-3 space-y-1.5">
        {stages.map((s, i) => {
          const current = i === stages.length - 1;
          return (
            <li key={`${s}-${i}`} className={`flex items-center gap-2 text-[13px] ${current ? "font-medium text-blue-800" : "text-slate-600"}`}>
              {current ? <span className="h-2 w-2 animate-pulse rounded-full bg-blue-600" /> : <CheckCircle2 size={14} className="text-emerald-600" />}{s}
            </li>
          );
        })}
      </ol>
    )}
  </div>
);

const HowFound = ({ trace, index }) => (
  <Collapsible className="border-t border-slate-100 pt-1">
    <CollapsibleTrigger data-testid={`how-found-accordion-${index}`} className="group flex w-full items-center gap-2 py-2 text-[13px] font-medium text-slate-600 transition-colors hover:text-slate-900">
      <ChevronDown size={15} className="transition-transform group-data-[state=open]:rotate-180" /> How this answer was found
    </CollapsibleTrigger>
    <CollapsibleContent>
      {trace.length === 0 ? <p className="pb-2 text-[13px] text-slate-500">The backend didn't return trace details for this answer.</p> : (
        <ol className="mb-2 space-y-2 rounded-lg bg-slate-50 p-3" data-testid={`how-found-steps-${index}`}>
          {trace.map((t, i) => (
            <li key={i} className="flex gap-2.5 text-[13px]">
              <span className="font-mono text-slate-400">{i + 1}.</span>
              <span className="text-slate-800">{t.label}{t.detail && <span className="block text-slate-500">{t.detail}</span>}</span>
            </li>
          ))}
        </ol>
      )}
    </CollapsibleContent>
  </Collapsible>
);

export const AssistantMessage = ({ msg, index, activeCitation, onCite, onShowSources, onRetry, isDesktop }) => {
  const r = msg.result;
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }} data-testid={`assistant-message-${index}`} className="space-y-3">
      {msg.pending && <Progress stages={msg.stages} />}
      {msg.error && (
        <StateBox testid={`error-state-${index}`} s={{ icon: AlertTriangle, tone: "red", title: "The request didn't go through", text: `${msg.error} No answer was produced.` }}>
          <button onClick={onRetry} data-testid={`retry-button-${index}`} className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-red-700 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-red-800"><RotateCcw size={13} /> Try again</button>
        </StateBox>
      )}
      {r && STATES[r.status] && <StateBox s={STATES[r.status]} testid={`status-${r.status}-${index}`} />}
      {r && r.answer && (
        <div className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
          {r.status === "answered" && r.citations.length > 0 && (
            <p className="mb-3 inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-800" data-testid={`grounded-badge-${index}`}>
              <CheckCircle2 size={13} /> Based on {r.citations.length} policy {r.citations.length === 1 ? "passage" : "passages"}
            </p>
          )}
          <AnswerText text={r.answer} msgIndex={index} ids={r.citations.map((c) => c.id)} activeId={activeCitation} onCite={onCite} />
          {r.limitations.length > 0 && (
            <ul className="mt-4 space-y-1 rounded-lg bg-slate-50 p-3 text-[13px] text-slate-600" data-testid={`limitations-${index}`}>
              {r.limitations.map((l) => <li key={l}><span className="font-semibold text-slate-700">Note: </span>{l}</li>)}
            </ul>
          )}
          {r.citations.length > 0 && !isDesktop && (
            <button onClick={onShowSources} data-testid={`view-sources-button-${index}`} className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-lg border border-slate-300 py-2 text-sm font-semibold text-slate-800 transition-colors hover:bg-slate-50">
              <FileSearch size={15} /> View {r.citations.length} {r.citations.length === 1 ? "source" : "sources"}
            </button>
          )}
          <div className="mt-3"><HowFound trace={r.trace} index={index} /></div>
        </div>
      )}
      {r && !r.answer && r.trace.length > 0 && <HowFound trace={r.trace} index={index} />}
    </motion.div>
  );
};
