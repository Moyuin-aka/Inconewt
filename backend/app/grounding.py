from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from .models import NPC, WorldSnapshot


CANON_PATH = Path(__file__).resolve().parent / "data" / "canon.json"


@lru_cache(maxsize=1)
def load_canon() -> dict:
    with CANON_PATH.open(encoding="utf-8") as handle:
        canon = json.load(handle)
    if not isinstance(canon.get("secrets"), list):
        raise ValueError("canon.json 缺少 secrets")
    return canon


def get_secret(secret_id: str) -> dict | None:
    return next((item for item in load_canon()["secrets"] if item["id"] == secret_id), None)


def eligible_secrets(npc: NPC, world: WorldSnapshot) -> list[dict]:
    relation = world.player.relationships.get(npc.id)
    affinity = relation.affinity if relation else 0
    return [
        item for item in load_canon()["secrets"]
        if npc.id in item["known_by"] and affinity >= item["min_affinity"]
    ]


def build_fact_card(world: WorldSnapshot, npc: NPC) -> dict:
    """由当前快照拼装唯一事实卡，不让模型补写世界实体。"""

    present_by_location = {
        location.id: [
            resident.profile.name for resident in world.npcs
            if resident.state.location == location.id
        ] + ([world.player.name] if world.player.location == location.id else [])
        for location in world.locations
    }
    relation = world.player.relationships.get(npc.id)
    secrets = []
    eligible_ids = {item["id"] for item in eligible_secrets(npc, world)}
    for secret in load_canon()["secrets"]:
        if npc.id not in secret["known_by"]:
            continue
        may_reveal = secret["id"] in eligible_ids
        secrets.append({
            "id": secret["id"],
            "title": secret["title"],
            "may_reveal": may_reveal,
            "canon_text": secret["text"] if may_reveal else None,
            "when_locked": None if may_reveal else secret["avoidance"],
        })
    return {
        "hard_rules": [
            "镇上居民只有莫莫、小柯、阿羯、利利四人，另有一位外来者玩家。",
            "只能把本事实卡、结构化记忆与 canon_text 中的内容当作事实。",
            "镇上没有其他居民、店铺、组织；被问到未列出的实体时必须承认不知道或明确回避。",
            "不得把玩家的提问、假设、传闻自动视为已经发生的事件。",
            "秘闻只能通过 reveal_secret_id 请求揭示；不得自行改写、补全或推测秘密正文。",
        ],
        "now": {
            "day": world.day,
            "minute": world.minute,
            "weather": world.weather,
            "announcement": world.announcement,
        },
        "residents": [
            {
                "id": item.id,
                "name": item.profile.name,
                "role": item.profile.role,
                "location": item.state.location,
                "action": item.state.action.type,
            }
            for item in world.npcs
        ],
        "locations": [
            {
                "id": item.id,
                "name": item.name,
                "description": item.description,
                "present": present_by_location[item.id],
            }
            for item in world.locations
        ],
        "player": {
            "name": world.player.name,
            "location": world.player.location,
            "pocket": [item.model_dump() for item in world.player.pocket],
            "relationship": relation.model_dump() if relation else None,
        },
        "active_quests": [
            item.model_dump() for item in world.quests if item.status != "completed"
        ],
        "recent_true_events": [
            {
                "id": item.id,
                "at": item.at,
                "kind": item.kind,
                "participants": item.participants,
                "text": None if item.kind == "npc_interaction" else item.text,
                "note": "确实发生过相遇；具体台词只作演出，不扩展事实" if item.kind == "npc_interaction" else None,
            }
            for item in world.recent_events[:5]
        ],
        "secrets_you_know": secrets,
    }


def known_terms(world: WorldSnapshot) -> set[str]:
    terms = {
        "新螈镇", "小镇", "劫", "外来者", "蝾螈", "公告板", "水潭", "日记", "计划",
        "拾光", "芽", "废墟", "塔灯", "收音机", "热汤", "水泵",
    }
    for npc in world.npcs:
        terms.update({npc.id, npc.profile.name, npc.profile.role})
    for location in world.locations:
        terms.update({location.id, location.name})
    for point in world.scavenge_points:
        terms.update({point.item.id, point.item.name})
    for quest in world.quests:
        terms.update({quest.id, quest.title})
    for secret in load_canon()["secrets"]:
        terms.update({secret["id"], secret["title"]})
    return {term for term in terms if term}


UNKNOWN_PATTERNS = (
    re.compile(r"(?:认识|知道|听说过)\s*[“\"「『]?([^吗么？?，。,！!]{1,18})"),
    re.compile(r"(?:镇上|这里|小镇里)?\s*(?:有|有没有)\s*[“\"「『]?([^吗么？?，。,！!]{1,18})"),
    re.compile(r"[“\"「『]?([^吗么？?，。,！!]{1,18}?)(?:发生过|存在)(?:吗|么|？|\?)"),
)


def unknown_subject(text: str, world: WorldSnapshot) -> str | None:
    """识别明确询问的未知人/店/事件；Mock 与记忆过滤共用。"""

    terms = known_terms(world)
    for pattern in UNKNOWN_PATTERNS:
        match = pattern.search(text.strip())
        if not match:
            continue
        subject = match.group(1).strip(" ‘'\"“”「」『』")
        subject = re.sub(r"^(?:你|那个|这个|一家|一个|叫|名叫)", "", subject).strip()
        if subject and not any(term in subject or subject in term for term in terms):
            return subject
    return None


ENTITY_PATTERNS = (
    re.compile(r"([^，。！？；：\s]{2,14}(?:酒吧|商店|店铺|餐馆|旅馆|组织|协会|公司|节日|节|村|镇|城))"),
    re.compile(r"(?:遇见|见到|认识|拜访|寻找)\s*([^，。！？；：\s]{2,6})"),
)


def memory_text_is_safe(text: str, world: WorldSnapshot) -> bool:
    """摘要落库前的实体闸门；无法映射到白名单的命名实体会触发降级。"""

    terms = known_terms(world)
    for pattern in ENTITY_PATTERNS:
        for candidate in pattern.findall(text):
            if not any(term in candidate or candidate in term for term in terms):
                return False
    return True


def mock_secret_for_message(npc: NPC, message: str, world: WorldSnapshot) -> dict | None:
    for secret in eligible_secrets(npc, world):
        cues = {
            "secret-sisters": ("姐妹", "姐姐", "同一锅汤"),
            "secret-keepsake": ("非卖品", "不卖", "旧物", "收音机"),
            "secret-first-fix": ("第一次修", "第一件修好", "塔灯"),
        }[secret["id"]]
        if any(cue in message for cue in cues):
            return secret
    return None
