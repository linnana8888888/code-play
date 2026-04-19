import { useState } from "react";
import { useWebSocket } from "../../api/websocket";
import type { WsEvent } from "../../types/api";

interface Row {
  id: string;
  time: number;
  kind: string;
  actor: string;
  detail: string;
  accent: string;
}

function shorten(s: string, n = 80) {
  if (!s) return "";
  return s.length > n ? s.slice(0, n) + "…" : s;
}

function fmtTime(ms: number) {
  const d = new Date(ms);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

function toRows(e: WsEvent): Row[] {
  const t = Date.now();
  const id = `${t}-${Math.random().toString(36).slice(2, 8)}`;
  const d: any = e.data || {};
  // Mintlify light-mode accent palette (darker shades for contrast on white)
  const C = {
    ok: "text-[color:var(--color-accent-hover)]",
    muted: "text-text-subtle",
    danger: "text-[color:var(--color-danger)]",
    warn: "text-[color:var(--color-warning)]",
    info: "text-[color:var(--color-info)]",
    accent: "text-[color:var(--color-accent-hover)]",
  };
  switch (e.type) {
    case "agent_spawned":
      return [{
        id, time: t, kind: "spawn", accent: C.ok,
        actor: d.agent_type || d.id || "agent",
        detail: `spawned (${d.model || "?"})`,
      }];
    case "agent_terminated":
      return [{
        id, time: t, kind: "end", accent: C.muted,
        actor: d.id || "agent", detail: "terminated",
      }];
    case "agent_error": {
      // Classified: transient 5xx/429 → warn, budget_exhausted → warn,
      // permanent config stalls → danger, spawn drift → warn.
      const cat = d.failure_category as string | undefined;
      const accent = cat === "permanent" ? C.danger : cat ? C.warn : C.danger;
      const prefix = cat ? `[${cat}] ` : "";
      return [{
        id, time: t, kind: cat ? `err:${cat}` : "error", accent,
        actor: d.instance_id || "agent",
        detail: prefix + shorten(d.error || ""),
      }];
    }
    case "task_stalled": {
      // Broadcast by backend when a task enters BLOCKED with a stall reason
      // (permanent config, budget exhausted, upstream drift, etc.). Must be
      // visible in the feed so the operator can jump to Needs Attention.
      const cat = (d.failure_category as string) || "permanent";
      const accent = cat === "permanent" ? C.danger : C.warn;
      const hint = d.stall_hint ? ` — ${shorten(String(d.stall_hint), 60)}` : "";
      return [{
        id, time: t, kind: `stall:${cat}`, accent,
        actor: d.task_id || "task",
        detail: `${shorten(String(d.stall_reason || d.error || ""), 90)}${hint}`,
      }];
    }
    case "agent_turn": {
      const calls = d.tool_calls || [];
      if (calls.length === 0) {
        if (!d.content) return [];
        return [{
          id, time: t, kind: "think", accent: C.info,
          actor: d.instance_id, detail: shorten(d.content, 100),
        }];
      }
      return calls.map((tc: any, i: number) => {
        const args = JSON.stringify(tc.arguments || {});
        let accent = C.info;
        let detail = `${tc.name}(${shorten(args, 70)})`;
        if (tc.name === "memory_write") {
          accent = C.warn;
          detail = `memory_write → ${tc.arguments?.key || "?"}`;
        } else if (tc.name === "memory_read") {
          accent = C.warn;
          detail = `memory_read ← ${tc.arguments?.key || "?"}`;
        } else if (tc.name === "channel_post") {
          accent = C.accent;
          detail = `#${tc.arguments?.channel || "general"}: ${shorten(tc.arguments?.content || "", 60)}`;
        } else if (tc.name === "file_write") {
          accent = C.ok;
          detail = `file_write → ${tc.arguments?.path || "?"}`;
        } else if (tc.name === "task_create") {
          accent = C.ok;
          detail = `task_create → "${shorten(tc.arguments?.title || "", 50)}"`;
        }
        return {
          id: `${id}-${i}`, time: t, kind: tc.name, accent,
          actor: d.instance_id, detail,
        };
      });
    }
    case "message":
      return [{
        id, time: t, kind: "msg", accent: C.accent,
        actor: d.sender || "?",
        detail: `#${d.channel || "general"}: ${shorten(d.content || "", 90)}`,
      }];
    case "task_created":
      return [{
        id, time: t, kind: "task+", accent: C.ok,
        actor: d.created_by || "?",
        detail: `created task: ${shorten(d.title || "", 70)}`,
      }];
    case "task_completed":
      return [{
        id, time: t, kind: "task✓", accent: C.ok,
        actor: d.instance_id || "?",
        detail: `completed ${d.task_id}`,
      }];
    case "spawn_failed":
      return [{
        id, time: t, kind: "blocked", accent: C.danger,
        actor: d.agent_type || "agent",
        detail: `BLOCKED after ${d.failures || "?"} failed spawns — ${shorten(d.error || "", 80)}`,
      }];
    default:
      return [];
  }
}

export default function ActivityFeed() {
  const [rows, setRows] = useState<Row[]>([]);
  const [paused, setPaused] = useState(false);
  const [filter, setFilter] = useState<string>("");

  useWebSocket((event) => {
    if (paused) return;
    const newRows = toRows(event);
    if (newRows.length === 0) return;
    setRows((prev) => [...newRows, ...prev].slice(0, 200));
  });

  const visible = filter
    ? rows.filter(
        (r) =>
          r.kind.includes(filter) ||
          r.actor.toLowerCase().includes(filter.toLowerCase()) ||
          r.detail.toLowerCase().includes(filter.toLowerCase()),
      )
    : rows;

  return (
    <div
      className="rounded-2xl border border-border bg-bg-card overflow-hidden"
      style={{ boxShadow: "rgba(0,0,0,0.03) 0px 2px 4px" }}
    >
      <div className="flex flex-wrap items-center gap-3 border-b border-border px-5 py-3.5">
        <h2 className="text-[15px] font-semibold tight-heading">Live Activity</h2>
        <span className="mono-label">
          {visible.length}
          {filter ? ` / ${rows.length}` : ""} events
        </span>
        <input
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter by kind, actor, or text…"
          className="ml-auto min-w-[240px] flex-1 max-w-[360px] rounded-full border border-border-strong bg-white px-3 py-1 text-xs outline-none placeholder:text-text-subtle focus:border-accent"
        />
        <button
          onClick={() => setPaused((p) => !p)}
          className="btn-ghost"
          style={{ padding: "4px 12px", fontSize: "12px" }}
          title={paused ? "Resume streaming" : "Pause streaming"}
        >
          {paused ? "▶ Resume" : "⏸ Pause"}
        </button>
        <button
          onClick={() => setRows([])}
          className="btn-ghost"
          style={{ padding: "4px 12px", fontSize: "12px" }}
        >
          Clear
        </button>
      </div>
      <div className="max-h-[480px] overflow-y-auto">
        {visible.length === 0 ? (
          <p className="p-5 text-sm text-text-muted">
            {rows.length === 0 ? "Waiting for events…" : "No events match filter."}
          </p>
        ) : (
          <table className="w-full table-fixed border-collapse text-sm">
            <thead className="sticky top-0 bg-bg-card">
              <tr className="border-b border-border">
                <th className="w-[86px] px-5 py-2 text-left mono-label" style={{ fontSize: "10px" }}>
                  time
                </th>
                <th className="w-[120px] px-3 py-2 text-left mono-label" style={{ fontSize: "10px" }}>
                  kind
                </th>
                <th className="w-[200px] px-3 py-2 text-left mono-label" style={{ fontSize: "10px" }}>
                  actor
                </th>
                <th className="px-3 py-2 text-left mono-label" style={{ fontSize: "10px" }}>
                  detail
                </th>
              </tr>
            </thead>
            <tbody>
              {visible.map((r) => (
                <tr key={r.id} className="border-b border-border last:border-b-0 hover:bg-bg-subtle">
                  <td
                    className="px-5 py-2 align-top text-text-muted"
                    style={{ fontFamily: "var(--font-mono)", fontSize: "11px" }}
                  >
                    {fmtTime(r.time)}
                  </td>
                  <td className="px-3 py-2 align-top">
                    <span
                      className={r.accent}
                      style={{
                        fontFamily: "var(--font-mono)",
                        fontSize: "11px",
                        fontWeight: 500,
                        letterSpacing: "0.6px",
                        textTransform: "uppercase",
                      }}
                    >
                      {r.kind}
                    </span>
                  </td>
                  <td
                    className="px-3 py-2 align-top text-text truncate"
                    style={{ fontFamily: "var(--font-mono)", fontSize: "11px" }}
                    title={r.actor}
                  >
                    {r.actor}
                  </td>
                  <td
                    className="px-3 py-2 align-top text-text-muted"
                    style={{ overflowWrap: "anywhere" }}
                  >
                    {r.detail}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
