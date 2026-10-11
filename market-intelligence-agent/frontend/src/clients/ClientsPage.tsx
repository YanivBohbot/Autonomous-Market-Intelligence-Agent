import { useMemo, useState } from "react";
import { ErrorState, Skeleton } from "../ui/FeedbackStates";
import { MetricCard } from "../ui/MetricCard";
import { PageHeader } from "../ui/PageHeader";
import { ClientsList } from "./ClientsList";
import { useClients } from "./useClients";

function titleCase(value: string) {
  return value ? `${value[0].toUpperCase()}${value.slice(1)}` : "Unknown";
}

export function ClientsPage() {
  const { clients, loading, error, retry } = useClients();
  const [query, setQuery] = useState("");
  const [segment, setSegment] = useState("all");
  const [riskProfile, setRiskProfile] = useState("all");

  const metrics = useMemo(() => {
    const holdingRows = clients.reduce((total, client) => total + client.holdings.length, 0);
    const segments = new Set(clients.map((client) => client.segment).filter(Boolean)).size;
    const risks = clients.reduce<Record<string, number>>((counts, client) => {
      const key = client.risk_profile || "unknown";
      counts[key] = (counts[key] ?? 0) + 1;
      return counts;
    }, {});
    const riskDistribution = Object.entries(risks)
      .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
      .map(([name, count]) => `${titleCase(name)} ${count}`)
      .join(" · ") || "No profiles";
    return { holdingRows, segments, riskDistribution };
  }, [clients]);

  const clearFilters = () => {
    setQuery("");
    setSegment("all");
    setRiskProfile("all");
  };

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-[1500px] space-y-6 p-4 sm:p-6 lg:p-8">
        <PageHeader
          eyebrow="Wealth management"
          title="Clients"
          description="Search client relationships, review portfolio coverage, and open a focused intelligence workspace."
        />

        {loading && clients.length === 0 ? (
          <div aria-label="Loading clients" className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="h-28" label="Loading client metric" />)}
            </div>
            <Skeleton className="h-64" label="Loading client directory" />
          </div>
        ) : error && clients.length === 0 ? (
          <ErrorState title="Clients unavailable" description={error} actionLabel="Retry" onAction={retry} />
        ) : (
          <>
            <section aria-label="Client overview" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <MetricCard label="Clients" value={clients.length} detail="Relationships in the directory" tone="info" />
              <MetricCard label="Holding rows" value={metrics.holdingRows} detail="Positions across all clients" />
              <MetricCard label="Segments" value={metrics.segments} detail="Distinct service segments" tone="success" />
              <MetricCard label="Risk distribution" value={<span className="text-base leading-snug">{metrics.riskDistribution}</span>} detail="Client profiles by count" tone="warning" />
            </section>
            <ClientsList
              clients={clients}
              query={query}
              segment={segment}
              riskProfile={riskProfile}
              onQueryChange={setQuery}
              onSegmentChange={setSegment}
              onRiskProfileChange={setRiskProfile}
              onClearFilters={clearFilters}
            />
          </>
        )}
      </div>
    </div>
  );
}
