from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


ActionType = Literal["move", "work", "rest", "eat", "chat", "idle", "observe"]


class Location(BaseModel):
    id: str
    name: str
    description: str
    tone: str


class NPCProfile(BaseModel):
    name: str
    role: str
    personality: str
    backstory: str
    color: str
    weights: dict[str, float]


class NPCAction(BaseModel):
    type: ActionType = "idle"
    target: str | None = None
    say: str = ""
    reason: str = "刚刚醒来，正在观察小镇。"
    source: Literal["mock", "deepseek"] = "mock"


class NPCNeeds(BaseModel):
    energy: int = Field(default=80, ge=0, le=100)
    hunger: int = Field(default=20, ge=0, le=100)
    social: int = Field(default=25, ge=0, le=100)


class NPCState(BaseModel):
    location: str
    action: NPCAction = Field(default_factory=NPCAction)
    needs: NPCNeeds = Field(default_factory=NPCNeeds)
    mood: str = "平静"


class NPCMemory(BaseModel):
    short_term: list[str] = Field(default_factory=list)
    diary: list[str] = Field(default_factory=list)


class Relationship(BaseModel):
    affinity: int = Field(ge=-100, le=100)
    impression: str


class NPC(BaseModel):
    id: str
    profile: NPCProfile
    state: NPCState
    memory: NPCMemory
    relationships: dict[str, Relationship] = Field(default_factory=dict)


class WorldEvent(BaseModel):
    id: str
    at: str
    kind: str
    text: str


class WorldSnapshot(BaseModel):
    day: int = 1
    minute: int = 8 * 60
    weather: str = "晴"
    announcement: str = "今天也慢慢把日子长回来。"
    locations: list[Location]
    npcs: list[NPC]
    recent_events: list[WorldEvent] = Field(default_factory=list)
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Decision(BaseModel):
    action: ActionType
    target: str | None = None
    say: str = ""
    reason: str = Field(min_length=1, max_length=120)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)


class ChatResponse(BaseModel):
    reply: str
    source: Literal["mock", "deepseek"]
    fallback_reason: str | None = None


class WorldActionRequest(BaseModel):
    action: Literal["weather", "announcement", "gift"]
    value: str = Field(min_length=1, max_length=200)
    npc_id: str | None = None


def initial_world() -> WorldSnapshot:
    """初始化数据集中在此处，方便 code review 与现场修改。"""
    locations = [
        Location(id="store", name="杂物铺「拾光」", description="旧物、暖灯与被仔细保存的记忆。", tone="amber"),
        Location(id="greenhouse", name="温室食堂「芽」", description="碎玻璃拼成的温室，长桌旁总有热汤。", tone="green"),
        Location(id="square", name="中央广场·水潭", description="公告板立在水潭边，蝾螈躲在石缝里。", tone="blue"),
    ]
    momo = NPC(
        id="momo",
        profile=NPCProfile(
            name="莫莫",
            role="杂物铺店主",
            personality="内向、温吞、恋旧，共情强但不轻易谈起「劫」。",
            backstory="守着一件从不出售的旧物，像守着一段没有讲完的过去。",
            color="#c98d62",
            weights={"work": 1.25, "social": 0.70, "rest": 1.10, "eat": 1.0},
        ),
        state=NPCState(location="store", needs=NPCNeeds(energy=74, hunger=18, social=38), mood="安静"),
        memory=NPCMemory(
            short_term=["清晨把那台坏收音机擦了一遍。"],
            diary=["第 1 天：有些旧物不是为了修好，只是提醒我曾经有人在这里。"],
        ),
        relationships={"lili": Relationship(affinity=60, impression="妹妹总能把冷掉的饭重新热好。")},
    )
    lili = NPC(
        id="lili",
        profile=NPCProfile(
            name="利利",
            role="温室食堂主理人",
            personality="外向、热心、爱操心，用种植和做饭照顾所有人。",
            backstory="她把照顾别人变成自己的重建方式，相信新芽总会回来。",
            color="#78a75a",
            weights={"work": 1.10, "social": 1.35, "rest": 0.75, "eat": 1.15},
        ),
        state=NPCState(location="greenhouse", needs=NPCNeeds(energy=88, hunger=24, social=46), mood="忙碌"),
        memory=NPCMemory(
            short_term=["给窗边那株番茄取名叫小红。"],
            diary=["第 1 天：土里只要还有一点绿，镇上的饭桌就不会散。"],
        ),
        relationships={"momo": Relationship(affinity=60, impression="姐姐什么都记得，所以更要提醒她按时吃饭。")},
    )
    return WorldSnapshot(locations=locations, npcs=[momo, lili])
