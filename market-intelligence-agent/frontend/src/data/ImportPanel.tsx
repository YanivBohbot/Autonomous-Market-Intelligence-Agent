import { useRef, useState, type ChangeEvent, type DragEvent, type KeyboardEvent } from "react";
import * as XLSX from "xlsx";
import { confirmImport, importPdf, previewImport, type ImportPreviewResult } from "../lib/api";
import { Icon } from "../ui/Icon";
import { SectionHeader } from "../ui/SectionHeader";
import { SurfaceCard } from "../ui/SurfaceCard";

const ACCEPTED_EXTENSIONS = [".pdf", ".xlsx", ".xls"] as const;

export function ImportPanel() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [preview, setPreview] = useState<ImportPreviewResult | null>(null);
  const [rawRows, setRawRows] = useState<Record<string, unknown>[] | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function selectFile(file: File | null): void {
    setStatus(null);
    setPreview(null);
    setRawRows(null);
    if (!file) {
      setSelectedFile(null);
      return;
    }
    const normalized = file.name.toLowerCase();
    if (!ACCEPTED_EXTENSIONS.some((extension) => normalized.endsWith(extension))) {
      setSelectedFile(null);
      setStatus("Unsupported file type. Choose a PDF, XLSX, or XLS file.");
      if (inputRef.current) inputRef.current.value = "";
      return;
    }
    setSelectedFile(file);
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    selectFile(event.target.files?.[0] ?? null);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    selectFile(event.dataTransfer.files[0] ?? null);
  }

  function onDropZoneKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      inputRef.current?.click();
    }
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

  const isError = status?.startsWith("Error:") || status?.startsWith("Unsupported");

  return (
    <div className="space-y-5">
      <SectionHeader title="Import files" description="PDF files are ingested directly. Excel files are validated in a preview before confirmation." />
      <SurfaceCard tone="soft" padding="lg" className="space-y-4">
        <div
          role="button"
          tabIndex={0}
          aria-label="Choose a file to import"
          data-dragging={dragging}
          onClick={() => inputRef.current?.click()}
          onKeyDown={onDropZoneKeyDown}
          onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`flex min-h-48 cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed p-6 text-center transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-blue ${dragging ? "border-brand-blue bg-blue-50 dark:bg-blue-950/30" : "border-terminal-border bg-terminal-panel hover:border-brand-blue/50"}`}
        >
          <span className="grid h-12 w-12 place-items-center rounded-2xl bg-blue-50 text-brand-blue dark:bg-blue-950/50"><Icon name="upload" /></span>
          <p className="mt-3 font-semibold text-terminal-text">{dragging ? "Drop file here" : selectedFile?.name ?? "Drop a PDF or Excel file here"}</p>
          <p className="mt-1 text-sm text-terminal-muted">or press Enter, Space, or click to browse · PDF, XLSX, XLS</p>
        </div>
        <label htmlFor="data-import-file" className="sr-only">Choose file</label>
        <input id="data-import-file" ref={inputRef} type="file" accept={ACCEPTED_EXTENSIONS.join(",")} onChange={onFileChange} className="sr-only" />
        <div className="flex justify-end">
          <button type="button" aria-label="Upload selected file" onClick={onUpload} disabled={!selectedFile || uploading} className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50">
            {uploading ? "Uploading…" : "Upload file"}
          </button>
        </div>
      </SurfaceCard>

      {status && (
        <div role={isError ? "alert" : "status"} className={`rounded-2xl border p-4 text-sm ${isError ? "border-red-200 bg-red-50 text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-200" : "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-200"}`}>
          {status}
        </div>
      )}

      {preview && (
        <SurfaceCard padding="lg" className="space-y-4">
          <SectionHeader title="Import preview" description={`Detected ${preview.type} data.`} />
          {preview.valid ? (
            <p className="text-sm font-semibold text-emerald-600 dark:text-emerald-300">{preview.rows.length} row(s) ready to import.</p>
          ) : (
            <ul className="space-y-2 text-sm text-terminal-danger">
              {preview.errors.map((error, index) => (
                <li key={`${error.row}-${error.field}-${index}`}>Row {error.row + 1}, {error.field}: {error.message}</li>
              ))}
            </ul>
          )}
          <button type="button" onClick={onConfirm} disabled={!preview.valid || confirming} className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50">
            {confirming ? "Importing…" : "Confirm import"}
          </button>
        </SurfaceCard>
      )}
    </div>
  );
}
