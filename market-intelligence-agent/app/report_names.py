"""Shared naming helpers for generated portfolio reports."""


def slugify(name: str) -> str:
    """Return the safe client-name prefix used by generated reports."""
    cleaned = "".join(c if c.isalnum() or c in (" ", "-") else "" for c in name.lower())
    return "-".join(cleaned.split())
