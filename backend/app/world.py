from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from uuid import uuid4

from .ai import AIService
from .grounding import eligible_secrets, get_secret, memory_text_is_safe, unknown_subject
from .intents import structurally_valid
from .models import (
    ActionRecord,
    CarriedMessage,
    ChatResponse,
    Decision,
    GiftRequest,
    JournalSecret,
    NPC,
    NPCAction,
    NPCIntent,
    PlayerAppearanceRequest,
    PlayerMoveRequest,
    QueuedNPCIntent,
    Relationship,
    ScavengeRequest,
    WeatherWishRequest,
    WishQuest,
    WorldActionRequest,
    WorldEvent,
    WorldSnapshot,
    initial_world,
    upgrade_world,
)
from .store import DEFAULT_WORLD_ID, WorldStore


class EventBus:
    def __init__(self) -> None:
        self.subscribers: set[asyncio.Queue[str]] = set()

    async def publish(self, event: WorldEvent) -> None:
        for queue in list(self.subscribers):
            if not queue.full():
                queue.put_nowait(event.model_dump_json())

    async def stream(self, heartbeat=None):
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=50)
        self.subscribers.add(queue)
        last_mode: str | None = None
        try:
            while True:
                mode = heartbeat() if heartbeat else "interactive"
                if mode != last_mode:
                    yield f"event: session\ndata: {{\"access_mode\":\"{mode}\"}}\n\n"
                    last_mode = mode
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=20)
                    yield f"event: world\ndata: {payload}\n\n"
                except TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            self.subscribers.discard(queue)


class WorldEngine:
    """v2 世界循环：计划 → 决策 → 行动 → 互动 → 记忆/日记 → 次日计划。"""

    def __init__(self, store: WorldStore, ai: AIService, world_id: str = DEFAULT_WORLD_ID) -> None:
        self.store = store
        self.ai = ai
        self.world_id = world_id
        loaded = store.load_current(world_id)
        self.world = loaded or initial_world()
        if (
            self.world.schema_version < 3
            or len(self.world.npcs) < 4
            or any(not npc.plan.items for npc in self.world.npcs)
        ):
            self.world = upgrade_world(self.world)
        self.store.save_current(self.world, self.world_id)
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
                queued_intent = self._pop_next_intent(npc)
                intent_narrative: str | None = None
                intent_participants = [npc.id]
                if queued_intent:
                    decision, intent_narrative, intent_participants = self._decision_for_intent(npc, queued_intent)
                    source, fallback = queued_intent.source, None
                elif npc.state.following_player:
                    decision = Decision(
                        action="visit", target=self.world.player.location, say="我跟着。",
                        reason=npc.state.following_reason or "已经答应与外来者同行，先跟上脚步。",
                    )
                    source, fallback = npc.state.following_source, None
                else:
                    decision, source, fallback = await self.ai.decide(npc, self.world)
                signature = f"{decision.action}|{decision.reason}"
                if signature == avoid and not npc.state.following_player and not queued_intent:
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
                narrative = intent_narrative or self._narrative_for_action(npc)
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
                event = self._event("npc_intent" if queued_intent else "npc_action", narrative, intent_participants)
                self._append_event(event)
                await self.events.publish(event)

            await self._maybe_interaction()
            await self._maybe_player_greeting()
            await self._ensure_quest_pool()
            await self._summarize_full_memories()
            self._touch_and_persist()
            if self.world.tick_index % 10 == 0:
                self.store.create_save(self.world, slot=0, kind="auto", world_id=self.world_id)
            return self.snapshot()

    async def chat(self, npc_id: str, message: str) -> ChatResponse:
        async with self.lock:
            npc = self.get_npc(npc_id)
            if not self._player_near_npc(npc):
                raise PermissionError("要走近居民才能交谈")
            reply, source, fallback, affinity_delta, impression, proposed_intents, revealed_secret_id = await self.ai.chat(npc, message, self.world)
            relation = self.world.player.relationships.setdefault(npc.id, Relationship(affinity=0, impression="仍是陌生人。"))
            relation.affinity = max(-100, min(100, relation.affinity + affinity_delta))
            relation.impression = impression
            npc.state.needs.social = max(0, npc.state.needs.social - 18)
            npc.state.mood = "被理解"
            completed = self._complete_quest_from_chat(npc)
            accepted_intents = self._enqueue_intents(npc, proposed_intents, message, source)
            eligible_secret_ids = {item["id"] for item in eligible_secrets(npc, self.world)}
            if revealed_secret_id not in eligible_secret_ids:
                revealed_secret_id = None
            if revealed_secret_id:
                self._unlock_secret(revealed_secret_id, npc.profile.name)
            self._remember(npc, self._chat_memory(npc, message, accepted_intents, revealed_secret_id))
            event = self._event("chat", f"{self._period()}，你在{self._location_name(npc.state.location)}与{npc.profile.name}聊了一会儿。TA 对你的印象有了变化。", [npc.id])
            self._append_event(event)
            self._touch_and_persist()
            await self.events.publish(event)
            if completed:
                await self.events.publish(completed[1])
            return ChatResponse(
                reply=reply, source=source, fallback_reason=fallback,
                affinity_delta=affinity_delta, impression=impression,
                completed_quest_id=completed[0].id if completed else None,
                intents=accepted_intents,
                revealed_secret_id=revealed_secret_id,
            )

    async def move_player(self, request: PlayerMoveRequest) -> WorldSnapshot:
        async with self.lock:
            if request.location not in {item.id for item in self.world.locations}:
                raise KeyError(request.location)
            self.world.player.x = request.x
            self.world.player.y = request.y
            self.world.player.location = request.location
            for npc in [item for item in self.world.npcs if item.state.following_player]:
                if npc.state.location == request.location:
                    continue
                npc.state.location = request.location
                npc.state.action = NPCAction(
                    type="visit", target=request.location, say="等等我。",
                    reason=npc.state.following_reason or "答应了同行，正沿路跟着外来者。",
                    source=npc.state.following_source,
                )
                text = f"{self._period()}，{npc.profile.name}跟着你走向{self._location_name(request.location)}。"
                self._remember(npc, text)
                event = self._event("companion_follow", text, [npc.id])
                self._append_event(event)
                await self.events.publish(event)
            self._touch_and_persist()
            return self.snapshot()

    async def set_player_appearance(self, request: PlayerAppearanceRequest) -> WorldSnapshot:
        async with self.lock:
            self.world.player.appearance = request.appearance
            self._touch_and_persist()
            return self.snapshot()

    async def accept_quest(self, quest_id: str) -> WorldSnapshot:
        async with self.lock:
            quest = self._get_quest(quest_id)
            if quest.status == "completed":
                return self.snapshot()
            quest.status = "accepted"
            if quest.type == "message" and quest.target_npc_id and quest.message:
                if not any(item.quest_id == quest.id for item in self.world.player.carried_messages):
                    self.world.player.carried_messages.append(CarriedMessage(
                        id=f"message-{quest.id}", quest_id=quest.id, from_npc_id=quest.giver_id,
                        to_npc_id=quest.target_npc_id, text=quest.message,
                    ))
            giver = self.get_npc(quest.giver_id)
            text = f"{self._period()}，你答应帮{giver.profile.name}完成心愿「{quest.title}」。"
            event = self._event("quest_accepted", text, [quest.giver_id])
            self._append_event(event)
            self._touch_and_persist()
            await self.events.publish(event)
            return self.snapshot()

    async def scavenge(self, request: ScavengeRequest) -> WorldSnapshot:
        async with self.lock:
            point = next((item for item in self.world.scavenge_points if item.id == request.point_id), None)
            if not point:
                raise KeyError(request.point_id)
            if not point.available:
                raise ValueError("这里已经找过了")
            if self.world.player.location != point.location:
                raise PermissionError("要走到拾取点附近")
            if math.hypot(self.world.player.x - point.x, self.world.player.y - point.y) > 155:
                raise PermissionError("再靠近一点才能看清这里的东西")
            if len(self.world.player.pocket) >= 4:
                raise ValueError("口袋只有四格，已经装满了")
            self.world.player.pocket.append(point.item.model_copy(deep=True))
            point.available = False
            event = self._event("item_found", f"{self._period()}，你在{self._location_name(point.location)}找到「{point.item.name}」。")
            self._append_event(event)
            self._touch_and_persist()
            await self.events.publish(event)
            return self.snapshot()

    async def gift(self, request: GiftRequest) -> WorldSnapshot:
        async with self.lock:
            npc = self.get_npc(request.npc_id)
            if not self._player_near_npc(npc):
                raise PermissionError("要走近居民才能送出物品")
            index = next((i for i, item in enumerate(self.world.player.pocket) if item.id == request.item_id), None)
            if index is None:
                raise KeyError(request.item_id)
            quest = next((item for item in self.world.quests if item.status != "completed" and item.required_item_id == request.item_id), None)
            if quest:
                if quest.status == "offered":
                    raise ValueError(f"先在手记里记下心愿「{quest.title}」")
                if quest.giver_id != npc.id:
                    raise ValueError(f"这是要交给{self.get_npc(quest.giver_id).profile.name}的心愿物品")
                completed = self._complete_quest_from_chat(npc)
                if completed:
                    self._touch_and_persist()
                    await self.events.publish(completed[1])
                    return self.snapshot()
            item = self.world.player.pocket.pop(index)
            relation = self.world.player.relationships.setdefault(npc.id, Relationship(affinity=0, impression="仍是陌生人。"))
            relation.affinity = min(100, relation.affinity + 5)
            relation.impression = f"会把找到的{item.name}送给我。"
            self._remember(npc, f"外来者在{self._location_name(npc.state.location)}送给我：{item.name}。")
            event = self._event("player_gift", f"{self._period()}，你把「{item.name}」交到{npc.profile.name}手里。", [npc.id])
            self._append_event(event)
            self._touch_and_persist()
            await self.events.publish(event)
            return self.snapshot()

    async def post_board(self, text: str) -> WorldSnapshot:
        async with self.lock:
            if self.world.player.location != "square":
                raise PermissionError("要走到中央广场的公告板前")
            self.world.announcement = text
            reactions = {
                "momo": "莫莫读了两遍，像要把这句话收进某个抽屉。",
                "lili": "利利在旁边添了一句：看完也要记得吃饭。",
                "xiaoke": "小柯拿炭笔画了一个歪歪扭扭的齿轮当回应。",
                "ajie": "阿羯从塔上确认过公告板，只点了一下头。",
            }
            event = self._event("board_post", f"公告板换上了你的字：「{text}」")
            self._append_event(event)
            await self.events.publish(event)
            for npc in self.world.npcs:
                self._remember(npc, f"外来者在公告板写道：{text}。{reactions[npc.id]}")
                reaction = self._event("board_reaction", reactions[npc.id], [npc.id])
                self._append_event(reaction)
                await self.events.publish(reaction)
            self._touch_and_persist()
            return self.snapshot()

    async def wish_weather(self, request: WeatherWishRequest) -> WorldSnapshot:
        async with self.lock:
            if self.world.player.location != "square":
                raise PermissionError("要走到水潭边才能许愿")
            if self.world.tick_index < self.world.player.weather_cooldown_until:
                raise ValueError("水潭还没有平静下来")
            self.world.weather = request.weather
            self.world.player.weather_cooldown_until = self.world.tick_index + 4
            verb = "掷下一颗石子，愿日光回来" if request.weather == "晴" else "用指尖划过水面，唤来薄雾"
            event = self._event("weather_wish", f"{self._period()}，你在蝾螈水潭边{verb}。")
            self._append_event(event)
            self._touch_and_persist()
            await self.events.publish(event)
            return self.snapshot()

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

    def save(self, slot: int = 1) -> int:
        return self.store.create_save(self.world, slot=slot, kind="manual", world_id=self.world_id)

    async def load(self, slot: int = 1, kind: str = "manual") -> WorldSnapshot:
        async with self.lock:
            loaded = self.store.load_save(slot=slot, kind=kind, world_id=self.world_id)
            if not loaded:
                raise LookupError("还没有可恢复的存档")
            needs_upgrade = (
                loaded.schema_version < 3
                or len(loaded.npcs) < 4
                or any(not npc.plan.items for npc in loaded.npcs)
            )
            self.world = upgrade_world(loaded) if needs_upgrade else loaded
            event = self._event("load", "风景倒退了一小段，世界回到最近一次手动存档。")
            self._append_event(event)
            self._touch_and_persist()
            await self.events.publish(event)
            return self.snapshot()

    async def set_player_name(self, name: str) -> WorldSnapshot:
        async with self.lock:
            self.world.player.name = name.strip() or "外来者"
            self._touch_and_persist()
            self.store.mark_started(self.world_id)
            return self.snapshot()

    async def import_snapshot(self, payload: dict) -> WorldSnapshot:
        imported = WorldSnapshot.model_validate(payload)
        if imported.schema_version != 3:
            raise ValueError(f"存档版本 {imported.schema_version} 不兼容，当前需要版本 3")
        if len(imported.npcs) != 4 or len(imported.locations) != 7:
            raise ValueError("存档内容不完整，无法导入")
        async with self.lock:
            self.world = imported
            self.store.save_current(self.world, self.world_id)
            self.store.mark_started(self.world_id)
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
        memory = f"{self.time_label()}，{first.profile.name}与{second.profile.name}在{location}相遇并交谈。"
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

    async def _maybe_player_greeting(self) -> None:
        """高好感居民偶尔主动注意玩家；事件与气泡共用一句短台词。"""
        if self.world.tick_index % 3 != 0:
            return
        candidates = [
            npc for npc in self.world.npcs
            if npc.state.location == self.world.player.location
            and self.world.player.relationships.get(npc.id, Relationship(affinity=0, impression="")).affinity >= 35
        ]
        if not candidates:
            return
        npc = candidates[self.world.tick_index % len(candidates)]
        if any(event.kind == "npc_greeting" and npc.id in event.participants for event in self.world.recent_events[:6]):
            return
        greetings = {
            "momo": "又见面了。上次那句话，我还记得。",
            "lili": "来得正好！汤还温着呢。",
            "xiaoke": "嘿！要不要看我刚修好的小玩意？",
            "ajie": "回来了。路上没事吧。",
        }
        greeting = greetings[npc.id]
        npc.state.action.say = greeting
        event = self._event("npc_greeting", f"{npc.profile.name}看见你，主动招呼：“{greeting}”", [npc.id])
        self._append_event(event)
        await self.events.publish(event)

    async def _ensure_quest_pool(self) -> None:
        active = [quest for quest in self.world.quests if quest.status != "completed"]
        if len(active) >= 2:
            return
        active_givers = {quest.giver_id for quest in active}
        npc = next((item for item in self.world.npcs if item.id not in active_givers), self.world.npcs[0])
        quest, fallback = await self.ai.make_wish(npc, self.world)
        if any(item.id == quest.id for item in self.world.quests):
            return
        self.world.quests.append(quest)
        text = f"{npc.profile.name}心里多了一件小事：「{quest.title}」。"
        if fallback:
            text += "（已由 Mock 生成）"
        event = self._event("quest_offered", text, [npc.id])
        self._append_event(event)
        await self.events.publish(event)

    def _complete_quest_from_chat(self, npc: NPC) -> tuple[WishQuest, WorldEvent] | None:
        pocket_ids = {item.id for item in self.world.player.pocket}
        quest = next((item for item in self.world.quests if item.status == "accepted" and (
            (item.type == "message" and item.target_npc_id == npc.id and any(message.quest_id == item.id for message in self.world.player.carried_messages))
            or (item.type == "fetch" and item.giver_id == npc.id and item.required_item_id in pocket_ids)
            or (item.type == "company" and item.giver_id == npc.id)
        )), None)
        if not quest:
            return None
        quest.status = "completed"
        if quest.required_item_id:
            self.world.player.pocket = [item for item in self.world.player.pocket if item.id != quest.required_item_id]
        self.world.player.carried_messages = [item for item in self.world.player.carried_messages if item.quest_id != quest.id]
        giver = self.get_npc(quest.giver_id)
        relation = self.world.player.relationships.setdefault(giver.id, Relationship(affinity=0, impression="仍是陌生人。"))
        relation.affinity = min(100, relation.affinity + 10)
        relation.impression = f"答应的「{quest.title}」真的做到了。"
        diary_line = f"第{self.world.day}天：外来者完成了「{quest.title}」。{quest.reward}。"
        for participant_id in {quest.giver_id, quest.target_npc_id} - {None}:
            participant = self.get_npc(str(participant_id))
            if diary_line not in participant.memory.diary:
                participant.memory.diary = (participant.memory.diary + [diary_line])[-12:]
        if quest.secret_id:
            self._unlock_secret(quest.secret_id, giver.profile.name)
        event = self._event(
            "quest_completed",
            f"心愿完成：「{quest.title}」。{giver.profile.name}对你的信任增加了。",
            [quest.giver_id] + ([quest.target_npc_id] if quest.target_npc_id else []),
        )
        self._append_event(event)
        return quest, event

    def _unlock_secret(self, secret_id: str, source: str) -> None:
        if any(item.id == secret_id for item in self.world.player.journal):
            return
        secret = get_secret(secret_id)
        if not secret:
            return
        self.world.player.journal.append(JournalSecret(
            id=secret_id, title=secret["title"], text=secret["text"], source=source, unlocked_at=self.time_label(),
        ))

    def _get_quest(self, quest_id: str) -> WishQuest:
        quest = next((item for item in self.world.quests if item.id == quest_id), None)
        if not quest:
            raise KeyError(quest_id)
        return quest

    def _player_near_npc(self, npc: NPC) -> bool:
        if self.world.player.location != npc.state.location:
            return False
        location = next((item for item in self.world.locations if item.id == npc.state.location), None)
        if not location:
            return False
        return math.hypot(self.world.player.x - location.x, self.world.player.y - (location.y + 55)) <= 185

    async def _summarize_full_memories(self) -> None:
        for npc in self.world.npcs:
            if len(npc.memory.short_term) < 20:
                continue
            diary = await self.ai.summarize(npc)
            if not memory_text_is_safe(diary, self.world):
                diary = f"这些时辰里，我只记下确实发生的事：{'；'.join(npc.memory.short_term[-3:])[:90]}"
            if diary not in npc.memory.diary:
                npc.memory.diary = (npc.memory.diary + [f"第{self.world.day}天：{diary}"])[-12:]
            npc.memory.short_term = npc.memory.short_term[-8:]

    @staticmethod
    def _remember(npc: NPC, text: str) -> None:
        normalized = text.strip()
        if normalized and normalized not in npc.memory.short_term:
            npc.memory.short_term = (npc.memory.short_term + [normalized])[-20:]

    def _chat_memory(
        self,
        npc: NPC,
        message: str,
        intents: list[NPCIntent],
        revealed_secret_id: str | None,
    ) -> str:
        """对话只落结构化事实，不把玩家假设或模型台词原样滚入记忆。"""

        prefix = f"{self.time_label()}，外来者在{self._location_name(npc.state.location)}与我交谈。"
        if unknown_subject(message, self.world):
            return prefix + "TA 问起一件事实卡里没有记录的事，我明确说不知道，没有把它当成事实。"
        secret = get_secret(revealed_secret_id or "")
        if secret:
            return prefix + f"我按已满足的信任条件讲出了手记「{secret['title']}」。"
        if intents:
            verbs = "、".join(intent.verb for intent in intents)
            return prefix + f"我接受了可执行的约定，已记录为行动队列：{verbs}。"
        return prefix + "我们聊了此刻的近况；没有把问句或猜测记作已发生的事。"

    @staticmethod
    def _increase_affinity(first: NPC, second: NPC) -> None:
        first_relation = first.relationships.setdefault(second.id, Relationship(affinity=20, impression="最近在镇上碰见过。"))
        second_relation = second.relationships.setdefault(first.id, Relationship(affinity=20, impression="最近在镇上碰见过。"))
        first_relation.affinity = min(100, first_relation.affinity + 1)
        second_relation.affinity = min(100, second_relation.affinity + 1)

    def _enqueue_intents(
        self,
        npc: NPC,
        proposed: list[NPCIntent],
        player_message: str,
        source: str,
    ) -> list[NPCIntent]:
        """只把白名单内且此刻可行的意图入队；非法项按协议静默忽略。"""

        accepted: list[NPCIntent] = []
        for intent in proposed:
            if len(accepted) >= 4 or len(npc.state.intent_queue) >= 8:
                break
            if not structurally_valid(intent, npc, self.world) or not self._intent_is_feasible(npc, intent):
                continue
            queued = QueuedNPCIntent(
                **intent.model_dump(),
                player_message=player_message,
                source=source,
                enqueued_tick=self.world.tick_index,
            )
            npc.state.intent_queue.append(queued)
            accepted.append(intent.model_copy(deep=True))
        return accepted

    def _intent_is_feasible(self, npc: NPC, intent: NPCIntent) -> bool:
        if intent.verb == "none":
            return False
        pending_verbs = {item.verb for item in npc.state.intent_queue}
        if intent.verb == "follow_player":
            return not npc.state.following_player and "follow_player" not in pending_verbs
        if intent.verb == "stop_following":
            return npc.state.following_player or "follow_player" in pending_verbs
        if intent.verb == "goto":
            return intent.args["location"] != npc.state.location
        if intent.verb in {"visit", "relay"}:
            if intent.args["npc"] == npc.id:
                return False
            hour = self.world.minute // 60
            is_sleeping_at_night = npc.state.action.type == "rest" and (hour >= 22 or hour < 5)
            return not is_sleeping_at_night
        return intent.verb == "do"

    def _pop_next_intent(self, npc: NPC) -> QueuedNPCIntent | None:
        while npc.state.intent_queue:
            intent = npc.state.intent_queue.pop(0)
            if structurally_valid(intent, npc, self.world) and self._intent_is_feasible(npc, intent):
                return intent
        return None

    def _decision_for_intent(
        self,
        npc: NPC,
        intent: QueuedNPCIntent,
    ) -> tuple[Decision, str, list[str]]:
        quote = intent.player_message.strip().replace("\n", " ")[:42]
        because = intent.because.strip()[:48]
        reason = f"因为你刚才说“{quote}”，{because or '我愿意照这个约定行动。'}"[:120]
        participants = [npc.id]

        if intent.verb == "follow_player":
            npc.state.following_player = True
            npc.state.following_source = intent.source
            npc.state.following_reason = reason
            decision = Decision(action="visit", target=self.world.player.location, say="我跟上。", reason=reason)
            narrative = f"{self._period()}，{npc.profile.name}答应你的邀请，开始与你同行。"
        elif intent.verb == "stop_following":
            npc.state.following_player = False
            npc.state.following_reason = ""
            decision = Decision(action="idle", say="我就在这里。", reason=reason)
            narrative = f"{self._period()}，{npc.profile.name}听懂你的意思，在{self._location_name(npc.state.location)}停下脚步。"
        elif intent.verb == "goto":
            location_id = intent.args["location"]
            decision = Decision(action="move", target=location_id, say="我这就去。", reason=reason)
            narrative = f"{self._period()}，{npc.profile.name}因为你的话，动身去{self._location_name(location_id)}。"
        elif intent.verb == "do":
            action_id = intent.args["action"]
            activity = next((item for item in npc.profile.activities if item.id == action_id), None)
            if activity:
                decision = Decision(
                    action="activity", target=activity.location, activity_id=activity.id,
                    say="我来处理。", reason=reason,
                )
                narrative = f"{self._period()}，{npc.profile.name}应你的请求，开始{activity.label}。"
            else:
                common = {
                    "eat": ("eat", "greenhouse", "去温室食堂吃点东西"),
                    "rest": ("rest", npc.state.location, "停下来休息"),
                    "observe": ("observe", "square", "去水潭边看看"),
                }
                action_type, target, label = common[action_id]
                decision = Decision(action=action_type, target=target, say="好。", reason=reason)
                narrative = f"{self._period()}，{npc.profile.name}应你的请求，{label}。"
        else:
            target = self.get_npc(intent.args["npc"])
            decision = Decision(
                action="visit", target=target.id,
                say="我替你捎过去。" if intent.verb == "relay" else "我去看看。",
                reason=reason,
            )
            participants.append(target.id)
            if intent.verb == "relay":
                relayed = intent.args["text"]
                fact = (
                    f"{self.time_label()}，{npc.profile.name}在{self._location_name(target.state.location)}"
                    f"替外来者转告{target.profile.name}：“{relayed}”"
                )
                self._remember(target, fact)
                narrative = f"{self._period()}，{npc.profile.name}去找{target.profile.name}，替你转告：“{relayed}”"
            else:
                narrative = f"{self._period()}，{npc.profile.name}因为你的话，去找{target.profile.name}。"

        return decision, narrative, participants

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
        self.store.save_current(self.world, self.world_id)
