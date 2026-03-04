"""Background memory consolidation and sliding-window history compaction.

Two mechanisms live here:

1. **Compaction** (``compact_history``): a ``before_model_callback`` that keeps
   the conversation under ``MAX_HISTORY_TOKENS`` using a sliding window plus a
   running summary. This prevents context bloat during long planning sessions.

2. **Consolidation** (``consolidate_learnings_async``): a fire-and-forget task
   spawned from ``after_agent_callback`` that reads the recent turns, extracts
   durable facts about the user (allergies, dislikes, favorite cuisines), and
   writes them to the ``user_learnings`` collection. Consolidation never blocks
   the UI response.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import tiktoken
from google.adk.agents.callback_context import CallbackContext
from google.genai import types

from app.config import MAX_HISTORY_TOKENS
from app.memory.firestore_store import get_store

logger = logging.getLogger(__name__)

_encoder = tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str) -> int:
    return len(_encoder.encode(text or ""))


def _content_tokens(content: types.Content | None) -> int:
    if content is None or not content.parts:
        return 0
    return sum(_count_tokens(getattr(p, "text", "") or "") for p in content.parts)


async def compact_history(callback_context: CallbackContext, llm_request: Any) -> None:
    """Trim conversation history to stay under the token budget.

    Runs as a ``before_model_callback``. Keeps the system instruction plus the
    most-recent turns that fit under ``MAX_HISTORY_TOKENS``; older turns are
    dropped after a one-line summary is stashed in session state as
    ``history_summary`` so the model still has an outline of what happened.
    """
    contents = getattr(llm_request, "contents", None)
    if not contents:
        return

    kept: list[types.Content] = []
    running = 0
    for content in reversed(contents):
        cost = _content_tokens(content)
        if running + cost > MAX_HISTORY_TOKENS and kept:
            break
        kept.insert(0, content)
        running += cost

    dropped = len(contents) - len(kept)
    if dropped > 0:
        summary = _summarize_dropped(contents[:dropped])
        callback_context.state["history_summary"] = summary
        llm_request.contents = kept
        logger.info(
            "compact_history: dropped=%d kept=%d tokens=%d",
            dropped,
            len(kept),
            running,
        )


def _summarize_dropped(contents: list[types.Content]) -> str:
    """Very lightweight extractive summary — first sentence of every 3rd turn."""
    bullets: list[str] = []
    for i, content in enumerate(contents):
        if i % 3 != 0 or not content.parts:
            continue
        text = " ".join(getattr(p, "text", "") or "" for p in content.parts).strip()
        if not text:
            continue
        first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
        bullets.append(f"- {first[:200]}")
        if len(bullets) >= 10:
            break
    if not bullets:
        return ""
    return "Earlier in the conversation:\n" + "\n".join(bullets)


_DIETARY_HINT_RE = re.compile(
    r"\b(vegetarian|vegan|gluten[- ]free|dairy[- ]free|nut[- ]free|kosher|halal|keto|low[- ]carb|pescatarian)\b",
    re.I,
)
_DISLIKE_RE = re.compile(
    r"\b(don'?t|do not|can'?t|cannot|won'?t|hate|dislike|allergic to)\s+(eat\s+)?([a-zA-Z ]{3,40})",
    re.I,
)


async def consolidate_learnings_async(user_id: str, transcript: str) -> None:
    """Extract durable user facts from a transcript and persist them.

    Runs off the request path. Uses cheap regex extraction; a production build
    could swap this for a Gemini Flash call. Idempotent - same key overwrites.
    """
    store = get_store()
    for match in _DIETARY_HINT_RE.finditer(transcript):
        canonical = match.group(1).lower().replace(" ", "_")
        await store.put_learning(
            user_id, f"dietary:{canonical}", f"User mentioned '{canonical}'."
        )
    for match in _DISLIKE_RE.finditer(transcript):
        food = match.group(3).strip().lower()
        if len(food) < 40:
            await store.put_learning(
                user_id, f"dislike:{food[:32]}", f"User dislikes or cannot eat {food}."
            )


def spawn_consolidation(callback_context: CallbackContext) -> None:
    """``after_agent_callback`` — fire consolidation without awaiting."""
    user_id = callback_context.state.get("user_id", "anonymous")
    transcript_parts: list[str] = []
    # Best-effort: recent state entries as the transcript
    for key in ("last_user_message", "last_agent_response"):
        val = callback_context.state.get(key)
        if isinstance(val, str):
            transcript_parts.append(val)
    transcript = "\n".join(transcript_parts)
    if not transcript:
        return
    try:
        loop = asyncio.get_running_loop()
        # Keep a strong reference so the task isn't garbage-collected mid-flight.
        task = loop.create_task(consolidate_learnings_async(user_id, transcript))
        _pending_tasks.add(task)
        task.add_done_callback(_pending_tasks.discard)
    except RuntimeError:
        # No running loop (e.g. test env) - run inline
        asyncio.run(consolidate_learnings_async(user_id, transcript))


_pending_tasks: set[asyncio.Task] = set()
