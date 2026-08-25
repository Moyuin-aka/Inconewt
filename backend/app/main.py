from __future__ import annotations

import asyncio
import contextlib
import json
import os
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from .ai import AIService
from .manager import WorldManager
from .models import (
    BoardPostRequest,
    ChatRequest,
    ChatResponse,
    GiftRequest,
    ImportSaveRequest,
    LoadRequest,
    NPC,
    PlayerAppearanceRequest,
    PlayerMoveRequest,
    PlayerNameRequest,
    SaveRequest,
    ScavengeRequest,
    WeatherWishRequest,
    WorldActionRequest,
    WorldSnapshot,
)
from .store import WorldStore
from .world import WorldEngine


COOKIE_NAME = "inconewt_world"
COOKIE_MAX_AGE = 30 * 24 * 60 * 60


async def tick_forever(manager: WorldManager, interval: int) -> None:
    while True:
        await asyncio.sleep(interval)
        await manager.tick_active_once()


async def cleanup_forever(manager: WorldManager) -> None:
    manager.cleanup_stale(30)
    while True:
        await asyncio.sleep(24 * 60 * 60)
        manager.cleanup_stale(30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = WorldStore(os.getenv("DATABASE_PATH", "./data/inconnewt.db"))
    manager = WorldManager(store)
    interval = max(5, int(os.getenv("TICK_SECONDS", "30")))
    tick_task = asyncio.create_task(tick_forever(manager, interval))
    cleanup_task = asyncio.create_task(cleanup_forever(manager))
    app.state.manager = manager
    try:
        yield
    finally:
        tick_task.cancel()
        cleanup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tick_task
        with contextlib.suppress(asyncio.CancelledError):
            await cleanup_task
        store.close()


app = FastAPI(title="Inconnewt API", version="0.3.3", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-World-Id"],
)


def manager() -> WorldManager:
    return app.state.manager


def world_id(request: Request) -> str:
    return request.state.world_id


def engine(request: Request) -> WorldEngine:
    return manager().engine(world_id(request))


def require_interactive(request: Request) -> None:
    try:
        manager().require_interactive(world_id(request))
    except PermissionError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


@app.middleware("http")
async def visitor_identity(request: Request, call_next):
    if not request.url.path.startswith("/api/") or request.url.path == "/api/health":
        return await call_next(request)
    cookie_id = request.cookies.get(COOKIE_NAME)
    recovery_id = request.headers.get("X-World-Id") if not cookie_id else None
    candidate = cookie_id or recovery_id
    assigned, is_new, valid_candidate = manager().ensure_world(candidate)
    request.state.world_id = assigned
    request.state.is_new = is_new
    request.state.recovered = bool(recovery_id and valid_candidate)
    response = await call_next(request)
    response_world_id = getattr(request.state, "response_world_id", assigned)
    response.set_cookie(
        COOKIE_NAME,
        response_world_id,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


@app.get("/api/health")
async def health() -> dict[str, str]:
    ai = AIService()
    return {"status": "ok", "ai_mode": ai.configured_mode, "model": ai.model}


@app.get("/api/session")
async def session(request: Request) -> dict:
    return manager().session(
        world_id(request),
        is_new=request.state.is_new,
        recovered=request.state.recovered,
    )


@app.post("/api/session/start", response_model=WorldSnapshot)
async def start_session(payload: PlayerNameRequest, request: Request) -> WorldSnapshot:
    return await engine(request).set_player_name(payload.name)


@app.post("/api/session/restart")
async def restart_session(payload: PlayerNameRequest, request: Request) -> dict:
    new_world_id = await manager().restart(world_id(request), payload.name)
    request.state.response_world_id = new_world_id
    return manager().session(new_world_id, is_new=False)


@app.get("/api/world", response_model=WorldSnapshot)
async def get_world(request: Request) -> WorldSnapshot:
    return engine(request).snapshot()


@app.get("/api/npcs/{npc_id}", response_model=NPC)
async def get_npc(npc_id: str, request: Request) -> NPC:
    try:
        return engine(request).get_npc(npc_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="NPC 不存在") from exc


@app.post("/api/world/tick", response_model=WorldSnapshot)
async def tick_world(request: Request) -> WorldSnapshot:
    require_interactive(request)
    return await engine(request).tick()


@app.post("/api/chat/{npc_id}", response_model=ChatResponse)
async def chat(npc_id: str, payload: ChatRequest, request: Request) -> ChatResponse:
    require_interactive(request)
    try:
        return await engine(request).chat(npc_id, payload.message)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="NPC 不存在") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.post("/api/chat/{npc_id}/stream")
async def chat_stream(npc_id: str, payload: ChatRequest, request: Request) -> StreamingResponse:
    require_interactive(request)
    try:
        response = await engine(request).chat(npc_id, payload.message)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="NPC 不存在") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    async def generate():
        meta = {
            "type": "meta",
            "source": response.source,
            "fallback_reason": response.fallback_reason,
            "affinity_delta": response.affinity_delta,
            "impression": response.impression,
            "completed_quest_id": response.completed_quest_id,
            "intents": [item.model_dump() for item in response.intents],
            "revealed_secret_id": response.revealed_secret_id,
        }
        yield f"data: {json.dumps(meta, ensure_ascii=False)}\n\n"
        for character in response.reply:
            yield f"data: {json.dumps({'type': 'delta', 'delta': character}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.018)
        yield 'data: {"type":"done"}\n\n'

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/api/world/actions", response_model=WorldSnapshot)
async def world_action(payload: WorldActionRequest, request: Request) -> WorldSnapshot:
    require_interactive(request)
    try:
        return await engine(request).apply_world_action(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="NPC 不存在") from exc


@app.post("/api/player/move", response_model=WorldSnapshot)
async def move_player(payload: PlayerMoveRequest, request: Request) -> WorldSnapshot:
    require_interactive(request)
    try:
        return await engine(request).move_player(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="地点不存在") from exc


@app.post("/api/player/appearance", response_model=WorldSnapshot)
async def set_player_appearance(payload: PlayerAppearanceRequest, request: Request) -> WorldSnapshot:
    require_interactive(request)
    return await engine(request).set_player_appearance(payload)


@app.post("/api/quests/{quest_id}/accept", response_model=WorldSnapshot)
async def accept_quest(quest_id: str, request: Request) -> WorldSnapshot:
    require_interactive(request)
    try:
        return await engine(request).accept_quest(quest_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="心愿不存在") from exc


@app.post("/api/player/scavenge", response_model=WorldSnapshot)
async def scavenge(payload: ScavengeRequest, request: Request) -> WorldSnapshot:
    require_interactive(request)
    try:
        return await engine(request).scavenge(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="拾取点不存在") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/player/gift", response_model=WorldSnapshot)
async def gift(payload: GiftRequest, request: Request) -> WorldSnapshot:
    require_interactive(request)
    try:
        return await engine(request).gift(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="居民或物品不存在") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/board", response_model=WorldSnapshot)
async def post_board(payload: BoardPostRequest, request: Request) -> WorldSnapshot:
    require_interactive(request)
    try:
        return await engine(request).post_board(payload.text)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.post("/api/wish-weather", response_model=WorldSnapshot)
async def wish_weather(payload: WeatherWishRequest, request: Request) -> WorldSnapshot:
    require_interactive(request)
    try:
        return await engine(request).wish_weather(payload)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/world/saves")
async def list_saves(request: Request) -> dict:
    return {"saves": manager().store.list_saves(world_id(request))}


@app.post("/api/world/save")
async def save_world(payload: SaveRequest, request: Request) -> dict[str, int | str]:
    require_interactive(request)
    save_id = engine(request).save(payload.slot)
    return {"message": f"世界已保存到槽位 {payload.slot}", "save_id": save_id, "slot": payload.slot}


@app.post("/api/world/load", response_model=WorldSnapshot)
async def load_world(
    request: Request,
    payload: LoadRequest = Body(default=LoadRequest(slot=1, kind="manual")),
) -> WorldSnapshot:
    require_interactive(request)
    try:
        return await engine(request).load(payload.slot, payload.kind)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/world/export")
async def export_world(request: Request) -> JSONResponse:
    bundle = manager().export_bundle(world_id(request))
    filename = f"inconewt-day-{bundle['world']['day']}.json"
    return JSONResponse(
        bundle,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/world/import", response_model=WorldSnapshot)
async def import_world(payload: ImportSaveRequest, request: Request) -> WorldSnapshot:
    require_interactive(request)
    if payload.schema_version != 3:
        raise HTTPException(
            status_code=409,
            detail=f"存档版本 {payload.schema_version} 不兼容，当前需要版本 3",
        )
    try:
        return await engine(request).import_snapshot(payload.world)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/events")
async def events(request: Request) -> StreamingResponse:
    current_world_id = world_id(request)
    return StreamingResponse(
        engine(request).events.stream(lambda: manager().heartbeat(current_world_id)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
