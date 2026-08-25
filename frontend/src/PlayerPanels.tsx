import { FormEvent, useState } from "react";
import type { PlayerState, WishQuest, World } from "./api";

type NotebookTab = "quests" | "journal";

function residentName(world: World, id: string | null) {
  return world.npcs.find((npc) => npc.id === id)?.profile.name ?? id ?? "未知居民";
}

export function PlayerDock({ world, nearbyNpc, onNotebook, onObserver, onAppearance, onBoard, onWish }: {
  world: World;
  nearbyNpc: string | null;
  onNotebook: (tab: NotebookTab) => void;
  onObserver: () => void;
  onAppearance: (appearance: PlayerState["appearance"]) => void;
  onBoard: () => void;
  onWish: (weather: "晴" | "雾") => void;
}) {
  const location = world.locations.find((item) => item.id === world.player.location);
  const atSquare = world.player.location === "square";
  const activeCount = world.quests.filter((quest) => quest.status !== "completed").length;
  return (
    <section className="player-dock">
      <div className="player-identity">
        <span className={`player-token appearance-${world.player.appearance}`}>旅</span>
        <div><small>THE OUTSIDER / 当前地点</small><strong>{location?.name ?? "镇上的旧路"}</strong></div>
        <div className="appearance-picker" aria-label="选择外观">
          {(["moss", "ember", "slate"] as const).map((appearance) => (
            <button key={appearance} className={`${appearance} ${world.player.appearance === appearance ? "active" : ""}`} onClick={() => onAppearance(appearance)} aria-label={`选择${appearance}外观`} />
          ))}
        </div>
      </div>
      <div className="pocket-strip">
        <small>四格口袋</small>
        <div>{[0, 1, 2, 3].map((index) => {
          const item = world.player.pocket[index];
          return <span key={index} className={item ? "filled" : ""} title={item?.description}>{item ? <><b>{item.symbol}</b>{item.name}</> : "空"}</span>;
        })}</div>
      </div>
      <div className="player-actions">
        {nearbyNpc && <span className="nearby-callout"><kbd>E</kbd> 与{residentName(world, nearbyNpc)}交谈</span>}
        {atSquare && <button onClick={onBoard}>在公告板写字</button>}
        {atSquare && <button onClick={() => onWish(world.weather === "雾" ? "晴" : "雾")} disabled={world.tick_index < world.player.weather_cooldown_until}>蝾螈许愿</button>}
        <button onClick={() => onNotebook("quests")}>心愿 <b>{activeCount}</b></button>
        <button onClick={() => onNotebook("journal")}>手记 <b>{world.player.journal.length}</b></button>
        <button onClick={onObserver}>观察者模式</button>
      </div>
      <div className="move-hint"><kbd>WASD</kbd><span>或点击地面移动</span></div>
    </section>
  );
}

export function NotebookPanel({ world, initialTab, onClose, onAccept }: {
  world: World;
  initialTab: NotebookTab;
  onClose: () => void;
  onAccept: (questId: string) => void;
}) {
  const [tab, setTab] = useState<NotebookTab>(initialTab);
  return (
    <aside className="notebook-panel">
      <button className="panel-close" onClick={onClose}>×</button>
      <p className="eyebrow">OUTSIDER'S FIELD NOTES</p>
      <h2>小镇手记</h2>
      <nav><button className={tab === "quests" ? "active" : ""} onClick={() => setTab("quests")}>居民心愿</button><button className={tab === "journal" ? "active" : ""} onClick={() => setTab("journal")}>秘闻碎片</button></nav>
      {tab === "quests" ? (
        <div className="quest-list">
          {world.quests.map((quest) => <QuestCard key={quest.id} quest={quest} world={world} onAccept={onAccept} />)}
        </div>
      ) : (
        <div className="secret-grid">
          {world.player.journal.map((secret, index) => <article key={secret.id}><span>{String(index + 1).padStart(2, "0")}</span><div><small>{secret.unlocked_at} · {secret.source}</small><h3>{secret.title}</h3><p>{secret.text}</p></div></article>)}
          {world.player.journal.length < 3 && Array.from({ length: 3 - world.player.journal.length }).map((_, index) => <article className="locked" key={index}><span>?</span><div><small>尚未解锁</small><h3>被折起的一页</h3><p>靠近居民、完成心愿，故事才会留下字迹。</p></div></article>)}
        </div>
      )}
    </aside>
  );
}

function QuestCard({ quest, world, onAccept }: { quest: WishQuest; world: World; onAccept: (questId: string) => void }) {
  const giver = residentName(world, quest.giver_id);
  return (
    <article className={`quest-card status-${quest.status}`}>
      <header><span>{quest.type === "fetch" ? "取物" : quest.type === "message" ? "传话" : "陪伴"}</span><small>{quest.source}</small></header>
      <h3>{quest.title}</h3>
      <p>{quest.description}</p>
      <dl><div><dt>发起</dt><dd>{giver}</dd></div><div><dt>回报</dt><dd>{quest.reward}</dd></div></dl>
      {quest.status === "offered" && <button onClick={() => onAccept(quest.id)}>记下这个心愿 →</button>}
      {quest.status === "accepted" && <footer>进行中 · 靠近相关居民交谈即可交付</footer>}
      {quest.status === "completed" && <footer>✓ 已写进彼此的日记</footer>}
    </article>
  );
}

export function ObserverPanel({ busy, onClose, onSave, onLoad, onTick, onWeather }: {
  busy: boolean;
  onClose: () => void;
  onSave: () => void;
  onLoad: () => void;
  onTick: () => void;
  onWeather: (weather: "晴" | "雾") => void;
}) {
  return (
    <aside className="observer-panel">
      <button className="panel-close" onClick={onClose}>×</button>
      <p className="eyebrow">OBSERVER / DEMO TOOLS</p><h2>观察者模式</h2>
      <p>这些操作用于演示存档、AI 降级与世界推进，不属于外来者在世界内的能力。</p>
      <div><button onClick={onSave} disabled={busy}>保存世界</button><button onClick={onLoad} disabled={busy}>恢复存档</button><button onClick={onTick} disabled={busy}>推进一刻</button><button onClick={() => onWeather("晴")} disabled={busy}>直接放晴</button><button onClick={() => onWeather("雾")} disabled={busy}>直接起雾</button></div>
    </aside>
  );
}

export function BoardComposer({ onClose, onSubmit }: { onClose: () => void; onSubmit: (text: string) => void }) {
  const [text, setText] = useState("");
  function submit(event: FormEvent) {
    event.preventDefault();
    const value = text.trim();
    if (!value) return;
    onSubmit(value);
  }
  return (
    <section className="board-composer">
      <form onSubmit={submit}><small>CENTRAL SQUARE / NOTICE BOARD</small><h2>留一句话给全镇</h2><p>它会进入四位居民接下来的决策与对话，他们会按各自的性格回应。</p><textarea value={text} onChange={(event) => setText(event.target.value)} maxLength={120} autoFocus placeholder="今天想让新螈镇记住什么？" /><footer><span>{text.length}/120</span><button type="button" onClick={onClose}>算了</button><button disabled={!text.trim()}>钉上公告板 →</button></footer></form>
    </section>
  );
}
