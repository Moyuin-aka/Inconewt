import type { World } from "./api";

export function DataMode({ world, onClose }: { world: World; onClose: () => void }) {
  return (
    <section className="data-mode">
      <header><div><p className="eyebrow">AIVILIZATION / DATA VIEW</p><h2>新螈镇数据模式</h2></div><button onClick={onClose}>返回游戏模式 ×</button></header>
      <div className="data-world-strip"><span>第 {world.day} 天</span><span>{Math.floor(world.minute / 60).toString().padStart(2, "0")}:00</span><span>{world.weather}</span><span>TICK {world.tick_index}</span><span>玩家 · {world.locations.find((item) => item.id === world.player.location)?.name}</span><span>口袋 {world.player.pocket.length}/4 · 手记 {world.player.journal.length}</span></div>
      <div className="data-grid">
        {world.npcs.map((npc) => <article key={npc.id} className="data-card" style={{ "--resident": npc.profile.color } as React.CSSProperties}>
          <header><div><small>{npc.profile.codename}</small><h3>{npc.profile.name}</h3></div><span>{npc.state.mood}</span></header>
          <dl><div><dt>地点</dt><dd>{world.locations.find((item) => item.id === npc.state.location)?.name}</dd></div><div><dt>行动</dt><dd>{npc.state.action.type}</dd></div><div><dt>来源</dt><dd>{npc.state.action.source}</dd></div></dl>
          <blockquote>{npc.state.action.reason}</blockquote>
          <div className="data-needs"><span>精力 {npc.state.needs.energy}</span><span>饥饿 {npc.state.needs.hunger}</span><span>社交 {npc.state.needs.social}</span></div>
          <section><small>今日计划</small><p>{npc.plan.summary}</p></section>
          <section><small>TA 眼中的玩家 · {world.player.relationships[npc.id]?.affinity ?? 0}</small><p>{world.player.relationships[npc.id]?.impression ?? "仍是陌生人。"}</p></section>
          <section><small>最近三次行动</small>{npc.memory.action_history.slice(-3).reverse().map((action, index) => <p key={index}>{action.type} · {action.reason}</p>)}</section>
        </article>)}
      </div>
      <div className="data-events"><p className="eyebrow">NARRATIVE EVENT STREAM</p>{world.recent_events.slice(0, 8).map((event) => <article key={event.id}><time>{event.at}</time><span>{event.text}</span></article>)}</div>
    </section>
  );
}
