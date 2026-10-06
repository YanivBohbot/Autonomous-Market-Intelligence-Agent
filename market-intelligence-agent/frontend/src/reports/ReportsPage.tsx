import { useMemo } from "react";
import { useClients } from "../clients/useClients";
import { ErrorState, Skeleton } from "../ui/FeedbackStates";
import { MetricCard } from "../ui/MetricCard";
import { PageHeader } from "../ui/PageHeader";
import { ReportsList } from "./ReportsList";

export function ReportsPage() {
  const { clients, loading, error, retry } = useClients();
  const metrics = useMemo(() => ({
    holdings: clients.reduce((total, client) => total + client.holdings.length, 0),
    segments: new Set(clients.map((client) => client.segment).filter(Boolean)).size,
    advisors: new Set(clients.map((client) => client.advisor).filter(Boolean)).size,
  }), [clients]);

  return (
    <main className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-[1500px] space-y-6 p-4 sm:p-6 lg:p-8">
        <PageHeader
          eyebrow="Portfolio intelligence"
          title="Reports"
          description="Choose a client, review the fast portfolio snapshot, then load deeper analysis only when you need it."
        />

        {loading && clients.length === 0 ? (
          <div aria-label="Loading reports" className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="h-28" label="Loading report metric" />)}
            </div>
            <Skeleton className="h-64" label="Loading report directory" />
          </div>
        ) : error && clients.length === 0 ? (
          <ErrorState title="Reports unavailable" description={error} actionLabel="Retry" onAction={retry} />
        ) : (
          <>
            <section aria-label="Report overview" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <MetricCard label="Report-ready clients" value={clients.length} detail="Client workspaces available" tone="info" />
              <MetricCard label="Holding rows" value={metrics.holdings} detail="Positions ready for analysis" />
              <MetricCard label="Segments" value={metrics.segments} detail="Service groups represented" tone="success" />
              <MetricCard label="Advisors" value={metrics.advisors} detail="Relationship coverage" tone="warning" />
            </section>
            <ReportsList clients={clients} />
          </>
        )}
      </div>
    </main>
  );
}
