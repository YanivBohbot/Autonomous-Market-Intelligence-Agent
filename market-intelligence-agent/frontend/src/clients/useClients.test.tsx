import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ClientWithHoldings } from "../lib/api";
import { useClients } from "./useClients";

const CLIENTS: ClientWithHoldings[] = [{
  client_id: 1,
  name: "Jane Doe",
  email: "jane@example.com",
  segment: "VIP",
  risk_profile: "balanced",
  advisor: "Sam",
  city: "Paris",
  holdings: [{ ticker: "AAPL", shares: 10, avg_cost: 150 }],
}];

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useClients", () => {
  it("loads all clients with exactly one /data/clients request", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => CLIENTS });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useClients());
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.clients).toEqual(CLIENTS);
    expect(result.current.error).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith("/data/clients");
  });

  it("reports a failure and retries only when requested", async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce({ ok: true, json: async () => CLIENTS });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useClients());
    await waitFor(() => expect(result.current.error).toBe("Failed to load clients."));
    expect(fetchMock).toHaveBeenCalledTimes(1);

    act(() => result.current.retry());
    await waitFor(() => expect(result.current.clients).toEqual(CLIENTS));

    expect(result.current.error).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
