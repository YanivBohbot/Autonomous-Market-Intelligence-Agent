import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { DeskView } from "../desk/DeskView";
import { newThreadId } from "../lib/api";
import { ConversationPanel } from "./ConversationPanel";

const newResearchId = () => `desk_${newThreadId()}`;

export function ResearchPage() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("c");
  const fallback = useMemo(newResearchId, [requested]);
  const threadId = requested && requested.startsWith("desk_") ? requested : fallback;
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    if (requested !== threadId) setParams({ c: threadId }, { replace: true });
  }, [requested, threadId, setParams]);

  const open = useCallback((id: string) => setParams({ c: id }), [setParams]);
  const startNew = useCallback(() => open(newResearchId()), [open]);
  const onDeleted = useCallback((id: string) => { if (id === threadId) startNew(); }, [threadId, startNew]);
  const onTurnFinished = useCallback(() => setRefreshKey((n) => n + 1), []);

  return (
    <div className="flex min-h-0 flex-1">
      <ConversationPanel activeId={threadId} refreshKey={refreshKey} onSelect={open} onNew={startNew} onDeleted={onDeleted} />
      <DeskView key={threadId} threadId={threadId} voiceEnabled onTurnFinished={onTurnFinished} />
    </div>
  );
}
