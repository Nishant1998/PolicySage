import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

function citationPlugin(ids) {
  const allowed = new Set(ids);
  function visit(node) {
    if (!node.children || ["link", "linkReference", "code", "inlineCode"].includes(node.type)) return;
    node.children = node.children.flatMap((child) => {
      if (child.type !== "text") {
        visit(child);
        return [child];
      }
      return child.value.split(/(\[[A-Za-z]?\d+\])/g).filter(Boolean).map((part) => {
        const id = part.match(/^\[([A-Za-z]?\d+)\]$/)?.[1];
        return id && allowed.has(id)
          ? { type: "link", url: `#citation-${id}`, children: [{ type: "text", value: part }] }
          : { type: "text", value: part };
      });
    });
  }
  return (tree) => visit(tree);
}

export const AnswerText = ({ text, ids, activeId, onCite, msgIndex }) => (
  <div className="space-y-3 text-[15px] leading-relaxed text-slate-700" data-testid={`answer-text-${msgIndex}`}>
    <ReactMarkdown remarkPlugins={[remarkGfm, [citationPlugin, ids]]} components={{
      h1: ({ node, ...props }) => <h3 className="font-display text-base font-semibold text-slate-900" {...props} />,
      h2: ({ node, ...props }) => <h3 className="font-display text-base font-semibold text-slate-900" {...props} />,
      h3: ({ node, ...props }) => <h3 className="font-display text-base font-semibold text-slate-900" {...props} />,
      p: ({ node, ...props }) => <p className="my-3" {...props} />,
      ul: ({ node, ...props }) => <ul className="my-3 list-disc space-y-1.5 pl-5" {...props} />,
      ol: ({ node, ...props }) => <ol className="my-3 list-decimal space-y-1.5 pl-5" {...props} />,
      table: ({ node, ...props }) => (
        <div className="my-3 max-w-full overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full min-w-[32rem] border-collapse text-left text-sm" {...props} />
        </div>
      ),
      th: ({ node, ...props }) => <th className="border-b border-slate-200 bg-slate-50 px-3 py-2 align-top font-semibold text-slate-900" {...props} />,
      td: ({ node, ...props }) => <td className="border-b border-slate-100 px-3 py-2 align-top" {...props} />,
      a: ({ node, href, children, ...props }) => {
        const id = href?.match(/^#citation-([A-Za-z]?\d+)$/)?.[1];
        if (!id || !ids.includes(id)) return <a href={href} {...props}>{children}</a>;
        return (
          <button type="button" onClick={() => onCite(id)} data-testid={`citation-marker-${msgIndex}-${id}`}
            aria-label={`Show source ${id}`}
            className={`mx-0.5 inline-flex h-5 min-w-[22px] -translate-y-px items-center justify-center rounded-md border px-1 font-mono text-[11px] font-semibold ${activeId === id ? "border-blue-600 bg-blue-600 text-white" : "border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100"}`}>
            {id}
          </button>
        );
      },
    }}>
      {text ?? ""}
    </ReactMarkdown>
  </div>
);
