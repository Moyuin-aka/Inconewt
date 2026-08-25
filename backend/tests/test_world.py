import asyncio

from app.ai import AIService
from app.models import WorldActionRequest, initial_world
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
