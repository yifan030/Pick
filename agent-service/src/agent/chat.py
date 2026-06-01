import json

from openai import AsyncOpenAI

from src.agent.config import LLM_MODEL


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


async def stream_chat(query: str, client: AsyncOpenAI):
    stream = await client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": query}],
        stream=True,
    )
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield _sse({"type": "text", "content": chunk.choices[0].delta.content})
    yield _sse({"type": "done"})
