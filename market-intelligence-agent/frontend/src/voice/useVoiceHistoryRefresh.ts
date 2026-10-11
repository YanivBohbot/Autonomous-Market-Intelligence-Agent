import { useEffect, useRef, useState } from "react";

import { getThreadHistory, type ThreadMessage } from "../lib/api";
import type { VoiceActivityEvent } from "./types";

const TRIGGERS = new Set<VoiceActivityEvent["kind"]>(["run_finished", "approval_required"]);

// Spoken turns are written to the checkpoint by the voice worker, not by
// CopilotKit, so the chat never sees them on its own. When a voice turn
// finishes (or pauses for approval), reload the thread's history -- the same
// call DeskView makes on mount -- so the spoken question and answer appear.
export function useVoiceHistoryRefresh(
  threadId: string,
  events: VoiceActivityEvent[] | undefined,
  setMessages: (messages: ThreadMessage[]) => void,
): { refreshError: string | null } {
  const handledRef = useRef(0);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  useEffect(() => {
    // A new voice session resets both the events list and the server-side
    // sequence counter, so forget what was handled when the list empties.
    if (!events?.length) {
      handledRef.current = 0;
      return;
    }
    const latestTrigger = events.reduce(
      (max, item) => (TRIGGERS.has(item.kind) && item.sequence > max ? item.sequence : max),
      0,
    );
    if (latestTrigger <= handledRef.current) return;
    handledRef.current = latestTrigger;
    let active = true;
    getThreadHistory(threadId)
      .then((history) => {
        if (!active) return;
        setMessages(history);
        setRefreshError(null);
      })
      .catch(() => {
        if (active) setRefreshError("Could not refresh the conversation");
      });
    return () => {
      active = false;
    };
  }, [events, setMessages, threadId]);

  return { refreshError };
}
