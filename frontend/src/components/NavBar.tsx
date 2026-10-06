import { NavLink } from "react-router-dom";

const links = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/prospects", label: "Prospects" },
  { to: "/disqualified", label: "Disqualified" },
  { to: "/qualification-settings", label: "Qualification" },
];

function linkClass(isActive: boolean): string {
  return [
    "px-3 py-2 rounded-md text-sm font-medium transition-colors",
    isActive
      ? "bg-brand-600 text-white"
      : "text-slate-600 hover:bg-slate-200 hover:text-slate-900",
  ].join(" ");
}

export default function NavBar() {
  return (
    <header className="bg-white border-b border-slate-200">
      <div className="mx-auto max-w-6xl px-4 py-3 flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <span className="text-lg font-semibold text-slate-900">
            Prospect Research Agent
          </span>
          <span className="hidden sm:inline text-xs text-slate-400 border border-slate-200 rounded px-1.5 py-0.5">
            internal tool
          </span>
        </div>
        <nav className="flex items-center gap-1">
          {links.map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              end={l.end}
              className={({ isActive }) => linkClass(isActive)}
            >
              {l.label}
            </NavLink>
          ))}
        </nav>
      </div>
    </header>
  );
}
