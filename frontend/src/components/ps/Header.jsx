import { Link, NavLink, useLocation } from "react-router-dom";
import { Logo } from "./Bits";

const navText = ({ isActive }) =>
  `whitespace-nowrap rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors ${isActive ? "bg-slate-100 text-slate-900" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"}`;

export const Header = () => {
  const { pathname } = useLocation();
  const onAdmin = pathname.startsWith("/admin");
  return (
    <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/85 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-2 px-4">
        <Link to="/" data-testid="app-logo" className="flex items-center gap-2.5">
          <Logo />
          <span className="font-display text-lg font-bold tracking-tight text-slate-900">PolicySage</span>
          {onAdmin && <span className="rounded-md bg-slate-900 px-2 py-0.5 text-[11px] font-semibold text-white">Admin</span>}
        </Link>
        <nav className="ml-auto flex items-center gap-1 sm:gap-2" aria-label="Main">
          {pathname !== "/" && <span className="hidden sm:inline"><NavLink to="/" end data-testid="live-demo-nav-link" className={navText}>Live Demo</NavLink></span>}
          <NavLink to="/about" data-testid="about-nav-link" className={navText}>About Project</NavLink>
          <NavLink to="/admin" data-testid="admin-nav-link"
            className={({ isActive }) => `rounded-md border px-2.5 py-1 text-xs font-medium transition-colors ${isActive ? "border-slate-300 bg-slate-100 text-slate-900" : "border-slate-200 text-slate-600 hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900"}`}>
            Admin
          </NavLink>
        </nav>
      </div>
    </header>
  );
};
