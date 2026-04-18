import { useCallback, useEffect, useRef, useState } from "react";
import {
  getDocs,
  getDocLatest,
  getDocHistory,
  getDocVersion,
  createDoc,
  reviseDoc,
} from "../api/client";
import { useWebSocket } from "../api/websocket";
import type {
  DocumentMeta,
  DocumentRead,
  DocumentRevisionRow,
  DocumentCreate,
  DocumentRevise,
} from "../types/api";

export function useDocs(projectId?: string) {
  const [docs, setDocs] = useState<DocumentMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const pidRef = useRef<string | undefined>(projectId);
  pidRef.current = projectId;

  const refresh = useCallback(() => {
    if (!projectId) {
      setDocs([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    getDocs(projectId)
      .then(setDocs)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [projectId]);

  useEffect(() => { refresh(); }, [refresh]);

  useWebSocket((event) => {
    if (event.type === "doc_written" || event.type === "doc_revised") {
      const d = event.data as { project_id?: string };
      if (d.project_id && d.project_id !== pidRef.current) return;
      refresh();
    }
  });

  const create = async (body: DocumentCreate) => {
    if (!projectId) throw new Error("projectId required");
    const res = await createDoc(projectId, body);
    refresh();
    return res;
  };

  const revise = async (docId: string, body: DocumentRevise) => {
    const res = await reviseDoc(docId, body);
    refresh();
    return res;
  };

  return { docs, loading, refresh, create, revise };
}

export function useDocContent(docId?: string, version?: number) {
  const [doc, setDoc] = useState<DocumentRead | null>(null);
  const [history, setHistory] = useState<DocumentRevisionRow[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!docId) {
      setDoc(null);
      setHistory([]);
      return;
    }
    setLoading(true);
    const contentP = version ? getDocVersion(docId, version) : getDocLatest(docId);
    Promise.all([contentP, getDocHistory(docId)])
      .then(([c, h]) => {
        setDoc(c);
        setHistory(h);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [docId, version]);

  return { doc, history, loading };
}
