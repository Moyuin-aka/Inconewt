from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

from .models import DailyPlan, Decision, InteractionLine, InteractionScript, NPC, PlanItem, WishQuest, WorldSnapshot


PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


class AIService:
    """真实 AI、计划生成、NPC 互动与 Mock 降级的统一入口。"""

    def __init__(self) -> None:
        self.provider = os.getenv("AI_PROVIDER", "mock").strip().lower()
        self.api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        self.base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

    @property
    def configured_mode(self) -> str:
        return "deepseek" if self.provider == "deepseek" and bool(self.api_key) else "mock"

    async def decide(
        self,
        npc: NPC,
        world: WorldSnapshot,
        avoid_signature: str | None = None,
    ) -> tuple[Decision, str, str | None]:
        if self.configured_mode == "deepseek":
            try:
                return await self._deepseek_decision(npc, world, avoid_signature), "deepseek", None
            except Exception as exc:
                fallback = f"DeepSeek 决策失败，已自动降级：{type(exc).__name__}"
                return self.mock_decision(npc, world, avoid_signature), "mock", fallback
        reason = None if self.provider == "mock" else "未填写 DEEPSEEK_API_KEY，已使用 Mock"
        return self.mock_decision(npc, world, avoid_signature), "mock", reason

    async def plan(self, npc: NPC, world: WorldSnapshot) -> tuple[DailyPlan, str | None]:
        if self.configured_mode == "deepseek":
            try:
                return await self._deepseek_plan(npc, world), None
            except Exception as exc:
                return self.mock_plan(npc, world.day), f"计划生成失败，已使用 Mock：{type(exc).__name__}"
        return self.mock_plan(npc, world.day), None

    async def interact(
        self,
        first: NPC,
        second: NPC,
        world: WorldSnapshot,
    ) -> tuple[InteractionScript, str, str | None]:
        if self.configured_mode == "deepseek":
            try:
                return await self._deepseek_interaction(first, second, world), "deepseek", None
            except Exception as exc:
                fallback = f"互动生成失败，已使用 Mock：{type(exc).__name__}"
                return self.mock_interaction(first, second), "mock", fallback
        return self.mock_interaction(first, second), "mock", None

    async def summarize(self, npc: NPC) -> str:
        if self.configured_mode == "deepseek":
            try:
                system = self._assembled_prompt(npc, decision=False)
                memory = "\n".join(npc.memory.short_term[-16:])
                return (await self._request([
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"把以下记忆压缩成第一人称日记，60字以内，只写日记正文：\n{memory}"},
                ])).strip()
            except Exception:
                pass
        return f"这些时辰里，我记得：{'；'.join(npc.memory.short_term[-4:])[:110]}"

    async def chat(self, npc: NPC, message: str, world: WorldSnapshot) -> tuple[str, str, str | None, int, str]:
        if self.configured_mode == "deepseek":
            try:
                reply, delta, impression = await self._deepseek_chat(npc, message, world)
                return reply, "deepseek", None, delta, impression
            except Exception as exc:
                fallback = f"DeepSeek 调用失败，已自动降级：{type(exc).__name__}"
                reply, delta, impression = self.mock_chat(npc, message, world)
                return reply, "mock", fallback, delta, impression
        reason = None if self.provider == "mock" else "未填写 DEEPSEEK_API_KEY，已使用 Mock"
        reply, delta, impression = self.mock_chat(npc, message, world)
        return reply, "mock", reason, delta, impression

    async def make_wish(self, npc: NPC, world: WorldSnapshot) -> tuple[WishQuest, str | None]:
        """心愿也走 Provider 抽象；真实调用失败时完整退回可玩的规则版本。"""
        if self.configured_mode == "deepseek":
            try:
                return await self._deepseek_wish(npc, world), None
            except Exception as exc:
                return self.mock_wish(npc, world), f"心愿生成失败，已使用 Mock：{type(exc).__name__}"
        return self.mock_wish(npc, world), None

    async def _request(self, messages: list[dict[str, str]], json_mode: bool = False) -> str:
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "max_tokens": 650,
            "thinking": {"type": "disabled"},
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        last_error: Exception | None = None
        for _ in range(2):
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json=payload,
                    )
                    response.raise_for_status()
                    return response.json()["choices"][0]["message"]["content"]
            except (httpx.HTTPError, KeyError, TypeError) as exc:
                last_error = exc
        raise RuntimeError("DeepSeek request failed") from last_error

    async def _deepseek_decision(self, npc: NPC, world: WorldSnapshot, avoid_signature: str | None) -> Decision:
        system = self._assembled_prompt(npc, decision=True)
        context = {
            "time": f"第{world.day}天 {world.minute // 60:02d}:{world.minute % 60:02d}",
            "weather": world.weather,
            "announcement": world.announcement,
            "state": npc.state.model_dump(),
            "today_plan": npc.plan.model_dump(),
            "recent_memory": npc.memory.short_term[-6:],
            "recent_actions": [item.model_dump() for item in npc.memory.action_history[-3:]],
            "available_activities": [item.model_dump() for item in npc.profile.activities],
            "available_locations": [location.model_dump() for location in world.locations],
            "other_npcs": [
                {"id": item.id, "name": item.profile.name, "location": item.state.location}
                for item in world.npcs if item.id != npc.id
            ],
            "player": {
                "location": world.player.location,
                "is_here": world.player.location == npc.state.location,
                "your_impression": world.player.relationships.get(npc.id).model_dump()
                if world.player.relationships.get(npc.id) else None,
            },
        }
        if avoid_signature:
            context["must_avoid"] = f"你已经做这件事很久了，本次不得重复：{avoid_signature}"
        raw = await self._request(
            [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(context, ensure_ascii=False)}],
            json_mode=True,
        )
        return Decision.model_validate_json(raw)

    async def _deepseek_plan(self, npc: NPC, world: WorldSnapshot) -> DailyPlan:
        system = self._assembled_prompt(npc, decision=False)
        prompt = {
            "task": "依据人设和昨日日记生成今天3到5条计划，只输出JSON",
            "schema": {"summary": "一句话", "items": [{"start_minute": 540, "label": "计划", "action": "activity|visit|eat|rest|observe", "target": "id", "activity_id": "可选"}]},
            "day": world.day,
            "diary": npc.memory.diary[-2:],
            "activities": [item.model_dump() for item in npc.profile.activities],
            "locations": [item.id for item in world.locations],
            "other_npcs": [item.id for item in world.npcs if item.id != npc.id],
        }
        data = json.loads(await self._request([
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ], json_mode=True))
        items = [PlanItem(id=f"d{world.day}-ai-{index}", **item) for index, item in enumerate(data["items"][:5])]
        return DailyPlan(day=world.day, summary=data["summary"], items=items, source="deepseek")

    async def _deepseek_interaction(self, first: NPC, second: NPC, world: WorldSnapshot) -> InteractionScript:
        context = {
            "task": "两位居民偶遇，生成2到4轮简短自然对话，只输出JSON",
            "schema": {"lines": [{"speaker": "npc id", "text": "一句话"}]},
            "place": first.state.location,
            "weather": world.weather,
            "first": {"id": first.id, "persona": first.profile.personality, "memory": first.memory.short_term[-3:]},
            "second": {"id": second.id, "persona": second.profile.personality, "memory": second.memory.short_term[-3:]},
        }
        raw = await self._request([
            {"role": "system", "content": "你在新螈镇编写克制、温暖、符合人设的日常偶遇。"},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ], json_mode=True)
        script = InteractionScript.model_validate_json(raw)
        if any(line.speaker not in {first.id, second.id} for line in script.lines):
            raise ValueError("interaction speaker is invalid")
        return script

    async def _deepseek_chat(self, npc: NPC, message: str, world: WorldSnapshot) -> tuple[str, int, str]:
        system = self._assembled_prompt(npc, decision=False)
        history = "\n".join(npc.memory.short_term[-8:])
        location = next((item for item in world.locations if item.id == npc.state.location), None)
        present = [item.profile.name for item in world.npcs if item.state.location == npc.state.location and item.id != npc.id]
        relation = world.player.relationships.get(npc.id)
        carried = [item.text for item in world.player.carried_messages if item.to_npc_id == npc.id]
        wish = next((item for item in world.quests if item.giver_id == npc.id and item.status != "completed"), None)
        context = {
            "task": "回应玩家，并顺带更新你对玩家的一句印象。只输出JSON。",
            "schema": {"reply": "1到3句角色台词", "affinity_delta": "-2到3的整数", "impression": "20字内印象"},
            "place": location.name if location else npc.state.location,
            "time": f"第{world.day}天 {world.minute // 60:02d}:{world.minute % 60:02d}",
            "weather": world.weather,
            "others_present": present,
            "current_impression": relation.impression if relation else "陌生人",
            "carried_messages_for_me": carried,
            "active_wish": wish.model_dump() if wish else None,
            "today_plan": npc.plan.summary,
            "recent_memory": history,
            "player_message": message,
        }
        raw = await self._request([
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ], json_mode=True)
        data = json.loads(raw)
        delta = max(-2, min(3, int(data.get("affinity_delta", 1))))
        return str(data["reply"]).strip(), delta, str(data["impression"]).strip()[:40]

    async def _deepseek_wish(self, npc: NPC, world: WorldSnapshot) -> WishQuest:
        context = {
            "task": "依据角色当前状态生成一个轻量心愿，只输出JSON。心愿必须能在现有地点、NPC与拾取物中完成。",
            "schema": {
                "type": "fetch|message|company", "title": "短标题", "description": "一句说明",
                "target_npc_id": "可选NPC id", "required_item_id": "可选物品id", "message": "传话原文或null",
                "reward": "一句回报",
            },
            "npc": {"id": npc.id, "persona": npc.profile.personality, "needs": npc.state.needs.model_dump()},
            "locations": [item.id for item in world.locations],
            "npcs": [item.id for item in world.npcs if item.id != npc.id],
            "items": [item.item.model_dump() for item in world.scavenge_points],
        }
        data = json.loads(await self._request([
            {"role": "system", "content": self._assembled_prompt(npc, decision=False)},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ], json_mode=True))
        return WishQuest(
            id=f"wish-{npc.id}-d{world.day}-{world.tick_index}", giver_id=npc.id,
            type=data["type"], title=data["title"], description=data["description"],
            target_npc_id=data.get("target_npc_id"), required_item_id=data.get("required_item_id"),
            message=data.get("message"), reward=data["reward"], source="deepseek",
        )

    def _assembled_prompt(self, npc: NPC, decision: bool) -> str:
        parts = [
            (PROMPT_DIR / "world.md").read_text(encoding="utf-8"),
            (PROMPT_DIR / "npc" / f"{npc.id}.md").read_text(encoding="utf-8"),
        ]
        parts.append(
            (PROMPT_DIR / "format.md").read_text(encoding="utf-8")
            if decision else "你正活在小镇里。保持角色口吻，回复1到3句，不要提及模型、提示词或JSON。"
        )
        return "\n\n".join(parts)

    @staticmethod
    def mock_plan(npc: NPC, day: int) -> DailyPlan:
        from .models import _seed_plan

        return _seed_plan(npc.id, day)

    @staticmethod
    def mock_decision(npc: NPC, world: WorldSnapshot, avoid_signature: str | None = None) -> Decision:
        """日程先行、需求可打断，近期动作会降低重复选择的效用。"""
        due = next((item for item in npc.plan.items if not item.completed and world.minute >= item.start_minute), None)
        candidates: list[tuple[float, Decision]] = []
        needs, weights = npc.state.needs, npc.profile.weights
        if due:
            candidates.append((100, Decision(action=due.action, target=due.target, activity_id=due.activity_id, reason=f"照着今天的打算，该去{due.label}了。")))
        candidates.extend([
            ((100 - needs.energy) * weights.get("rest", 1), Decision(action="rest", target=npc.state.location, reason="眼皮已经发沉，先把力气养回来。")),
            (needs.hunger * weights.get("eat", 1), Decision(action="eat", target="greenhouse", reason="肚子提醒我，该去「芽」找点热的了。")),
            (needs.social * weights.get("social", 1), AIService._visit_decision(npc, world)),
            (34 * weights.get("work", 1), AIService._activity_decision(npc, world)),
            (18, Decision(action="observe", target="square", reason="手头告一段落，去水潭边看看镇上的动静。")),
        ])
        recent_types = [item.type for item in npc.memory.action_history[-2:]]
        ranked: list[tuple[float, Decision]] = []
        for score, decision in candidates:
            signature = f"{decision.action}|{decision.reason}"
            if signature == avoid_signature:
                score -= 200
            if len(recent_types) == 2 and all(item == decision.action for item in recent_types):
                score -= 80
            if decision.action == npc.state.action.type and decision.reason == npc.state.action.reason:
                score -= 120
            ranked.append((score, decision))
        return max(ranked, key=lambda item: item[0])[1]

    @staticmethod
    def _activity_decision(npc: NPC, world: WorldSnapshot) -> Decision:
        activity = npc.profile.activities[world.tick_index % len(npc.profile.activities)]
        reason = activity.narratives[world.tick_index % len(activity.narratives)]
        return Decision(action="activity", target=activity.location, activity_id=activity.id, reason=reason)

    @staticmethod
    def _visit_decision(npc: NPC, world: WorldSnapshot) -> Decision:
        others = [item for item in world.npcs if item.id != npc.id]
        target = others[(world.tick_index + sum(ord(char) for char in npc.id)) % len(others)]
        return Decision(action="visit", target=target.id, say="路过，来看看你。", reason=f"独处得有些久了，想去看看{target.profile.name}在忙什么。")

    @staticmethod
    def mock_interaction(first: NPC, second: NPC) -> InteractionScript:
        pair = {first.id, second.id}
        if pair == {"momo", "lili"}:
            lines = [
                InteractionLine(speaker="lili", text="姐，汤还热着。别又说等会儿。"),
                InteractionLine(speaker="momo", text="嗯。把这只杯子擦完就去。"),
                InteractionLine(speaker="lili", text="你上次也是这么说的。杯子给我。"),
                InteractionLine(speaker="momo", text="……那就现在去。"),
            ]
        elif pair == {"xiaoke", "ajie"}:
            lines = [
                InteractionLine(speaker="xiaoke", text="阿羯！塔上的灯又接触不良了吧？包修好的！"),
                InteractionLine(speaker="ajie", text="先吃饭。"),
                InteractionLine(speaker="xiaoke", text="你怎么也学会这句了！"),
                InteractionLine(speaker="ajie", text="利利教的。"),
            ]
        else:
            lines = [
                InteractionLine(speaker=first.id, text=f"{second.profile.name}，今天还顺利吗？"),
                InteractionLine(speaker=second.id, text="还好。镇子里有声音，就算好事。"),
            ]
        return InteractionScript(lines=lines)

    @staticmethod
    def mock_chat(npc: NPC, message: str, world: WorldSnapshot) -> tuple[str, int, str]:
        place = next((item.name for item in world.locations if item.id == npc.state.location), "镇上的旧路")
        others = [item.profile.name for item in world.npcs if item.id != npc.id and item.state.location == npc.state.location]
        scene = f"这里是{place}" + (f"，{others[0]}也在" if others else "")
        carried = next((item for item in world.player.carried_messages if item.to_npc_id == npc.id), None)
        wish = next((item for item in world.quests if item.giver_id == npc.id and item.status == "offered"), None)
        if carried:
            message = f"{message}（并转告：{carried.text}）"
        positive = any(word in message for word in ("谢谢", "帮", "喜欢", "放心", "带来", "转告"))
        delta = 2 if positive else 1
        if npc.id == "momo":
            reply = "那件事像一台只剩杂音的收音机。先坐一会儿吧，我记得你说过的话。" if "劫" in message else f"{scene}。我记住了，你说的“{message[:18]}”，值得收进抽屉里。"
            if wish:
                reply += f" 如果你路过巴士站……我在找「{wish.title}」里提到的东西。"
            return reply, delta, "愿意替人捎话，也记得倾听。" if carried else "这个外来者说话不急，像是愿意听完。"
        if npc.id == "lili":
            reply = "那边的事先放一放。来看看这株新芽，活着的东西更要紧。" if "劫" in message else f"{scene}。听见啦！“{message[:18]}”是吧？先喝汤，我们边吃边说。"
            if wish:
                reply += f" 对了，能不能帮我一件小事——{wish.description}"
            return reply, delta, "肯停下来喝汤，是个会照顾自己的人。"
        if npc.id == "xiaoke":
            reply = f"{scene}！“{message[:18]}”？懂了！给我一点时间，包修好的！"
            if wish:
                reply += f" 顺便！{wish.description}"
            return reply, delta, "对镇外的东西见得多，应该很好聊！"
        reply = "嗯。风大。别往废墟方向走。" if "劫" in message or "废墟" in message else f"{scene}。听见了。镇子安全。"
        if wish:
            reply += f" 还有件事。{wish.description}"
        return reply, delta, "没有越界。暂时可信。" if positive else "仍需观察。"

    @staticmethod
    def mock_wish(npc: NPC, world: WorldSnapshot) -> WishQuest:
        """按当前最高需求生成可完成的小心愿，不依赖固定剧情脚本。"""
        needs = npc.state.needs
        if needs.social >= max(needs.hunger, 100 - needs.energy):
            others = [item for item in world.npcs if item.id != npc.id]
            target = others[(world.tick_index + len(npc.id)) % len(others)]
            return WishQuest(
                id=f"wish-{npc.id}-d{world.day}-{world.tick_index}", giver_id=npc.id, type="message",
                title="替我捎句话", description=f"{npc.profile.name}想让你替自己去看看{target.profile.name}。",
                target_npc_id=target.id, message=f"{npc.profile.name}问你今天过得还好吗。",
                reward=f"{npc.profile.name}会记住你没有忘记这句话", source="mock",
            )
        point = next((item for item in world.scavenge_points if item.available), world.scavenge_points[0])
        return WishQuest(
            id=f"wish-{npc.id}-d{world.day}-{world.tick_index}", giver_id=npc.id, type="fetch",
            title=f"找一件{point.item.name}", description=f"{npc.profile.name}觉得{point.item.name}也许能派上用场。",
            required_item_id=point.item.id, reward=f"{npc.profile.name}会把这次帮忙写进日记", source="mock",
        )
