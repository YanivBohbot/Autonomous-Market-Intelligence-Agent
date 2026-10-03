import { useState } from "react";
import { ClientsList } from "./ClientsList";
import { DocumentsList } from "./DocumentsList";
import { ImportPanel } from "./ImportPanel";

type Tab = "clients" | "documents" | "import";

export function DataPage() {
  const [tab, setTab] = useState<Tab>("clients");

  const tabs: { id: Tab; label: string }[] = [
    { id: "clients", label: "Clients" },
    { id: "documents", label: "Documents" },
    { id: "import", label: "Import" },
  ];

  return (
    <div className="flex min-h-0 flex-1 flex-col p-4">
      <div className="mb-3 flex gap-1 overflow-hidden rounded border border-terminal-border self-start">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`px-3 py-1.5 font-mono text-xs transition-colors ${
              tab === t.id ? "bg-terminal-accent/15 text-terminal-accent" : "bg-terminal-bg text-terminal-muted hover:text-terminal-text"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {tab === "clients" && <ClientsList />}
        {tab === "documents" && <DocumentsList />}
        {tab === "import" && <ImportPanel />}
      </div>
    </div>
  );
}
