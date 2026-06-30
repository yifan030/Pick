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


# === 记忆提取模型（独立低成本模型）===
EXTRACTOR_MODEL = os.getenv("EXTRACTOR_MODEL", None)
EXTRACTOR_BASE_URL = os.getenv("EXTRACTOR_BASE_URL", None)
EXTRACTOR_API_KEY = os.getenv("EXTRACTOR_API_KEY", None)


def get_extractor_model():
    """获取记忆提取专用模型。

    如果配置了独立提取模型（EXTRACTOR_MODEL），返回该模型实例；
    否则回退到对话主模型（渐进式接入：Phase 3-6 开发期用主模型跑通逻辑）。
    """
    if EXTRACTOR_MODEL:
        return init_chat_model(
            model=EXTRACTOR_MODEL,
            model_provider="openai",
            base_url=EXTRACTOR_BASE_URL or os.getenv("LLM_BASE_URL"),
            api_key=EXTRACTOR_API_KEY or os.getenv("LLM_API_KEY", "sk-placeholder"),
        )
    # 回退：使用对话主模型
    return get_model()
