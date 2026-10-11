import type { HttpAgent } from "@copilotkit/react-core/v2";

import type { ThreadMessage } from "../lib/api";

type Message = HttpAgent["messages"][number];

// /history returns only plain user/assistant text, so replacing the chat's
// messages with it would drop the tool-call messages the tool cards render
// from. Keep what the agent already has and append only unseen ids.
export function mergeHistory(current: readonly Message[], history: readonly ThreadMessage[]): Message[] {
  const seen = new Set(current.map((message) => message.id));
  const fresh = history.filter((message) => !seen.has(message.id));
  return [...current, ...(fresh as unknown as Message[])];
}
