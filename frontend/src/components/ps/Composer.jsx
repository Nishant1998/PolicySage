import { useState } from "react";
import { ArrowUp, Loader2 } from "lucide-react";

export const Composer = ({ onSend, busy, large = false }) => {
  const [text, setText] = useState("");
  const submit = (e) => {
    e.preventDefault();
    const q = text.trim();
    if (!q || busy) return;
    onSend(q);
    setText("");
  };
  const onKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) submit(e);
  };
  return (
    <form onSubmit={submit} data-testid="question-composer"
      className={`flex items-end gap-2 rounded-2xl border border-slate-300 bg-white p-2 shadow-sm transition-shadow focus-within:border-blue-500 focus-within:ring-4 focus-within:ring-blue-100 ${large ? "shadow-[0_10px_30px_-12px_rgba(15,23,42,0.25)]" : ""}`}>
      <label htmlFor="question" className="sr-only">Your insurance question</label>
      <textarea id="question" rows={large ? 2 : 1} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey}
        data-testid="question-textarea" placeholder="Ask about an insurance policy…"
        className="max-h-36 min-h-[44px] flex-1 resize-none bg-transparent px-2 py-2.5 text-[15px] text-slate-900 outline-none placeholder:text-slate-400" />
      <button type="submit" disabled={busy || !text.trim()} data-testid="send-question-button"
        className="inline-flex h-11 items-center gap-1.5 rounded-xl bg-blue-600 px-4 text-sm font-semibold text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300">
        {busy ? <Loader2 size={16} className="animate-spin" /> : <ArrowUp size={16} />} Ask
      </button>
    </form>
  );
};
