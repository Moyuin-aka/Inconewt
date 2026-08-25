import { useEffect, useState } from "react";
import type { NPC } from "./api";

type Tab = "profile" | "memory" | "relations";

function NeedBar({ label, value, invert = false }: { label: string; value: number; invert?: boolean }) {
  const display = invert ? 100 - value : value;
  return (
    <div className="archive-need">
      <span>{label}</span><i><b style={{ width: `${display}%` }} /></i><strong>{display}</strong>
    </div>
  );
}

function timeLabel(minute: number) {
  return `${String(Math.floor(minute / 60)).padStart(2, "0")}:00`;
}

export function ArchivePanel({ npc, residents, onClose, onTalk }: {
  npc: NPC;
  residents: NPC[];
  onClose: () => void;
  onTalk: () => void;
}) {
  const [tab, setTab] = useState<Tab>("profile");
  useEffect(() => setTab("profile"), [npc.id]);
  return (
    <aside className="archive-panel">
      <button className="panel-close" onClick={onClose} aria-label="关闭居民档案">×</button>
      <div className={`resident-art resident-${npc.id}`} role="img" aria-label={`${npc.profile.name}的角色立绘`} />
      <div className="archive-content">
        <p className="eyebrow">RESIDENT FILE / {npc.id.toUpperCase()}</p>
        <div className="archive-title"><div><h2>{npc.profile.name}</h2><p>{npc.profile.codename}</p></div><span>{npc.state.mood}</span></div>
        <div className="tag-list">{npc.profile.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
        <nav className="archive-tabs" aria-label="档案分页">
          <button className={tab === "profile" ? "active" : ""} onClick={() => setTab("profile")}>档案</button>
          <button className={tab === "memory" ? "active" : ""} onClick={() => setTab("memory")}>记忆</button>
          <button className={tab === "relations" ? "active" : ""} onClick={() => setTab("relations")}>关系</button>
        </nav>

        <div className="archive-tab-body">
          {tab === "profile" && <>
            <p className="archive-role">{npc.profile.role}</p>
            <p className="archive-copy">{npc.profile.personality}</p>
            <p className="archive-backstory">{npc.profile.backstory}</p>
            <div className="current-decision"><small>当前行动 · {npc.state.action.source}</small><p>“{npc.state.action.reason}”</p></div>
            <NeedBar label="精力" value={npc.state.needs.energy} />
            <NeedBar label="饱腹" value={npc.state.needs.hunger} invert />
            <NeedBar label="陪伴" value={npc.state.needs.social} invert />
            <section className="daily-plan">
              <header><span>第 {npc.plan.day} 天计划</span><small>{npc.plan.source}</small></header>
              <p>{npc.plan.summary}</p>
              {npc.plan.items.map((item) => <div key={item.id} className={item.completed ? "done" : ""}><time>{timeLabel(item.start_minute)}</time><span>{item.label}</span><b>{item.completed ? "✓" : "·"}</b></div>)}
            </section>
          </>}
          {tab === "memory" && <>
            <p className="tab-caption">SHORT TERM / 最近发生</p>
            {[...npc.memory.short_term].reverse().map((memory, index) => <article className="memory-entry" key={`${memory}-${index}`}>{memory}</article>)}
            <p className="tab-caption diary-caption">DIARY / 日记</p>
            {[...npc.memory.diary].reverse().map((memory, index) => <article className="diary-entry" key={`${memory}-${index}`}>{memory}</article>)}
          </>}
          {tab === "relations" && <>
            <p className="tab-caption">RELATION MAP / 对他人的印象</p>
            {Object.entries(npc.relationships).map(([id, relation]) => {
              const other = residents.find((resident) => resident.id === id);
              return <article className="relation-entry" key={id}><header><b>{other?.profile.name ?? id}</b><span>{relation.affinity}</span></header><i><b style={{ width: `${Math.max(0, relation.affinity)}%` }} /></i><p>{relation.impression}</p></article>;
            })}
          </>}
        </div>
        <button className="talk-button" onClick={onTalk}><span>和{npc.profile.name}说话</span><b>进入剧情 →</b></button>
      </div>
    </aside>
  );
}
