from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app
from src.agent.config import get_llm_client


def make_mock_chunk(content: str):
    chunk = MagicMock()
    delta = MagicMock()
    delta.content = content
    choice = MagicMock()
    choice.delta = delta
    chunk.choices = [choice]
    return chunk


class AsyncIter:
    def __init__(self, items):
        self._items = list(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


def mock_llm(*chunks: str):
    mock = AsyncMock()
    mock.chat.completions.create = AsyncMock(
        return_value=AsyncIter([make_mock_chunk(c) for c in chunks])
    )
    return mock


@pytest.fixture(autouse=True)
def clean_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


class TestChatEndpoint:
    async def test_post_chat_returns_sse_content_type(self):
        app.dependency_overrides[get_llm_client] = lambda: mock_llm()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/chat", json={"query": "你好"})

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream"

    async def test_chat_stream_contains_text_events(self):
        app.dependency_overrides[get_llm_client] = lambda: mock_llm("你好", "世界")

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
        app.dependency_overrides[get_llm_client] = lambda: mock_llm()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream("POST", "/chat", json={"query": "hello"}) as response:
                events = [line async for line in response.aiter_lines()]

        data_events = [e for e in events if e.startswith("data:")]
        assert len(data_events) == 1
        assert data_events[0] == 'data: {"type":"done"}'
