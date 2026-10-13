import type { DisplayPayload } from "./types";

const cell = (v: unknown) => (v === null || v === undefined ? "—" : String(v));

export function SqlResultTable({ display }: { display: Extract<DisplayPayload, { type: "sql_table" }> }) {
  return (
    <div className="w-full rounded-xl border border-terminal-border bg-terminal-panel card-shadow p-3 font-mono text-xs text-terminal-text">
      <div className="max-h-72 overflow-auto">
        <table className="w-full">
          <thead>
            <tr>
              {display.columns.map((c) => (
                <th key={c} className="sticky top-0 bg-terminal-panel px-2 py-1 text-left text-terminal-muted">{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {display.rows.map((row, i) => (
              <tr key={i} className="border-t border-terminal-border/50">
                {row.map((v, j) => <td key={j} className={`px-2 py-1 ${typeof v === "number" ? "text-right" : ""}`}>{cell(v)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {display.truncated && <div className="mt-1 text-terminal-muted">Showing the first 50 rows.</div>}
    </div>
  );
}
