import os

from openai import AsyncOpenAI
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")


def get_model() -> BaseChatModel:
    """返回 LangChain 兼容的 BaseChatModel，使用 init_chat_model 封装。

    通过环境变量配置 OpenAI 兼容端点：
    - LLM_BASE_URL: API 基础地址（可选，默认 OpenAI）
    - LLM_API_KEY: API 密钥
    - LLM_MODEL: 模型名称（默认 gpt-4o-mini）
    """
    return init_chat_model(
        model=LLM_MODEL,
        model_provider="openai",
        base_url=os.environ.get("LLM_BASE_URL"),
        api_key=os.environ.get("LLM_API_KEY", "sk-placeholder"),
    )


def get_llm_client() -> AsyncOpenAI:
    """向后兼容：返回原生 AsyncOpenAI 客户端。

    推荐新代码使用 get_model() 获取 LangChain 兼容模型。
    保留此函数供 ingestion 和未迁移代码使用。
    """
    return AsyncOpenAI(
        base_url=os.environ.get("LLM_BASE_URL"),
        api_key=os.environ.get("LLM_API_KEY", "sk-placeholder"),
    )
