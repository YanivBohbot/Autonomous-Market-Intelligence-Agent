import { describe, it, expect, vi, beforeEach } from "vitest";
import { uploadToWorkspace, getClients, getClientSummary, getDocuments, importPdf, previewImport, confirmImport } from "./api";

describe("uploadToWorkspace", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ path: "uploads/ab12cd34_report.pdf" }),
    }));
  });

  it("posts the file as multipart form data and returns the saved path", async () => {
    const file = new File(["content"], "report.pdf", { type: "application/pdf" });
    const result = await uploadToWorkspace(file);
    expect(result).toEqual({ path: "uploads/ab12cd34_report.pdf" });

    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/copilot/uploads");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("file")).toBe(file);
  });

  it("throws when the upload fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 413, text: async () => "too big" }));
    const file = new File(["x"], "big.bin");
    await expect(uploadToWorkspace(file)).rejects.toThrow("413");
  });
});

describe("data section API", () => {
  it("getClients fetches /data/clients", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [{ email: "jane@x.com" }] });
    vi.stubGlobal("fetch", fetchMock);
    const result = await getClients();
    expect(fetchMock).toHaveBeenCalledWith("/data/clients");
    expect(result).toEqual([{ email: "jane@x.com" }]);
  });

  it("getClientSummary fetches /data/clients/:id/summary", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        client_id: 1, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
        risk_profile: "balanced", advisor: "Sam", city: "Paris",
        totals: { market_value: 2000, cost_basis: 1500, unrealized_pnl: 500, unrealized_pnl_pct: 33.33 },
        positions: [], unpriced_tickers: [],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const result = await getClientSummary(1);
    expect(fetchMock).toHaveBeenCalledWith("/data/clients/1/summary");
    expect(result.name).toBe("Jane Doe");
    expect(result.totals?.market_value).toBe(2000);
  });

  it("getDocuments fetches /data/documents", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ["a.pdf"] }));
    expect(await getDocuments()).toEqual(["a.pdf"]);
  });

  it("importPdf posts multipart to /data/import/pdf", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ filename: "a.pdf", chunks_added: 2 }) });
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["%PDF"], "a.pdf", { type: "application/pdf" });
    const result = await importPdf(file);
    expect(fetchMock.mock.calls[0][0]).toBe("/data/import/pdf");
    expect(result).toEqual({ filename: "a.pdf", chunks_added: 2 });
  });

  it("previewImport posts rows to /data/import/preview", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ type: "holdings", valid: true, rows: [], errors: [] }) });
    vi.stubGlobal("fetch", fetchMock);
    const rows = [{ ticker: "AAPL" }];
    const result = await previewImport(rows);
    expect(fetchMock).toHaveBeenCalledWith("/data/import/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rows }),
    });
    expect(result.valid).toBe(true);
  });

  it("confirmImport posts type and rows to /data/import/confirm", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ written: 1 }) });
    vi.stubGlobal("fetch", fetchMock);
    const rows = [{ ticker: "AAPL" }];
    const result = await confirmImport("holdings", rows);
    expect(fetchMock).toHaveBeenCalledWith("/data/import/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type: "holdings", rows }),
    });
    expect(result).toEqual({ written: 1 });
  });
});
