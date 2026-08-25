import { useEffect, useMemo, useState } from "react";
import { api, type Health, type World } from "./api";
import { ArchivePanel } from "./ArchivePanel";
import { DataMode } from "./DataMode";
import { DialogueOverlay, type DialogueLine } from "./DialogueOverlay";
import { TownStage } from "./TownStage";

function timeText(world: World) {
  const hour = Math.floor(world.minute / 60).toString().padStart(2, "0");
  return `第 ${world.day} 天 / ${hour}:00`;
}

function phaseText(minute: number) {
  const hour = minute / 60;
  if (hour < 6 || hour >= 20) return "夜色压蓝";
  if (hour >= 18) return "篝火初亮";
  if (hour < 9) return "清晨薄光";
  return "日光漫过屋脊";
}

const giftByNpc: Record<string, string> = {
  momo: "一枚旧唱片", lili: "一包番茄种子", xiaoke: "一盒旧螺丝", ajie: "一盏备用灯芯",
};

export default function App() {
  const [world, setWorld] = useState<World | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [archiveId, setArchiveId] = useState<string | null>(null);
  const [dialogueId, setDialogueId] = useState<string | null>(null);
  const [dataMode, setDataMode] = useState(false);
  const [busy, setBusy] = useState("");
  const [banner, setBanner] = useState("");
  const [error, setError] = useState("");
  const [dialogues, setDialogues] = useState<Record<string, DialogueLine[]>>({});

  async function refresh() {
    const [nextWorld, nextHealth] = await Promise.all([api.world(), api.health()]);
    setWorld(nextWorld);
    setHealth(nextHealth);
  }

  useEffect(() => {
    refresh().catch((reason) => setError(reason.message));
    const events = new EventSource("/api/events");
    let refreshTimer: number | undefined;
    let bannerTimer: number | undefined;
    const scheduleWorldRefresh = () => {
      if (refreshTimer !== undefined) return;
      refreshTimer = window.setTimeout(() => {
        refreshTimer = undefined;
        api.world().then(setWorld).catch(() => undefined);
      }, 300);
    };
    events.addEventListener("world", (event) => {
      try {
        const update = JSON.parse((event as MessageEvent).data);
        setBanner(update.text);
        if (bannerTimer !== undefined) window.clearTimeout(bannerTimer);
        bannerTimer = window.setTimeout(() => setBanner(""), 3600);
      } catch { /* 保持世界轮询可用 */ }
      scheduleWorldRefresh();
    });
    return () => {
      events.close();
      if (refreshTimer !== undefined) window.clearTimeout(refreshTimer);
      if (bannerTimer !== undefined) window.clearTimeout(bannerTimer);
    };
  }, []);

  const archiveNpc = useMemo(() => world?.npcs.find((npc) => npc.id === archiveId), [world, archiveId]);
  const dialogueNpc = useMemo(() => world?.npcs.find((npc) => npc.id === dialogueId), [world, dialogueId]);

  async function run(label: string, operation: () => Promise<World | unknown>) {
    setBusy(label);
    setError("");
    try {
      const result = await operation();
      if (result && typeof result === "object" && "npcs" in result) setWorld(result as World);
      else await refresh();
      setBanner(label);
      window.setTimeout(() => setBanner(""), 2800);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "世界没有回应这次操作");
    } finally {
      setBusy("");
    }
  }

  async function sendDialogue(message: string) {
    if (!dialogueNpc) return;
    const npcId = dialogueNpc.id;
    setBusy("对话生成中");
    setDialogues((current) => ({
      ...current,
      [npcId]: [...(current[npcId] ?? []), { from: "player", text: message }, { from: "npc", text: "" }],
    }));
    try {
      const response = await api.chatStream(npcId, message, (delta) => {
        setDialogues((current) => {
          const lines = [...(current[npcId] ?? [])];
          const last = lines.length - 1;
          lines[last] = { ...lines[last], text: `${lines[last]?.text ?? ""}${delta}` };
          return { ...current, [npcId]: lines };
        });
      });
      setDialogues((current) => {
        const lines = [...(current[npcId] ?? [])];
        const last = lines.length - 1;
        lines[last] = { ...lines[last], source: response.source };
        if (response.fallbackReason) lines.push({ from: "system", text: response.fallbackReason });
        return { ...current, [npcId]: lines };
      });
      setWorld(await api.world());
    } catch (reason) {
      setDialogues((current) => ({
        ...current,
        [npcId]: [...(current[npcId] ?? []), { from: "system", text: reason instanceof Error ? reason.message : "对话中断" }],
      }));
    } finally {
      setBusy("");
    }
  }

  if (!world) {
    return <main className="loading-screen"><div className="newt-sigil">≈</div><h1>INCONNEWT</h1><p>{error || "正在等新螈镇醒来……"}</p></main>;
  }

  return (
    <main className={`game-shell weather-${world.weather} ${dialogueNpc ? "dialogue-open" : ""}`}>
      <TownStage world={world} onResidentClick={(npcId) => { setArchiveId(npcId); setDataMode(false); }} />

      <section className="hud-world">
        <div className="brand-lockup"><span className="newt-mark">≈</span><div><h1>INCONNEWT</h1><p>NEW(T) TOWN / LIVE WORLD</p></div></div>
        <div className="world-clock"><strong>{timeText(world)}</strong><span>{world.weather} · {phaseText(world.minute)}</span></div>
      </section>

      <section className="hud-system">
        <span className={`ai-chip ${health?.ai_mode ?? "mock"}`}><i />{health?.ai_mode === "deepseek" ? "DEEPSEEK V4" : "MOCK WORLD"}</span>
        <button onClick={() => run("世界已存档", api.save)} disabled={Boolean(busy)}>保存</button>
        <button onClick={() => run("已恢复最近存档", api.load)} disabled={Boolean(busy)}>恢复</button>
        <button className={dataMode ? "active" : ""} onClick={() => setDataMode(true)}>数据模式</button>
      </section>

      <div className="announcement-ribbon"><b>公告板</b><span>{world.announcement}</span></div>
      {(banner || error) && <div className={`event-banner ${error ? "error" : ""}`}><small>TOWN EVENT</small><p>{error || banner}</p></div>}

      <section className="story-feed">
        <header><span>镇上刚刚发生</span><small>LIVE / SSE</small></header>
        {world.recent_events.slice(0, 3).map((event) => <article key={event.id} className={event.kind}><time>{event.at}</time><p>{event.text}</p></article>)}
      </section>

      <section className="god-controls">
        <div className="control-label"><small>GENTLE INTERVENTIONS</small><strong>轻轻推动世界</strong></div>
        <div className="control-buttons">
          <button onClick={() => run("日光重新落回屋顶", () => api.worldAction("weather", "晴"))}><i>☼</i><span>放晴</span></button>
          <button onClick={() => run("雾从废墟方向漫进小镇", () => api.worldAction("weather", "雾"))}><i>≋</i><span>起雾</span></button>
          <button onClick={() => run("公告板上的旧照片在风里轻响", () => api.worldAction("announcement", "公告板贴出一张来自劫前的旧照片。"))}><i>▧</i><span>贴旧照片</span></button>
          <button disabled={!archiveNpc} onClick={() => archiveNpc && run(`礼物已经送到${archiveNpc.profile.name}手里`, () => api.worldAction("gift", giftByNpc[archiveNpc.id], archiveNpc.id))}><i>◇</i><span>{archiveNpc ? `送给${archiveNpc.profile.name}` : "先选居民"}</span></button>
        </div>
        <button className="advance-button" onClick={() => run("世界向前走了一刻", api.tick)} disabled={Boolean(busy)}><small>{busy || "NEXT TICK"}</small><strong>推进一刻</strong><b>→</b></button>
      </section>

      <div className="version-mark">WORLD v0.2.1 · TICK {world.tick_index}</div>
      {archiveNpc && !dialogueNpc && <ArchivePanel npc={archiveNpc} residents={world.npcs} onClose={() => setArchiveId(null)} onTalk={() => setDialogueId(archiveNpc.id)} />}
      {dataMode && <DataMode world={world} onClose={() => setDataMode(false)} />}
      {dialogueNpc && <DialogueOverlay npc={dialogueNpc} lines={dialogues[dialogueNpc.id] ?? []} busy={busy === "对话生成中"} onClose={() => setDialogueId(null)} onSend={sendDialogue} />}
    </main>
  );
}
