import asyncio
import time
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.ai import AIService
from app.grounding import build_fact_card, get_secret, memory_text_is_safe, unknown_subject
from app.manager import WorldManager
from app.models import Decision, GiftRequest, NPCIntent, PlayerMoveRequest, ScavengeRequest, WorldActionRequest, initial_world
from app.store import WorldStore
from app.world import WorldEngine


def test_mock_decision_responds_to_needs():
    world = initial_world()
    momo = world.npcs[0]
    momo.state.needs.energy = 5
    momo.state.needs.hunger = 10
    momo.state.needs.social = 10

    decision = AIService.mock_decision(momo, world)

    assert decision.action == "rest"


def test_two_world_ids_are_fully_isolated(tmp_path):
    store = WorldStore(str(tmp_path / "isolated.db"))
    manager = WorldManager(store, max_active=20)
    first = manager.create_world(started=True)
    second = manager.create_world(started=True)

    async def scenario():
        await manager.engine(first).apply_world_action(WorldActionRequest(action="weather", value="雾"))
        assert manager.engine(first).snapshot().weather == "雾"
        assert manager.engine(second).snapshot().weather == "晴"

    asyncio.run(scenario())
    store.close()


def test_three_manual_slots_round_trip_independently(tmp_path):
    store = WorldStore(str(tmp_path / "slots.db"))
    manager = WorldManager(store)
    identity = manager.create_world(started=True)
    engine = manager.engine(identity)

    async def scenario():
        for slot, weather in ((1, "雾"), (2, "晴"), (3, "雨")):
            engine.world.weather = weather
            engine.save(slot)
        engine.world.weather = "风"
        assert (await engine.load(1)).weather == "雾"
        assert (await engine.load(2)).weather == "晴"
        assert (await engine.load(3)).weather == "雨"

    asyncio.run(scenario())
    assert {item["slot"] for item in store.list_saves(identity)} == {1, 2, 3}
    store.close()


def test_export_then_import_is_equivalent(tmp_path):
    store = WorldStore(str(tmp_path / "portable.db"))
    manager = WorldManager(store)
    source_id = manager.create_world(started=True)
    target_id = manager.create_world(started=True)
    source = manager.engine(source_id)
    source.world.day = 8
    source.world.player.name = "小满"
    source.world.player.location = "square"
    bundle = manager.export_bundle(source_id)

    imported = asyncio.run(manager.engine(target_id).import_snapshot(bundle["world"]))

    assert imported.model_dump(mode="json") == source.snapshot().model_dump(mode="json")
    store.close()


def test_active_limit_enters_observer_mode(tmp_path):
    store = WorldStore(str(tmp_path / "capacity.db"))
    manager = WorldManager(store, max_active=1)
    first = manager.create_world(started=True)
    second = manager.create_world(started=True)
    assert manager.heartbeat(first) == "interactive"
    assert manager.heartbeat(second) == "observer"
    store.close()


def test_idle_world_is_not_ticked(tmp_path):
    store = WorldStore(str(tmp_path / "idle.db"))
    manager = WorldManager(store, active_seconds=300)
    active = manager.create_world(started=True)
    idle = manager.create_world(started=True)
    store.touch_world(active)
    store.touch_world(idle, (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat())

    ticked = asyncio.run(manager.tick_active_once())

    assert ticked == [active]
    assert manager.engine(active).snapshot().tick_index == 1
    assert manager.engine(idle).snapshot().tick_index == 0
    store.close()


def test_cleanup_removes_only_worlds_idle_past_threshold(tmp_path):
    store = WorldStore(str(tmp_path / "cleanup.db"))
    manager = WorldManager(store)
    fresh = manager.create_world(started=True)
    stale = manager.create_world(started=True)
    # 一次心跳模拟前端首次连上 SSE；新世界在此之前 last_seen_at 冻结在 1970，不应被误判为过期。
    store.touch_world(fresh)
    store.create_save(store.load_current(stale), world_id=stale, slot=1, kind="manual")
    store.touch_world(stale, (datetime.now(timezone.utc) - timedelta(days=31)).isoformat())

    removed = store.cleanup_stale(30)

    assert removed == 1
    assert store.world_exists(fresh)
    assert not store.world_exists(stale)
    assert store.list_saves(stale) == []
    store.close()


def test_daily_ai_budget_is_scoped_per_world(tmp_path):
    store = WorldStore(str(tmp_path / "budget.db"))
    manager = WorldManager(store, daily_ai_limit=2)
    first = manager.create_world(started=True)
    second = manager.create_world(started=True)

    assert store.consume_ai_call(first, 2)
    assert store.consume_ai_call(first, 2)
    assert not store.consume_ai_call(first, 2)
    assert store.consume_ai_call(second, 2)
    store.close()


def test_save_and_load_round_trip(tmp_path):
    store = WorldStore(str(tmp_path / "world.db"))
    engine = WorldEngine(store, AIService())

    async def scenario():
        await engine.apply_world_action(WorldActionRequest(action="weather", value="雾"))
        engine.save()
        await engine.apply_world_action(WorldActionRequest(action="weather", value="晴"))
        loaded = await engine.load()
        assert loaded.weather == "雾"

    asyncio.run(scenario())
    store.close()


def test_tick_executes_mock_decision(tmp_path):
    store = WorldStore(str(tmp_path / "tick.db"))
    engine = WorldEngine(store, AIService())

    snapshot = asyncio.run(engine.tick())

    assert all(npc.state.action.type != "idle" for npc in snapshot.npcs)
    assert all(npc.state.action.source == "mock" for npc in snapshot.npcs)
    store.close()


def test_ten_ticks_have_variety_and_autonomous_interaction(tmp_path):
    store = WorldStore(str(tmp_path / "v2.db"))
    engine = WorldEngine(store, AIService())

    async def scenario():
        actions = {npc.id: set() for npc in engine.world.npcs}
        for _ in range(10):
            snapshot = await engine.tick()
            for npc in snapshot.npcs:
                actions[npc.id].add(npc.state.action.type)
        assert all(len(types) >= 3 for types in actions.values())
        assert any(event.kind == "npc_interaction" for event in engine.world.recent_events)

    asyncio.run(scenario())
    store.close()


def test_mock_daily_plan_is_available_without_api_key():
    world = initial_world()
    plan = AIService.mock_plan(world.npcs[0], day=2)

    assert plan.day == 2
    assert plan.source == "mock"
    assert len(plan.items) >= 3


def test_mock_decision_respects_anti_repeat_signature():
    world = initial_world()
    npc = world.npcs[0]
    repeated = AIService._activity_decision(npc, world)
    signature = f"{repeated.action}|{repeated.reason}"

    next_decision = AIService.mock_decision(npc, world, avoid_signature=signature)

    assert f"{next_decision.action}|{next_decision.reason}" != signature


def test_memory_deduplicates_identical_content(tmp_path):
    store = WorldStore(str(tmp_path / "memory.db"))
    engine = WorldEngine(store, AIService())
    npc = engine.world.npcs[0]

    engine._remember(npc, "同一件值得记住的事。")
    engine._remember(npc, "同一件值得记住的事。")

    assert npc.memory.short_term.count("同一件值得记住的事。") == 1
    store.close()


def test_invalid_decision_json_is_rejected():
    with pytest.raises(ValidationError):
        Decision.model_validate_json('{"action":"teleport","reason":"越过规则"}')


def test_fetch_quest_lifecycle_updates_affinity_diary_and_journal(tmp_path):
    store = WorldStore(str(tmp_path / "quest.db"))
    engine = WorldEngine(store, AIService())

    async def scenario():
        before = engine.world.player.relationships["momo"].affinity
        await engine.accept_quest("wish-momo-ticket")
        await engine.scavenge(ScavengeRequest(point_id="bus-luggage"))
        await engine.move_player(PlayerMoveRequest(x=365, y=360, location="store"))
        await engine.gift(GiftRequest(npc_id="momo", item_id="old-ticket"))

        quest = next(item for item in engine.world.quests if item.id == "wish-momo-ticket")
        assert quest.status == "completed"
        assert engine.world.player.relationships["momo"].affinity >= before + 10
        assert not any(item.id == "old-ticket" for item in engine.world.player.pocket)
        assert any(item.id == "secret-keepsake" for item in engine.world.player.journal)
        assert any("没有终点的车票" in line for line in engine.get_npc("momo").memory.diary)

    asyncio.run(scenario())
    store.close()


def test_message_quest_writes_both_npc_memories(tmp_path):
    store = WorldStore(str(tmp_path / "message.db"))
    engine = WorldEngine(store, AIService())

    async def scenario():
        await engine.accept_quest("wish-lili-message")
        assert engine.world.player.carried_messages[0].to_npc_id == "momo"
        await engine.move_player(PlayerMoveRequest(x=365, y=360, location="store"))
        await engine.chat("momo", "利利让我替她捎句话。")

        quest = next(item for item in engine.world.quests if item.id == "wish-lili-message")
        assert quest.status == "completed"
        assert not engine.world.player.carried_messages
        assert any("还热着的汤" in line for line in engine.get_npc("lili").memory.diary)
        assert any("还热着的汤" in line for line in engine.get_npc("momo").memory.diary)

    asyncio.run(scenario())
    store.close()


def test_player_save_round_trip_keeps_position_pocket_and_journal(tmp_path):
    store = WorldStore(str(tmp_path / "player-save.db"))
    engine = WorldEngine(store, AIService())

    async def scenario():
        await engine.scavenge(ScavengeRequest(point_id="bus-luggage"))
        engine._unlock_secret("secret-keepsake", "莫莫")
        await engine.move_player(PlayerMoveRequest(x=510, y=575, location="square"))
        engine.save()

        engine.world.player.x = 100
        engine.world.player.location = "bus_stop"
        engine.world.player.pocket.clear()
        engine.world.player.journal.clear()
        loaded = await engine.load()

        assert (loaded.player.x, loaded.player.location) == (510, "square")
        assert [item.id for item in loaded.player.pocket] == ["old-ticket"]
        assert [item.id for item in loaded.player.journal] == ["secret-keepsake"]

    asyncio.run(scenario())
    store.close()


def test_high_affinity_resident_greets_nearby_player(tmp_path):
    store = WorldStore(str(tmp_path / "greeting.db"))
    engine = WorldEngine(store, AIService())
    engine.world.tick_index = 3
    engine.world.player.location = "greenhouse"
    engine.world.player.relationships["lili"].affinity = 40
    engine.get_npc("lili").state.location = "greenhouse"

    asyncio.run(engine._maybe_player_greeting())

    assert engine.world.recent_events[0].kind == "npc_greeting"
    assert engine.get_npc("lili").state.action.say
    store.close()


def test_intent_whitelist_and_args_validation_drop_invalid_items(tmp_path):
    store = WorldStore(str(tmp_path / "intent-validation.db"))
    engine = WorldEngine(store, AIService())
    npc = engine.get_npc("momo")

    accepted = engine._enqueue_intents(npc, [
        NPCIntent(verb="teleport", args={"location": "greenhouse"}),
        NPCIntent(verb="goto", args={"location": "not-a-place"}),
        NPCIntent(verb="goto", args={"location": "greenhouse", "extra": "bad"}),
        NPCIntent(verb="visit", args={"npc": "momo"}),
        NPCIntent(verb="goto", args={"location": "greenhouse"}, because="玩家请我过去。"),
    ], "去温室看看", "deepseek")

    assert [item.verb for item in accepted] == ["goto"]
    assert [item.verb for item in npc.state.intent_queue] == ["goto"]
    store.close()


def test_infeasible_intents_are_silently_dropped(tmp_path):
    store = WorldStore(str(tmp_path / "intent-feasibility.db"))
    engine = WorldEngine(store, AIService())
    npc = engine.get_npc("momo")
    engine.world.minute = 23 * 60
    npc.state.action.type = "rest"

    accepted = engine._enqueue_intents(npc, [
        NPCIntent(verb="goto", args={"location": "store"}),
        NPCIntent(verb="visit", args={"npc": "lili"}),
        NPCIntent(verb="stop_following"),
    ], "现在去找利利", "deepseek")

    assert accepted == []
    assert npc.state.intent_queue == []
    store.close()


def test_chat_enqueues_intent_without_executing_until_next_tick(tmp_path):
    store = WorldStore(str(tmp_path / "intent-queue.db"))
    engine = WorldEngine(store, AIService())

    async def fake_chat(npc, message, world):
        return "好，我一会儿过去。", "deepseek", None, 1, "会给我明确的委托。", [
            NPCIntent(verb="goto", args={"location": "greenhouse"}, because="玩家请我去温室。")
        ], None

    engine.ai.chat = fake_chat

    async def scenario():
        await engine.move_player(PlayerMoveRequest(x=365, y=360, location="store"))
        momo = engine.get_npc("momo")
        before_action = momo.state.action.model_copy(deep=True)
        started = time.perf_counter()
        response = await engine.chat("momo", "请去温室帮我看看")
        elapsed = time.perf_counter() - started

        assert elapsed < 0.5
        assert [item.verb for item in response.intents] == ["goto"]
        assert momo.state.location == "store"
        assert momo.state.action == before_action
        assert [item.verb for item in momo.state.intent_queue] == ["goto"]

        snapshot = await engine.tick()
        momo_after = next(item for item in snapshot.npcs if item.id == "momo")
        assert momo_after.state.location == "greenhouse"
        assert not momo_after.state.intent_queue
        assert "请去温室帮我看看" in momo_after.state.action.reason
        assert any(event.kind == "npc_intent" and "动身去" in event.text for event in snapshot.recent_events)

    asyncio.run(scenario())
    store.close()


def test_relay_executes_on_tick_and_writes_memory_and_event(tmp_path):
    store = WorldStore(str(tmp_path / "relay.db"))
    engine = WorldEngine(store, AIService())
    momo = engine.get_npc("momo")
    relay = NPCIntent(
        verb="relay",
        args={"npc": "ajie", "text": "今晚风大，早点回来。"},
        because="玩家请我替他捎话。",
    )
    engine._enqueue_intents(momo, [relay], "帮我告诉阿羯今晚风大", "deepseek")

    snapshot = asyncio.run(engine.tick())

    ajie = engine.get_npc("ajie")
    assert any("今晚风大，早点回来" in line for line in ajie.memory.short_term)
    assert any(event.kind == "npc_intent" and set(event.participants) == {"momo", "ajie"} for event in snapshot.recent_events)
    store.close()


def test_mock_follow_and_stop_use_unified_intent_queue(tmp_path):
    store = WorldStore(str(tmp_path / "mock-follow.db"))
    engine = WorldEngine(store, AIService())

    async def scenario():
        await engine.move_player(PlayerMoveRequest(x=365, y=360, location="store"))
        follow_response = await engine.chat("momo", "跟我来")
        assert [item.verb for item in follow_response.intents] == ["follow_player"]
        assert not engine.get_npc("momo").state.following_player

        await engine.tick()
        assert engine.get_npc("momo").state.following_player

        stop_response = await engine.chat("momo", "别跟着我了")
        assert [item.verb for item in stop_response.intents] == ["stop_following"]
        await engine.tick()
        assert not engine.get_npc("momo").state.following_player

    asyncio.run(scenario())
    store.close()


def test_fact_card_contains_only_current_structured_world_facts():
    world = initial_world()
    card = build_fact_card(world, world.npcs[0])

    assert {item["name"] for item in card["residents"]} == {"莫莫", "利利", "小柯", "阿羯"}
    assert len(card["locations"]) == 7
    assert card["player"]["name"] == "外来者"
    assert len(card["recent_true_events"]) <= 5
    assert any("事实卡" in rule for rule in card["hard_rules"])


@pytest.mark.parametrize("npc_id, expected", [
    ("momo", "没听说过"),
    ("lili", "没听说过"),
    ("xiaoke", "啥？没听说过"),
    ("ajie", "不知道"),
])
def test_mock_unknown_entity_reply_is_grounded_and_characterful(npc_id, expected):
    world = initial_world()
    npc = next(item for item in world.npcs if item.id == npc_id)

    for message in ("你认识张三吗？", "镇上有蓝月酒吧吗？", "黑潮节发生过吗？"):
        reply, _, _, intents, revealed = AIService.mock_chat(npc, message, world)
        assert expected in reply
        assert not intents
        assert revealed is None


def test_unknown_dialogue_does_not_pollute_memory(tmp_path):
    store = WorldStore(str(tmp_path / "unknown-memory.db"))
    engine = WorldEngine(store, AIService())

    async def scenario():
        await engine.move_player(PlayerMoveRequest(x=365, y=360, location="store"))
        for message in ("你认识张三吗？", "镇上有蓝月酒吧吗？", "黑潮节发生过吗？"):
            await engine.chat("momo", message)

    asyncio.run(scenario())
    memory = "\n".join(engine.get_npc("momo").memory.short_term)
    assert "张三" not in memory
    assert "蓝月酒吧" not in memory
    assert "黑潮节" not in memory
    assert "没有记录的事" in memory
    store.close()


def test_canon_secret_is_revealed_verbatim_and_unlocked(tmp_path):
    store = WorldStore(str(tmp_path / "canon-secret.db"))
    engine = WorldEngine(store, AIService())
    engine.world.player.relationships["momo"].affinity = 50
    canon = get_secret("secret-keepsake")

    async def scenario():
        await engine.move_player(PlayerMoveRequest(x=365, y=360, location="store"))
        response = await engine.chat("momo", "那件不卖的收音机是什么？")
        assert response.revealed_secret_id == "secret-keepsake"
        assert canon["text"] in response.reply

    asyncio.run(scenario())
    unlocked = next(item for item in engine.world.player.journal if item.id == "secret-keepsake")
    assert unlocked.text == canon["text"]
    store.close()


def test_memory_entity_gate_rejects_unknown_named_place():
    world = initial_world()

    assert memory_text_is_safe("今天在拾光整理了收音机。", world)
    assert not memory_text_is_safe("傍晚去了蓝月酒吧。", world)
    assert unknown_subject("镇上有蓝月酒吧吗？", world) == "蓝月酒吧"
