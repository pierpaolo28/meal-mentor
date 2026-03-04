"""OpenTelemetry tracing helpers for tools.

The scaffolded ``app/app_utils/telemetry.py`` already wires the Cloud Trace
exporter for ADK internals. This module adds a decorator that wraps every tool
call in its own OTel span so custom traces line up with the ADK spans in
Cloud Trace's waterfall view.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any, TypeVar

from opentelemetry import trace

from app.observability.logging_config import get_logger, log_intent, log_outcome

_tracer = trace.get_tracer("meal_mentor.tools")
F = TypeVar("F", bound=Callable[..., Any])


def traced_tool(tool_name: str) -> Callable[[F], F]:
    """Decorator that adds an OTel span, intent log, and outcome log per call.

    Works on both sync and async tool functions.
    """

    def decorator(fn: F) -> F:
        logger = get_logger(f"tools.{tool_name}")

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                call_id, start = log_intent(logger, tool_name, kwargs)
                with _tracer.start_as_current_span(f"tool.{tool_name}") as span:
                    span.set_attribute("tool.name", tool_name)
                    span.set_attribute("call_id", call_id)
                    try:
                        result = await fn(*args, **kwargs)
                        status = _status_of(result)
                        span.set_attribute("tool.status", status)
                        log_outcome(
                            logger,
                            tool_name,
                            call_id,
                            start,
                            status,
                            result_summary=_summarize(result),
                        )
                        return result
                    except Exception as exc:
                        span.record_exception(exc)
                        span.set_attribute("tool.status", "error")
                        log_outcome(
                            logger,
                            tool_name,
                            call_id,
                            start,
                            "error",
                            error=str(exc),
                        )
                        raise

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            call_id, start = log_intent(logger, tool_name, kwargs)
            with _tracer.start_as_current_span(f"tool.{tool_name}") as span:
                span.set_attribute("tool.name", tool_name)
                span.set_attribute("call_id", call_id)
                try:
                    result = fn(*args, **kwargs)
                    status = _status_of(result)
                    span.set_attribute("tool.status", status)
                    log_outcome(
                        logger,
                        tool_name,
                        call_id,
                        start,
                        status,
                        result_summary=_summarize(result),
                    )
                    return result
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_attribute("tool.status", "error")
                    log_outcome(
                        logger, tool_name, call_id, start, "error", error=str(exc)
                    )
                    raise

        return sync_wrapper  # type: ignore[return-value]

    return decorator


def _status_of(result: Any) -> str:
    if isinstance(result, dict):
        return str(result.get("status", "ok"))
    if hasattr(result, "status"):
        return str(result.status)
    return "ok"


def _summarize(result: Any, max_chars: int = 400) -> Any:
    if isinstance(result, dict):
        keys = list(result.keys())
        return {"keys": keys[:20], "preview": str(result)[:max_chars]}
    if hasattr(result, "model_dump"):
        payload = result.model_dump()  # type: ignore[attr-defined]
        return {"keys": list(payload.keys())[:20], "preview": str(payload)[:max_chars]}
    return {"repr": str(result)[:max_chars]}
