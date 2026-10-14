import { describe, expect, it } from "vitest";
import { relativeTime } from "./relativeTime";

const now = new Date("2026-10-14T12:00:00Z");
describe("relativeTime", () => {
  it.each([
    ["2026-10-14T11:59:40Z", "just now"],
    ["2026-10-14T11:55:00Z", "5m ago"],
    ["2026-10-14T10:00:00Z", "2h ago"],
    ["2026-10-11T12:00:00Z", "3d ago"],
  ])("%s -> %s", (iso, out) => expect(relativeTime(iso, now)).toBe(out));
  it("falls back to a short date after a week", () => {
    expect(relativeTime("2026-10-01T12:00:00Z", now)).toMatch(/Oct/);
  });
});
