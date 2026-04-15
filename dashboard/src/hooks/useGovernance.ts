import { useState, useEffect, useCallback } from "react";
import { getApprovals, getGovernanceLog, getSkills } from "../api/client";
import type { GovernanceApproval, GovernanceLogEntry, Skill } from "../types/api";

export function useGovernance() {
  const [approvals, setApprovals] = useState<GovernanceApproval[]>([]);
  const [log, setLog] = useState<GovernanceLogEntry[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    Promise.all([getApprovals(), getGovernanceLog(), getSkills()])
      .then(([a, l, s]) => { setApprovals(a); setLog(l); setSkills(s); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  return { approvals, log, skills, loading, refresh };
}
