import { useEffect, useState } from "react";
import { getDocuments } from "../lib/api";
import { EmptyState, ErrorState, Skeleton } from "../ui/FeedbackStates";
import { SectionHeader } from "../ui/SectionHeader";

function documentType(filename: string): { label: string; mark: string; classes: string } {
  const normalized = filename.toLowerCase();
  if (normalized.endsWith(".pdf")) return { label: "PDF document", mark: "PDF", classes: "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300" };
  if (normalized.endsWith(".xlsx") || normalized.endsWith(".xls")) return { label: "Excel document", mark: "XLS", classes: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300" };
  return { label: "Generic document", mark: "FILE", classes: "bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300" };
}

export function DocumentsList() {
  const [documents, setDocuments] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    getDocuments()
      .then((loaded) => {
        if (active) setDocuments(loaded);
      })
      .catch(() => {
        if (active) setError("Failed to load documents.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [attempt]);

  if (loading && documents.length === 0) {
    return <Skeleton className="h-52" label="Loading documents" />;
  }

  if (error && documents.length === 0) {
    return <ErrorState title="Documents unavailable" description={error} actionLabel="Retry" onAction={() => setAttempt((value) => value + 1)} />;
  }

  if (documents.length === 0) {
    return <EmptyState title="No documents ingested yet" description="Import a PDF or spreadsheet to add it to the knowledge workspace." icon="document" />;
  }

  return (
    <section aria-label="Document library" className="space-y-4">
      <SectionHeader title="Document library" description={`${documents.length} ${documents.length === 1 ? "file" : "files"} available to the system.`} />
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {documents.map((document) => {
          const type = documentType(document);
          return (
            <li key={document} className="flex items-center gap-3 rounded-2xl border border-terminal-border bg-surface-elevated p-4 shadow-sm">
              <span role="img" aria-label={type.label} className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl text-[10px] font-extrabold tracking-wide ${type.classes}`}>{type.mark}</span>
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-terminal-text" title={document}>{document}</p>
                <p className="mt-0.5 text-xs text-terminal-muted">Ingested knowledge file</p>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
