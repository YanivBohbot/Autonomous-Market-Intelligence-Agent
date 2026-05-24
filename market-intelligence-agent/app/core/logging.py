import json
import logging
import sys
from datetime import datetime, timezone

from app.core.config import settings


# Keys of `Settings` whose values must never appear in log output. Any record
# whose formatted message contains one of these literal values is redacted
# before reaching the JSON formatter. The check is on the resolved string —
# i.e. the actual secret characters, not the env-var name.
_REDACTED_SETTING_KEYS = (
    "OPENAI_API_KEY",
    "PINECONE_API_KEY",
    "TAVILY_API_KEY",
    "EMAIL_PASSWORD",
    "LIVEKIT_API_SECRET",
    "DEEPGRAM_API_KEY",
    "ELEVENLABS_API_KEY",
)

REDACTED = "***REDACTED***"


def _secret_values() -> tuple[str, ...]:
    """Resolve current secret values from Settings, skipping anything blank
    or shorter than 8 chars (avoids matching trivial test placeholders that
    would over-redact normal log messages)."""
    out: list[str] = []
    for key in _REDACTED_SETTING_KEYS:
        val = getattr(settings, key, None)
        if isinstance(val, str) and len(val) >= 8:
            out.append(val)
    return tuple(out)


class SecretRedactionFilter(logging.Filter):
    """Replaces any occurrence of a known secret value in the log message with
    `***REDACTED***`. Operates on the formatted message AND on each positional
    arg, because callers commonly log via `logger.info("got %s", token)`."""

    def __init__(self) -> None:
        super().__init__()
        self._secrets = _secret_values()

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._secrets:
            return True

        if isinstance(record.msg, str):
            new_msg = record.msg
            for s in self._secrets:
                if s and s in new_msg:
                    new_msg = new_msg.replace(s, REDACTED)
            record.msg = new_msg

        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: self._scrub(v) for k, v in record.args.items()
                }
            else:
                record.args = tuple(self._scrub(a) for a in record.args)

        return True

    def _scrub(self, value):
        if not isinstance(value, str):
            return value
        for s in self._secrets:
            if s and s in value:
                value = value.replace(s, REDACTED)
        return value


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    handler.addFilter(SecretRedactionFilter())
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]
