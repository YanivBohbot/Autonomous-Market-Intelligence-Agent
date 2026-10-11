# Data Import & View — Design

**Status:** Approved by user, 2026-10-03. Ready for `writing-plans`.

**Roadmap context:** CopilotKit program (see `docs/superpowers/specs/2026-09-24-copilotkit-foundation-design.md`, 5 sub-projects). This spec merges sub-project 4 ("Imports: PDF → RAG; client Excel → validated preview → DB after approval") and sub-project 5 ("Data view page: clients, portfolios and RAG documents") into one chantier — the user chose to build the "Clients" section of a future multi-section Market Desk navigation shell now, scoped to just this piece; the rest of that shell (Briefing, Recherche, Rapports) is a future north star, not built here.

## Goal

A new `/data` section in the React console where a user can:
1. Browse existing clients, their holdings, and the documents already ingested into the RAG knowledge base (read-only).
2. Upload a PDF → it gets ingested into the Pinecone knowledge base immediately, same pipeline as `app/ingest.py`.
3. Upload a client Excel file → preview the parsed, validated rows → confirm → write to `customers.db` (new clients, or upserted holdings).

## Why

Closes two known gaps: chat-uploaded files never reach the RAG index (`project_rag_upload_gap.md`), and there's no way to bulk-update client/portfolio data except by hand-editing `customers.db` or re-running `create_db.py`.

## Decisions (from brainstorming)

1. **Entry point:** a dedicated UI section, not a chat upload — matches the "Clients" tab in the future nav shell mockup the user showed, not the existing CopilotKit chat flow.
2. **Routing:** `react-router-dom` (new dependency) replaces the existing `ConsoleMode` state-toggle pattern (`frontend/src/desk/mode.ts`) with real routes — chosen deliberately over keeping the existing pattern, because more nav-shell sections (Briefing, Recherche, Rapports) are coming later and should be real URLs (bookmarkable, back-button-correct) from the start rather than migrated off the mode-toggle afterward.
3. **PDF ingestion:** automatic, no human approval. Pinecone upsert uses deterministic chunk IDs (`hashlib.sha256(source:page:chunk_index)`, already in `app/ingest.py`), so re-ingesting the same file is idempotent — nothing destructive to approve.
4. **Excel import target:** auto-detected per file from its column headers — either new `clients` rows, or `holdings` upserts for an existing client. One file is one type, detected once from its header row.
5. **Approval granularity:** one global approve/reject for the whole parsed file, matching the existing HITL pattern (`send_email`, `write_file`, `save_memory`) — no per-row editing UI.
6. **Invalid rows:** block the entire file if any row fails validation. No partial import. The user fixes the source file and re-uploads.
7. **Holdings semantics:** upsert only. A row for `(client, ticker)` that already exists in `holdings` updates `shares`/`avg_cost`. Existing holdings for that client that are NOT in the file are left untouched — never deleted. This is an incremental update, not a full-portfolio replacement.
8. **Data view scope:** read-only. No edit/delete actions on clients, holdings, or documents from this page (future work, not this sub-project).
9. **No LLM in this path.** Validation, type detection, and DB writes are deterministic Python — this is a data-entry tool, not an agent capability. Matches the project's existing preference for deterministic calculation over LLM-copied data (`concentration_screen`'s docstring).
10. **Validation happens twice:** once by the backend on `/preview` (to show the user what will happen) and again on `/confirm` (defense in depth — never trust that nothing changed between the two calls, e.g. a client deleted meanwhile).

## Architecture

### Backend — `app/api/routers/data.py` (new router, NOT wired into the agent graph)

| Method | Path | Does |
|---|---|---|
| GET | `/data/clients` | SQL join of `clients` + `holdings` + `companies`, grouped by client. |
| GET | `/data/documents` | Reads `app/agent/tools/kb_documents.json` (existing RAG manifest). |
| POST | `/data/import/pdf` | Multipart file upload → `ingest_single_pdf()` → Pinecone upsert + manifest union. |
| POST | `/data/import/preview` | Body `{rows: list[dict]}` → `detect_import_type` + `validate_*_rows` → `{type, valid, rows_or_errors}`. Writes nothing. |
| POST | `/data/import/confirm` | Body `{type, rows: list[dict]}` → re-validates → writes in one SQLite transaction (all-or-nothing) → `{written: int}`. |

### Backend — `app/data_import/` (new module, business logic, no FastAPI imports — independently testable)

- `detect_import_type(rows: list[dict]) -> Literal["clients", "holdings"] | None` — inspects the first row's keys against two fixed column sets:
  - `clients` columns (case-insensitive header match): `name, email, segment, risk_profile, advisor, city` required, `joined_on` optional.
  - `holdings` columns: `client_email, ticker, shares, avg_cost`, all required.
  - If the row's keys are a superset of the `clients` set → `"clients"`. Else if a superset of the `holdings` set → `"holdings"`. Else → `None` (unrecognized).
- `validate_clients_rows(rows) -> ValidationResult` — required: `name, email, segment, risk_profile, advisor, city`; `joined_on` optional (defaults to today). Rules: `segment in {VIP, Premium, Standard}`, `risk_profile in {conservative, balanced, aggressive}` (mirrors `create_db.py`'s `CHECK` constraints), no duplicate `email` within the file, `email` must NOT already exist in `clients` (this endpoint adds new clients, never silently overwrites an existing one's segment/advisor/city).
- `validate_holdings_rows(rows) -> ValidationResult` — required: `client_email, ticker, shares, avg_cost`. Rules: `shares > 0`, `avg_cost > 0` (mirrors the `CHECK` constraints), `client_email` must resolve to an existing client, `ticker` must exist in `companies`, no duplicate `(client_email, ticker)` within the file.
- `write_clients(rows)` — `INSERT` each row.
- `write_holdings(rows)` — `INSERT ... ON CONFLICT (client_id, ticker) DO UPDATE SET shares=?, avg_cost=?` (upsert on the existing composite primary key).
- `ingest_single_pdf(file_bytes: bytes, filename: str) -> int` (returns chunk count added) — extracted from `app/ingest.py`'s per-file loop body; updates `kb_documents.json` by reading the existing manifest, adding this filename, and writing the union back (never overwrites the list with just this one file — `app/ingest.py`'s bulk CLI path keeps its own full-overwrite behavior unchanged, since a full re-run is still "the whole corpus").

`ValidationResult` shape: `{valid: bool, rows: list[dict] | None, errors: list[{row: int, field: str, message: str}]}`.

### Frontend — `frontend/src/data/` (new, mirrors the existing `frontend/src/desk/` structure)

- `DataPage.tsx` — the `/data` route; internal tab switch (Clients | Documents | Import), no further routing nesting needed.
- `ClientsList.tsx` — table from `GET /data/clients`; each client row expands to show its holdings.
- `DocumentsList.tsx` — simple list from `GET /data/documents`.
- `ImportPanel.tsx` — file input; branches on file extension:
  - `.pdf` → `POST /data/import/pdf` (multipart) → success/error message, refresh `DocumentsList`.
  - `.xlsx`/`.xls` → parsed client-side with the new `xlsx` (SheetJS) npm dependency into `rows: Record<string, unknown>[]` (sheet 1, header row = keys, no business logic in JS) → `POST /data/import/preview` → render preview table or per-row errors → "Confirmer" button (disabled until `valid: true`) → `POST /data/import/confirm` → success message, refresh `ClientsList`.

### Routing change

`react-router-dom` added. `App.tsx`'s current `mode` state (`"desk" | "classic"`, `frontend/src/desk/mode.ts`) is replaced by real routes: `/` (Desk), `/classic`, `/data`. `Header.tsx`'s mode toggle becomes navigation links. `mode.ts`'s `localStorage` persistence is dropped — the URL itself is now the persisted state.

## Data flow

**Excel import (happy path):** browser parses file → `rows` sent to `/preview` → backend detects type + validates → preview rendered → user clicks Confirm → same `rows` sent to `/confirm` → backend re-validates → writes in one transaction → `ClientsList` refetches.

**PDF import:** file uploaded directly to `/import/pdf` → backend loads/splits/embeds/upserts to Pinecone with deterministic IDs → manifest updated (union) → `DocumentsList` refetches.

## Error handling

- Unrecognized file shape (neither clients nor holdings columns match) → `400 {"error": "unrecognized file format"}`.
- Row-level validation failures → `200 {"valid": false, "errors": [...]}` from `/preview` — this is an expected response shape, not a server error.
- `/confirm` re-validation fails (state changed since `/preview`) → `409`, nothing written.
- A write fails mid-transaction → the whole transaction rolls back, `500`, zero rows written — never a half-updated DB.
- Concurrent imports from two different users at once: **out of scope**, accepted as a known limitation given this project's single-advisor demo scale.
- Corrupt/unreadable PDF → `400 {"error": "invalid PDF"}`.
- Same PDF re-uploaded → not an error; idempotent upsert on the same deterministic chunk IDs.
- Pinecone/OpenAI failure mid-embedding → `500`; a partial upsert with a not-yet-updated manifest is a known, pre-existing limitation shared with `app/ingest.py`'s bulk path — safe to retry (idempotent).
- Frontend: row-level preview errors shown inline in the table; network/server errors shown as a generic toast.

## Testing

**Backend (pytest, TDD):**
- `tests/unit/test_data_import_validation.py` — `detect_import_type` and both `validate_*_rows` functions: valid rows, and each error rule individually (missing field, bad enum, unknown ticker/email, in-file duplicate).
- `tests/unit/test_data_import_write.py` — `write_clients` inserts; `write_holdings` upserts correctly (existing pair updated, new pair added, untouched holdings for that client preserved); forced mid-write failure rolls back to zero rows written.
- `tests/unit/test_ingest_single_pdf.py` — Pinecone/OpenAI mocked (no live calls); manifest ends up as a union of old + new filenames, never a replacement.
- `tests/unit/test_data_endpoints.py` — FastAPI `TestClient` against all 5 routes: happy paths, the `409` re-validation-conflict path, the `500` rollback path.

**Frontend (Vitest, matching the existing `*.test.tsx` convention):**
- `ImportPanel.test.tsx` — extension-based routing to the right endpoint; preview rendering (valid vs. errors); Confirm disabled until valid.
- `ClientsList.test.tsx` / `DocumentsList.test.tsx` — render from mocked fetch responses.

**Live QA (one grounded pass, per project convention):** upload a small real clients Excel, then a small real holdings Excel, then a small real PDF — against the dev `customers.db` and Pinecone index — and confirm `search_knowledge_base` actually finds the new PDF's content, and both list views reflect the real written state.

## Out of scope (explicitly, for this sub-project)

- Editing or deleting clients/holdings/documents from the Data page (read-only for now).
- Per-row edit/partial-approve on Excel import (global approve/reject only).
- The rest of the future nav shell (Briefing, Recherche, Rapports sections) — this spec builds only the "Clients" piece.
- Concurrent-import conflict handling beyond the transaction-level all-or-nothing guarantee.
- Routing the import through the multi-agent graph or any LLM — this is intentionally a deterministic, non-agentic data tool.
