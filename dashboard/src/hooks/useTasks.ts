import { useState, useEffect, useCallback, useRef } from "react";
import { getTasks, createTask } from "../api/client";
import { useWebSocket } from "../api/websocket";
import type { Task, TaskCreate } from "../types/api";

export function useTasks(projectId?: string) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const pidRef = useRef<string | undefined>(projectId);
  pidRef.current = projectId;

  const refresh = useCallback(() => {
    setLoading(true);
    getTasks(projectId)
      .then(setTasks)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [projectId]);

  useEffect(() => { refresh(); }, [refresh]);

  // Live updates via WS so the kanban reflects agent-created tasks immediately.
  useWebSocket((event) => {
    if (event.type === "task_created") {
      const t = event.data as unknown as Task;
      if (pidRef.current && t.project_id !== pidRef.current) return;
      setTasks((prev) => (prev.find((x) => x.id === t.id) ? prev : [...prev, t]));
    } else if (event.type === "task_completed" || event.type === "task_updated") {
      const d = event.data as { id?: string; task_id?: string; status?: string } & Record<string, unknown>;
      const id = d.id || d.task_id;
      if (!id) return;
      setTasks((prev) =>
        prev.map((x) => (x.id === id ? ({ ...x, ...d, id: x.id } as Task) : x))
      );
    }
  });

  const create = async (data: TaskCreate) => {
    const t = await createTask(data);
    setTasks((prev) => [...prev, t]);
    return t;
  };

  return { tasks, loading, refresh, create };
}
