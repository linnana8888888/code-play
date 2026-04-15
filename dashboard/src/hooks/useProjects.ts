import { useState, useEffect, useCallback } from "react";
import { getProjects, createProject } from "../api/client";
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

  return { projects, loading, refresh, create };
}
