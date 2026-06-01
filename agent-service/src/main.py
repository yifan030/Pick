from fastapi import Depends, FastAPI
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel

from src.agent.chat import stream_chat
from src.agent.config import get_llm_client

app = FastAPI(title="Pick AI Shopping Guide")


class ChatRequest(BaseModel):
    session_id: str | None = None
    user_id: str | None = None
    query: str
    longitude: float | None = None
    latitude: float | None = None


@app.post("/chat")
async def chat(request: ChatRequest, client: AsyncOpenAI = Depends(get_llm_client)):
    response = StreamingResponse(
        stream_chat(request.query, client),
        media_type="text/event-stream",
    )
    response.headers["content-type"] = "text/event-stream"
    return response


@app.get("/health")
async def health():
    return {"status": "ok"}
