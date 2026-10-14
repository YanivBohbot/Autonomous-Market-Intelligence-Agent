// @vitest-environment node
import { describe, expect, it } from "vitest";
import type { UserConfig } from "vite";
import config from "../vite.config";

describe("Vite development proxy", () => {
  it("keeps the /data page available while proxying only API paths below it", () => {
    const proxy = (config as UserConfig).server?.proxy;

    expect(proxy).toHaveProperty("/data/");
    expect(proxy).not.toHaveProperty("/data");
  });

  it("proxies the Research conversation history API", () => {
    const proxy = (config as UserConfig).server?.proxy;

    expect(proxy).toHaveProperty("/conversations");
  });
});
