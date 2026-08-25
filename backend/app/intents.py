from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .models import NPC, NPCIntent, WorldSnapshot


INTENT_CATALOG_PATH = Path(__file__).resolve().parent / "data" / "npc_intents.json"
COMMON_ACTIONS = {
    "eat": "在温室食堂吃饭",
    "rest": "在当前位置休息",
    "observe": "去水潭边观察",
}


@lru_cache(maxsize=1)
def load_intent_catalog() -> dict:
    with INTENT_CATALOG_PATH.open(encoding="utf-8") as handle:
        catalog = json.load(handle)
    verbs = catalog.get("verbs")
    if not isinstance(verbs, list) or not verbs:
        raise ValueError("npc_intents.json 缺少 verbs")
    return catalog


def available_actions(npc: NPC) -> dict[str, str]:
    actions = dict(COMMON_ACTIONS)
    actions.update({item.id: item.label for item in npc.profile.activities})
    return actions


def prompt_capabilities(npc: NPC, world: WorldSnapshot) -> dict:
    """给 LLM 的封闭能力表；ID 全部来自当前世界数据。"""

    return {
        "verbs": load_intent_catalog()["verbs"],
        "locations": [{"id": item.id, "name": item.name} for item in world.locations],
        "npcs": [
            {"id": item.id, "name": item.profile.name, "location": item.state.location}
            for item in world.npcs if item.id != npc.id
        ],
        "actions": [{"id": key, "label": value} for key, value in available_actions(npc).items()],
        "current": {
            "location": npc.state.location,
            "following_player": npc.state.following_player,
            "player_location": world.player.location,
        },
    }


def structurally_valid(intent: NPCIntent, npc: NPC, world: WorldSnapshot) -> bool:
    """按数据表验证 verb、参数名、参数类型与动态 ID；非法项静默丢弃。"""

    definitions = {item["verb"]: item for item in load_intent_catalog()["verbs"]}
    definition = definitions.get(intent.verb)
    if not definition:
        return False

    expected: dict[str, str] = definition.get("args", {})
    if set(intent.args) != set(expected):
        return False

    locations = {item.id for item in world.locations}
    npcs = {item.id for item in world.npcs}
    actions = set(available_actions(npc))
    for name, value_type in expected.items():
        value = intent.args.get(name, "").strip()
        if not value:
            return False
        if value_type == "location_id" and value not in locations:
            return False
        if value_type == "npc_id" and value not in npcs:
            return False
        if value_type == "action_id" and value not in actions:
            return False
        if value_type == "text" and len(value) > 200:
            return False
    return True
