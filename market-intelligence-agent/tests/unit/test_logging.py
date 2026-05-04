import logging
import json
from app.core.logging import configure_logging, JSONFormatter


def test_json_formatter_produces_valid_json():
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="hello world", args=(), exc_info=None,
    )
    output = formatter.format(record)
    parsed = json.loads(output)
    assert parsed["message"] == "hello world"
    assert parsed["level"] == "INFO"
    assert "timestamp" in parsed


def test_configure_logging_sets_root_level():
    configure_logging("WARNING")
    assert logging.getLogger().level == logging.WARNING
    configure_logging("INFO")  # reset for other tests
