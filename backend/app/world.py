from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from .ai import AIService
from .models import ChatResponse, NPC, NPCAction, WorldActionRequest, WorldEvent, WorldSnapshot, initial_world
from .store import WorldStore


class EventBus:
    def __init__(self) -> None:
        self.subscribers: set[asyncio.Queue[str]] = set()

    async def publish(self, event: WorldEvent) -> None:
        for queue in list(self.subscribers):
            await queue.put(event.model_dump_json())

    async def stream(self):
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=50)
        self.subscribers.add(queue)
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=20)
                    yield f"event: world\ndata: {payload}\n\n"
                except TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            self.subscribers.discard(queue)


class WorldEngine:
    """世界推进、NPC 行为执行与持久化都聚合在这里，便于追踪一次 tick。"""

    def __init__(self, store: WorldStore, ai: AIService) -> None:
        self.store = store
        self.ai = ai
        self.world = store.load_current() or initial_world()
        self.store.save_current(self.world)
        self.lock = asyncio.Lock()
        self.events = EventBus()

    def snapshot(self) -> WorldSnapshot:
        return self.world.model_copy(deep=True)

    def get_npc(self, npc_id: str) -> NPC:
        npc = next((item for item in self.world.npcs if item.id == npc_id), None)
        if not npc:
            raise KeyError(npc_id)
        return npc

    async def tick(self) -> WorldSnapshot:
        async with self.lock:
            self.world.minute += 60
            if self.world.minute >= 24 * 60:
                self.world.day += 1
                self.world.minute %= 24 * 60

            for npc in self.world.npcs:
                self._age_needs(npc)
                decision, source, fallback = await self.ai.decide(npc, self.world)
                # Decision 对外字段是 action，运行态字段是 type；显式映射可避免默认成 idle。
                npc.state.action = NPCAction(
                    type=decision.action,
                    target=decision.target,
                    say=decision.say,
                    reason=decision.reason,
                    source=source,
                )
                self._apply_decision(npc)
                memory = f"{self.time_label()}：{decision.reason}"
                if fallback:
                    memory += f"（{fallback}）"
                npc.memory.short_term = (npc.memory.short_term + [memory])[-20:]
                event = self._event("npc_action", f"{npc.profile.name}：{decision.reason}")
                self._append_event(event)
                await self.events.publish(event)

            self._touch_and_persist()
            return self.snapshot()

    async def chat(self, npc_id: str, message: str) -> ChatResponse:
        async with self.lock:
            npc = self.get_npc(npc_id)
            reply, source, fallback = await self.ai.chat(npc, message, self.world)
            npc.memory.short_term = (npc.memory.short_term + [f"玩家说：{message}", f"{npc.profile.name}回答：{reply}"])[-20:]
            npc.state.needs.social = max(0, npc.state.needs.social - 18)
            event = self._event("chat", f"你与{npc.profile.name}聊了几句。")
            self._append_event(event)
            self._touch_and_persist()
            await self.events.publish(event)
            return ChatResponse(reply=reply, source=source, fallback_reason=fallback)

    async def apply_world_action(self, request: WorldActionRequest) -> WorldSnapshot:
        async with self.lock:
            if request.action == "weather":
                self.world.weather = request.value
                text = f"天气变成了「{request.value}」。"
            elif request.action == "announcement":
                self.world.announcement = request.value
                text = f"公告板更新：{request.value}"
            else:
                npc = self.get_npc(request.npc_id or "")
                npc.memory.short_term = (npc.memory.short_term + [f"玩家送来：{request.value}"])[-20:]
                npc.state.mood = "被惦记着"
                text = f"你把「{request.value}」送给了{npc.profile.name}。"
            event = self._event("world_action", text)
            self._append_event(event)
            self._touch_and_persist()
            await self.events.publish(event)
            return self.snapshot()

    def save(self) -> int:
        return self.store.create_save(self.world)

    async def load(self) -> WorldSnapshot:
        async with self.lock:
            loaded = self.store.load_latest_save()
            if not loaded:
                raise LookupError("还没有可恢复的存档")
            self.world = loaded
            event = self._event("load", "世界已恢复到最近一次手动存档。")
            self._append_event(event)
            self._touch_and_persist()
            await self.events.publish(event)
            return self.snapshot()

    def time_label(self) -> str:
        return f"第{self.world.day}天 {self.world.minute // 60:02d}:{self.world.minute % 60:02d}"

    @staticmethod
    def _age_needs(npc: NPC) -> None:
        npc.state.needs.energy = max(0, npc.state.needs.energy - 7)
        npc.state.needs.hunger = min(100, npc.state.needs.hunger + 9)
        npc.state.needs.social = min(100, npc.state.needs.social + 6)

    def _apply_decision(self, npc: NPC) -> None:
        action = npc.state.action
        if action.type == "rest":
            npc.state.needs.energy = min(100, npc.state.needs.energy + 28)
            npc.state.mood = "松弛"
        elif action.type == "eat":
            npc.state.location = "greenhouse"
            npc.state.needs.hunger = max(0, npc.state.needs.hunger - 48)
            npc.state.mood = "满足"
        elif action.type == "chat":
            target = next((item for item in self.world.npcs if item.id == action.target), None)
            if target:
                npc.state.location = target.state.location
            npc.state.needs.social = max(0, npc.state.needs.social - 42)
            npc.state.mood = "有人作伴"
        elif action.type in {"work", "move", "observe"} and action.target in {item.id for item in self.world.locations}:
            npc.state.location = action.target or npc.state.location
            npc.state.mood = "专注"

    def _event(self, kind: str, text: str) -> WorldEvent:
        return WorldEvent(id=uuid4().hex[:10], at=self.time_label(), kind=kind, text=text)

    def _append_event(self, event: WorldEvent) -> None:
        self.world.recent_events = ([event] + self.world.recent_events)[:16]

    def _touch_and_persist(self) -> None:
        self.world.updated_at = datetime.now(timezone.utc).isoformat()
        self.store.save_current(self.world)
