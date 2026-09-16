export const Logo = ({ size = 28 }) => (
  <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
    <rect width="32" height="32" rx="8" fill="#0F172A" />
    <path d="M10 8h9l4 4v12H10z" fill="#fff" />
    <path d="M19 8v4h4" fill="none" stroke="#0F172A" strokeWidth="1.4" />
    <rect x="12.5" y="15" width="8" height="2" rx="1" fill="#2563EB" />
    <rect x="12.5" y="19" width="5" height="2" rx="1" fill="#94A3B8" />
  </svg>
);

export const ExampleBadge = ({ children = "Example", testid }) => (
  <span data-testid={testid} className="inline-flex items-center rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-amber-800">
    {children}
  </span>
);

export const pageText = (c) => {
  if (!c?.pageStart) return null;
  return c.pageEnd && c.pageEnd !== c.pageStart ? `pp. ${c.pageStart}–${c.pageEnd}` : `p. ${c.pageStart}`;
};
