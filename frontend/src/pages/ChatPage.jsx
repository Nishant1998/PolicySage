import { useEffect, useRef, useState } from "react";
import { FileText } from "lucide-react";
import { Header } from "../components/ps/Header";
import { Composer } from "../components/ps/Composer";
import { AssistantMessage } from "../components/ps/AssistantMessage";
import { SourcesList } from "../components/ps/Sources";
import { Footer } from "../components/ps/Footer";
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from "../components/ui/drawer";
import { askQuestion } from "../lib/api";
import { exampleQuestions } from "../lib/examples";
import { useIsDesktop } from "../hooks/use-desktop";

let nextId = 1;

const Welcome = ({ onSend, busy }) => (
  <div className="mx-auto w-full max-w-2xl px-4 pt-10 sm:pt-16" data-testid="welcome-panel">
    <h1 className="font-display text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">Understand insurance policies with evidence</h1>
    <p className="mt-2 text-[15px] text-slate-600">Ask a question and explore answers supported by policy documents.</p>
    <div className="mt-6"><Composer onSend={onSend} busy={busy} large /></div>
    <p className="mt-6 text-xs font-semibold uppercase tracking-wide text-slate-500">Suggested questions</p>
    <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
      {exampleQuestions.map((q, i) => (
        <button key={q} onClick={() => onSend(q)} data-testid={`example-question-chip-${i}`}
          className="rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-left text-sm text-slate-700 transition-colors hover:border-blue-400 hover:text-slate-900">
          {q}
        </button>
      ))}
    </div>
  </div>
);

const EmptySources = () => (
  <div className="flex h-full flex-col items-start justify-center p-8 text-slate-500" data-testid="sources-empty">
    <FileText size={22} className="text-slate-400" />
    <p className="mt-3 text-sm font-semibold text-slate-700">Sources appear here</p>
    <p className="mt-1 max-w-xs text-sm">After an answer arrives, you can check each cited passage, its page and the source PDF.</p>
  </div>
);

export default function ChatPage() {
  const [messages, setMessages] = useState([]);
  const [active, setActive] = useState({ msgId: null, citeId: null });
  const [drawerOpen, setDrawerOpen] = useState(false);
  const isDesktop = useIsDesktop();
  const endRef = useRef(null);

  useEffect(() => {
    const el = endRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [messages.length]);

  const patch = (id, data) => setMessages((m) => m.map((x) => (x.id === id ? { ...x, ...data } : x)));
  const busy = messages.some((m) => m.pending);

  const run = async (id, question, history) => {
    try {
      const result = await askQuestion({
        question,
        history,
        onStage: (s) => setMessages((m) => m.map((x) => (x.id === id && x.stages.at(-1) !== s ? { ...x, stages: [...x.stages, s] } : x))),
      });
      patch(id, { pending: false, result });
      if (result.citations.length) setActive({ msgId: id, citeId: null });
    } catch (e) {
      patch(id, { pending: false, error: e.message || "The request failed." });
    }
  };

  const send = (question) => {
    const history = messages.filter((m) => m.result?.answer?.trim())
      .map((m) => ({ question: m.question, answer: m.result.answer.slice(0, 4000) }))
      .slice(-4);
    const userId = nextId++;
    const id = nextId++;
    setMessages((m) => [...m, { id: userId, role: "user", text: question }, { id, role: "assistant", question, history, pending: true, stages: [] }]);
    run(id, question, history);
  };

  const retry = (msg) => {
    patch(msg.id, { pending: true, error: null, stages: [] });
    run(msg.id, msg.question, msg.history);
  };

  const cite = (msgId, citeId) => {
    setActive({ msgId, citeId });
    if (!isDesktop) setDrawerOpen(true);
  };

  const activeMsg = messages.find((m) => m.id === active.msgId);
  const citations = activeMsg?.result?.citations ?? [];
  const answerNumber = messages.filter((m) => m.role === "assistant").findIndex((m) => m.id === active.msgId) + 1;

  return (
    <div className="min-h-[100dvh] bg-slate-50">
      <Header />
      <div className="mx-auto grid h-[calc(100dvh-3.5rem)] w-full max-w-7xl gap-4 p-0 sm:p-4 lg:grid-cols-12">
        <section className="flex min-h-0 flex-col overflow-hidden bg-white sm:rounded-2xl sm:border sm:border-slate-200 lg:col-span-7" data-testid="chat-panel">
          <div ref={endRef} className="min-h-0 flex-1 overflow-y-auto" data-testid="chat-messages-container">
            {messages.length === 0 ? <Welcome onSend={send} busy={busy} /> : (
              <div className="mx-auto max-w-2xl space-y-6 px-4 py-6">
                {messages.map((m, i) => m.role === "user" ? (
                  <div key={m.id} data-testid={`user-message-${i}`} className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-md bg-slate-900 px-4 py-2.5 text-[15px] text-white">{m.text}</div>
                ) : (
                  <AssistantMessage key={m.id} msg={m} index={i} isDesktop={isDesktop}
                    activeCitation={active.msgId === m.id ? active.citeId : null}
                    onCite={(cid) => cite(m.id, cid)} onRetry={() => retry(m)}
                    onShowSources={() => { setActive({ msgId: m.id, citeId: null }); setDrawerOpen(true); }} />
                ))}
              </div>
            )}
          </div>
          {messages.length > 0 && (
            <div className="border-t border-slate-200 bg-slate-50/80 p-3 sm:p-4">
              <div className="mx-auto max-w-2xl"><Composer onSend={send} busy={busy} /></div>
            </div>
          )}
        </section>
        <aside className="hidden min-h-0 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-slate-100/70 lg:col-span-5 lg:flex" data-testid="sources-side-panel">
          <div className="flex items-center justify-between border-b border-slate-200 bg-white px-5 py-3.5">
            <h2 className="font-display text-sm font-semibold text-slate-900">Sources</h2>
            {citations.length > 0 && <span className="text-xs text-slate-500" data-testid="sources-panel-caption">{citations.length} cited in answer {answerNumber}</span>}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            {citations.length ? <SourcesList citations={citations} activeId={active.citeId} scope="panel" onSelect={(cid) => setActive((a) => ({ ...a, citeId: cid }))} /> : <EmptySources />}
          </div>
        </aside>
      </div>
      <Footer />
      {!isDesktop && (
        <Drawer open={drawerOpen} onOpenChange={setDrawerOpen}>
          <DrawerContent data-testid="sources-drawer" className="max-h-[85dvh]">
            <DrawerHeader className="text-left">
              <DrawerTitle>Sources</DrawerTitle>
              <DrawerDescription>{citations.length} cited in this answer. Tap a source to highlight it.</DrawerDescription>
            </DrawerHeader>
            <div className="overflow-y-auto px-4 pb-6">
              <SourcesList citations={citations} activeId={active.citeId} scope="drawer" onSelect={(cid) => setActive((a) => ({ ...a, citeId: cid }))} />
            </div>
          </DrawerContent>
        </Drawer>
      )}
    </div>
  );
}
