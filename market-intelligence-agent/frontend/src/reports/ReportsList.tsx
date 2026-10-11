import { useNavigate } from "react-router-dom";
import type { ClientWithHoldings } from "../lib/api";
import { EmptyState } from "../ui/FeedbackStates";
import { SectionHeader } from "../ui/SectionHeader";
import { StatusBadge, type StatusTone } from "../ui/StatusBadge";

function titleCase(value: string) {
  return value ? `${value[0].toUpperCase()}${value.slice(1)}` : "Unknown";
}

function riskTone(profile: string): StatusTone {
  const normalized = profile.toLowerCase();
  if (normalized.includes("aggressive") || normalized.includes("high")) return "warning";
  if (normalized.includes("conservative") || normalized.includes("low")) return "success";
  return "info";
}

function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("") || "CL";
}

export function ReportsList({ clients }: { clients: ClientWithHoldings[] }) {
  const navigate = useNavigate();

  if (clients.length === 0) {
    return <EmptyState title="No report clients yet" description="Import client portfolios to make report workspaces available." icon="document" />;
  }

  return (
    <section aria-label="Report client directory" className="space-y-4">
      <SectionHeader title="Choose a client" description="Open a lightweight snapshot before deciding whether to load the full analysis." />
      <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
        {clients.map((client) => {
          const holdingLabel = `${client.holdings.length} ${client.holdings.length === 1 ? "holding" : "holdings"}`;
          return (
            <button
              key={client.client_id}
              type="button"
              aria-label={`Open report for ${client.name}`}
              onClick={() => navigate(`/reports/${client.client_id}`)}
              className="group rounded-2xl border border-terminal-border bg-surface-elevated p-5 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:border-brand-blue/45 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-blue"
            >
              <div className="flex items-start gap-3">
                <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-blue-600 text-sm font-bold text-white">{initials(client.name)}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate font-semibold text-terminal-text group-hover:text-brand-blue">{client.name}</p>
                      <p className="truncate text-xs text-terminal-muted">{client.email}</p>
                    </div>
                    <span className="shrink-0 text-xs font-semibold text-brand-blue" aria-hidden="true">Open →</span>
                  </div>
                  <p className="mt-2 text-xs text-terminal-muted">{client.city} · {holdingLabel}</p>
                </div>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <StatusBadge>{client.segment}</StatusBadge>
                <StatusBadge tone={riskTone(client.risk_profile)}>{titleCase(client.risk_profile)} risk</StatusBadge>
                <StatusBadge>Advisor {client.advisor}</StatusBadge>
              </div>
            </button>
          );
        })}
      </div>
    </section>
  );
}
