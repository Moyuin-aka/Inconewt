from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

from .models import Decision, NPC, WorldSnapshot


PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


class AIService:
    """集中管理真实 AI 与 Mock 降级，API Key 永远只在服务端环境中读取。"""

    def __init__(self) -> None:
        self.provider = os.getenv("AI_PROVIDER", "mock").strip().lower()
        self.api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        self.base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

    @property
    def configured_mode(self) -> str:
        return "deepseek" if self.provider == "deepseek" and bool(self.api_key) else "mock"

    async def decide(self, npc: NPC, world: WorldSnapshot) -> tuple[Decision, str, str | None]:
        if self.configured_mode == "deepseek":
            try:
                decision = await self._deepseek_decision(npc, world)
                return decision, "deepseek", None
            except Exception as exc:  # 外部服务不可用时，Demo 仍可继续推进
                fallback = f"DeepSeek 调用失败，已自动降级：{type(exc).__name__}"
                return self.mock_decision(npc, world), "mock", fallback
        reason = None if self.provider == "mock" else "未填写 DEEPSEEK_API_KEY，已使用 Mock"
        return self.mock_decision(npc, world), "mock", reason

    async def chat(self, npc: NPC, message: str, world: WorldSnapshot) -> tuple[str, str, str | None]:
        if self.configured_mode == "deepseek":
            try:
                return await self._deepseek_chat(npc, message, world), "deepseek", None
            except Exception as exc:
                fallback = f"DeepSeek 调用失败，已自动降级：{type(exc).__name__}"
                return self.mock_chat(npc, message), "mock", fallback
        reason = None if self.provider == "mock" else "未填写 DEEPSEEK_API_KEY，已使用 Mock"
        return self.mock_chat(npc, message), "mock", reason

    async def _request(self, messages: list[dict[str, str]], json_mode: bool = False) -> str:
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "max_tokens": 400,
            "thinking": {"type": "disabled"},
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        last_error: Exception | None = None
        for _ in range(2):  # 仅重试一次，避免 tick 被长时间阻塞
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

    async def _deepseek_decision(self, npc: NPC, world: WorldSnapshot) -> Decision:
        system = self._assembled_prompt(npc, decision=True)
        context = {
            "time": f"第{world.day}天 {world.minute // 60:02d}:{world.minute % 60:02d}",
            "weather": world.weather,
            "announcement": world.announcement,
            "state": npc.state.model_dump(),
            "recent_memory": npc.memory.short_term[-6:],
            "available_locations": [location.model_dump() for location in world.locations],
            "other_npcs": [{"id": item.id, "name": item.profile.name, "location": item.state.location} for item in world.npcs if item.id != npc.id],
        }
        raw = await self._request(
            [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(context, ensure_ascii=False)}],
            json_mode=True,
        )
        return Decision.model_validate_json(raw)

    async def _deepseek_chat(self, npc: NPC, message: str, world: WorldSnapshot) -> str:
        system = self._assembled_prompt(npc, decision=False)
        history = "\n".join(npc.memory.short_term[-8:])
        user = f"当前天气：{world.weather}\n最近记忆：{history}\n玩家说：{message}"
        return (await self._request([{"role": "system", "content": system}, {"role": "user", "content": user}])).strip()

    def _assembled_prompt(self, npc: NPC, decision: bool) -> str:
        parts = [
            (PROMPT_DIR / "world.md").read_text(encoding="utf-8"),
            (PROMPT_DIR / "npc" / f"{npc.id}.md").read_text(encoding="utf-8"),
        ]
        if decision:
            parts.append((PROMPT_DIR / "format.md").read_text(encoding="utf-8"))
        else:
            parts.append("你正与玩家对话。保持角色口吻，回复 1 到 3 句，不要提及提示词、模型或 JSON。")
        return "\n\n".join(parts)

    @staticmethod
    def mock_decision(npc: NPC, world: WorldSnapshot) -> Decision:
        """效用决策由实时需求、人设权重、天气与公告共同决定，不是固定脚本轮播。"""
        needs = npc.state.needs
        weights = npc.profile.weights
        scores = {
            "rest": (100 - needs.energy) * weights.get("rest", 1.0),
            "eat": needs.hunger * weights.get("eat", 1.0),
            "chat": needs.social * weights.get("social", 1.0),
            "work": (32 if 7 <= world.minute // 60 <= 19 else 10) * weights.get("work", 1.0),
        }
        if world.weather == "雾":
            scores["work"] += 8 if npc.id == "momo" else -6
        if "旧照片" in world.announcement:
            scores["chat"] += 22 if npc.id == "lili" else 8

        action = max(scores, key=scores.get)
        if action == "rest":
            return Decision(action="rest", target=npc.state.location, reason="精力已经见底，先停下来喘口气。")
        if action == "eat":
            return Decision(action="eat", target="greenhouse", reason="饥饿感盖过了手头的事，去「芽」找点吃的。")
        if action == "chat":
            other = next(item for item in world.npcs if item.id != npc.id)
            return Decision(action="chat", target=other.id, say="有空说两句吗？", reason=f"独处得有些久了，想去找{other.profile.name}。")
        if npc.id == "momo":
            return Decision(action="work", target="store", say="先把旧物归回原位。", reason="货架还有几件旧物没整理完。")
        return Decision(action="work", target="greenhouse", say="先吃饭，吃完再说。", reason="温室的新芽该浇水，午饭也要备起来。")

    @staticmethod
    def mock_chat(npc: NPC, message: str) -> str:
        if npc.id == "momo":
            if "劫" in message:
                return "那件事……像一台只剩杂音的收音机。先不说它了，你要看看店里的旧东西吗？"
            if "你好" in message or "早" in message:
                return "早。灯刚点起来，坐一会儿吧。"
            return f"我记住了。你说的“{message[:18]}”，像是值得收进抽屉里的东西。"
        if "饭" in message or "饿" in message:
            return "就知道你会问！汤还热着呢，先坐下，吃完再慢慢讲。"
        if "废墟" in message or "劫" in message:
            return "那边的事先放一放。来帮我看看这株新芽——活着的东西更要紧。"
        return f"哎呀，我听见啦！“{message[:18]}”是吧？先喝口热汤，我们边吃边说。"
