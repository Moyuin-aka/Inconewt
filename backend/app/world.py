from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from .ai import AIService
from .models import (
    ActionRecord,
    ChatResponse,
    NPC,
    NPCAction,
    Relationship,
    WorldActionRequest,
    WorldEvent,
    WorldSnapshot,
    initial_world,
    upgrade_world,
)
from .store import WorldStore


class EventBus:
    def __init__(self) -> None:
        self.subscribers: set[asyncio.Queue[str]] = set()

    async def publish(self, event: WorldEvent) -> None:
        for queue in list(self.subscribers):
            if not queue.full():
                queue.put_nowait(event.model_dump_json())

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
    """v2 世界循环：计划 → 决策 → 行动 → 互动 → 记忆/日记 → 次日计划。"""

    def __init__(self, store: WorldStore, ai: AIService) -> None:
        self.store = store
        self.ai = ai
        loaded = store.load_current()
        self.world = loaded or initial_world()
        if (
            self.world.schema_version < 2
            or len(self.world.npcs) < 4
            or any(not npc.plan.items for npc in self.world.npcs)
        ):
            self.world = upgrade_world(self.world)
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
            previous_day = self.world.day
            self.world.tick_index += 1
            self.world.minute += 60
            if self.world.minute >= 24 * 60:
                self.world.day += 1
                self.world.minute %= 24 * 60
            if self.world.day != previous_day:
                await self._start_new_day()

            for npc in self.world.npcs:
                self._age_needs(npc)
                previous = npc.memory.action_history[-1] if npc.memory.action_history else None
                avoid = f"{previous.type}|{previous.reason}" if previous else None
                decision, source, fallback = await self.ai.decide(npc, self.world)
                signature = f"{decision.action}|{decision.reason}"
                if signature == avoid:
                    decision, source, retry_fallback = await self.ai.decide(npc, self.world, avoid)
                    fallback = retry_fallback or fallback

                npc.state.action = NPCAction(
                    type=decision.action,
                    target=decision.target,
                    activity_id=decision.activity_id,
                    say=decision.say,
                    reason=decision.reason,
                    source=source,
                )
                self._apply_decision(npc)
                self._complete_plan_item(npc)
                narrative = self._narrative_for_action(npc)
                if fallback:
                    narrative += f"（{fallback}）"
                self._remember(npc, narrative)
                npc.memory.action_history = (npc.memory.action_history + [ActionRecord(
                    day=self.world.day,
                    minute=self.world.minute,
                    type=decision.action,
                    target=decision.target,
                    activity_id=decision.activity_id,
                    reason=decision.reason,
                )])[-12:]
                event = self._event("npc_action", narrative, [npc.id])
                self._append_event(event)
                await self.events.publish(event)

            await self._maybe_interaction()
            await self._summarize_full_memories()
            self._touch_and_persist()
            return self.snapshot()

    async def chat(self, npc_id: str, message: str) -> ChatResponse:
        async with self.lock:
            npc = self.get_npc(npc_id)
            reply, source, fallback = await self.ai.chat(npc, message, self.world)
            self._remember(npc, f"玩家说：{message}")
            self._remember(npc, f"{npc.profile.name}回答：{reply}")
            npc.state.needs.social = max(0, npc.state.needs.social - 18)
            npc.state.mood = "被理解"
            event = self._event("chat", f"{self._period()}，你在{self._location_name(npc.state.location)}与{npc.profile.name}聊了一会儿。", [npc.id])
            self._append_event(event)
            self._touch_and_persist()
            await self.events.publish(event)
            return ChatResponse(reply=reply, source=source, fallback_reason=fallback)

    async def apply_world_action(self, request: WorldActionRequest) -> WorldSnapshot:
        async with self.lock:
            if request.action == "weather":
                self.world.weather = request.value
                text = f"{self._period()}，一阵风穿过屋脊，天气渐渐变成「{request.value}」。"
            elif request.action == "announcement":
                self.world.announcement = request.value
                text = f"广场公告板发出轻响：{request.value}"
            else:
                npc = self.get_npc(request.npc_id or "")
                self._remember(npc, f"玩家送来：{request.value}")
                npc.state.mood = "被惦记着"
                text = f"{self._period()}，一份「{request.value}」被送到{npc.profile.name}手里。"
            event = self._event("world_action", text, [request.npc_id] if request.npc_id else [])
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
            needs_upgrade = (
                loaded.schema_version < 2
                or len(loaded.npcs) < 4
                or any(not npc.plan.items for npc in loaded.npcs)
            )
            self.world = upgrade_world(loaded) if needs_upgrade else loaded
            event = self._event("load", "风景倒退了一小段，世界回到最近一次手动存档。")
            self._append_event(event)
            self._touch_and_persist()
            await self.events.publish(event)
            return self.snapshot()

    async def _start_new_day(self) -> None:
        for npc in self.world.npcs:
            plan, fallback = await self.ai.plan(npc, self.world)
            npc.plan = plan
            text = f"第{self.world.day}天，{npc.profile.name}为自己定下日程：{plan.summary}"
            if fallback:
                text += f"（{fallback}）"
            self._remember(npc, text)
        event = self._event("new_day", f"第{self.world.day}天的晨光落在新螈镇，四个人各自有了新的打算。")
        self._append_event(event)
        await self.events.publish(event)

    async def _maybe_interaction(self) -> None:
        groups: dict[str, list[NPC]] = {}
        for npc in self.world.npcs:
            groups.setdefault(npc.state.location, []).append(npc)
        candidates = [group[:2] for group in groups.values() if len(group) >= 2]
        if not candidates:
            return
        pair = next((items for items in candidates if any(npc.state.action.type in {"visit", "chat"} for npc in items)), None)
        if pair is None and self.world.tick_index % 4 != 0:
            return
        first, second = pair or candidates[0]
        recent_pair = {first.id, second.id}
        if any(event.kind == "npc_interaction" and set(event.participants) == recent_pair for event in self.world.recent_events[:4]):
            return

        script, source, fallback = await self.ai.interact(first, second, self.world)
        transcript_parts: list[str] = []
        for line in script.lines:
            speaker = self.get_npc(line.speaker)
            transcript_parts.append(f"{speaker.profile.name}：“{line.text}”")
        transcript = "  ".join(transcript_parts)
        location = self._location_name(first.state.location)
        memory = f"{self.time_label()}在{location}偶遇：{transcript}"
        self._remember(first, memory)
        self._remember(second, memory)
        self._increase_affinity(first, second)
        first.state.mood = second.state.mood = "有人作伴"
        text = f"{self._period()}，{first.profile.name}与{second.profile.name}在{location}碰见了。{transcript}"
        if fallback:
            text += "（本次互动由 Mock 接力）"
        event = self._event("npc_interaction", text, [first.id, second.id])
        self._append_event(event)
        await self.events.publish(event)

    async def _summarize_full_memories(self) -> None:
        for npc in self.world.npcs:
            if len(npc.memory.short_term) < 20:
                continue
            diary = await self.ai.summarize(npc)
            if diary not in npc.memory.diary:
                npc.memory.diary = (npc.memory.diary + [f"第{self.world.day}天：{diary}"])[-12:]
            npc.memory.short_term = npc.memory.short_term[-8:]

    @staticmethod
    def _remember(npc: NPC, text: str) -> None:
        normalized = text.strip()
        if normalized and normalized not in npc.memory.short_term:
            npc.memory.short_term = (npc.memory.short_term + [normalized])[-20:]

    @staticmethod
    def _increase_affinity(first: NPC, second: NPC) -> None:
        first_relation = first.relationships.setdefault(second.id, Relationship(affinity=20, impression="最近在镇上碰见过。"))
        second_relation = second.relationships.setdefault(first.id, Relationship(affinity=20, impression="最近在镇上碰见过。"))
        first_relation.affinity = min(100, first_relation.affinity + 1)
        second_relation.affinity = min(100, second_relation.affinity + 1)

    def _complete_plan_item(self, npc: NPC) -> None:
        action = npc.state.action
        item = next((plan for plan in npc.plan.items if not plan.completed and self.world.minute >= plan.start_minute), None)
        if not item:
            return
        same_action = item.action == action.type
        same_activity = not item.activity_id or item.activity_id == action.activity_id
        if same_action and same_activity:
            item.completed = True

    @staticmethod
    def _age_needs(npc: NPC) -> None:
        npc.state.needs.energy = max(0, npc.state.needs.energy - 7)
        npc.state.needs.hunger = min(100, npc.state.needs.hunger + 9)
        npc.state.needs.social = min(100, npc.state.needs.social + 6)

    def _apply_decision(self, npc: NPC) -> None:
        action = npc.state.action
        location_ids = {item.id for item in self.world.locations}
        if action.type == "rest":
            npc.state.needs.energy = min(100, npc.state.needs.energy + 28)
            npc.state.mood = "松弛"
        elif action.type == "eat":
            npc.state.location = "greenhouse"
            npc.state.needs.hunger = max(0, npc.state.needs.hunger - 48)
            npc.state.mood = "满足"
        elif action.type in {"chat", "visit"}:
            target = next((item for item in self.world.npcs if item.id == action.target), None)
            if target:
                npc.state.location = target.state.location
            elif action.target in location_ids:
                npc.state.location = action.target or npc.state.location
            npc.state.needs.social = max(0, npc.state.needs.social - 30)
            npc.state.mood = "期待相遇"
        elif action.type in {"work", "move", "observe", "activity"} and action.target in location_ids:
            npc.state.location = action.target or npc.state.location
            npc.state.mood = "专注"

    def _narrative_for_action(self, npc: NPC) -> str:
        action, period = npc.state.action, self._period()
        if action.type == "activity" and action.activity_id:
            activity = next((item for item in npc.profile.activities if item.id == action.activity_id), None)
            if activity:
                index = self.world.tick_index % len(activity.narratives)
                return f"{period}，{activity.narratives[index]}"
        if action.type == "visit":
            target = next((item for item in self.world.npcs if item.id == action.target), None)
            if target:
                return f"{period}，{npc.profile.name}离开{self._location_name(npc.profile.home)}，去{self._location_name(target.state.location)}看看{target.profile.name}。"
        templates = {
            "rest": f"{period}，{npc.profile.name}在{self._location_name(npc.state.location)}停下手里的事，安静地歇了一会儿。",
            "eat": f"{period}，{npc.profile.name}循着热汤的香气走进温室食堂「芽」。",
            "observe": f"{period}，{npc.profile.name}走到水潭边，看了一会儿石缝里的蝾螈。",
            "chat": f"{period}，{npc.profile.name}忽然想找个人说两句话。",
            "work": f"{period}，{npc.profile.name}重新埋头做起熟悉的工作。",
            "idle": f"{period}，{npc.profile.name}让思绪随着风停了一小会儿。",
            "move": f"{period}，{npc.profile.name}沿着镇上的旧路走向别处。",
        }
        return templates.get(action.type, f"{period}，{npc.profile.name}继续过着自己的日常。")

    def time_label(self) -> str:
        return f"第{self.world.day}天 {self.world.minute // 60:02d}:{self.world.minute % 60:02d}"

    def _period(self) -> str:
        hour = self.world.minute // 60
        if 5 <= hour < 9:
            return "清晨"
        if 9 <= hour < 12:
            return "上午"
        if 12 <= hour < 14:
            return "正午"
        if 14 <= hour < 18:
            return "午后"
        if 18 <= hour < 20:
            return "黄昏"
        return "夜里"

    def _location_name(self, location_id: str) -> str:
        location = next((item for item in self.world.locations if item.id == location_id), None)
        return location.name if location else "镇上的旧路"

    def _event(self, kind: str, text: str, participants: list[str] | None = None) -> WorldEvent:
        return WorldEvent(id=uuid4().hex[:10], at=self.time_label(), kind=kind, text=text, participants=participants or [])

    def _append_event(self, event: WorldEvent) -> None:
        self.world.recent_events = ([event] + self.world.recent_events)[:24]

    def _touch_and_persist(self) -> None:
        self.world.updated_at = datetime.now(timezone.utc).isoformat()
        self.store.save_current(self.world)
