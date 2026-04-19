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
    case "agent_error":
      return [{
        id, time: t, kind: "error", accent: C.danger,
        actor: d.instance_id || "agent", detail: shorten(d.error || ""),
      }];
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

  useWebSocket((event) => {
    const newRows = toRows(event);
    if (newRows.length === 0) return;
    setRows((prev) => [...newRows, ...prev].slice(0, 80));
  });

  return (
    <div
      className="rounded-2xl border border-border bg-bg-card overflow-hidden"
      style={{ boxShadow: "rgba(0,0,0,0.03) 0px 2px 4px" }}
    >
      <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
        <h2 className="text-[15px] font-semibold tight-heading">Live Activity</h2>
        <span className="mono-label">{rows.length} events</span>
      </div>
      <div className="max-h-80 overflow-y-auto">
        {rows.length === 0 ? (
          <p className="p-5 text-sm text-text-muted">Waiting for events…</p>
        ) : (
          rows.map((r) => (
            <div key={r.id} className="border-b border-border px-5 py-2.5 text-sm last:border-b-0">
              <div className="flex items-center justify-between gap-3">
                <span
                  className={`${r.accent}`}
                  style={{ fontFamily: "var(--font-mono)", fontSize: "11px", fontWeight: 500, letterSpacing: "0.6px", textTransform: "uppercase" }}
                >
                  {r.kind}
                </span>
                <span className="mono-label" style={{ fontSize: "10px" }}>
                  {new Date(r.time).toLocaleTimeString()}
                </span>
              </div>
              <p className="mt-1 text-text-muted truncate">
                <span className="font-medium text-text" style={{ fontFamily: "var(--font-mono)", fontSize: "11px" }}>
                  {r.actor.slice(0, 24)}
                </span>{" "}
                {r.detail}
              </p>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
