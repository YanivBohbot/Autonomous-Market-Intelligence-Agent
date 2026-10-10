import { useEffect, useRef, useState } from "react";
import { useAgent } from "@copilotkit/react-core/v2";
import { Icon } from "../ui/Icon";
import type { VoiceActivityEvent } from "../voice/types";
import { MARKET_DESK_AGENT_ID } from "./constants";
import {
  groupActivityRuns,
  humanizeToolName,
  reduceActivity,
  voiceActivityToAgUi,
  type ActivityRun,
  type AgUiEvent,
  type DeskActivity,
  type SpecialistLabel,
} from "./activity";

const SPECIALIST_NAME: Record<SpecialistLabel, string> = {
  SUPERVISOR: "Supervisor",
  RAG: "RAG",
  FINANCE: "Finance",
  PORTFOLIO: "Portfolio",
  BROWSER: "Browser",
  EMAIL: "Email",
  FILES: "Files",
  MEMORY: "Memory",
};

const SPECIALIST_TONE: Record<SpecialistLabel, string> = {
  SUPERVISOR: "border-blue-500 bg-blue-500",
  RAG: "border-sky-500 bg-sky-500",
  FINANCE: "border-amber-500 bg-amber-500",
  PORTFOLIO: "border-emerald-500 bg-emerald-500",
  BROWSER: "border-violet-500 bg-violet-500",
  EMAIL: "border-pink-500 bg-pink-500",
  FILES: "border-teal-500 bg-teal-500",
  MEMORY: "border-indigo-500 bg-indigo-500",
};

const RUN_STATUS: Record<ActivityRun["status"], { label: string; className: string }> = {
  running: { label: "Running", className: "bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300" },
  awaiting: { label: "Waiting", className: "bg-amber-50 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300" },
  done: { label: "Complete", className: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300" },
  error: { label: "Failed", className: "bg-red-50 text-red-700 dark:bg-red-950/50 dark:text-red-300" },
};

function formatTime(timestamp: number) {
  return new Date(timestamp).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function formatDuration(durationMs: number) {
  return durationMs < 1_000 ? `${durationMs} ms` : `${(durationMs / 1_000).toFixed(1)} s`;
}

function TimelineItem({ item }: { item: DeskActivity }) {
  let nodeClass = "border-terminal-border bg-surface-elevated";
  let content;

  switch (item.kind) {
    case "specialist":
      nodeClass = SPECIALIST_TONE[item.label];
      content = (
        <div>
          <p className="text-sm font-semibold text-terminal-text">{SPECIALIST_NAME[item.label]}</p>
          <p className="text-[11px] text-terminal-muted">Agent step started</p>
        </div>
      );
      break;
    case "tool":
      nodeClass = item.status === "running" ? "border-blue-500 bg-blue-500" : "border-emerald-500 bg-emerald-500";
      content = (
        <div>
          <p className="text-sm font-medium text-terminal-text">{humanizeToolName(item.name)}</p>
          <div className="mt-0.5 flex items-center gap-2 text-[11px] text-terminal-muted">
            <span>{item.status === "running" ? "Running tool" : "Tool completed"}</span>
            {item.durationMs !== undefined && <span className="font-mono tabular-nums">{formatDuration(item.durationMs)}</span>}
          </div>
        </div>
      );
      break;
    case "awaiting":
      nodeClass = "border-amber-500 bg-amber-500";
      content = (
        <div>
          <p className="text-sm font-semibold text-amber-700 dark:text-amber-300">Awaiting approval</p>
          <p className="text-[11px] text-terminal-muted">Human decision required</p>
        </div>
      );
      break;
    case "done":
      nodeClass = "border-emerald-500 bg-emerald-500";
      content = (
        <div>
          <p className="text-sm font-semibold text-emerald-700 dark:text-emerald-300">Completed</p>
          {item.totalTokens !== null && <p className="font-mono text-[11px] tabular-nums text-terminal-muted">{item.totalTokens.toLocaleString("en-US")} tokens</p>}
        </div>
      );
      break;
    case "error":
      nodeClass = "border-red-500 bg-red-500";
      content = (
        <div className="min-w-0">
          <p className="text-sm font-semibold text-red-700 dark:text-red-300">Run failed</p>
          <p className="break-words text-[11px] leading-relaxed text-terminal-muted">{item.message}</p>
        </div>
      );
      break;
  }

  return (
    <li className="relative pb-4 pl-5 last:pb-0">
      <span className={`absolute -left-[5px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-surface-elevated ${nodeClass}`} aria-hidden="true" />
      <div className="flex items-start justify-between gap-3">
        {content}
        <time className="shrink-0 pt-0.5 font-mono text-[9px] tabular-nums text-terminal-muted">{formatTime(item.ts)}</time>
      </div>
    </li>
  );
}

function RunCard({ run, index, count }: { run: ActivityRun; index: number; count: number }) {
  const current = index === 0 && (run.status === "running" || run.status === "awaiting");
  const status = RUN_STATUS[run.status];

  return (
    <article data-testid="activity-run" className="rounded-2xl border border-terminal-border bg-surface-elevated p-4 shadow-sm">
      <header className="mb-4 flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold text-terminal-text">{current ? "Current run" : `Run ${count - index}`}</p>
          <time className="font-mono text-[10px] tabular-nums text-terminal-muted">Started {formatTime(run.startedAt)}</time>
        </div>
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${status.className}`}>{status.label}</span>
      </header>
      <ol className="ml-1 border-l border-terminal-border" aria-label={`${current ? "Current" : "Previous"} run timeline`}>
        {run.items.map((item) => <TimelineItem key={item.id} item={item} />)}
      </ol>
    </article>
  );
}

// Same agent instance CopilotChat drives (useAgent({agentId}) without a
// threadId; a threadId would create a private, thread-scoped copy). DeskView is
// remounted per thread, so the list never mixes sessions.
const NO_VOICE_EVENTS: VoiceActivityEvent[] = [];

export function DeskActivityRail({
  voiceEvents = NO_VOICE_EVENTS,
}: {
  voiceEvents?: VoiceActivityEvent[];
}) {
  const { agent } = useAgent({ agentId: MARKET_DESK_AGENT_ID });
  const [items, setItems] = useState<DeskActivity[]>([]);
  const lastVoiceSequence = useRef(0);
  const runs = groupActivityRuns(items);

  useEffect(() => {
    const subscription = agent.subscribe({
      onEvent: ({ event }) => {
        setItems((previous) => reduceActivity(previous, event as unknown as AgUiEvent, Date.now()));
      },
      // HTTP errors and dropped streams do not arrive as RUN_ERROR events.
      onRunFailed: ({ error }) => {
        const failure: AgUiEvent = { type: "RUN_ERROR", message: error?.message ?? String(error) };
        setItems((previous) => reduceActivity(previous, failure, Date.now()));
      },
    });
    return () => subscription.unsubscribe();
  }, [agent]);

  useEffect(() => {
    if (voiceEvents.length === 0) {
      lastVoiceSequence.current = 0;
      return;
    }

    const fresh = voiceEvents
      .filter((event) => event.sequence > lastVoiceSequence.current)
      .sort((left, right) => left.sequence - right.sequence);
    if (fresh.length === 0) return;

    setItems((previous) =>
      fresh.reduce(
        (next, event) =>
          reduceActivity(next, voiceActivityToAgUi(event), Date.now()),
        previous,
      ),
    );
    lastVoiceSequence.current = fresh[fresh.length - 1].sequence;
  }, [voiceEvents]);

  return (
    <section aria-label="Agent activity timeline" className="flex h-full min-h-0 flex-col bg-surface-soft">
      <header className="border-b border-terminal-border bg-surface-elevated px-4 py-3">
        <div className="flex items-center gap-2">
          <Icon name="activity" className="h-4 w-4 text-brand-blue" />
          <h2 className="text-sm font-semibold text-terminal-text">Activity timeline</h2>
        </div>
        <p className="mt-1 text-[11px] leading-relaxed text-terminal-muted">Supervisor, specialist, and tool progress for this session.</p>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto p-3" aria-live="polite">
        {runs.length === 0 ? (
          <div className="flex h-full min-h-48 flex-col items-center justify-center px-3 text-center">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-blue-50 text-brand-blue dark:bg-blue-950/50" aria-hidden="true">
              <Icon name="activity" className="h-5 w-5" />
            </span>
            <p className="mt-3 text-sm font-semibold text-terminal-text">System ready</p>
            <p className="mt-1 text-xs leading-relaxed text-terminal-muted">Activity will appear when a Research or client workspace run begins.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {runs.map((run, index) => <RunCard key={run.id} run={run} index={index} count={runs.length} />)}
          </div>
        )}
      </div>
    </section>
  );
}
