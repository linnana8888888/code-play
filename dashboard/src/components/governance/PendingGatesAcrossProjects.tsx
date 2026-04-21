import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { getProjects, getGates } from "../../api/client";
import { useWebSocket } from "../../api/websocket";
import type { HumanGate, Project } from "../../types/api";

type GateRow = HumanGate & { project_id: string; project_name: string };

export default function PendingGatesAcrossProjects() {
  const [rows, setRows] = useState<GateRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const projects = await getProjects();
      const perProject = await Promise.all(
        projects.map(async (p: Project) => {
          const gates = await getGates(p.id).catch(() => [] as HumanGate[]);
          return gates.map((g) => ({
            ...g,
            project_id: p.id,
            project_name: p.name,
          }));
        }),
      );
      setRows(perProject.flat());
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useWebSocket((event) => {
    const e = event as { type?: string };
    const relevant = [
      "gate_ready", "task_completed", "task_created", "task_updated",
      "pipeline_started", "roster_proposed",
    ];
    if (relevant.includes(e.type || "")) load();
  });

  useEffect(() => {
    load();
  }, [load]);

  const ready = rows?.filter((g) => g.ready) ?? [];
  const waiting = rows?.filter((g) => !g.ready) ?? [];

  return (
    <div>
      <div className="mb-3 flex items-center gap-3">
        <h2 className="text-lg font-semibold">Pending Gates</h2>
        {rows && (
          <>
            <span className="rounded-full bg-accent/15 px-2 py-0.5 text-xs font-medium text-accent">
              {ready.length} ready for review
            </span>
            {waiting.length > 0 && (
              <span className="rounded-full bg-warning/15 px-2 py-0.5 text-xs text-warning">
                {waiting.length} waiting on upstream
              </span>
            )}
          </>
        )}
      </div>
      {err ? (
        <p className="text-sm text-danger">Failed to load gates: {err}</p>
      ) : rows === null ? (
        <p className="text-sm text-text-muted">Loading pending gates…</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-text-muted">
          No pending gates across any project. Launch a pipeline from a project to create one.
        </p>
      ) : (
        <div className="space-y-2">
          {[...ready, ...waiting].map((g) => (
            <Link
              key={`${g.project_id}-${g.task_id}`}
              to={`/projects/${g.project_id}?expanded=${g.task_id}`}
              className={`flex items-start justify-between gap-3 rounded-xl border p-3 transition ${
                g.ready
                  ? "border-accent/40 bg-bg-card hover:border-accent"
                  : "border-border bg-bg-card opacity-75 hover:opacity-100"
              }`}
            >
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{g.project_name}</span>
                  <span className="rounded bg-bg-hover px-1.5 py-0.5 text-[10px] text-text-muted">
                    {g.pipeline_label}
                  </span>
                  <span className="rounded bg-bg-hover px-1.5 py-0.5 text-[10px] font-mono text-text-muted">
                    {g.step_id}
                  </span>
                  {g.review_of && (
                    <span className="text-xs text-text-muted">
                      review {g.review_of}
                      {g.review_of_agent ? ` by ${g.review_of_agent}` : ""}
                    </span>
                  )}
                </div>
                <p className="mt-1 line-clamp-2 text-xs text-text-muted">{g.prompt}</p>
              </div>
              <span
                className={`shrink-0 rounded px-2 py-0.5 text-[10px] font-medium ${
                  g.ready ? "bg-success/20 text-success" : "bg-warning/20 text-warning"
                }`}
              >
                {g.ready ? "review →" : "waiting"}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
