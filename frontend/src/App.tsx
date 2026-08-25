import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, Health, NPC, World } from "./api";

type ChatLine = { from: "player" | "npc" | "system"; text: string };

const locationSymbols: Record<string, string> = {
  store: "旧",
  greenhouse: "芽",
  square: "水",
};

const actionNames: Record<string, string> = {
  work: "忙手头的事",
  rest: "休息",
  eat: "吃东西",
  chat: "找人聊天",
  move: "前往别处",
  observe: "观察",
  idle: "发呆",
};

function timeText(world: World) {
  const hour = Math.floor(world.minute / 60).toString().padStart(2, "0");
  const minute = (world.minute % 60).toString().padStart(2, "0");
  return `第 ${world.day} 天 · ${hour}:${minute}`;
}

function NeedBar({ label, value, inverse = false }: { label: string; value: number; inverse?: boolean }) {
  const display = inverse ? 100 - value : value;
  return (
    <div className="need-row">
      <span>{label}</span>
      <div className="need-track" aria-label={`${label} ${display}%`}>
        <i style={{ width: `${display}%` }} />
      </div>
      <b>{display}</b>
    </div>
  );
}

function TownMap({ world, selectedId, onSelect }: { world: World; selectedId: string; onSelect: (id: string) => void }) {
  return (
    <section className="town-map" aria-label="新螈镇地图">
      <div className="map-caption">
        <span>NEW(T) TOWN / OBSERVATION MAP</span>
        <small>点击居民查看她此刻为何行动</small>
      </div>
      <div className="water-lines" />
      {world.locations.map((location) => (
        <article key={location.id} className={`location location-${location.id}`}>
          <div className="location-symbol">{locationSymbols[location.id]}</div>
          <div>
            <h2>{location.name}</h2>
            <p>{location.description}</p>
          </div>
          <div className="npc-markers">
            {world.npcs
              .filter((npc) => npc.state.location === location.id)
              .map((npc) => (
                <button
                  className={`npc-marker ${selectedId === npc.id ? "selected" : ""}`}
                  key={npc.id}
                  style={{ "--npc-color": npc.profile.color } as React.CSSProperties}
                  onClick={() => onSelect(npc.id)}
                >
                  <span className="npc-figure" aria-hidden="true"><i /></span>
                  <span>
                    <b>{npc.profile.name}</b>
                    <small>{actionNames[npc.state.action.type] ?? npc.state.action.type}</small>
                  </span>
                </button>
              ))}
          </div>
        </article>
      ))}
      <div className="map-note">劫后第十年<br />水潭里的蝾螈又多了一只</div>
    </section>
  );
}

function NPCPanel({ npc, onChat }: { npc: NPC; onChat: () => void }) {
  const memories = [...npc.memory.short_term].reverse().slice(0, 4);
  return (
    <aside className="npc-panel">
      <div className="panel-kicker">RESIDENT FILE / {npc.id.toUpperCase()}</div>
      <header className="npc-heading">
        <span className="portrait" style={{ "--npc-color": npc.profile.color } as React.CSSProperties}>{npc.profile.name[0]}</span>
        <div>
          <h2>{npc.profile.name}</h2>
          <p>{npc.profile.role}</p>
        </div>
        <span className="mood">{npc.state.mood}</span>
      </header>

      <p className="personality">{npc.profile.personality}</p>
      <div className="reason-card">
        <div>
          <span className={`mode-dot ${npc.state.action.source}`} />
          此刻的决定 · {npc.state.action.source === "deepseek" ? "DeepSeek" : "Mock"}
        </div>
        <strong>“{npc.state.action.reason}”</strong>
      </div>

      <div className="needs">
        <NeedBar label="精力" value={npc.state.needs.energy} />
        <NeedBar label="饱腹" value={npc.state.needs.hunger} inverse />
        <NeedBar label="陪伴" value={npc.state.needs.social} inverse />
      </div>

      <div className="memory-block">
        <div className="section-title"><span>最近记忆</span><small>保留 20 条</small></div>
        {memories.map((memory, index) => <p key={`${memory}-${index}`}>{memory}</p>)}
      </div>

      <button className="primary-button" onClick={onChat}>和{npc.profile.name}说话 <span>↗</span></button>
    </aside>
  );
}

function ChatDrawer({ npc, lines, busy, onClose, onSend }: {
  npc: NPC;
  lines: ChatLine[];
  busy: boolean;
  onClose: () => void;
  onSend: (message: string) => Promise<void>;
}) {
  const [message, setMessage] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    const text = message.trim();
    if (!text || busy) return;
    setMessage("");
    await onSend(text);
  }
  return (
    <div className="drawer-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="chat-drawer" aria-label={`与${npc.profile.name}对话`}>
        <header>
          <div><small>正在交谈</small><h2>{npc.profile.name}</h2></div>
          <button className="icon-button" onClick={onClose} aria-label="关闭对话">×</button>
        </header>
        <div className="chat-lines">
          {lines.length === 0 && <p className="chat-empty">她正做着自己的事。说点什么吧。</p>}
          {lines.map((line, index) => (
            <div key={index} className={`chat-line ${line.from}`}><span>{line.text}</span></div>
          ))}
          {busy && <div className="chat-line npc"><span className="typing">正在想……</span></div>}
        </div>
        <form onSubmit={submit}>
          <input value={message} onChange={(event) => setMessage(event.target.value)} maxLength={500} placeholder="问问今天发生了什么……" autoFocus />
          <button type="submit" disabled={busy || !message.trim()}>发送</button>
        </form>
      </section>
    </div>
  );
}

export default function App() {
  const [world, setWorld] = useState<World | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [selectedId, setSelectedId] = useState("momo");
  const [chatting, setChatting] = useState(false);
  const [chatLines, setChatLines] = useState<Record<string, ChatLine[]>>({});
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function refresh() {
    const [nextWorld, nextHealth] = await Promise.all([api.world(), api.health()]);
    setWorld(nextWorld);
    setHealth(nextHealth);
  }

  useEffect(() => {
    refresh().catch((err) => setError(err.message));
    const stream = new EventSource("/api/events");
    stream.addEventListener("world", () => api.world().then(setWorld).catch(() => undefined));
    return () => stream.close();
  }, []);

  const selectedNpc = useMemo(
    () => world?.npcs.find((npc) => npc.id === selectedId) ?? world?.npcs[0],
    [world, selectedId],
  );

  async function run(label: string, action: () => Promise<World | unknown>) {
    setBusy(label);
    setError("");
    try {
      const result = await action();
      if (result && typeof result === "object" && "npcs" in result) setWorld(result as World);
      else await refresh();
      setNotice(label);
      window.setTimeout(() => setNotice(""), 2200);
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setBusy("");
    }
  }

  async function sendChat(message: string) {
    if (!selectedNpc) return;
    const npcId = selectedNpc.id;
    setChatLines((current) => ({ ...current, [npcId]: [...(current[npcId] ?? []), { from: "player", text: message }] }));
    setBusy("对话生成中");
    try {
      const response = await api.chat(npcId, message);
      const additions: ChatLine[] = [{ from: "npc", text: response.reply }];
      if (response.fallback_reason) additions.push({ from: "system", text: response.fallback_reason });
      setChatLines((current) => ({ ...current, [npcId]: [...(current[npcId] ?? []), ...additions] }));
      setWorld(await api.world());
    } catch (err) {
      setChatLines((current) => ({
        ...current,
        [npcId]: [...(current[npcId] ?? []), { from: "system", text: err instanceof Error ? err.message : "对话失败" }],
      }));
    } finally {
      setBusy("");
    }
  }

  if (!world || !selectedNpc) {
    return <main className="loading"><div className="newt-loader">≈</div><p>{error || "正在等小镇醒来……"}</p></main>;
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand"><span className="brand-mark">≈</span><div><h1>INCONNEWT</h1><p>新螈镇观察站</p></div></div>
        <div className="world-status">
          <span>{timeText(world)}</span><i />
          <span>{world.weather}</span><i />
          <span className={`ai-status ${health?.ai_mode ?? "mock"}`}><b />{health?.ai_mode === "deepseek" ? "DEEPSEEK V4" : "MOCK WORLD"}</span>
        </div>
        <div className="save-actions">
          <button onClick={() => run("存档完成", api.save)} disabled={Boolean(busy)}>保存</button>
          <button onClick={() => run("已恢复存档", api.load)} disabled={Boolean(busy)}>恢复</button>
        </div>
      </header>

      <div className="announcement"><span>公告板</span><p>{world.announcement}</p></div>
      {(error || notice) && <div className={`toast ${error ? "error" : ""}`}>{error || notice}</div>}

      <div className="main-grid">
        <TownMap world={world} selectedId={selectedNpc.id} onSelect={setSelectedId} />
        <NPCPanel npc={selectedNpc} onChat={() => setChatting(true)} />
      </div>

      <section className="control-deck">
        <div className="control-heading"><small>GENTLE INTERVENTIONS</small><h2>给世界一点轻微的推动</h2></div>
        <div className="control-group"><span>天气</span><button onClick={() => run("天气已切换", () => api.worldAction("weather", "晴"))}>放晴</button><button onClick={() => run("雾正在靠近", () => api.worldAction("weather", "雾"))}>起雾</button></div>
        <div className="control-group"><span>公告</span><button onClick={() => run("旧照片已贴出", () => api.worldAction("announcement", "公告板贴出一张来自劫前的旧照片。"))}>贴旧照片</button></div>
        <div className="control-group"><span>礼物</span><button onClick={() => run("礼物已送达", () => api.worldAction("gift", selectedNpc.id === "momo" ? "一枚旧唱片" : "一包番茄种子", selectedNpc.id))}>送给{selectedNpc.profile.name}</button></div>
        <button className="tick-button" onClick={() => run("世界推进了一刻", api.tick)} disabled={Boolean(busy)}><span>{busy || "推进一刻"}</span><b>→</b></button>
      </section>

      <section className="event-strip">
        <div className="section-title"><span>镇上刚刚发生</span><small>LIVE / SSE</small></div>
        <div className="event-list">
          {world.recent_events.length === 0 && <p className="empty-event">还很安静。推进一刻，看看谁会先动起来。</p>}
          {world.recent_events.slice(0, 5).map((event) => <article key={event.id}><time>{event.at}</time><p>{event.text}</p></article>)}
        </div>
      </section>

      <footer><span>INCONNU × NEWT</span><p>未知之中，也保留再生的能力。</p><small>Demo v0.1.1</small></footer>

      {chatting && <ChatDrawer npc={selectedNpc} lines={chatLines[selectedNpc.id] ?? []} busy={busy === "对话生成中"} onClose={() => setChatting(false)} onSend={sendChat} />}
    </main>
  );
}
