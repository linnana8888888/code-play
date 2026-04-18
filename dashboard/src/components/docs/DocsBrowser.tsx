import { useMemo, useState } from "react";
import { useDocs } from "../../hooks/useDocs";
import { getDocHistory } from "../../api/client";
import DocRevisionView from "./DocRevisionView";
import type {
  DocumentCategory,
  DocumentMeta,
  DocumentRevisionRow,
} from "../../types/api";

const CATEGORIES: DocumentCategory[] = [
  "design",
  "architecture",
  "testing",
  "analytics",
  "notes",
];

export default function DocsBrowser({ projectId }: { projectId: string }) {
  const { docs, loading, create } = useDocs(projectId);
  const [activeDocId, setActiveDocId] = useState<string | null>(null);
  const [activeVersion, setActiveVersion] = useState<number | undefined>(undefined);
  const [history, setHistory] = useState<DocumentRevisionRow[]>([]);

  const [newCategory, setNewCategory] = useState<DocumentCategory>("design");
  const [newSlug, setNewSlug] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [newContent, setNewContent] = useState("");
  const [showNew, setShowNew] = useState(false);

  const grouped = useMemo(() => {
    const map = new Map<string, DocumentMeta[]>();
    for (const d of docs) {
      if (!map.has(d.category)) map.set(d.category, []);
      map.get(d.category)!.push(d);
    }
    for (const list of map.values()) {
      list.sort((a, b) => a.title.localeCompare(b.title));
    }
    return CATEGORIES.filter((cat) => map.has(cat)).map((cat) => ({
      cat,
      docs: map.get(cat)!,
    }));
  }, [docs]);

  async function selectDoc(doc: DocumentMeta) {
    setActiveDocId(doc.id);
    setActiveVersion(undefined);
    try {
      const h = await getDocHistory(doc.id);
      setHistory(h);
    } catch {
      setHistory([]);
    }
  }

  async function onCreate() {
    if (!newSlug.trim() || !newTitle.trim() || !newContent.trim()) return;
    const res = await create({
      category: newCategory,
      slug: newSlug.trim(),
      title: newTitle.trim(),
      content: newContent,
      change_summary: "initial version",
    });
    setActiveDocId(res.document_id);
    setActiveVersion(undefined);
    setShowNew(false);
    setNewSlug("");
    setNewTitle("");
    setNewContent("");
    try {
      setHistory(await getDocHistory(res.document_id));
    } catch {
      setHistory([]);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[260px_1fr]" style={{ minHeight: 500 }}>
      {/* Left rail */}
      <div className="flex flex-col rounded-xl border border-border bg-bg-card">
        <div className="flex items-center justify-between border-b border-border p-3">
          <p className="text-sm font-semibold">Docs</p>
          <button
            onClick={() => setShowNew((s) => !s)}
            className="rounded bg-accent px-2 py-0.5 text-xs font-medium text-white"
          >
            {showNew ? "Close" : "New"}
          </button>
        </div>
        {loading ? (
          <p className="p-3 text-xs text-text-muted">Loading…</p>
        ) : docs.length === 0 ? (
          <p className="p-3 text-xs text-text-muted">
            No documents yet. Agents can create them via the{" "}
            <span className="font-mono">document_write</span> tool, or start one
            here.
          </p>
        ) : (
          <div className="flex-1 overflow-y-auto">
            {grouped.map(({ cat, docs }) => (
              <div key={cat} className="border-b border-border/60">
                <p className="bg-bg px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                  {cat}
                </p>
                <ul>
                  {docs.map((d) => (
                    <li key={d.id}>
                      <button
                        onClick={() => selectDoc(d)}
                        className={`flex w-full flex-col items-start px-3 py-2 text-left text-xs hover:bg-bg-hover ${
                          activeDocId === d.id
                            ? "bg-bg-hover text-accent"
                            : "text-text"
                        }`}
                      >
                        <span className="font-medium">{d.title}</span>
                        <span className="mt-0.5 text-[10px] text-text-muted">
                          {d.slug} · v{d.current_version}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}

        {showNew && (
          <div className="space-y-2 border-t border-border bg-bg p-3">
            <select
              value={newCategory}
              onChange={(e) =>
                setNewCategory(e.target.value as DocumentCategory)
              }
              className="w-full rounded border border-border bg-bg-card px-2 py-1 text-xs"
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            <input
              value={newSlug}
              onChange={(e) => setNewSlug(e.target.value)}
              placeholder="slug (e.g. game-design)"
              className="w-full rounded border border-border bg-bg-card px-2 py-1 text-xs"
            />
            <input
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              placeholder="Title"
              className="w-full rounded border border-border bg-bg-card px-2 py-1 text-xs"
            />
            <textarea
              value={newContent}
              onChange={(e) => setNewContent(e.target.value)}
              rows={6}
              placeholder="Markdown content…"
              className="w-full rounded border border-border bg-bg-card px-2 py-1 text-xs"
            />
            <button
              onClick={onCreate}
              disabled={
                !newSlug.trim() || !newTitle.trim() || !newContent.trim()
              }
              className="w-full rounded bg-accent px-2 py-1 text-xs font-semibold text-white disabled:opacity-40"
            >
              Create v1
            </button>
          </div>
        )}
      </div>

      {/* Right pane */}
      <div className="flex flex-col gap-2">
        {history.length > 1 && activeDocId && (
          <div className="rounded-xl border border-border bg-bg-card p-2 text-xs">
            <span className="mr-2 text-text-muted">Version:</span>
            <select
              value={activeVersion ?? history[0]?.version ?? ""}
              onChange={(e) =>
                setActiveVersion(
                  e.target.value ? Number(e.target.value) : undefined,
                )
              }
              className="rounded border border-border bg-bg px-2 py-0.5 text-xs"
            >
              {history.map((h) => (
                <option key={h.version} value={h.version}>
                  v{h.version}
                  {h.change_summary ? ` — ${h.change_summary}` : ""}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="flex-1" style={{ minHeight: 450 }}>
          <DocRevisionView docId={activeDocId ?? undefined} version={activeVersion} />
        </div>
      </div>
    </div>
  );
}
