import { useState, useEffect, useCallback } from "react";
import {
  getApprovals,
  getGovernanceLog,
  getSkills,
  getToolCatalog,
} from "../api/client";
import type {
  GovernanceApproval,
  GovernanceLogEntry,
  Skill,
  ToolCatalogEntry,
} from "../types/api";

export function useGovernance() {
  const [approvals, setApprovals] = useState<GovernanceApproval[]>([]);
  const [log, setLog] = useState<GovernanceLogEntry[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [tools, setTools] = useState<ToolCatalogEntry[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    Promise.all([getApprovals(), getGovernanceLog(), getSkills(), getToolCatalog()])
      .then(([a, l, s, t]) => {
        setApprovals(a);
        setLog(l);
        setSkills(s);
        setTools(t);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  return { approvals, log, skills, tools, loading, refresh };
}
