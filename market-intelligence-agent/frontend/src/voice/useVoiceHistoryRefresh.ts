import { useEffect, useRef, useState } from "react";

import { getThreadHistory, type ThreadMessage } from "../lib/api";
import type { VoiceActivityEvent } from "./types";

const TRIGGERS = new Set<VoiceActivityEvent["kind"]>(["run_finished", "approval_required", "run_error"]);

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
  const requestIdRef = useRef(0);

  // In-flight fetches must survive `events` changing identity (every appended
  // event does that); only unmount or a thread switch invalidates them.
  useEffect(() => {
    return () => {
      requestIdRef.current += 1;
    };
  }, [threadId]);

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
    const requestId = ++requestIdRef.current;
    getThreadHistory(threadId)
      .then((history) => {
        if (requestId !== requestIdRef.current) return;
        setMessages(history);
        setRefreshError(null);
      })
      .catch(() => {
        if (requestId === requestIdRef.current) setRefreshError("Could not refresh the conversation");
      });
  }, [events, setMessages, threadId]);

  return { refreshError };
}
