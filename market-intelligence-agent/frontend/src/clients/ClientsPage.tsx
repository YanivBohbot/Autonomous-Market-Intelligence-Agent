import { ClientsList } from "./ClientsList";

export function ClientsPage() {
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto p-4">
      <ClientsList />
    </div>
  );
}
