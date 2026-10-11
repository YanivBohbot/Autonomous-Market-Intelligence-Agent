import { useState } from "react";
import { PageHeader } from "../ui/PageHeader";
import { DocumentsList } from "./DocumentsList";
import { ImportPanel } from "./ImportPanel";

type Tab = "documents" | "import";

const TABS: { id: Tab; label: string }[] = [
  { id: "documents", label: "Documents" },
  { id: "import", label: "Import" },
];

export function DataPage() {
  const [tab, setTab] = useState<Tab>("documents");

  return (
    <main className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-[1500px] space-y-6 p-4 sm:p-6 lg:p-8">
        <PageHeader
          eyebrow="Knowledge operations"
          title="Data"
          description="Review ingested knowledge files and import new PDF or spreadsheet data through a validated workflow."
        />

        <div role="tablist" aria-label="Data workspace" className="inline-flex gap-1 rounded-xl border border-terminal-border bg-terminal-panel p-1 shadow-sm">
          {TABS.map((item) => (
            <button
              key={item.id}
              id={`data-tab-${item.id}`}
              type="button"
              role="tab"
              aria-selected={tab === item.id}
              aria-controls={`data-panel-${item.id}`}
              tabIndex={tab === item.id ? 0 : -1}
              onClick={() => setTab(item.id)}
              className={`rounded-lg px-4 py-2 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-blue ${
                tab === item.id ? "bg-blue-600 text-white shadow-sm" : "text-terminal-muted hover:bg-terminal-bg hover:text-terminal-text"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>

        <section id={`data-panel-${tab}`} role="tabpanel" aria-labelledby={`data-tab-${tab}`} aria-label={TABS.find((item) => item.id === tab)?.label}>
          {tab === "documents" ? <DocumentsList /> : <ImportPanel />}
        </section>
      </div>
    </main>
  );
}
