import { describe, it, expect } from "vitest";
import { parseSseBuffer, type SseEvent } from "./sse";

describe("parseSseBuffer", () => {
  it("parses a single complete frame", () => {
    const buf = 'event: token\ndata: {"token":"Hi"}\n\n';
    const { events, rest } = parseSseBuffer(buf);
    expect(events).toEqual<SseEvent[]>([{ event: "token", data: { token: "Hi" } }]);
    expect(rest).toBe("");
  });

  it("parses multiple frames in one buffer", () => {
    const buf =
      'event: node\ndata: {"node":"rag","tool_calls":null}\n\n' +
      'event: token\ndata: {"token":"Hello"}\n\n';
    const { events } = parseSseBuffer(buf);
    expect(events.map((e) => e.event)).toEqual(["node", "token"]);
  });

  it("keeps an incomplete trailing frame in rest", () => {
    const buf = 'event: token\ndata: {"token":"Hi"}\n\nevent: tok';
    const { events, rest } = parseSseBuffer(buf);
    expect(events).toHaveLength(1);
    expect(rest).toBe("event: tok");
  });

  it("handles a data-only frame (no event line) as event 'message'", () => {
    const buf = 'data: {"x":1}\n\n';
    const { events } = parseSseBuffer(buf);
    expect(events[0].event).toBe("message");
    expect(events[0].data).toEqual({ x: 1 });
  });

  it("tolerates non-JSON data by passing the raw string", () => {
    const buf = "event: ping\ndata: keepalive\n\n";
    const { events } = parseSseBuffer(buf);
    expect(events[0].data).toBe("keepalive");
  });
});
