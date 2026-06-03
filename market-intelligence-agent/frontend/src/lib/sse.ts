export interface SseEvent {
  event: string;
  data: unknown;
}

export interface ParseResult {
  events: SseEvent[];
  rest: string;
}

/**
 * Parse a growing SSE text buffer into complete frames.
 * Frames are separated by a blank line ("\n\n"). Any trailing partial
 * frame is returned in `rest` so the caller can prepend the next chunk.
 */
export function parseSseBuffer(buffer: string): ParseResult {
  const events: SseEvent[] = [];
  const parts = buffer.split("\n\n");
  const rest = parts.pop() ?? "";

  for (const frame of parts) {
    if (!frame.trim()) continue;
    let event = "message";
    const dataLines: string[] = [];
    for (const line of frame.split("\n")) {
      if (line.startsWith("event:")) {
        event = line.slice("event:".length).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice("data:".length).trim());
      }
    }
    const raw = dataLines.join("\n");
    let data: unknown = raw;
    try {
      data = JSON.parse(raw);
    } catch {
      // leave as raw string (e.g. keepalive comments)
    }
    events.push({ event, data });
  }

  return { events, rest };
}
