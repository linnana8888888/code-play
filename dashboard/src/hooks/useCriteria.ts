import { useCallback, useEffect, useRef, useState } from "react";
import {
  getCriteria,
  createCriterion,
  updateCriterion,
  deleteCriterion,
} from "../api/client";
import { useWebSocket } from "../api/websocket";
import type {
  SuccessCriterion,
  CriterionCreate,
  CriterionUpdate,
} from "../types/api";

export function useCriteria(projectId?: string) {
  const [criteria, setCriteria] = useState<SuccessCriterion[]>([]);
  const [loading, setLoading] = useState(true);
  const pidRef = useRef<string | undefined>(projectId);
  pidRef.current = projectId;

  const refresh = useCallback(() => {
    if (!projectId) {
      setCriteria([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    getCriteria(projectId)
      .then(setCriteria)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [projectId]);

  useEffect(() => { refresh(); }, [refresh]);

  useWebSocket((event) => {
    if (!pidRef.current) return;
    const d = event.data as Partial<SuccessCriterion> & { id?: string };
    if (event.type === "criterion_created" && d.project_id === pidRef.current) {
      setCriteria((prev) =>
        prev.find((c) => c.id === d.id) ? prev : [...prev, d as SuccessCriterion],
      );
    } else if (event.type === "criterion_updated") {
      setCriteria((prev) =>
        prev.map((c) => (c.id === d.id ? ({ ...c, ...d } as SuccessCriterion) : c)),
      );
    } else if (event.type === "criterion_deleted") {
      setCriteria((prev) => prev.filter((c) => c.id !== d.id));
    }
  });

  const create = async (body: CriterionCreate) => {
    if (!projectId) throw new Error("projectId required");
    const c = await createCriterion(projectId, body);
    setCriteria((prev) => (prev.find((x) => x.id === c.id) ? prev : [...prev, c]));
    return c;
  };

  const update = async (id: string, body: CriterionUpdate) => {
    const c = await updateCriterion(id, body);
    setCriteria((prev) => prev.map((x) => (x.id === id ? c : x)));
    return c;
  };

  const remove = async (id: string) => {
    await deleteCriterion(id);
    setCriteria((prev) => prev.filter((c) => c.id !== id));
  };

  return { criteria, loading, refresh, create, update, remove };
}
