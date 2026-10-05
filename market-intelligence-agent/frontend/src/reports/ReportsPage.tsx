import { ClientsList } from "../clients/ClientsList";

export function ReportsPage() {
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto p-4">
      <ClientsList basePath="/reports" />
    </div>
  );
}
