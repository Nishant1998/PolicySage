import { Github, Globe } from "lucide-react";
import { LINKS } from "../../lib/config";

const link = "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900";

export const Footer = () => (
  <footer data-testid="site-footer" className="border-t border-slate-200 bg-white">
    <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3">
      <p className="text-xs text-slate-500">PolicySage · Answers come from published policy documents and aren't financial or legal advice.</p>
      <nav className="ml-auto flex items-center gap-1" aria-label="Project links">
        <a href={LINKS.github} data-testid="github-repo-link" className={link}><Github size={14} aria-hidden="true" /> GitHub</a>
        <a href={LINKS.portfolio} data-testid="portfolio-link" className={link}><Globe size={14} aria-hidden="true" /> Portfolio</a>
      </nav>
    </div>
  </footer>
);
