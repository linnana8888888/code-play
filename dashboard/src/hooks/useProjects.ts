import { useState, useEffect, useCallback } from "react";
import { getProjects, createProject, deleteProject, cleanupProjects } from "../api/client";
import type { Project, ProjectCreate } from "../types/api";

export function useProjects() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    getProjects().then(setProjects).catch(() => {}).finally(() => setLoading(false));
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const create = async (data: ProjectCreate) => {
    const p = await createProject(data);
    setProjects((prev) => [...prev, p]);
    return p;
  };

  const remove = async (id: string) => {
    await deleteProject(id);
    setProjects((prev) => prev.filter((p) => p.id !== id));
  };

  const cleanup = async (opts: { dryRun?: boolean; onlyEmpty?: boolean; olderThanDays?: number } = {}) => {
    const result = await cleanupProjects({ dryRun: false, onlyEmpty: true, ...opts });
    refresh();
    return result;
  };

  const previewCleanup = (opts: { onlyEmpty?: boolean; olderThanDays?: number } = {}) =>
    cleanupProjects({ dryRun: true, onlyEmpty: true, ...opts });

  return { projects, loading, refresh, create, remove, cleanup, previewCleanup };
}
