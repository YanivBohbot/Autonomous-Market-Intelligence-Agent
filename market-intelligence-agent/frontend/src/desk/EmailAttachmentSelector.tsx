import { useEffect, useRef, useState } from "react";

import { getGeneratedReports, type GeneratedReportOption } from "../lib/api";

interface EmailAttachmentSelectorProps {
  recipient: string;
  value: string;
  disabled?: boolean;
  onChange: (filename: string) => void;
}

function formatGeneratedAt(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString();
}

export function EmailAttachmentSelector({
  recipient,
  value,
  disabled = false,
  onChange,
}: EmailAttachmentSelectorProps) {
  const [reports, setReports] = useState<GeneratedReportOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const valueRef = useRef(value);
  const onChangeRef = useRef(onChange);

  valueRef.current = value;
  onChangeRef.current = onChange;

  useEffect(() => {
    let active = true;
    setLoading(true);
    setFailed(false);

    const timer = window.setTimeout(async () => {
      try {
        const nextReports = await getGeneratedReports(recipient);
        if (!active) return;
        setReports(nextReports);
        if (
          valueRef.current
          && !nextReports.some((report) => report.filename === valueRef.current)
        ) {
          onChangeRef.current("");
        }
      } catch {
        if (!active) return;
        setReports([]);
        setFailed(true);
      } finally {
        if (active) setLoading(false);
      }
    }, 250);

    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [recipient]);

  return (
    <div className="approval-field">
      <label htmlFor="email-attachment">Attachment (optional)</label>
      <select
        id="email-attachment"
        value={value}
        disabled={disabled || loading || reports.length === 0}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">No attachment</option>
        {reports.map((report) => (
          <option key={report.filename} value={report.filename}>
            {report.filename} · {formatGeneratedAt(report.generated_at)}
          </option>
        ))}
      </select>
      {loading && <span role="status">Loading generated reports…</span>}
      {!loading && failed && <span role="alert">Generated reports unavailable</span>}
      {!loading && !failed && reports.length === 0 && (
        <span>No generated reports available</span>
      )}
    </div>
  );
}
