"""Structured logging (Phase 6).

Every record is one JSON object per line::

    {"ts": "2026-10-08T09:00:00.123Z", "level": "INFO", "service": "api",
     "event": "article_publish", "logger": "app.services.article_service",
     "article_id": 12, "user_id": 3}

`event` is a stable machine-readable name (what log pipelines should filter
on); everything else useful rides along as fields. Code emits events with
`log_event(logger, "article_publish", article_id=12)`. Plain `logger.info("...")`
calls still work: their message becomes the event.

Only the fields passed in are logged -- never request bodies, tokens, passwords
or email addresses; callers log ids.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Attributes every LogRecord has; anything else was passed via `extra=`.
_STANDARD = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime", "taskName"}
_REDACT = ("password", "token", "secret", "authorization", "cookie", "email")


def _safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple, set)):
        return [_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    return str(value)


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "service": self.service,
            "event": getattr(record, "event", None) or record.getMessage(),
            "logger": record.name,
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        for key, value in record.__dict__.items():
            if key in _STANDARD or key == "event" or key.startswith("_"):
                continue
            payload[key] = "[redacted]" if any(part in key.lower() for part in _REDACT) else _safe(value)
        if getattr(record, "event", None) and record.getMessage() and record.getMessage() != payload["event"]:
            payload["message"] = record.getMessage()
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(service: str | None = None) -> None:
    """Idempotent: replaces the root handler so the API and every Celery
    process log in the same shape."""
    service = service or settings.service_name
    handler = logging.StreamHandler(sys.stdout)
    if settings.log_format.lower() == "json":
        handler.setFormatter(JsonFormatter(service))
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, "_livepitch", False):
            root.removeHandler(existing)
    handler._livepitch = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())
    # uvicorn's access log duplicates the request event we emit ourselves
    logging.getLogger("uvicorn.access").disabled = True


def log_event(logger: logging.Logger, event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    logger.log(level, event, extra={"event": event, **fields})
