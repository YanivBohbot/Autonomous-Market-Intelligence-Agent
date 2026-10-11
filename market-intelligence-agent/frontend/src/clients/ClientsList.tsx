import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import type { ClientWithHoldings } from "../lib/api";
import { EmptyState } from "../ui/FeedbackStates";
import { StatusBadge, type StatusTone } from "../ui/StatusBadge";

export interface ClientsListProps {
  clients: ClientWithHoldings[];
  query: string;
  segment: string;
  riskProfile: string;
  onQueryChange: (value: string) => void;
  onSegmentChange: (value: string) => void;
  onRiskProfileChange: (value: string) => void;
  onClearFilters: () => void;
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

export function ClientsList({
  clients,
  query,
  segment,
  riskProfile,
  onQueryChange,
  onSegmentChange,
  onRiskProfileChange,
  onClearFilters,
}: ClientsListProps) {
  const navigate = useNavigate();
  const segments = useMemo(() => [...new Set(clients.map((client) => client.segment).filter(Boolean))].sort(), [clients]);
  const riskProfiles = useMemo(() => [...new Set(clients.map((client) => client.risk_profile).filter(Boolean))].sort(), [clients]);
  const normalizedQuery = query.trim().toLowerCase();
  const filtered = clients.filter((client) => {
    const matchesQuery = !normalizedQuery
      || client.name.toLowerCase().includes(normalizedQuery)
      || client.email.toLowerCase().includes(normalizedQuery)
      || client.holdings.some((holding) => holding.ticker.toLowerCase().includes(normalizedQuery));
    return matchesQuery
      && (segment === "all" || client.segment === segment)
      && (riskProfile === "all" || client.risk_profile === riskProfile);
  });
  const filtering = Boolean(normalizedQuery || segment !== "all" || riskProfile !== "all");

  if (clients.length === 0) {
    return <EmptyState title="No clients yet" description="Imported clients will appear here with their portfolio holdings." icon="clients" />;
  }

  return (
    <section aria-label="Client directory" className="space-y-4">
      <div className="rounded-2xl border border-terminal-border bg-surface-elevated p-4 shadow-sm">
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_180px_180px_auto]">
          <label className="space-y-1.5">
            <span className="text-xs font-semibold text-terminal-muted">Search clients</span>
            <input
              type="search"
              aria-label="Search clients"
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder="Name, email, or ticker"
              className="w-full rounded-xl border border-terminal-border bg-terminal-bg px-3 py-2 text-sm text-terminal-text outline-none transition-colors placeholder:text-terminal-muted/70 focus:border-brand-blue focus:ring-2 focus:ring-brand-blue/20"
            />
          </label>
          <label className="space-y-1.5">
            <span className="text-xs font-semibold text-terminal-muted">Segment</span>
            <select aria-label="Segment" value={segment} onChange={(event) => onSegmentChange(event.target.value)} className="w-full rounded-xl border border-terminal-border bg-terminal-bg px-3 py-2 text-sm text-terminal-text outline-none focus:border-brand-blue focus:ring-2 focus:ring-brand-blue/20">
              <option value="all">All segments</option>
              {segments.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <label className="space-y-1.5">
            <span className="text-xs font-semibold text-terminal-muted">Risk profile</span>
            <select aria-label="Risk profile" value={riskProfile} onChange={(event) => onRiskProfileChange(event.target.value)} className="w-full rounded-xl border border-terminal-border bg-terminal-bg px-3 py-2 text-sm text-terminal-text outline-none focus:border-brand-blue focus:ring-2 focus:ring-brand-blue/20">
              <option value="all">All risk profiles</option>
              {riskProfiles.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <button type="button" onClick={onClearFilters} disabled={!filtering} className="self-end rounded-xl border border-terminal-border px-3 py-2 text-sm font-semibold text-terminal-muted transition-colors hover:border-brand-blue/50 hover:text-brand-blue disabled:cursor-not-allowed disabled:opacity-45">
            Clear filters
          </button>
        </div>
        <p className="mt-3 text-xs text-terminal-muted">Showing {filtered.length} of {clients.length} clients</p>
      </div>

      {filtered.length === 0 ? (
        <EmptyState title="No clients match your filters" description="Try a broader search or clear the active filters." icon="clients" />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
          {filtered.map((client) => {
            const preview = client.holdings.slice(0, 3);
            const overflow = client.holdings.length - preview.length;
            return (
              <button
                key={client.client_id}
                type="button"
                aria-label={`Open client ${client.name}`}
                onClick={() => navigate(`/clients/${client.client_id}`)}
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
                      <span className="shrink-0 text-xs font-semibold text-brand-blue" aria-hidden="true">View →</span>
                    </div>
                    <p className="mt-2 text-xs text-terminal-muted">Advisor {client.advisor} · {client.city}</p>
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap items-center gap-2">
                  <StatusBadge tone="neutral">{client.segment}</StatusBadge>
                  <StatusBadge tone={riskTone(client.risk_profile)}>{client.risk_profile}</StatusBadge>
                  <span className="ml-auto text-xs text-terminal-muted">{client.holdings.length} {client.holdings.length === 1 ? "holding" : "holdings"}</span>
                </div>

                <div className="mt-4 border-t border-terminal-border pt-3">
                  {preview.length === 0 ? (
                    <p className="text-xs text-terminal-muted">No holdings</p>
                  ) : (
                    <div className="flex flex-wrap items-center gap-2">
                      {preview.map((holding) => (
                        <span key={holding.ticker} className="rounded-lg bg-surface-soft px-2.5 py-1 font-mono text-xs font-semibold text-terminal-text">
                          {holding.ticker}
                        </span>
                      ))}
                      {overflow > 0 && <span className="text-xs font-semibold text-terminal-muted">+{overflow} more</span>}
                    </div>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}
