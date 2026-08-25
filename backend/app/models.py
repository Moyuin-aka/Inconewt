from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


ActionType = Literal["move", "work", "rest", "eat", "chat", "idle", "observe", "visit", "activity"]


class Location(BaseModel):
    id: str
    name: str
    description: str
    tone: str
    symbol: str = "·"
    x: int = Field(default=500, ge=0, le=1000)
    y: int = Field(default=325, ge=0, le=650)


class ActivityDefinition(BaseModel):
    id: str
    label: str
    location: str
    narratives: list[str]


class NPCProfile(BaseModel):
    name: str
    role: str
    personality: str
    backstory: str
    color: str
    weights: dict[str, float]
    codename: str = "RESIDENT"
    home: str = "square"
    tags: list[str] = Field(default_factory=list)
    activities: list[ActivityDefinition] = Field(default_factory=list)


class NPCAction(BaseModel):
    type: ActionType = "idle"
    target: str | None = None
    activity_id: str | None = None
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


class ActionRecord(BaseModel):
    day: int
    minute: int
    type: ActionType
    target: str | None = None
    activity_id: str | None = None
    reason: str


class NPCMemory(BaseModel):
    short_term: list[str] = Field(default_factory=list)
    diary: list[str] = Field(default_factory=list)
    action_history: list[ActionRecord] = Field(default_factory=list)


class PlanItem(BaseModel):
    id: str
    start_minute: int = Field(ge=0, le=1439)
    label: str
    action: ActionType
    target: str | None = None
    activity_id: str | None = None
    completed: bool = False


class DailyPlan(BaseModel):
    day: int = 0
    summary: str = "今天先照常过日子。"
    items: list[PlanItem] = Field(default_factory=list)
    source: Literal["mock", "deepseek"] = "mock"


class Relationship(BaseModel):
    affinity: int = Field(ge=-100, le=100)
    impression: str


class NPC(BaseModel):
    id: str
    profile: NPCProfile
    state: NPCState
    memory: NPCMemory
    plan: DailyPlan = Field(default_factory=DailyPlan)
    relationships: dict[str, Relationship] = Field(default_factory=dict)


class WorldEvent(BaseModel):
    id: str
    at: str
    kind: str
    text: str
    participants: list[str] = Field(default_factory=list)


class WorldSnapshot(BaseModel):
    schema_version: int = 1
    tick_index: int = 0
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
    activity_id: str | None = None
    say: str = ""
    reason: str = Field(min_length=1, max_length=120)


class InteractionLine(BaseModel):
    speaker: str
    text: str = Field(min_length=1, max_length=100)


class InteractionScript(BaseModel):
    lines: list[InteractionLine] = Field(min_length=2, max_length=4)


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


def _activity(id_: str, label: str, location: str, *narratives: str) -> ActivityDefinition:
    return ActivityDefinition(id=id_, label=label, location=location, narratives=list(narratives))


def _seed_plan(npc_id: str, day: int = 1) -> DailyPlan:
    templates: dict[str, list[PlanItem]] = {
        "momo": [
            PlanItem(id="m1", start_minute=540, label="擦拭旧收音机", action="activity", target="store", activity_id="polish_radio"),
            PlanItem(id="m2", start_minute=660, label="去温室看看利利", action="visit", target="lili"),
            PlanItem(id="m3", start_minute=840, label="在「芽」吃点东西", action="eat", target="greenhouse"),
            PlanItem(id="m4", start_minute=1020, label="去水潭边坐一会儿", action="observe", target="square"),
        ],
        "lili": [
            PlanItem(id="l1", start_minute=540, label="给新苗浇水", action="activity", target="greenhouse", activity_id="tend_seedlings"),
            PlanItem(id="l2", start_minute=660, label="去提醒莫莫吃饭", action="visit", target="momo"),
            PlanItem(id="l3", start_minute=780, label="给大家煮热汤", action="activity", target="greenhouse", activity_id="cook_soup"),
            PlanItem(id="l4", start_minute=1080, label="把汤带去广场", action="visit", target="square"),
        ],
        "xiaoke": [
            PlanItem(id="x1", start_minute=540, label="拆开旧水泵", action="activity", target="repair", activity_id="repair_pump"),
            PlanItem(id="x2", start_minute=720, label="去食堂补一顿饭", action="eat", target="greenhouse"),
            PlanItem(id="x3", start_minute=900, label="去塔下找阿羯", action="visit", target="ajie"),
            PlanItem(id="x4", start_minute=1080, label="把零件归类", action="activity", target="repair", activity_id="sort_parts"),
        ],
        "ajie": [
            PlanItem(id="a1", start_minute=540, label="白天补觉", action="rest", target="tower"),
            PlanItem(id="a2", start_minute=720, label="检查镇外动静", action="activity", target="tower", activity_id="watch_horizon"),
            PlanItem(id="a3", start_minute=960, label="去修理棚看一眼", action="visit", target="xiaoke"),
            PlanItem(id="a4", start_minute=1200, label="开始夜间巡逻", action="activity", target="tower", activity_id="night_patrol"),
        ],
    }
    summaries = {
        "momo": "整理旧物，也给自己留一点走出店门的时间。",
        "lili": "照顾新芽，记得把没来吃饭的人找回来。",
        "xiaoke": "修好水泵，别再忙到忘记吃饭。",
        "ajie": "养足精神，天黑前巡一遍小镇边缘。",
    }
    items = [item.model_copy(update={"id": f"d{day}-{item.id}"}) for item in templates[npc_id]]
    return DailyPlan(day=day, summary=summaries[npc_id], items=items)


def initial_world() -> WorldSnapshot:
    """v2 初始化数据：地点、人物、动作定义与关系集中在一处，便于审阅。"""
    locations = [
        Location(id="store", name="杂物铺「拾光」", description="旧物、暖灯与被仔细保存的记忆。", tone="amber", symbol="旧", x=190, y=205),
        Location(id="repair", name="修理棚", description="铁皮、帆布和总也收不完的零件。", tone="rust", symbol="修", x=510, y=140),
        Location(id="tower", name="边缘瞭望塔", description="风从废墟方向来，塔顶一直亮着孤灯。", tone="slate", symbol="塔", x=820, y=190),
        Location(id="greenhouse", name="温室食堂「芽」", description="碎玻璃拼成的温室，长桌旁总有热汤。", tone="green", symbol="芽", x=785, y=470),
        Location(id="square", name="中央广场·水潭", description="公告板立在水潭边，蝾螈躲在石缝里。", tone="blue", symbol="水", x=390, y=455),
    ]
    momo = NPC(
        id="momo",
        profile=NPCProfile(name="莫莫", role="杂物铺店主", codename="KEEPER OF ECHOES", home="store", personality="内向、温吞、恋旧，共情强但不轻易谈起「劫」。", backstory="守着一件从不出售的旧物，像守着一段没有讲完的过去。", color="#c98d62", tags=["恋旧", "共情", "慢热"], weights={"work": 1.25, "social": 0.70, "rest": 1.10, "eat": 1.0}, activities=[_activity("polish_radio", "擦拭旧收音机", "store", "莫莫用软布擦去收音机旋钮上的灰，像在拂过某段旧日回声。", "拾光的灯下，莫莫重新排列那几件从不标价的旧物。"), _activity("catalog_relics", "给旧物编目", "store", "莫莫在发黄的账页上补了一行小字，又轻轻合上本子。")]),
        state=NPCState(location="store", needs=NPCNeeds(energy=74, hunger=18, social=38), mood="安静"),
        memory=NPCMemory(short_term=["清晨把那台坏收音机擦了一遍。"], diary=["第 1 天：有些旧物不是为了修好，只是提醒我曾经有人在这里。"]), plan=_seed_plan("momo"),
        relationships={"lili": Relationship(affinity=60, impression="妹妹总能把冷掉的饭重新热好。"), "ajie": Relationship(affinity=50, impression="彼此都知道对方藏着一些往事。")},
    )
    lili = NPC(
        id="lili",
        profile=NPCProfile(name="利利", role="温室食堂主理人", codename="TENDER OF SPROUTS", home="greenhouse", personality="外向、热心、爱操心，用种植和做饭照顾所有人。", backstory="她把照顾别人变成自己的重建方式，相信新芽总会回来。", color="#78a75a", tags=["热心", "行动派", "爱念叨"], weights={"work": 1.10, "social": 1.35, "rest": 0.75, "eat": 1.15}, activities=[_activity("tend_seedlings", "照料新苗", "greenhouse", "利利挨个检查叶片，把歪掉的苗扶回向光的方向。", "温室里响起细细的水声，利利正给每株植物点名。"), _activity("cook_soup", "熬一锅热汤", "greenhouse", "利利掀开汤锅，热气把拼接的玻璃窗熏出一片白雾。")]),
        state=NPCState(location="greenhouse", needs=NPCNeeds(energy=88, hunger=24, social=46), mood="忙碌"),
        memory=NPCMemory(short_term=["给窗边那株番茄取名叫小红。"], diary=["第 1 天：土里只要还有一点绿，镇上的饭桌就不会散。"]), plan=_seed_plan("lili"),
        relationships={"momo": Relationship(affinity=60, impression="姐姐什么都记得，所以更要提醒她按时吃饭。"), "xiaoke": Relationship(affinity=55, impression="总得亲自把这个小忙人抓来吃饭。")},
    )
    xiaoke = NPC(
        id="xiaoke",
        profile=NPCProfile(name="小柯", role="修理工", codename="MAKER OF TOMORROW", home="repair", personality="外向、乐天、话密，精力过剩，行动总比思考快半拍。", backstory="她几乎不记得「劫」，相信没有修不好的东西。", color="#d6843c", tags=["乐天", "话密", "机械迷"], weights={"work": 1.45, "social": 1.20, "rest": 0.55, "eat": 0.85}, activities=[_activity("repair_pump", "拆装旧水泵", "repair", "修理棚传来叮叮当当的响声，小柯说这次一定只多出两颗螺丝。", "小柯趴在水泵旁，把一枚齿轮叫作“爱闹脾气的小三号”。"), _activity("sort_parts", "整理零件", "repair", "小柯把零件按“马上有用”和“总会有用”分成了两大堆。")]),
        state=NPCState(location="repair", needs=NPCNeeds(energy=92, hunger=40, social=30), mood="兴奋"),
        memory=NPCMemory(short_term=["水泵又卡住了，但这正好说明它还有救。"], diary=["第 1 天：今天一定把水泵修好。包修好的！"]), plan=_seed_plan("xiaoke"),
        relationships={"lili": Relationship(affinity=70, impression="她做的汤能让脑子转得更快。"), "ajie": Relationship(affinity=65, impression="阿羯话少，但从不嫌我吵。")},
    )
    ajie = NPC(
        id="ajie",
        profile=NPCProfile(name="阿羯", role="守夜人", codename="WATCHER AT THE EDGE", home="tower", personality="内向、寡言、警觉，外冷内热，习惯把危险挡在镇外。", backstory="见过「劫」的某个真相，却从不讲述。", color="#657064", tags=["寡言", "可靠", "夜行"], weights={"work": 1.35, "social": 0.45, "rest": 1.25, "eat": 0.95}, activities=[_activity("watch_horizon", "登塔瞭望", "tower", "阿羯站在塔顶，目光越过小镇屋脊，停在远处废墟的轮廓上。", "塔上的孤灯还亮着，阿羯重新校准了望远镜。"), _activity("night_patrol", "沿边界巡逻", "tower", "入夜后，阿羯的脚步沿镇子边缘绕过一圈，没有惊动任何人。")]),
        state=NPCState(location="tower", needs=NPCNeeds(energy=58, hunger=20, social=24), mood="警觉"),
        memory=NPCMemory(short_term=["天亮前，废墟方向似乎闪过一道光。"], diary=["第 1 天：风向没变。镇子安全。别的事以后再说。"]), plan=_seed_plan("ajie"),
        relationships={"xiaoke": Relationship(affinity=45, impression="太吵。但这很好。"), "momo": Relationship(affinity=50, impression="不需要解释，也能坐在同一盏灯下。")},
    )
    return WorldSnapshot(schema_version=2, locations=locations, npcs=[momo, lili, xiaoke, ajie])


def upgrade_world(world: WorldSnapshot) -> WorldSnapshot:
    """把 v1 数据温和合并进 v2 种子，部署升级后不丢时间、天气与已有记忆。"""
    fresh = initial_world()
    fresh.day, fresh.minute = world.day, world.minute
    fresh.weather, fresh.announcement = world.weather, world.announcement
    fresh.recent_events = world.recent_events[:16]
    existing = {npc.id: npc for npc in world.npcs}
    for npc in fresh.npcs:
        old = existing.get(npc.id)
        if old:
            npc.state.needs, npc.state.mood = old.state.needs, old.state.mood
            npc.memory.short_term, npc.memory.diary = old.memory.short_term[-20:], old.memory.diary[-12:]
            npc.relationships.update(old.relationships)
    return fresh
