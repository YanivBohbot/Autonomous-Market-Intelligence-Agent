import { useEffect, useState } from "react";
import { getDocuments } from "../lib/api";

export function DocumentsList() {
  const [documents, setDocuments] = useState<string[]>([]);

  useEffect(() => {
    void getDocuments().then(setDocuments);
  }, []);

  if (documents.length === 0) {
    return <div className="font-mono text-sm text-terminal-muted">No documents ingested yet.</div>;
  }

  return (
    <ul className="space-y-1 font-mono text-sm text-terminal-text">
      {documents.map((d) => (
        <li key={d} className="rounded border border-terminal-border bg-terminal-panel px-3 py-1.5">{d}</li>
      ))}
    </ul>
  );
}
