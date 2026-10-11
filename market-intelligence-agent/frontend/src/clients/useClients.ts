import { useCallback, useEffect, useState } from "react";
import { getClients, type ClientWithHoldings } from "../lib/api";

export function useClients(): {
  clients: ClientWithHoldings[];
  loading: boolean;
  error: string | null;
  retry: () => void;
} {
  const [clients, setClients] = useState<ClientWithHoldings[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);

    getClients()
      .then((loaded) => {
        if (active) setClients(loaded);
      })
      .catch(() => {
        if (active) setError("Failed to load clients.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [attempt]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  return { clients, loading, error, retry };
}
