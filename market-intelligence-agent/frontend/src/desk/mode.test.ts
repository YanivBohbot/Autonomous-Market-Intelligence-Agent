import { describe, it, expect, beforeEach, vi } from "vitest";
import { loadMode, saveMode } from "./mode";

describe("console mode persistence", () => {
  beforeEach(() => localStorage.clear());

  it("defaults to desk", () => {
    expect(loadMode()).toBe("desk");
  });

  it("round-trips through localStorage", () => {
    saveMode("classic");
    expect(loadMode()).toBe("classic");
  });

  it("ignores garbage values", () => {
    localStorage.setItem("mia.consoleMode", "banana");
    expect(loadMode()).toBe("desk");
  });

  it("survives a throwing storage", () => {
    const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(loadMode()).toBe("desk");
    expect(() => saveMode("classic")).not.toThrow();
    get.mockRestore();
    set.mockRestore();
  });
});
