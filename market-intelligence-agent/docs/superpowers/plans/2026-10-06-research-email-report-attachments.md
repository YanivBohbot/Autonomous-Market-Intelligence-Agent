# Research Email Report Attachments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the persistent Research prompt shortcuts and let users manually attach one recipient-owned generated report from the `send_email` HITL card.

**Architecture:** A shared synchronous report-catalog module is the authority for recipient lookup, safe report listing, and recipient-aware file resolution. FastAPI exposes the catalog as lightweight metadata; the React approval card uses a focused selector and converts attachment choices into HITL edit decisions; the email tool revalidates ownership and sends a MIME message through SES only when an attachment is present.

**Tech Stack:** Python 3.12, FastAPI, sqlite3, LangChain/LangGraph HITL middleware, Amazon SES/boto3, React 18, TypeScript, CopilotKit v2, Vitest, Testing Library, pytest.

**Spec:** `docs/superpowers/specs/2026-10-06-research-email-report-attachments-design.md`

## Global Constraints

- Report selection is manual and starts at `No attachment`; never auto-select the newest report.
- Only one already-generated report may be selected; no file upload or report generation belongs in the approval card.
- The API and email tool must expose only reports that match the current recipient's canonical client-name prefix.
- The browser submits a basename only; the backend rejects traversal, separators, missing files, non-files, symlink escapes, and cross-client filenames.
- Serialized raw email with an attachment must be at most `10_000_000` bytes.
- Existing attachment-free `send_email`, HITL approve/edit/reject, and client-recipient guard behavior must remain compatible.
- Update `docs/TOOLS.md` in the same commit as the tool schema.
- Add no runtime or frontend dependency.
- Preserve and do not stage the pre-existing Task 13 changes in `frontend/src/App.test.tsx`, `frontend/src/setupTests.ts`, `frontend/vite.config.ts`, and `frontend/src/viteProxy.test.ts` while making feature commits.
- After completion, run the complete backend/frontend suites and production build, then restart backend and frontend on `127.0.0.1` for the user.

## Review Focus

- A recipient changed after selecting a report must clear the stale choice; Task 3 tests selector invalidation and Task 4 tests the resulting decision payload.
- A report deleted between catalog load and approval must send nothing; Task 2 tests stale resolution and Task 5 verifies no SES call after resolution failure.
- Traversal, Windows separators, absolute paths, and symlink escapes must never reach email content; Task 2 exercises each class.
- An attachment whose encoded MIME message exceeds `10_000_000` bytes must fail before SES; Task 5 pins the byte-limit behavior.
- An interrupt that permits approve/reject but not edit must not offer a mutable attachment selector; Task 4 tests this review-config boundary.

---

### Task 1: Remove Persistent Research Suggestions

**Files:**
- Modify: `frontend/src/desk/DeskView.tsx`
- Modify: `frontend/src/desk/DeskView.test.tsx`

**Interfaces:**
- Consumes: existing `DeskView({threadId})` and CopilotKit provider/chat contracts.
- Produces: the same Research workspace without any call to `useConfigureSuggestions`.

- [ ] **Step 1: Replace the suggestion-presence regression with an absence test**

In `DeskView.test.tsx`, retain the mock counter but replace the test named `keeps all three suggestions permanently available` with:

```tsx
it("does not register persistent prompt suggestions", () => {
  render(<DeskView threadId="research_3" />);
  expect(suggestionConfigs).toHaveLength(0);
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
npm test -- --run src/desk/DeskView.test.tsx
```

Expected: FAIL because `DeskBody` still calls `useConfigureSuggestions` once.

- [ ] **Step 3: Remove suggestion registration**

In `DeskView.tsx`, remove `useConfigureSuggestions` from the CopilotKit import and delete this block from `DeskBody`:

```tsx
useConfigureSuggestions({
  suggestions: [
    { title: "Portfolio value", message: "What is the total value of a client's portfolio?" },
    { title: "Stock price", message: "What is AAPL trading at?" },
    { title: "Concentration risk", message: "Are any clients over-concentrated in one stock?" },
  ],
  available: "always",
}, []);
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `npm test -- --run src/desk/DeskView.test.tsx`

Expected: all DeskView tests PASS.

- [ ] **Step 5: Commit only the Research files**

```powershell
git add -- frontend/src/desk/DeskView.tsx frontend/src/desk/DeskView.test.tsx
git commit -m "fix(research): remove persistent prompt suggestions"
```

---

### Task 2: Add the Recipient-Scoped Report Catalog

**Files:**
- Create: `app/report_catalog.py`
- Create: `tests/unit/test_report_catalog.py`
- Modify: `app/api/routers/workspace.py`
- Modify: `tests/unit/test_workspace_files.py`

**Interfaces:**
- Consumes: `app.data_import.db.DB_PATH`, `settings.WORKSPACE_ROOT`, and `slugify(name)` from `app.agent.tools.portfolio_report`.
- Produces: `GeneratedReport`, `list_generated_reports(recipient, *, db_path=None, workspace_root=None)`, `resolve_generated_report(recipient, filename, *, db_path=None, workspace_root=None)`, and `GET /workspace/reports?recipient=...`.

- [ ] **Step 1: Write failing pure catalog tests**

Create `tests/unit/test_report_catalog.py` with a temporary SQLite database containing two clients and report files for both. Cover newest-first ordering, unknown recipients, missing files, cross-client filenames, `../`, `/`, `\\`, absolute paths, and a symlink escape when the platform permits symlinks:

```python
from __future__ import annotations

import os
import sqlite3

import pytest

from app.report_catalog import list_generated_reports, resolve_generated_report


def _db(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE clients (name TEXT NOT NULL, email TEXT NOT NULL)")
    conn.executemany(
        "INSERT INTO clients (name, email) VALUES (?, ?)",
        [("Margaret Collins", "margaret@example.com"), ("Jane Doe", "jane@example.com")],
    )
    conn.commit()
    conn.close()


def test_lists_only_recipient_reports_newest_first(tmp_path):
    db = tmp_path / "customers.db"
    _db(db)
    reports = tmp_path / "workspace" / "reports"
    reports.mkdir(parents=True)
    older = reports / "margaret-collins-portfolio-brief-2026-10-01.xlsx"
    newer = reports / "margaret-collins-portfolio-brief-2026-10-06.xlsx"
    other = reports / "jane-doe-portfolio-brief-2026-10-06.xlsx"
    for path in (older, newer, other):
        path.write_bytes(path.name.encode())
    os.utime(older, (1, 1))
    os.utime(newer, (2, 2))

    items = list_generated_reports(
        "MARGARET@example.com", db_path=db, workspace_root=tmp_path / "workspace"
    )

    assert [item.filename for item in items] == [newer.name, older.name]
    assert all(item.size_bytes > 0 for item in items)


def test_unknown_recipient_has_empty_catalog(tmp_path):
    db = tmp_path / "customers.db"
    _db(db)
    assert list_generated_reports(
        "unknown@example.com", db_path=db, workspace_root=tmp_path / "workspace"
    ) == []


@pytest.mark.parametrize("filename", ["../secret.txt", "..\\secret.txt", "/tmp/secret.txt"])
def test_rejects_unsafe_names(tmp_path, filename):
    db = tmp_path / "customers.db"
    _db(db)
    with pytest.raises(ValueError, match="unsafe report filename"):
        resolve_generated_report(
            "margaret@example.com", filename, db_path=db, workspace_root=tmp_path / "workspace"
        )


def test_rejects_another_clients_report(tmp_path):
    db = tmp_path / "customers.db"
    _db(db)
    reports = tmp_path / "workspace" / "reports"
    reports.mkdir(parents=True)
    filename = "jane-doe-portfolio-brief-2026-10-06.xlsx"
    (reports / filename).write_bytes(b"report")
    with pytest.raises(ValueError, match="does not belong to recipient"):
        resolve_generated_report(
            "margaret@example.com", filename, db_path=db, workspace_root=tmp_path / "workspace"
        )


def test_rejects_a_report_deleted_after_listing(tmp_path):
    db = tmp_path / "customers.db"
    _db(db)
    reports = tmp_path / "workspace" / "reports"
    reports.mkdir(parents=True)
    filename = "margaret-collins-portfolio-brief-2026-10-06.xlsx"
    path = reports / filename
    path.write_bytes(b"report")
    path.unlink()
    with pytest.raises(ValueError, match="report not found"):
        resolve_generated_report(
            "margaret@example.com", filename, db_path=db, workspace_root=tmp_path / "workspace"
        )
```

Add the symlink escape regression:

```python
def test_rejects_symlink_escape(tmp_path):
    db = tmp_path / "customers.db"
    _db(db)
    reports = tmp_path / "workspace" / "reports"
    reports.mkdir(parents=True)
    outside = tmp_path / "outside.xlsx"
    outside.write_bytes(b"secret")
    link = reports / "margaret-collins-portfolio-brief-linked.xlsx"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(ValueError, match="report escapes workspace"):
        resolve_generated_report(
            "margaret@example.com", link.name,
            db_path=db, workspace_root=tmp_path / "workspace",
        )
```

- [ ] **Step 2: Write the failing endpoint tests**

Extend `tests/unit/test_workspace_files.py` with:

```python
from app.report_catalog import GeneratedReport


def test_lists_generated_reports_for_recipient(tmp_path, monkeypatch):
    seen = []
    items = [GeneratedReport(
        filename="margaret-collins-portfolio-brief-2026-10-06.xlsx",
        generated_at="2026-10-06T09:30:00+00:00",
        size_bytes=24832,
    )]
    monkeypatch.setattr(
        "app.api.routers.workspace.list_generated_reports",
        lambda recipient: seen.append(recipient) or items,
    )
    response = _client(tmp_path, monkeypatch).get(
        "/workspace/reports?recipient=margaret%40example.com"
    )
    assert response.status_code == 200
    assert response.json() == {"items": [{
        "filename": items[0].filename,
        "generated_at": items[0].generated_at,
        "size_bytes": items[0].size_bytes,
    }]}
    assert seen == ["margaret@example.com"]


def test_unknown_recipient_report_catalog_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.api.routers.workspace.list_generated_reports", lambda recipient: []
    )
    response = _client(tmp_path, monkeypatch).get(
        "/workspace/reports?recipient=unknown%40example.com"
    )
    assert response.status_code == 200
    assert response.json() == {"items": []}
```

- [ ] **Step 3: Run catalog and workspace tests and verify RED**

Run:

```powershell
uv run pytest tests/unit/test_report_catalog.py tests/unit/test_workspace_files.py -v
```

Expected: collection/import FAIL because `app.report_catalog` and the route do not exist.

- [ ] **Step 4: Implement the shared catalog**

Create `app/report_catalog.py` with these public shapes:

```python
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.agent.tools.portfolio_report import slugify
from app.core.config import settings
from app.data_import.db import DB_PATH


@dataclass(frozen=True)
class GeneratedReport:
    filename: str
    generated_at: str
    size_bytes: int


def _paths(db_path, workspace_root):
    return Path(db_path or DB_PATH), Path(workspace_root or settings.WORKSPACE_ROOT)


def _client_prefix(recipient: str, db_path: Path) -> str | None:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT name FROM clients WHERE lower(email) = lower(?)", (recipient.strip(),)
        ).fetchone()
    return None if row is None else f"{slugify(row[0])}-portfolio-brief-"


def list_generated_reports(recipient: str, *, db_path=None, workspace_root=None) -> list[GeneratedReport]:
    database, workspace = _paths(db_path, workspace_root)
    prefix = _client_prefix(recipient, database)
    if prefix is None:
        return []
    root = (workspace / "reports").resolve()
    if not root.is_dir():
        return []
    items = []
    for candidate in root.glob(f"{prefix}*"):
        resolved = candidate.resolve()
        if resolved.parent != root or not resolved.is_file():
            continue
        stat = resolved.stat()
        items.append(GeneratedReport(
            filename=candidate.name,
            generated_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            size_bytes=stat.st_size,
        ))
    return sorted(items, key=lambda item: item.generated_at, reverse=True)
```

Implement `resolve_generated_report` in the same module. It must reject empty names and any name containing `/` or `\\`, require `Path(filename).name == filename`, require a known recipient prefix, require `filename.startswith(prefix)`, resolve the candidate, require `resolved.parent == reports_root`, and require `resolved.is_file()` before returning the `Path`.

- [ ] **Step 5: Add the API route**

In `workspace.py`, import `asdict` and `list_generated_reports`, then add:

```python
@router.get("/reports")
async def get_generated_reports(recipient: str) -> dict:
    return {"items": [asdict(item) for item in list_generated_reports(recipient)]}
```

Keep this route independent from report generation and market-data endpoints.

- [ ] **Step 6: Run tests and verify GREEN**

Run: `uv run pytest tests/unit/test_report_catalog.py tests/unit/test_workspace_files.py -v`

Expected: all catalog and workspace tests PASS.

- [ ] **Step 7: Commit the catalog slice**

```powershell
git add -- app/report_catalog.py app/api/routers/workspace.py tests/unit/test_report_catalog.py tests/unit/test_workspace_files.py
git commit -m "feat(reports): add recipient-scoped report catalog"
```

---

### Task 3: Build the Frontend Report Selector

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/lib/api.test.ts`
- Create: `frontend/src/desk/EmailAttachmentSelector.tsx`
- Create: `frontend/src/desk/EmailAttachmentSelector.test.tsx`

**Interfaces:**
- Consumes: `GET /workspace/reports?recipient=...`.
- Produces: `GeneratedReportOption`, `getGeneratedReports(recipient, base?)`, and `EmailAttachmentSelector({recipient, value, disabled, onChange})`.

- [ ] **Step 1: Add a failing API-client test**

Import `getGeneratedReports` in `api.test.ts` and add:

```tsx
it("getGeneratedReports encodes the recipient and returns report metadata", async () => {
  const payload = { items: [{
    filename: "margaret-collins-portfolio-brief-2026-10-06.xlsx",
    generated_at: "2026-10-06T09:30:00+00:00",
    size_bytes: 24832,
  }] };
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => payload });
  vi.stubGlobal("fetch", fetchMock);

  await expect(getGeneratedReports("margaret+vip@example.com")).resolves.toEqual(payload.items);
  expect(fetchMock).toHaveBeenCalledWith(
    "/workspace/reports?recipient=margaret%2Bvip%40example.com",
  );
});
```

Add a failed-response test expecting `report catalog 503`.

- [ ] **Step 2: Add failing selector tests**

Create `EmailAttachmentSelector.test.tsx`. Mock `getGeneratedReports`, use fake timers for the 250 ms debounce, and cover:

```tsx
it("loads recipient reports without selecting one", async () => {
  getGeneratedReportsMock.mockResolvedValue([REPORT]);
  render(<EmailAttachmentSelector recipient="margaret@example.com" value="" onChange={onChange} />);
  await vi.advanceTimersByTimeAsync(250);
  expect(await screen.findByRole("option", { name: /margaret-collins/ })).toBeInTheDocument();
  expect(screen.getByRole("combobox", { name: "Attachment (optional)" })).toHaveValue("");
  expect(onChange).not.toHaveBeenCalled();
});
```

Add these concrete edge tests (using `REPORT`, `getGeneratedReportsMock`, and `onChange` from the test fixture):

```tsx
it("shows an empty state without changing the selection", async () => {
  getGeneratedReportsMock.mockResolvedValue([]);
  render(<EmailAttachmentSelector recipient="margaret@example.com" value="" onChange={onChange} />);
  await vi.advanceTimersByTimeAsync(250);
  expect(await screen.findByText("No generated reports available")).toBeInTheDocument();
  expect(onChange).not.toHaveBeenCalled();
});

it("keeps no-attachment usable when loading fails", async () => {
  getGeneratedReportsMock.mockRejectedValue(new Error("503"));
  render(<EmailAttachmentSelector recipient="margaret@example.com" value="" onChange={onChange} />);
  await vi.advanceTimersByTimeAsync(250);
  expect(await screen.findByRole("alert")).toHaveTextContent("Generated reports unavailable");
  expect(onChange).not.toHaveBeenCalled();
});

it("returns a manually selected filename", async () => {
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  getGeneratedReportsMock.mockResolvedValue([REPORT]);
  render(<EmailAttachmentSelector recipient="margaret@example.com" value="" onChange={onChange} />);
  await vi.advanceTimersByTimeAsync(250);
  await user.selectOptions(await screen.findByRole("combobox"), REPORT.filename);
  expect(onChange).toHaveBeenCalledWith(REPORT.filename);
});

it("clears a stale selection after the recipient changes", async () => {
  getGeneratedReportsMock
    .mockResolvedValueOnce([REPORT])
    .mockResolvedValueOnce([]);
  const { rerender } = render(
    <EmailAttachmentSelector recipient="margaret@example.com" value={REPORT.filename} onChange={onChange} />,
  );
  await vi.advanceTimersByTimeAsync(250);
  rerender(<EmailAttachmentSelector recipient="jane@example.com" value={REPORT.filename} onChange={onChange} />);
  await vi.advanceTimersByTimeAsync(250);
  expect(onChange).toHaveBeenCalledWith("");
});

it("disables selection when edits are forbidden", async () => {
  getGeneratedReportsMock.mockResolvedValue([REPORT]);
  render(<EmailAttachmentSelector recipient="margaret@example.com" value="" disabled onChange={onChange} />);
  await vi.advanceTimersByTimeAsync(250);
  expect(await screen.findByRole("combobox")).toBeDisabled();
});
```

- [ ] **Step 3: Run frontend API and selector tests and verify RED**

Run:

```powershell
npm test -- --run src/lib/api.test.ts src/desk/EmailAttachmentSelector.test.tsx
```

Expected: FAIL because the API function and component do not exist.

- [ ] **Step 4: Implement the typed API client**

Add to `api.ts`:

```ts
export interface GeneratedReportOption {
  filename: string;
  generated_at: string;
  size_bytes: number;
}

export async function getGeneratedReports(
  recipient: string,
  base = API_BASE,
): Promise<GeneratedReportOption[]> {
  const query = new URLSearchParams({ recipient });
  const res = await fetch(`${base}/workspace/reports?${query.toString()}`);
  if (!res.ok) throw new Error(`report catalog ${res.status}`);
  const payload = await res.json();
  return payload.items;
}
```

- [ ] **Step 5: Implement the isolated selector**

Create `EmailAttachmentSelector.tsx` with a 250 ms debounced effect keyed by `recipient`. Maintain `reports`, `loading`, and `error` locally; ignore stale promise results with an `active` flag. When a successful refresh does not include a non-empty `value`, call `onChange("")`. Render an accessible label and select:

```tsx
<label className="flex flex-col gap-1.5">
  <span className="text-[10px] uppercase text-terminal-muted">Attachment (optional)</span>
  <select
    aria-label="Attachment (optional)"
    value={value}
    disabled={disabled || loading || reports.length === 0}
    onChange={(event) => onChange(event.target.value)}
    className="w-full rounded border border-terminal-border bg-terminal-bg px-2 py-1 text-terminal-text disabled:opacity-60"
  >
    <option value="">No attachment</option>
    {reports.map((report) => (
      <option key={report.filename} value={report.filename}>
        {report.filename} · {new Date(report.generated_at).toLocaleDateString()}
      </option>
    ))}
  </select>
  {loading && <span role="status">Loading generated reports…</span>}
  {!loading && !error && reports.length === 0 && <span>No generated reports available</span>}
  {error && <span role="alert">Generated reports unavailable</span>}
</label>
```

The error path must preserve `No attachment`, clear the displayed report list, and never call `onChange` merely because fetching failed.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `npm test -- --run src/lib/api.test.ts src/desk/EmailAttachmentSelector.test.tsx`

Expected: all API and selector tests PASS.

- [ ] **Step 7: Commit the selector slice**

```powershell
git add -- frontend/src/lib/api.ts frontend/src/lib/api.test.ts frontend/src/desk/EmailAttachmentSelector.tsx frontend/src/desk/EmailAttachmentSelector.test.tsx
git commit -m "feat(research): add generated report selector"
```

---

### Task 4: Integrate Attachment Choice into HITL Decisions

**Files:**
- Modify: `frontend/src/desk/ApprovalPanel.tsx`
- Modify: `frontend/src/desk/ApprovalPanel.test.tsx`

**Interfaces:**
- Consumes: `EmailAttachmentSelector` and existing `Decision` union.
- Produces: unchanged approve decisions when no attachment changes, and `edit` decisions with `attachment_filename` when a report is selected or cleared.

- [ ] **Step 1: Add failing approval-card tests**

Mock `getGeneratedReports` to resolve one recipient report. Add tests that assert:

```tsx
it("keeps approve unchanged when no report is selected", async () => {
  const { user, onSubmit } = setup({ requests: [email], allowed: [[...ALL]] });
  await screen.findByRole("option", { name: /margaret-collins/ });
  await user.click(screen.getByRole("button", { name: "Approve" }));
  expect(onSubmit).toHaveBeenCalledWith([{ type: "approve" }]);
});

it("submits a selected report as an edited email action", async () => {
  const { user, onSubmit } = setup({ requests: [email], allowed: [[...ALL]] });
  await user.selectOptions(
    await screen.findByRole("combobox", { name: "Attachment (optional)" }),
    REPORT.filename,
  );
  await user.click(screen.getByRole("button", { name: "Approve" }));
  expect(onSubmit).toHaveBeenCalledWith([{
    type: "edit",
    edited_action: {
      name: "send_email",
      args: { ...email.args, attachment_filename: REPORT.filename },
    },
  }]);
});
```

Add these attachment-decision regressions:

```tsx
it("keeps the selected report when sending edited fields", async () => {
  const { user, onSubmit } = setup({ requests: [email], allowed: [[...ALL]] });
  await user.selectOptions(await screen.findByRole("combobox"), REPORT.filename);
  await user.click(screen.getByRole("button", { name: "Edit" }));
  await user.clear(screen.getByLabelText("subject"));
  await user.type(screen.getByLabelText("subject"), "Updated report");
  await user.click(screen.getByRole("button", { name: "Send edited" }));
  expect(onSubmit.mock.calls[0][0][0].edited_action.args).toMatchObject({
    subject: "Updated report", attachment_filename: REPORT.filename,
  });
});

it("clears a pre-proposed attachment through an edit decision", async () => {
  const request = { ...email, args: { ...email.args, attachment_filename: REPORT.filename } };
  const { user, onSubmit } = setup({ requests: [request], allowed: [[...ALL]] });
  await user.selectOptions(await screen.findByRole("combobox"), "");
  await user.click(screen.getByRole("button", { name: "Approve" }));
  expect(onSubmit.mock.calls[0][0][0].edited_action.args.attachment_filename).toBeNull();
});

it("disables attachment changes when edit is not allowed", async () => {
  setup({ requests: [email], allowed: [["approve", "reject"]] });
  expect(await screen.findByRole("combobox", { name: "Attachment (optional)" })).toBeDisabled();
});
```

- [ ] **Step 2: Run the approval-panel tests and verify RED**

Run: `npm test -- --run src/desk/ApprovalPanel.test.tsx`

Expected: FAIL because the email card has no attachment selector or attachment-aware decisions.

- [ ] **Step 3: Integrate the selector and decision builder**

In `RequestCard`, derive the original attachment safely:

```tsx
const originalAttachment = request.name === "send_email" && typeof request.args.attachment_filename === "string"
  ? request.args.attachment_filename
  : "";
const [attachment, setAttachment] = useState(originalAttachment);
```

Render `EmailAttachmentSelector` only for `send_email`, using the current editable recipient value and `disabled={locked || !can("edit")}`. Add a local builder:

```tsx
function editedEmailArgs(includeFieldEdits: boolean) {
  return {
    ...request.args,
    ...(includeFieldEdits ? values : {}),
    attachment_filename: attachment || null,
  };
}
```

For `Approve`, preserve `{type: "approve"}` only when there is no selected attachment and the original call also had none. Otherwise submit an `edit` decision with `editedEmailArgs(false)`. For `Send edited`, use `editedEmailArgs(true)`. Non-email tools keep their current logic exactly.

- [ ] **Step 4: Run approval and interrupt tests and verify GREEN**

Run:

```powershell
npm test -- --run src/desk/ApprovalPanel.test.tsx src/desk/approvals.test.ts
```

Expected: all approval and parsing tests PASS.

- [ ] **Step 5: Commit the HITL UI slice**

```powershell
git add -- frontend/src/desk/ApprovalPanel.tsx frontend/src/desk/ApprovalPanel.test.tsx
git commit -m "feat(research): attach reports during email approval"
```

---

### Task 5: Send Validated Reports as MIME Attachments

**Files:**
- Create: `tests/unit/test_emails.py`
- Modify: `app/agent/tools/emails.py`
- Modify: `app/agent/prompts/system.py`
- Modify: `app/agent/prompts/specialist_agent_prompts.py`
- Modify: `docs/TOOLS.md`

**Interfaces:**
- Consumes: `resolve_generated_report(recipient, attachment_filename)` from Task 2.
- Produces: `EmailInput.attachment_filename: str | None`, `MAX_RAW_EMAIL_BYTES = 10_000_000`, plain SES `send_email` without an attachment, and SES `send_raw_email` with an attachment.

- [ ] **Step 1: Write failing email-tool tests**

Create `tests/unit/test_emails.py`. Invoke the tool with `send_email_tool.invoke(...)`, monkeypatch `settings.EMAIL_SENDER`, `resolve_generated_report`, and a new `_create_ses_client` helper. Start with:

```python
from email import policy
from email.parser import BytesParser

from app.agent.tools import emails


class FakeSesClient:
    def __init__(self):
        self.send_email_calls = []
        self.send_raw_email_calls = []

    def send_email(self, **kwargs):
        self.send_email_calls.append(kwargs)
        return {"MessageId": "plain-1"}

    def send_raw_email(self, **kwargs):
        self.send_raw_email_calls.append(kwargs)
        return {"MessageId": "raw-1"}


def test_plain_email_keeps_structured_ses_path(monkeypatch):
    client = FakeSesClient()
    monkeypatch.setattr(emails.settings, "EMAIL_SENDER", "advisor@firm.com")
    monkeypatch.setattr(emails, "_create_ses_client", lambda: client)
    result = emails.send_email_tool.invoke({
        "recipient": "margaret@example.com", "subject": "Report", "body": "Body"
    })
    assert "MessageId" in result
    assert len(client.send_email_calls) == 1
    assert client.send_raw_email_calls == []


def test_attachment_uses_raw_mime_email(tmp_path, monkeypatch):
    report = tmp_path / "margaret-collins-portfolio-brief-2026-10-06.xlsx"
    report.write_bytes(b"xlsx bytes")
    client = FakeSesClient()
    monkeypatch.setattr(emails.settings, "EMAIL_SENDER", "advisor@firm.com")
    monkeypatch.setattr(emails, "resolve_generated_report", lambda recipient, filename: report)
    monkeypatch.setattr(emails, "_create_ses_client", lambda: client)

    emails.send_email_tool.invoke({
        "recipient": "margaret@example.com",
        "subject": "Portfolio report",
        "body": "Attached.",
        "attachment_filename": report.name,
    })

    raw = client.send_raw_email_calls[0]["RawMessage"]["Data"]
    message = BytesParser(policy=policy.default).parsebytes(raw)
    attachment = next(message.iter_attachments())
    assert message["To"] == "margaret@example.com"
    assert attachment.get_filename() == report.name
    assert attachment.get_content() == b"xlsx bytes"
```

Add the validation and compatibility tests:

```python
def test_simulation_names_the_validated_attachment(tmp_path, monkeypatch):
    report = tmp_path / "margaret-collins-portfolio-brief-2026-10-06.xlsx"
    report.write_bytes(b"report")
    monkeypatch.setattr(emails.settings, "EMAIL_SENDER", "placeholder@example.com")
    monkeypatch.setattr(emails, "resolve_generated_report", lambda recipient, filename: report)
    result = emails.send_email_tool.invoke({
        "recipient": "margaret@example.com", "subject": "Report", "body": "Attached",
        "attachment_filename": report.name,
    })
    assert report.name in result


def test_resolution_failure_blocks_before_ses(monkeypatch):
    client = FakeSesClient()
    monkeypatch.setattr(emails.settings, "EMAIL_SENDER", "advisor@firm.com")
    monkeypatch.setattr(
        emails, "resolve_generated_report",
        lambda recipient, filename: (_ for _ in ()).throw(ValueError("wrong client")),
    )
    monkeypatch.setattr(emails, "_create_ses_client", lambda: client)
    result = emails.send_email_tool.invoke({
        "recipient": "margaret@example.com", "subject": "Report", "body": "Attached",
        "attachment_filename": "jane-doe-portfolio-brief.xlsx",
    })
    assert result == "Email blocked: wrong client"
    assert client.send_email_calls == client.send_raw_email_calls == []


def test_oversized_raw_message_blocks_before_ses(tmp_path, monkeypatch):
    report = tmp_path / "margaret-collins-portfolio-brief.xlsx"
    report.write_bytes(b"large")
    client = FakeSesClient()
    monkeypatch.setattr(emails.settings, "EMAIL_SENDER", "advisor@firm.com")
    monkeypatch.setattr(emails, "resolve_generated_report", lambda recipient, filename: report)
    monkeypatch.setattr(emails, "_create_ses_client", lambda: client)
    monkeypatch.setattr(emails, "MAX_RAW_EMAIL_BYTES", 1)
    result = emails.send_email_tool.invoke({
        "recipient": "margaret@example.com", "subject": "Report", "body": "Attached",
        "attachment_filename": report.name,
    })
    assert "10,000,000 bytes" in result
    assert client.send_raw_email_calls == []


def test_attachment_field_is_optional():
    parsed = emails.EmailInput(recipient="margaret@example.com", subject="Hi", body="Body")
    assert parsed.attachment_filename is None
```

- [ ] **Step 2: Run the focused email tests and verify RED**

Run: `uv run pytest tests/unit/test_emails.py -v`

Expected: FAIL because the optional schema field, resolver integration, SES helper, and raw MIME path do not exist.

- [ ] **Step 3: Extend the email schema and build MIME delivery**

In `emails.py`, add built-in imports from `email.message`, `mimetypes`, and `Path`, import `resolve_generated_report`, and define:

```python
MAX_RAW_EMAIL_BYTES = 10_000_000


class EmailInput(BaseModel):
    recipient: str = Field(description="The recipient's email address.")
    subject: str = Field(description="Subject line of the email.")
    body: str = Field(description="Plain-text body of the email.")
    attachment_filename: str | None = Field(
        default=None,
        description="Optional generated report basename selected during human approval.",
    )


def _create_ses_client():
    import boto3
    return boto3.client("ses", region_name=os.environ.get("AWS_REGION", "us-east-1"))
```

Change `send_email_tool` to accept `attachment_filename: str | None = None`. Resolve the report before the simulation gate and return `Email blocked: <reason>` on `ValueError`. For attachments, build:

```python
message = EmailMessage()
message["From"] = sender
message["To"] = recipient
message["Subject"] = subject
message.set_content(body)
content_type, _ = mimetypes.guess_type(report.name)
maintype, subtype = (content_type or "application/octet-stream").split("/", 1)
message.add_attachment(
    report.read_bytes(), maintype=maintype, subtype=subtype, filename=report.name
)
raw = message.as_bytes()
if len(raw) > MAX_RAW_EMAIL_BYTES:
    return "Email blocked: attachment makes the message exceed 10,000,000 bytes."
resp = client.send_raw_email(
    Source=sender,
    Destinations=[recipient],
    RawMessage={"Data": raw},
)
```

Use the existing structured `client.send_email(...)` branch when `report is None`. Wrap client creation and delivery in `try/except Exception as exc`; inside the exception block lazily import `BotoCoreError` and `ClientError`, preserve the existing messages when `isinstance(exc, ...)` matches, and re-raise unknown exceptions. This keeps successful unit tests independent of a local boto3 install without swallowing programming errors:

```python
except Exception as exc:
    from botocore.exceptions import BotoCoreError, ClientError
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "Unknown")
        msg = exc.response.get("Error", {}).get("Message", str(exc))
        return f"Erreur SES ({code}) : {msg}"
    if isinstance(exc, BotoCoreError):
        return f"Erreur réseau SES : {exc}"
    raise
```

- [ ] **Step 4: Update prompts and the tool catalog**

Update `EMAIL_SYSTEM_PROMPT` to document `attachment_filename: str | None` and explicitly say: leave it unset because the human chooses a generated report in the approval card; never invent a filename. Update the single-agent tool list with the same optional argument.

In `docs/TOOLS.md`, replace the stale SMTP/Gmail description with Amazon SES, list `recipient, subject, body, attachment_filename (optional)`, explain `send_raw_email` for a validated generated report, and retain the HITL rationale.

- [ ] **Step 5: Run focused email, registry, and prompt tests and verify GREEN**

Run:

```powershell
uv run pytest tests/unit/test_emails.py tests/unit/test_multi_agent_email_agent.py tests/unit/test_wealth_tools_registration.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit the email delivery slice**

```powershell
git add -- tests/unit/test_emails.py app/agent/tools/emails.py app/agent/prompts/system.py app/agent/prompts/specialist_agent_prompts.py docs/TOOLS.md
git commit -m "feat(email): send generated report attachments"
```

---

### Task 6: Prove End-to-End HITL Behavior and Deliver the Running Feature

**Files:**
- Modify: `tests/unit/test_multi_agent_hitl.py`
- Verify only: all backend and frontend files changed in Tasks 1–5

**Interfaces:**
- Consumes: the optional `attachment_filename` tool contract, frontend edit decisions, and LangGraph `Command(resume={decisions: ...})`.
- Produces: regression proof that attachment arguments survive pause/resume and are never executed after reject.

- [ ] **Step 1: Extend the fake email tool and add failing HITL coverage**

Change the fake tool signature to:

```python
@tool("send_email")
async def _fake_send_email(
    recipient: str,
    subject: str,
    body: str,
    attachment_filename: str | None = None,
) -> str:
    """Fake send."""
    SENT.append({
        "recipient": recipient,
        "subject": subject,
        "body": body,
        "attachment_filename": attachment_filename,
    })
    return f"sent to {recipient}"
```

Normalize existing assertions to include `attachment_filename: None`, then add a test that resumes with an edit decision containing `margaret-collins-portfolio-brief-2026-10-06.xlsx` and asserts the fake tool receives it exactly. Keep the reject assertion at `SENT == []`.

- [ ] **Step 2: Run HITL tests and verify RED, then GREEN after fixture compatibility**

Run: `uv run pytest tests/unit/test_multi_agent_hitl.py -v`

Expected RED before updating old expected payloads; after updating them, all HITL tests PASS.

- [ ] **Step 3: Run all focused frontend and backend tests**

Run:

```powershell
uv run pytest tests/unit/test_report_catalog.py tests/unit/test_workspace_files.py tests/unit/test_emails.py tests/unit/test_multi_agent_email_agent.py tests/unit/test_multi_agent_hitl.py -v
npm test -- --run src/desk/DeskView.test.tsx src/desk/EmailAttachmentSelector.test.tsx src/desk/ApprovalPanel.test.tsx src/desk/approvals.test.ts src/lib/api.test.ts
```

Expected: all focused tests PASS with no unhandled promise or React `act` warnings.

- [ ] **Step 4: Run complete verification**

From the repository root:

```powershell
$env:UV_PROJECT_ENVIRONMENT='F:\langchain-langgraph-mcp\market-agent\market-intelligence-agent\.venv'
$env:UV_CACHE_DIR='F:\langchain-langgraph-mcp\market-agent\market-intelligence-agent\.uv-cache-ui'
uv run pytest tests/unit -v
```

From `frontend/`:

```powershell
npm test -- --run
npm run build
```

Expected: the complete pytest and Vitest suites PASS and Vite production build succeeds. The existing chunk-size advisory is acceptable; new failures or warnings are not.

- [ ] **Step 5: Perform manual Research/HITL QA**

Verify in the browser:

1. `/research` contains no `Portfolio value`, `Stock price`, or `Concentration risk` shortcut row.
2. A `send_email` interrupt shows `Attachment (optional)` at `No attachment`.
3. The selector lists only the recipient's generated reports and does not select one automatically.
4. Selecting a report and approving produces an attachment-aware edit decision.
5. Editing the recipient refreshes the list and clears a stale choice.
6. Reject sends nothing.
7. The card remains usable when the catalog is empty or unavailable.

- [ ] **Step 6: Commit the end-to-end regression**

```powershell
git add -- tests/unit/test_multi_agent_hitl.py
git commit -m "test(email): cover report attachment approval flow"
```

- [ ] **Step 7: Restart both services safely**

Use `netstat -ano` and `Get-CimInstance Win32_Process` to identify only listeners whose command lines belong to this worktree on ports 8000 and 5173. Stop only those exact PIDs. Start both processes hidden and bound to `127.0.0.1`:

```powershell
uv run uvicorn app.api.server:app --host 127.0.0.1 --port 8000 --reload
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Preserve the explicit process PATH and shared UV environment required by this worktree.

- [ ] **Step 8: Verify the running handoff**

Verify:

```text
GET http://127.0.0.1:8000/health
GET http://127.0.0.1:8000/workspace/reports?recipient=<known-client-email>
GET http://127.0.0.1:5173/research
```

Expected: health reports `ok`, the catalog returns only recipient-owned metadata, and Research returns HTTP 200 without the shortcut row. Report final test counts, build status, URLs, simulation/SES limitations, and the worktree branch.
