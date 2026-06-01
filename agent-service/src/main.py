from fastapi import FastAPI

app = FastAPI(title="Pick AI Shopping Guide")


@app.get("/health")
async def health():
    return {"status": "ok"}
