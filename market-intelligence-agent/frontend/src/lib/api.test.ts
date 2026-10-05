import { describe, it, expect, vi, beforeEach } from "vitest";
import { uploadToWorkspace, getClients, getClientSummary, getDocuments, getThreadHistory, importPdf, previewImport, confirmImport, getClientReport, generateClientReport } from "./api";

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

  it("getThreadHistory fetches /copilot/market-desk/history?thread_id=...", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{ id: "u1", role: "user", content: "hi" }],
    });
    vi.stubGlobal("fetch", fetchMock);
    const result = await getThreadHistory("clients_17");
    expect(fetchMock).toHaveBeenCalledWith("/copilot/market-desk/history?thread_id=clients_17");
    expect(result).toEqual([{ id: "u1", role: "user", content: "hi" }]);
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

describe("reports API", () => {
  it("getClientReport fetches /data/clients/:id/report", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        client_id: 1, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
        risk_profile: "balanced", advisor: "Sam", city: "Paris",
        totals: null, positions: [], sector_allocation: null, concentration: null,
        price_history: {}, unpriced_tickers: [], generated_reports: [],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const result = await getClientReport(1);
    expect(fetchMock).toHaveBeenCalledWith("/data/clients/1/report");
    expect(result.name).toBe("Jane Doe");
  });

  it("generateClientReport posts to /data/clients/:id/report/generate", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ filename: "jane-doe-portfolio-brief-2026-01-01.xlsx" }) });
    vi.stubGlobal("fetch", fetchMock);
    const result = await generateClientReport(1);
    expect(fetchMock).toHaveBeenCalledWith("/data/clients/1/report/generate", { method: "POST" });
    expect(result.filename).toBe("jane-doe-portfolio-brief-2026-01-01.xlsx");
  });

  it("generateClientReport throws the backend's detail message on failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 502, json: async () => ({ detail: "could not price: AAPL" }),
    }));
    await expect(generateClientReport(1)).rejects.toThrow("could not price: AAPL");
  });

  it("generateClientReport falls back to a generic message when the body isn't JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 500, json: async () => { throw new Error("not json"); },
    }));
    await expect(generateClientReport(1)).rejects.toThrow("500");
  });
});
