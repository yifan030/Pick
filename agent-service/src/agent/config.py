import os

from openai import AsyncOpenAI

LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")


def get_llm_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=os.environ.get("LLM_BASE_URL"),
        api_key=os.environ.get("LLM_API_KEY", "sk-placeholder"),
    )
