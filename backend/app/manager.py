from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import UUID, uuid4

from .ai import AIService
from .models import WorldSnapshot, initial_world
from .store import WorldStore
from .world import WorldEngine


class WorldManager:
    """按访客隔离 WorldEngine，并集中管理活跃度、容量与 AI 配额。"""

    def __init__(
        self,
        store: WorldStore,
        *,
        max_active: int | None = None,
        active_seconds: int = 300,
        daily_ai_limit: int | None = None,
    ) -> None:
        self.store = store
        self.max_active = max_active if max_active is not None else max(1, int(os.getenv("MAX_ACTIVE_WORLDS", "20")))
        self.active_seconds = active_seconds
        self.daily_ai_limit = daily_ai_limit if daily_ai_limit is not None else max(0, int(os.getenv("AI_DAILY_CALL_LIMIT", "120")))
        self.engines: dict[str, WorldEngine] = {}

    @staticmethod
    def valid_world_id(value: str | None) -> bool:
        if not value:
            return False
        try:
            return str(UUID(value)) == value.lower()
        except ValueError:
            return False

    def create_world(self, *, name: str = "外来者", started: bool = False) -> str:
        world_id = str(uuid4())
        world = initial_world()
        world.player.name = name.strip() or "外来者"
        self.store.create_world(world_id, world, started=started)
        return world_id

    def ensure_world(self, candidate: str | None = None) -> tuple[str, bool, bool]:
        if self.valid_world_id(candidate) and self.store.world_exists(str(candidate)):
            return str(candidate), False, True
        world_id = self.create_world()
        return world_id, True, False

    def engine(self, world_id: str) -> WorldEngine:
        if world_id not in self.engines:
            if not self.store.world_exists(world_id):
                raise KeyError(world_id)
            ai = AIService(
                budget_consumer=lambda: self.store.consume_ai_call(world_id, self.daily_ai_limit)
            )
            self.engines[world_id] = WorldEngine(self.store, ai, world_id)
        return self.engines[world_id]

    def active_world_ids(self) -> list[str]:
        return self.store.active_world_ids(self.active_seconds)

    def access_mode(self, world_id: str) -> str:
        active = self.active_world_ids()
        if world_id in active or len(active) < self.max_active:
            return "interactive"
        return "observer"

    def heartbeat(self, world_id: str) -> str:
        mode = self.access_mode(world_id)
        if mode == "interactive":
            self.store.touch_world(world_id)
        return mode

    def require_interactive(self, world_id: str) -> None:
        if self.access_mode(world_id) != "interactive":
            raise PermissionError("当前活跃世界已满，你正在观察模式中；有空位后会自动接入。")

    async def tick_active_once(self) -> list[str]:
        ticked: list[str] = []
        for world_id in self.active_world_ids():
            await self.engine(world_id).tick()
            ticked.append(world_id)
        return ticked

    async def restart(self, old_world_id: str, name: str) -> str:
        new_world_id = self.create_world(name=name, started=True)
        self.engines.pop(old_world_id, None)
        self.store.delete_world(old_world_id)
        return new_world_id

    def session(self, world_id: str, *, is_new: bool = False, recovered: bool = False) -> dict:
        metadata = self.store.world_metadata(world_id)
        if not metadata:
            raise KeyError(world_id)
        calls = self.store.ai_calls(world_id)
        configured = self.engine(world_id).ai.configured_mode
        return {
            "world_id": world_id,
            "is_new": is_new or not bool(metadata["started"]),
            "recovered": recovered,
            "player_name": metadata["player_name"],
            "updated_at": metadata["updated_at"],
            "access_mode": self.access_mode(world_id),
            "active_worlds": len(self.active_world_ids()),
            "max_active_worlds": self.max_active,
            "ai_mode": "mock" if configured == "mock" or calls >= self.daily_ai_limit else "deepseek",
            "ai_budget_exhausted": configured == "deepseek" and calls >= self.daily_ai_limit,
            "ai_calls_today": calls,
            "ai_daily_limit": self.daily_ai_limit,
        }

    def export_bundle(self, world_id: str) -> dict:
        world = self.engine(world_id).snapshot()
        return {
            "schema_version": world.schema_version,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "world": world.model_dump(mode="json"),
        }

    def cleanup_stale(self, days: int = 30) -> int:
        stale_before = set(self.engines)
        deleted = self.store.cleanup_stale(days)
        for world_id in stale_before:
            if not self.store.world_exists(world_id):
                self.engines.pop(world_id, None)
        return deleted
