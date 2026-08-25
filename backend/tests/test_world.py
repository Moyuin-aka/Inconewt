import asyncio

import pytest
from pydantic import ValidationError

from app.ai import AIService
from app.models import Decision, GiftRequest, PlayerMoveRequest, ScavengeRequest, WorldActionRequest, initial_world
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
