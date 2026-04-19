import { NavLink } from "react-router-dom";

const links = [
  { to: "/", label: "Dashboard", icon: "M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-4 0h4" },
  { to: "/?tab=agents", label: "Agents", icon: "M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" },
  { to: "/?tab=tasks", label: "Tasks", icon: "M9 5H7a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" },
  { to: "/?tab=governance", label: "Governance", icon: "M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" },
];

export default function Sidebar() {
  return (
    <aside className="flex w-60 flex-col border-r border-border bg-bg-sidebar">
      {/* Logo */}
      <div className="flex h-16 items-center gap-2.5 px-5">
        <div
          className="flex h-8 w-8 items-center justify-center rounded-xl text-sm font-semibold text-[#0d0d0d]"
          style={{ background: "linear-gradient(135deg, #18e299 0%, #d4fae8 100%)" }}
        >
          P
        </div>
        <span className="text-[15px] font-semibold tracking-tight">Code PLAY</span>
      </div>

      {/* Nav */}
      <div className="px-5 pt-4">
        <p className="mono-label">Workspace</p>
      </div>
      <nav className="flex-1 space-y-1 px-3 pt-2">
        {links.map((l) => (
          <NavLink
            key={l.label}
            to={l.to}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-full px-3 py-2 text-sm transition-colors ${
                isActive
                  ? "bg-[#0d0d0d] text-white font-medium"
                  : "text-text-muted hover:bg-bg-hover hover:text-text"
              }`
            }
          >
            <svg className="h-[18px] w-[18px] shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d={l.icon} />
            </svg>
            {l.label}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="border-t border-border p-5 text-[13px] text-text-muted">
        <p className="mono-label mb-1">Studio</p>
        <p>Multi-Agent Game Studio</p>
      </div>
    </aside>
  );
}
