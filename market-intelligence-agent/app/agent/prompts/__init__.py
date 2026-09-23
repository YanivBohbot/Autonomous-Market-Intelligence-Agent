from datetime import date


def with_today(prompt: str) -> str:
    """Append the current date to a system prompt. Computed per call (not at
    import) so long-running servers don't serve a stale date. Without it the
    LLM falls back to its training-era year, e.g. adding "2023" to web_search
    queries for "most recent" questions."""
    return f"{prompt}\n\nToday's date is {date.today().isoformat()}."
