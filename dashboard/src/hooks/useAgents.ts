import { useState, useEffect, useCallback } from "react";
import {
  getDefinitions,
  getCategories,
  getInstances,
  spawnAgent,
  terminateAgent,
} from "../api/client";
import type { AgentDefinition, AgentInstance } from "../types/api";

export function useAgents() {
  const [definitions, setDefinitions] = useState<AgentDefinition[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [instances, setInstances] = useState<AgentInstance[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    Promise.all([getDefinitions(), getCategories(), getInstances()])
      .then(([defs, cats, insts]) => {
        setDefinitions(defs);
        setCategories(cats);
        setInstances(insts);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const spawn = async (agentType: string, projectId?: string) => {
    const inst = await spawnAgent(agentType, projectId);
    setInstances((prev) => [...prev, inst]);
    return inst;
  };

  const terminate = async (id: string) => {
    await terminateAgent(id);
    setInstances((prev) =>
      prev.map((i) => (i.id === id ? { ...i, status: "terminated" as const } : i)),
    );
  };

  return { definitions, categories, instances, loading, refresh, spawn, terminate };
}
