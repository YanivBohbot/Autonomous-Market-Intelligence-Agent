import { describe, it, expect, vi, beforeEach } from "vitest";
import { uploadToWorkspace } from "./api";

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
