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
  switch (e.type) {
    case "agent_spawned":
      return [{
        id, time: t, kind: "spawn", accent: "text-emerald-400",
        actor: d.agent_type || d.id || "agent",
        detail: `spawned (${d.model || "?"})`,
      }];
    case "agent_terminated":
      return [{
        id, time: t, kind: "end", accent: "text-slate-400",
        actor: d.id || "agent", detail: "terminated",
      }];
    case "agent_error":
      return [{
        id, time: t, kind: "error", accent: "text-red-400",
        actor: d.instance_id || "agent", detail: shorten(d.error || ""),
      }];
    case "agent_turn": {
      const calls = d.tool_calls || [];
      if (calls.length === 0) {
        if (!d.content) return [];
        return [{
          id, time: t, kind: "think", accent: "text-sky-400",
          actor: d.instance_id, detail: shorten(d.content, 100),
        }];
      }
      return calls.map((tc: any, i: number) => {
        const args = JSON.stringify(tc.arguments || {});
        let accent = "text-indigo-400";
        let detail = `${tc.name}(${shorten(args, 70)})`;
        if (tc.name === "memory_write") {
          accent = "text-amber-400";
          detail = `memory_write → ${tc.arguments?.key || "?"}`;
        } else if (tc.name === "memory_read") {
          accent = "text-amber-300";
          detail = `memory_read ← ${tc.arguments?.key || "?"}`;
        } else if (tc.name === "channel_post") {
          accent = "text-fuchsia-400";
          detail = `#${tc.arguments?.channel || "general"}: ${shorten(tc.arguments?.content || "", 60)}`;
        } else if (tc.name === "file_write") {
          accent = "text-teal-400";
          detail = `file_write → ${tc.arguments?.path || "?"}`;
        } else if (tc.name === "task_create") {
          accent = "text-emerald-300";
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
        id, time: t, kind: "msg", accent: "text-fuchsia-400",
        actor: d.sender || "?",
        detail: `#${d.channel || "general"}: ${shorten(d.content || "", 90)}`,
      }];
    case "task_created":
      return [{
        id, time: t, kind: "task+", accent: "text-green-400",
        actor: d.created_by || "?",
        detail: `created task: ${shorten(d.title || "", 70)}`,
      }];
    case "task_completed":
      return [{
        id, time: t, kind: "task✓", accent: "text-green-500",
        actor: d.instance_id || "?",
        detail: `completed ${d.task_id}`,
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
    <div className="rounded-xl border border-border bg-bg-card">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">Live Activity</h2>
        <span className="text-[10px] text-text-muted">{rows.length} events</span>
      </div>
      <div className="max-h-80 overflow-y-auto">
        {rows.length === 0 ? (
          <p className="p-4 text-sm text-text-muted">Waiting for events…</p>
        ) : (
          rows.map((r) => (
            <div key={r.id} className="border-b border-border/40 px-4 py-2 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className={`font-mono text-[10px] uppercase tracking-wider ${r.accent}`}>{r.kind}</span>
                <span className="text-[10px] text-text-muted">
                  {new Date(r.time).toLocaleTimeString()}
                </span>
              </div>
              <p className="mt-0.5 text-text-muted truncate">
                <span className="font-mono text-[11px] text-text">{r.actor.slice(0, 24)}</span> {r.detail}
              </p>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
