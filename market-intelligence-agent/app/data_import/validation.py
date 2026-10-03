"""Pure, framework-free validation for the Data section's two Excel import
shapes (new clients, or holdings upserts for existing clients). No DB, no
network -- the caller (app/api/routers/data.py) fetches the DB-dependent
lookup sets and passes them in, so this stays independently testable and
has nothing to mock."""

from __future__ import annotations

import datetime
from typing import Literal, TypedDict

CLIENT_COLUMNS = {"name", "email", "segment", "risk_profile", "advisor", "city"}
HOLDING_COLUMNS = {"client_email", "ticker", "shares", "avg_cost"}
SEGMENTS = {"VIP", "Premium", "Standard"}
RISK_PROFILES = {"conservative", "balanced", "aggressive"}


class ValidationError(TypedDict):
    row: int
    field: str
    message: str


class ValidationResult(TypedDict):
    valid: bool
    rows: list[dict]
    errors: list[ValidationError]


def _normalize_keys(row: dict) -> dict:
    return {str(k).strip().lower(): v for k, v in row.items()}


def detect_import_type(rows: list[dict]) -> Literal["clients", "holdings"] | None:
    if not rows:
        return None
    keys = set(_normalize_keys(rows[0]).keys())
    if keys >= CLIENT_COLUMNS:
        return "clients"
    if keys >= HOLDING_COLUMNS:
        return "holdings"
    return None


def validate_clients_rows(rows: list[dict], *, existing_emails: set[str]) -> ValidationResult:
    errors: list[ValidationError] = []
    out_rows: list[dict] = []
    seen_emails: set[str] = set()

    for i, raw in enumerate(rows):
        row = _normalize_keys(raw)
        for field in ("name", "email", "segment", "risk_profile", "advisor", "city"):
            if not row.get(field):
                errors.append({"row": i, "field": field, "message": f"{field} is required"})
        if errors and errors[-1]["row"] == i:
            continue
        if row["segment"] not in SEGMENTS:
            errors.append({"row": i, "field": "segment", "message": f"must be one of {sorted(SEGMENTS)}"})
            continue
        if row["risk_profile"] not in RISK_PROFILES:
            errors.append({"row": i, "field": "risk_profile", "message": f"must be one of {sorted(RISK_PROFILES)}"})
            continue
        email = row["email"]
        if email in existing_emails:
            errors.append({"row": i, "field": "email", "message": "a client with this email already exists"})
            continue
        if email in seen_emails:
            errors.append({"row": i, "field": "email", "message": "duplicate email in this file"})
            continue
        seen_emails.add(email)
        out_rows.append({
            "name": row["name"],
            "email": email,
            "segment": row["segment"],
            "risk_profile": row["risk_profile"],
            "advisor": row["advisor"],
            "city": row["city"],
            "joined_on": row.get("joined_on") or datetime.date.today().isoformat(),
        })

    return {"valid": not errors, "rows": out_rows if not errors else [], "errors": errors}


def validate_holdings_rows(
    rows: list[dict],
    *,
    client_id_by_email: dict[str, int],
    known_tickers: set[str],
) -> ValidationResult:
    errors: list[ValidationError] = []
    out_rows: list[dict] = []
    seen_pairs: set[tuple[int, str]] = set()

    for i, raw in enumerate(rows):
        row = _normalize_keys(raw)
        for field in ("client_email", "ticker", "shares", "avg_cost"):
            if row.get(field) in (None, ""):
                errors.append({"row": i, "field": field, "message": f"{field} is required"})
        if errors and errors[-1]["row"] == i:
            continue
        email = row["client_email"]
        if email not in client_id_by_email:
            errors.append({"row": i, "field": "client_email", "message": "no client with this email"})
            continue
        ticker = str(row["ticker"]).upper()
        if ticker not in known_tickers:
            errors.append({"row": i, "field": "ticker", "message": "unknown ticker"})
            continue
        try:
            shares = float(row["shares"])
            avg_cost = float(row["avg_cost"])
        except (TypeError, ValueError):
            errors.append({"row": i, "field": "shares", "message": "shares/avg_cost must be numeric"})
            continue
        if shares <= 0:
            errors.append({"row": i, "field": "shares", "message": "must be > 0"})
            continue
        if avg_cost <= 0:
            errors.append({"row": i, "field": "avg_cost", "message": "must be > 0"})
            continue
        client_id = client_id_by_email[email]
        pair = (client_id, ticker)
        if pair in seen_pairs:
            errors.append({"row": i, "field": "ticker", "message": "duplicate client/ticker in this file"})
            continue
        seen_pairs.add(pair)
        out_rows.append({"client_id": client_id, "ticker": ticker, "shares": shares, "avg_cost": avg_cost})

    return {"valid": not errors, "rows": out_rows if not errors else [], "errors": errors}
