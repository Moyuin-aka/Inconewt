from __future__ import annotations

import asyncio
import contextlib
import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .ai import AIService
from .models import ChatRequest, ChatResponse, NPC, WorldActionRequest, WorldSnapshot
from .store import WorldStore
from .world import WorldEngine


async def tick_forever(engine: WorldEngine, interval: int) -> None:
    while True:
        await asyncio.sleep(interval)
        await engine.tick()


@asynccontextmanager
async def lifespan(app: FastAPI):
    database_path = os.getenv("DATABASE_PATH", "./data/inconnewt.db")
    store = WorldStore(database_path)
    engine = WorldEngine(store, AIService())
    interval = max(5, int(os.getenv("TICK_SECONDS", "30")))
    task = asyncio.create_task(tick_forever(engine, interval))
    app.state.engine = engine
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        store.close()


app = FastAPI(title="Inconnewt API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def engine() -> WorldEngine:
    return app.state.engine


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "ai_mode": engine().ai.configured_mode, "model": engine().ai.model}


@app.get("/api/world", response_model=WorldSnapshot)
async def get_world() -> WorldSnapshot:
    return engine().snapshot()


@app.get("/api/npcs/{npc_id}", response_model=NPC)
async def get_npc(npc_id: str) -> NPC:
    try:
        return engine().get_npc(npc_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="NPC 不存在") from exc


@app.post("/api/world/tick", response_model=WorldSnapshot)
async def tick_world() -> WorldSnapshot:
    return await engine().tick()


@app.post("/api/chat/{npc_id}", response_model=ChatResponse)
async def chat(npc_id: str, request: ChatRequest) -> ChatResponse:
    try:
        return await engine().chat(npc_id, request.message)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="NPC 不存在") from exc


@app.post("/api/chat/{npc_id}/stream")
async def chat_stream(npc_id: str, request: ChatRequest) -> StreamingResponse:
    """AVG 前端使用的 SSE 文本流；Mock 与真实 AI 共享相同演出协议。"""
    try:
        response = await engine().chat(npc_id, request.message)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="NPC 不存在") from exc

    async def generate():
        meta = {"type": "meta", "source": response.source, "fallback_reason": response.fallback_reason}
        yield f"data: {json.dumps(meta, ensure_ascii=False)}\n\n"
        for character in response.reply:
            yield f"data: {json.dumps({'type': 'delta', 'delta': character}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.018)
        yield 'data: {"type":"done"}\n\n'

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/api/world/actions", response_model=WorldSnapshot)
async def world_action(request: WorldActionRequest) -> WorldSnapshot:
    try:
        return await engine().apply_world_action(request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="NPC 不存在") from exc


@app.post("/api/world/save")
async def save_world() -> dict[str, int | str]:
    save_id = engine().save()
    return {"message": "世界已保存", "save_id": save_id}


@app.post("/api/world/load", response_model=WorldSnapshot)
async def load_world() -> WorldSnapshot:
    try:
        return await engine().load()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/events")
async def events() -> StreamingResponse:
    return StreamingResponse(
        engine().events.stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
