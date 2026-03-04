"""Structured JSON logging with intent-vs-outcome capture.

Every tool logs two events per call:

* ``tool.intent`` — emitted *before* the side-effect. Includes the tool name,
  scrubbed arguments, and a unique ``call_id``.
* ``tool.outcome`` — emitted *after*. Includes the same ``call_id`` plus
  ``status`` (``ok`` / ``error``), latency, and a scrubbed result summary.

Grepping ``call_id`` in Cloud Logging shows you exactly what the agent intended
and what actually happened, which is the "intent vs. outcome" pattern the
review rubric asks for.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from typing import Any

from app.observability.pii import redact_pii

try:
    import google.cloud.logging as cloud_logging
except ImportError:  # pragma: no cover - optional in local dev
    cloud_logging = None

_configured = False


class _JsonFormatter(logging.Formatter):
    """Minimal JSON formatter — one line per record, structured metadata."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
        }
        for key, value in record.__dict__.items():
            if key.startswith("_") or key in _RESERVED:
                continue
            if key == "structured":
                payload.update(value)
            else:
                payload[key] = value
        return json.dumps(payload, default=str)


_RESERVED = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "getMessage",
    "message",
}


def _configure_once() -> None:
    global _configured
    if _configured:
        return

    handler: logging.Handler
    if cloud_logging is not None and os.environ.get("GOOGLE_CLOUD_PROJECT"):
        try:
            client = cloud_logging.Client()
            handler = cloud_logging.handlers.CloudLoggingHandler(
                client, name="meal_mentor"
            )
        except Exception:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(_JsonFormatter())
    else:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JsonFormatter())

    root = logging.getLogger("meal_mentor")
    root.setLevel(logging.INFO)
    root.handlers = [handler]
    root.propagate = False
    _configured = True


def get_logger(name: str) -> logging.Logger:
    _configure_once()
    return logging.getLogger(f"meal_mentor.{name}")


def new_call_id() -> str:
    return uuid.uuid4().hex[:12]


def log_intent(
    logger: logging.Logger, tool: str, args: dict[str, Any]
) -> tuple[str, float]:
    """Log an ``intent`` event and return (call_id, start_time)."""
    call_id = new_call_id()
    scrubbed = redact_pii(args)
    logger.info(
        "tool.intent %s",
        tool,
        extra={
            "structured": {
                "event": "tool.intent",
                "tool": tool,
                "call_id": call_id,
                "args": scrubbed,
            }
        },
    )
    return call_id, time.monotonic()


def log_outcome(
    logger: logging.Logger,
    tool: str,
    call_id: str,
    start: float,
    status: str,
    result_summary: dict[str, Any] | str | None = None,
    error: str | None = None,
) -> None:
    """Log an ``outcome`` event correlated to a prior ``log_intent``."""
    latency_ms = round((time.monotonic() - start) * 1000, 2)
    payload: dict[str, Any] = {
        "event": "tool.outcome",
        "tool": tool,
        "call_id": call_id,
        "status": status,
        "latency_ms": latency_ms,
    }
    if result_summary is not None:
        payload["result"] = redact_pii(result_summary)
    if error is not None:
        payload["error"] = error
    logger.info(
        "tool.outcome %s status=%s", tool, status, extra={"structured": payload}
    )
