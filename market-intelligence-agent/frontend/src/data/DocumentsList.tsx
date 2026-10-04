import { useEffect, useState } from "react";
import { getDocuments } from "../lib/api";

export function DocumentsList() {
  const [documents, setDocuments] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDocuments()
      .then(setDocuments)
      .catch(() => setError("Failed to load documents."));
  }, []);

  if (error) {
    return (
      <div className="rounded border border-terminal-danger/40 bg-terminal-danger/10 px-3 py-2 font-mono text-xs text-terminal-danger">
        {error}
      </div>
    );
  }

  if (documents.length === 0) {
    return <div className="font-mono text-sm text-terminal-muted">No documents ingested yet.</div>;
  }

  return (
    <ul className="space-y-1 font-mono text-sm text-terminal-text">
      {documents.map((d) => (
        <li key={d} className="rounded border border-terminal-border bg-terminal-panel card-shadow px-3 py-1.5">{d}</li>
      ))}
    </ul>
  );
}
