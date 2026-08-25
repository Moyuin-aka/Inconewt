import asyncio

import pytest
from pydantic import ValidationError

from app.ai import AIService
from app.models import Decision, WorldActionRequest, initial_world
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
