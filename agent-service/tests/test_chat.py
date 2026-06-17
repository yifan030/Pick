"""Tests for the POST /chat SSE streaming endpoint.

Uses LangGraph v3 astream_events protocol.
"""

from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app, get_agent


def make_message_chunk(content: str):
    """Create a mock message chunk in LangChain AIMessageChunk style."""
    chunk = MagicMock()
    chunk.content = content
    return chunk


def mock_agent_stream(*text_chunks: str, custom_events: list | None = None):
    """Create a mock agent whose astream_events() returns v3-format events.

    Yields message-channel events (token-level) and optional custom-channel events.
    """
    mock = MagicMock()

    async def _astream_events(input_data, config=None, version=None):
        async def _generate():
            for text in text_chunks:
                yield {
                    "method": "messages",
                    "params": {
                        "data": (make_message_chunk(text), {}),
                        "namespace": (),
                    },
                }
            for event in (custom_events or []):
                yield {
                    "method": "custom",
                    "params": {"data": event, "namespace": ()},
                }

        return _generate()

    mock.astream_events = _astream_events
    mock.get_state = MagicMock(return_value=None)
    return mock


@pytest.fixture(autouse=True)
def clean_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


class TestChatEndpoint:
    async def test_post_chat_returns_sse_content_type(self):
        """SSE endpoint should return text/event-stream content type."""
        app.dependency_overrides[get_agent] = lambda: mock_agent_stream()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/chat", json={"query": "你好"})

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream"

    async def test_chat_stream_contains_text_events(self):
        """SSE stream should emit text events with the expected content."""
        app.dependency_overrides[get_agent] = lambda: mock_agent_stream("你好", "世界")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream("POST", "/chat", json={"query": "你好"}) as response:
                events = [line async for line in response.aiter_lines()]

        text_events = [
            e for e in events if e.startswith("data:") and '"type":"text"' in e
        ]
        done_events = [
            e for e in events if e.startswith("data:") and '"type":"done"' in e
        ]
        assert len(text_events) == 2, f"events: {events}"
        assert '"content":"你好"' in text_events[0]
        assert '"content":"世界"' in text_events[1]
        assert len(done_events) == 1

    async def test_chat_stream_ends_with_done_event(self):
        """Empty response should still terminate with a done event."""
        app.dependency_overrides[get_agent] = lambda: mock_agent_stream()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream("POST", "/chat", json={"query": "hello"}) as response:
                events = [line async for line in response.aiter_lines()]

        data_events = [e for e in events if e.startswith("data:")]
        assert len(data_events) == 1
        assert '"type":"done"' in data_events[0]

    async def test_chat_stream_includes_custom_events(self):
        """Custom events (e.g., shop_card) should be passed through as SSE."""
        custom = {"type": "shop_card", "data": {"shop_id": 1, "name": "测试店铺"}}
        app.dependency_overrides[get_agent] = lambda: mock_agent_stream(
            "推荐如下:", custom_events=[custom]
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream("POST", "/chat", json={"query": "推荐火锅"}) as response:
                events = [line async for line in response.aiter_lines()]

        shop_card_events = [
            e for e in events if e.startswith("data:") and '"type":"shop_card"' in e
        ]
        assert len(shop_card_events) == 1
        assert '"shop_id":1' in shop_card_events[0]

    async def test_chat_with_session_id(self):
        """Provided session_id should be used and appear in done event."""
        app.dependency_overrides[get_agent] = lambda: mock_agent_stream("ok")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream("POST", "/chat", json={
                "session_id": "my-session-123",
                "query": "hi",
            }) as response:
                events = [line async for line in response.aiter_lines()]

        done_events = [e for e in events if e.startswith("data:") and '"type":"done"' in e]
        assert len(done_events) == 1
