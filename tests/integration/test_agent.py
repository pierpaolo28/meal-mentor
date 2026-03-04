"""Integration test - imports the full agent graph and runs a smoke query.

Requires network + Vertex AI creds when GOOGLE_GENAI_USE_VERTEXAI is set,
otherwise skips so unit CI still passes.
"""

from __future__ import annotations

import os

import pytest
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

os.environ.setdefault("USE_IN_MEMORY_STORE", "1")

_HAS_CREDS = bool(
    os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GEMINI_API_KEY")
)


@pytest.mark.skipif(
    not _HAS_CREDS, reason="Requires GOOGLE_CLOUD_PROJECT or GEMINI_API_KEY"
)
def test_agent_stream() -> None:
    from app.agent import root_agent

    session_service = InMemorySessionService()
    session = session_service.create_session_sync(
        user_id="test_user", app_name="test", state={"user_id": "test_user"}
    )
    runner = Runner(agent=root_agent, session_service=session_service, app_name="test")

    message = types.Content(
        role="user",
        parts=[types.Part.from_text(text="I just bought 500g of pasta.")],
    )
    events = list(
        runner.run(
            new_message=message,
            user_id="test_user",
            session_id=session.id,
            run_config=RunConfig(streaming_mode=StreamingMode.SSE),
        )
    )
    assert len(events) > 0

    has_text = any(
        e.content and e.content.parts and any(p.text for p in e.content.parts)
        for e in events
    )
    assert has_text


def test_agent_module_imports_without_network():
    """Even without creds the module should import - unit CI depends on this."""
    from app import agent as agent_module

    assert agent_module.root_agent.name == "meal_mentor"
    sub_names = {a.name for a in agent_module.root_agent.sub_agents}
    assert sub_names == {"planner", "pantry_keeper", "nutritionist", "shopper", "coach"}
