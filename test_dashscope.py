"""Test DashScope LLM, Text Embedding, and MultiModal Embedding connectivity."""
import io
import os
import sys
import requests

# Fix Windows console encoding for emoji output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


def load_env(env_path: str):
    """Load key=value pairs from a .env file into os.environ."""
    if not os.path.isfile(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key not in os.environ:
                os.environ[key] = val


# ── Load env ──
load_env(os.path.join(os.path.dirname(__file__), "agent-service", ".env"))

LLM_KEY = os.environ.get("LLM_API_KEY", "")
LLM_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")

EMB_KEY = os.environ.get("EMBEDDING_API_KEY", "")
EMB_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-v4")
EMB_DIM = int(os.environ.get("EMBEDDING_DIM", "1024"))
MM_MODEL = os.environ.get("MULTIMODAL_EMBEDDING_MODEL", "tongyi-embedding-vision-plus")


def test_chat():
    """Test LLM chat completion (OpenAI-compatible endpoint)."""
    print(f"[LLM] endpoint={LLM_URL}")
    print(f"[LLM] model={LLM_MODEL}")
    resp = requests.post(
        f"{LLM_URL}/chat/completions",
        headers={"Authorization": f"Bearer {LLM_KEY}", "Content-Type": "application/json"},
        json={
            "model": LLM_MODEL,
            "messages": [{"role": "user", "content": "说一个词：你好"}],
            "max_tokens": 10,
        },
        timeout=30,
    )
    print(f"[LLM] status={resp.status_code}")
    if resp.ok:
        data = resp.json()
        reply = data["choices"][0]["message"]["content"]
        print(f"[LLM] reply={reply}")
        return True
    else:
        print(f"[LLM] body={resp.text[:400]}")
        return False


def test_text_embedding():
    """Test text-only embedding via DashScope TextEmbedding API."""
    import dashscope
    from dashscope import TextEmbedding

    dashscope.api_key = EMB_KEY

    print(f"\n[TextEmbedding] model={EMB_MODEL} dimension={EMB_DIM}")
    response = TextEmbedding.call(
        model=EMB_MODEL,
        input="推荐附近的火锅店",
        dimension=EMB_DIM,
    )
    print(f"[TextEmbedding] status_code={response.status_code}")
    if response.status_code == 200:
        output = response.output
        if isinstance(output, dict):
            emb = output["embeddings"][0]["embedding"]
        else:
            emb = output.embeddings[0].embedding
        print(f"[TextEmbedding] dim={len(emb)}, first 5 values={emb[:5]}")
        return True
    else:
        print(f"[TextEmbedding] error: code={response.code}, message={response.message}")
        return False


def test_multimodal_embedding():
    """Test multimodal embedding via DashScope MultiModalEmbedding API (text-only input)."""
    import dashscope
    from dashscope import (
        MultiModalEmbedding,
        MultiModalEmbeddingItemText,
    )

    dashscope.api_key = EMB_KEY

    print(f"\n[MultiModalEmbedding] model={MM_MODEL}")
    response = MultiModalEmbedding.call(
        model=MM_MODEL,
        input=[
            MultiModalEmbeddingItemText("推荐附近的火锅店", factor=1.0),
        ],
    )
    print(f"[MultiModalEmbedding] status_code={response.status_code}")
    if response.status_code == 200:
        output = response.output
        if isinstance(output, dict):
            emb = output["embeddings"][0]["embedding"]
        else:
            emb = output.embeddings[0].embedding
        print(f"[MultiModalEmbedding] dim={len(emb)}, first 5 values={emb[:5]}")
        return True
    else:
        print(f"[MultiModalEmbedding] error: code={response.code}, message={response.message}")
        return False


if __name__ == "__main__":
    if not LLM_KEY:
        print("LLM_API_KEY not set in agent-service/.env")
        sys.exit(1)
    if not EMB_KEY:
        print("EMBEDDING_API_KEY not set in agent-service/.env")
        sys.exit(1)

    print("=" * 60)
    ok1 = test_chat()
    ok2 = test_text_embedding()
    ok3 = test_multimodal_embedding()
    print("=" * 60)

    all_ok = [ok1, ok2, ok3]
    passed = sum(all_ok)
    total = len(all_ok)
    print(f"Passed: {passed}/{total}")
    if passed == total:
        print("All checks passed.")
        sys.exit(0)
    else:
        print("Some checks failed — review errors above.")
        sys.exit(1)
