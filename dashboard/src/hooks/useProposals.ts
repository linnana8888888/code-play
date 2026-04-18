import { useCallback, useEffect, useState } from "react";
import {
  getProposals,
  approveProposalBatch,
  rejectProposalBatch,
  approveProposal,
  rejectProposal,
} from "../api/client";
import { useWebSocket } from "../api/websocket";
import type { AgentProposal } from "../types/api";

/**
 * Group proposals by batch_id. Returns { batchId, proposals }[] ordered newest first.
 */
export function groupByBatch(proposals: AgentProposal[]) {
  const map = new Map<string, AgentProposal[]>();
  for (const p of proposals) {
    if (!map.has(p.batch_id)) map.set(p.batch_id, []);
    map.get(p.batch_id)!.push(p);
  }
  return Array.from(map.entries())
    .map(([batch_id, ps]) => ({
      batch_id,
      proposals: ps.sort((a, b) => (a.created_at ?? "").localeCompare(b.created_at ?? "")),
    }))
    .sort((a, b) => {
      const at = a.proposals[0]?.created_at ?? "";
      const bt = b.proposals[0]?.created_at ?? "";
      return bt.localeCompare(at);
    });
}

export function useProposals(projectId?: string) {
  const [proposals, setProposals] = useState<AgentProposal[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    setLoading(true);
    getProposals(projectId)
      .then(setProposals)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [projectId]);

  useEffect(() => { refresh(); }, [refresh]);

  useWebSocket((event) => {
    if (
      event.type === "proposal_created" ||
      event.type === "roster_proposed" ||
      event.type === "roster_approved" ||
      event.type === "roster_rejected"
    ) {
      refresh();
    }
  });

  const approveBatch = async (
    batchId: string,
    opts?: { keep?: string[]; decidedBy?: string },
  ) => {
    const res = await approveProposalBatch(batchId, {
      decided_by: opts?.decidedBy ?? "human",
      keep_proposal_ids: opts?.keep,
    });
    refresh();
    return res;
  };

  const rejectBatch = async (batchId: string, reason = "") => {
    const res = await rejectProposalBatch(batchId, { reason, decided_by: "human" });
    refresh();
    return res;
  };

  const approveOne = async (id: string) => {
    const res = await approveProposal(id, { decided_by: "human" });
    refresh();
    return res;
  };

  const rejectOne = async (id: string, reason = "") => {
    const res = await rejectProposal(id, { decided_by: "human", reason });
    refresh();
    return res;
  };

  const pending = proposals.filter((p) => p.status === "pending");

  return {
    proposals,
    pending,
    pendingBatches: groupByBatch(pending),
    loading,
    refresh,
    approveBatch,
    rejectBatch,
    approveOne,
    rejectOne,
  };
}
