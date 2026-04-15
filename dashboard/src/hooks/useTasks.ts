import { useState, useEffect, useCallback } from "react";
import { getTasks, createTask } from "../api/client";
import type { Task, TaskCreate } from "../types/api";

export function useTasks(projectId: string | undefined) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    if (!projectId) return;
    getTasks(projectId).then(setTasks).catch(() => {}).finally(() => setLoading(false));
  }, [projectId]);

  useEffect(() => { refresh(); }, [refresh]);

  const create = async (data: TaskCreate) => {
    const t = await createTask(data);
    setTasks((prev) => [...prev, t]);
    return t;
  };

  return { tasks, loading, refresh, create };
}
