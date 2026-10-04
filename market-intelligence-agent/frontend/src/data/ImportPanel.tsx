import { useRef, useState, type ChangeEvent } from "react";
import * as XLSX from "xlsx";
import { confirmImport, importPdf, previewImport, type ImportPreviewResult } from "../lib/api";

export function ImportPanel() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [preview, setPreview] = useState<ImportPreviewResult | null>(null);
  const [rawRows, setRawRows] = useState<Record<string, unknown>[] | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function onFileChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0] ?? null;
    setSelectedFile(file);
    setStatus(null);
    setPreview(null);
    setRawRows(null);
  }

  async function onUpload() {
    const file = selectedFile;
    if (!file) return;
    setUploading(true);
    setStatus(null);
    try {
      if (file.name.toLowerCase().endsWith(".pdf")) {
        const result = await importPdf(file);
        setStatus(`Ingested ${result.filename}: ${result.chunks_added} chunks added.`);
        return;
      }

      const buffer = await file.arrayBuffer();
      const workbook = XLSX.read(buffer, { type: "array" });
      const sheet = workbook.Sheets[workbook.SheetNames[0]];
      const rows = XLSX.utils.sheet_to_json(sheet) as Record<string, unknown>[];

      const result = await previewImport(rows);
      setPreview(result);
      setRawRows(rows);
    } catch (err) {
      setStatus(`Error: ${(err as Error).message}`);
    } finally {
      setUploading(false);
      setSelectedFile(null);
      // Reset so re-selecting the SAME filename (e.g. after fixing a
      // rejected import) still fires a change event.
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function onConfirm() {
    if (!preview || !preview.valid || !rawRows) return;
    setConfirming(true);
    try {
      const result = await confirmImport(preview.type, rawRows);
      setStatus(`Imported ${result.written} row(s).`);
      setPreview(null);
      setRawRows(null);
    } catch (err) {
      setStatus(`Error: ${(err as Error).message}`);
    } finally {
      setConfirming(false);
    }
  }

  return (
    <div className="space-y-3 font-mono text-sm text-terminal-text">
      <div className="flex items-center gap-2">
        <label className="block">
          <span className="mb-1 block text-xs text-terminal-muted">Choose a file (.pdf, .xlsx)</span>
          <input ref={inputRef} type="file" accept=".pdf,.xlsx,.xls" onChange={onFileChange} className="text-xs" />
        </label>
        <button
          type="button"
          onClick={onUpload}
          disabled={!selectedFile || uploading}
          className="mt-4 rounded-xl bg-terminal-accent px-4 py-2 font-mono text-sm font-semibold text-terminal-bg disabled:cursor-not-allowed disabled:opacity-40"
        >
          {uploading ? "Uploading…" : "Upload"}
        </button>
      </div>

      {status && <div className="rounded border border-terminal-border bg-terminal-panel card-shadow p-2 text-xs">{status}</div>}

      {preview && (
        <div className="rounded-xl border border-terminal-border bg-terminal-panel card-shadow p-3">
          <div className="mb-2 text-xs text-terminal-muted">Type detected: {preview.type}</div>
          {preview.valid ? (
            <div className="text-xs text-terminal-accent">{preview.rows.length} row(s) ready to import.</div>
          ) : (
            <ul className="space-y-1 text-xs text-terminal-danger">
              {preview.errors.map((e, i) => (
                <li key={i}>Row {e.row + 1}, {e.field}: {e.message}</li>
              ))}
            </ul>
          )}
          <button
            type="button"
            onClick={onConfirm}
            disabled={!preview.valid || confirming}
            className="mt-3 rounded-xl bg-terminal-accent px-4 py-2 font-mono text-sm font-semibold text-terminal-bg disabled:cursor-not-allowed disabled:opacity-40"
          >
            Confirmer
          </button>
        </div>
      )}
    </div>
  );
}
