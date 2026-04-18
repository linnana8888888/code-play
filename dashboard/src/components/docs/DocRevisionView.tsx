import { useDocContent } from "../../hooks/useDocs";

interface Props {
  docId?: string;
  version?: number;
}

export default function DocRevisionView({ docId, version }: Props) {
  const { doc, history, loading } = useDocContent(docId, version);

  if (!docId) {
    return (
      <div className="flex h-full items-center justify-center rounded-xl border border-border bg-bg-card p-8 text-sm text-text-muted">
        Select a document to view.
      </div>
    );
  }
  if (loading) {
    return (
      <div className="rounded-xl border border-border bg-bg-card p-6 text-sm text-text-muted">
        Loading…
      </div>
    );
  }
  if (!doc) {
    return (
      <div className="rounded-xl border border-border bg-bg-card p-6 text-sm text-text-muted">
        Document not found.
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col rounded-xl border border-border bg-bg-card">
      <div className="border-b border-border p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-wide text-text-muted">
              {doc.category} / {doc.slug}
            </p>
            <h3 className="text-base font-semibold">{doc.title}</h3>
          </div>
          <div className="text-right text-xs text-text-muted">
            <p>
              v{doc.version}
              {doc.version === doc.current_version ? " (latest)" : ""}
            </p>
            {doc.change_summary && (
              <p className="mt-1 max-w-[18rem] italic">{doc.change_summary}</p>
            )}
          </div>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-text">
{doc.content}
        </pre>
      </div>
      {history.length > 1 && (
        <div className="border-t border-border p-3 text-xs text-text-muted">
          History: {history.length} revision{history.length === 1 ? "" : "s"}
        </div>
      )}
    </div>
  );
}
