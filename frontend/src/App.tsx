import { useCallback, useEffect, useMemo, useState } from "react";
import { api, rememberWorldId, type SaveInfo, type SessionInfo, type World } from "./api";
import { ArchivePanel } from "./ArchivePanel";
import { DataMode } from "./DataMode";
import { DialogueOverlay, type DialogueLine } from "./DialogueOverlay";
import { BoardComposer, NotebookPanel, PlayerDock } from "./PlayerPanels";
import { SaveManager, TitleScreen } from "./SaveManager";
import { TownStage, type StageCallbacks } from "./TownStage";

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

export default function App() {
  const [world, setWorld] = useState<World | null>(null);
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [entered, setEntered] = useState(false);
  const [saves, setSaves] = useState<SaveInfo[]>([]);
  const [archiveId, setArchiveId] = useState<string | null>(null);
  const [dialogueId, setDialogueId] = useState<string | null>(null);
  const [nearbyNpcId, setNearbyNpcId] = useState<string | null>(null);
  const [dataMode, setDataMode] = useState(false);
  const [observerOpen, setObserverOpen] = useState(false);
  const [notebookTab, setNotebookTab] = useState<"quests" | "journal" | null>(null);
  const [boardOpen, setBoardOpen] = useState(false);
  const [busy, setBusy] = useState("");
  const [banner, setBanner] = useState("");
  const [error, setError] = useState("");
  const [dialogues, setDialogues] = useState<Record<string, DialogueLine[]>>({});

  const refresh = useCallback(async () => {
    const [nextWorld, nextSession] = await Promise.all([api.world(), api.session()]);
    setWorld(nextWorld);
    setSession(nextSession);
    rememberWorldId(nextSession.world_id);
  }, []);

  useEffect(() => {
    api.session().then((nextSession) => {
      setSession(nextSession);
      rememberWorldId(nextSession.world_id);
    }).catch((reason) => setError(reason.message));
  }, []);

  useEffect(() => {
    if (!entered) return;
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
    events.addEventListener("session", (event) => {
      try {
        const update = JSON.parse((event as MessageEvent).data);
        setSession((current) => current ? { ...current, access_mode: update.access_mode } : current);
        if (update.access_mode === "interactive") setBanner("小镇为你的世界腾出了位置，现在可以继续行动。");
      } catch { /* 等待下一次心跳 */ }
    });
    return () => {
      events.close();
      if (refreshTimer !== undefined) window.clearTimeout(refreshTimer);
      if (bannerTimer !== undefined) window.clearTimeout(bannerTimer);
    };
  }, [entered, refresh]);

  const archiveNpc = useMemo(() => world?.npcs.find((npc) => npc.id === archiveId), [world, archiveId]);
  const dialogueNpc = useMemo(() => world?.npcs.find((npc) => npc.id === dialogueId), [world, dialogueId]);

  const run = useCallback(async (label: string, operation: () => Promise<World | unknown>) => {
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
  }, [refresh]);

  async function enterJourney(name: string) {
    setBusy("正在唤醒小镇");
    setError("");
    try {
      const nextWorld = await api.startSession(name);
      const nextSession = await api.session();
      rememberWorldId(nextSession.world_id);
      setWorld(nextWorld);
      setSession(nextSession);
      setEntered(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "旅签没有得到回应");
    } finally {
      setBusy("");
    }
  }

  async function restartJourney(name: string) {
    setBusy("正在重建世界");
    setError("");
    try {
      const nextSession = await api.restartSession(name);
      rememberWorldId(nextSession.world_id);
      setSession(nextSession);
      const nextWorld = await api.world();
      setWorld(nextWorld);
      setDialogues({});
      setEntered(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "没能重新点亮这个世界");
    } finally {
      setBusy("");
    }
  }

  async function openSaveManager() {
    setObserverOpen(true);
    try {
      setSaves((await api.saves()).saves);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "没能打开存档匣");
    }
  }

  function refreshSaves() {
    api.saves().then((result) => setSaves(result.saves)).catch(() => undefined);
  }

  function exportWorld() {
    void run("世界副本已经导出", async () => {
      const blob = await api.exportWorld();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `inconewt-${world?.player.name ?? "traveller"}-day-${world?.day ?? 1}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
      return {};
    });
  }

  function importWorld(file: File) {
    void run("世界副本已经还原", async () => {
      let bundle: unknown;
      try { bundle = JSON.parse(await file.text()); }
      catch { throw new Error("这不是有效的 JSON 存档文件"); }
      return api.importWorld(bundle);
    });
  }

  const stageCallbacks = useMemo<StageCallbacks>(() => ({
    onResidentClick: (npcId) => { setArchiveId(npcId); setDataMode(false); },
    onTalkRequest: (npcId, x, y, location) => {
      api.movePlayer(x, y, location).then(() => {
        setArchiveId(npcId);
        setDialogueId(npcId);
        setDataMode(false);
      }).catch((reason) => setError(reason.message));
    },
    onPlayerMove: (x, y, location) => {
      setWorld((current) => current ? { ...current, player: { ...current.player, x, y, location } } : current);
      api.movePlayer(x, y, location).catch((reason) => setError(reason.message));
    },
    onNearbyChange: setNearbyNpcId,
    onScavengeRequest: (pointId) => { void run("找到了一件可以带走的旧物", () => api.scavenge(pointId)); },
  }), [run]);

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
        if (response.affinityDelta) lines.push({ from: "system", text: `关系变化 +${response.affinityDelta} · ${response.impression ?? "TA 对你有了新的印象"}` });
        if (response.completedQuestId) lines.push({ from: "system", text: "心愿完成，新的记忆已经写进手记。" });
        if (response.revealedSecretId) lines.push({ from: "system", text: "一段经过确认的旧事已收进小镇手记。" });
        return { ...current, [npcId]: lines };
      });
      const [nextWorld, nextSession] = await Promise.all([api.world(), api.session()]);
      setWorld(nextWorld);
      setSession(nextSession);
    } catch (reason) {
      setDialogues((current) => ({
        ...current,
        [npcId]: [...(current[npcId] ?? []), { from: "system", text: reason instanceof Error ? reason.message : "对话中断" }],
      }));
    } finally {
      setBusy("");
    }
  }

  if (!session) {
    return <main className="loading-screen"><div className="newt-sigil">≈</div><h1>INCONNEWT</h1><p>{error || "正在等新螈镇醒来……"}</p></main>;
  }
  if (!entered) return <TitleScreen session={session} busy={Boolean(busy)} error={error} onEnter={enterJourney} onRestart={restartJourney} />;
  if (!world) return <main className="loading-screen"><div className="newt-sigil">≈</div><h1>INCONNEWT</h1><p>{error || "正在唤醒你的新螈镇……"}</p></main>;

  const dialogueLocation = dialogueNpc ? world.locations.find((item) => item.id === dialogueNpc.state.location) : null;
  const presentNames = dialogueNpc ? world.npcs.filter((item) => item.id !== dialogueNpc.id && item.state.location === dialogueNpc.state.location).map((item) => item.profile.name) : [];
  const dialogueContext = dialogueNpc
    ? `${dialogueLocation?.name ?? "镇上的旧路"} · ${Math.floor(world.minute / 60).toString().padStart(2, "0")}:00 · ${world.weather}${presentNames.length ? ` · ${presentNames.join("、")}也在场` : ""}`
    : "";

  return (
    <main className={`game-shell weather-${world.weather} ${dialogueNpc ? "dialogue-open" : ""} ${session.access_mode === "observer" ? "observer-world" : ""}`}>
      <TownStage world={world} callbacks={stageCallbacks} />

      <section className="hud-world">
        <div className="brand-lockup"><span className="newt-mark">≈</span><div><h1>INCONNEWT</h1><p>NEW(T) TOWN / LIVE WORLD</p></div></div>
        <div className="world-clock"><strong>{timeText(world)}</strong><span>{world.weather} · {phaseText(world.minute)}</span></div>
      </section>

      <section className="hud-system">
        <span className={`ai-chip ${session.ai_mode}`} title={`今日 AI 调用 ${session.ai_calls_today}/${session.ai_daily_limit}`}><i />{session.ai_budget_exhausted ? "AI 额度已满 · MOCK" : session.ai_mode === "deepseek" ? "DEEPSEEK V4" : "MOCK WORLD"}</span>
        <button className={dataMode ? "active" : ""} onClick={() => setDataMode(true)}>数据模式</button>
      </section>

      <div className="announcement-ribbon"><b>公告板</b><span>{world.announcement}</span></div>
      {session.access_mode === "observer" && <div className="observer-queue"><b>观察模式</b><span>活跃世界已满；此世界暂时冻结，有空位后会自动接入。</span></div>}
      {(banner || error) && <div className={`event-banner ${error ? "error" : ""}`}><small>TOWN EVENT</small><p>{error || banner}</p></div>}

      <section className="story-feed">
        <header><span>镇上刚刚发生</span><small>LIVE / SSE</small></header>
        {world.recent_events.slice(0, 3).map((event) => <article key={event.id} className={event.kind}><time>{event.at}</time><p>{event.text}</p></article>)}
      </section>

      <PlayerDock
        world={world}
        nearbyNpc={nearbyNpcId}
        onNotebook={setNotebookTab}
        onObserver={() => void openSaveManager()}
        onAppearance={(appearance) => void run("换好了适合赶路的衣服", () => api.setAppearance(appearance))}
        onBoard={() => setBoardOpen(true)}
        onWish={(weather) => void run(weather === "雾" ? "水面升起一层薄雾" : "日光重新落回水潭", () => api.wishWeather(weather))}
      />

      <div className="version-mark">WORLD v0.3.3 · TICK {world.tick_index}</div>
      {archiveNpc && !dialogueNpc && (
        <ArchivePanel
          npc={archiveNpc}
          residents={world.npcs}
          playerRelation={world.player.relationships[archiveNpc.id] ?? { affinity: 0, impression: "仍是陌生人。" }}
          pocket={world.player.pocket}
          canTalk={nearbyNpcId === archiveNpc.id}
          onClose={() => setArchiveId(null)}
          onTalk={() => setDialogueId(archiveNpc.id)}
          onGift={(itemId) => void run(`把口袋里的东西交给了${archiveNpc.profile.name}`, () => api.gift(archiveNpc.id, itemId))}
        />
      )}
      {dataMode && <DataMode world={world} onClose={() => setDataMode(false)} />}
      {observerOpen && <SaveManager
        saves={saves}
        session={session}
        busy={Boolean(busy)}
        onClose={() => setObserverOpen(false)}
        onSave={(slot) => void run(`世界已保存到槽位 ${slot}`, async () => { const result = await api.save(slot); refreshSaves(); return result; })}
        onLoad={(slot, kind) => void run("已恢复所选存档", () => api.load(slot, kind))}
        onExport={exportWorld}
        onImport={importWorld}
        onTick={() => void run("世界向前走了一刻", api.tick)}
        onWeather={(weather) => void run(`观察者将天气改为${weather}`, () => api.worldAction("weather", weather))}
      />}
      {notebookTab && <NotebookPanel world={world} initialTab={notebookTab} onClose={() => setNotebookTab(null)} onAccept={(questId) => void run("心愿已经记进手记", () => api.acceptQuest(questId))} />}
      {boardOpen && <BoardComposer onClose={() => setBoardOpen(false)} onSubmit={(text) => { setBoardOpen(false); void run("你的字留在了公告板上", () => api.postBoard(text)); }} />}
      {dialogueNpc && (
        <DialogueOverlay
          npc={dialogueNpc}
          lines={dialogues[dialogueNpc.id] ?? []}
          busy={busy === "对话生成中"}
          context={dialogueContext}
          locationName={dialogueLocation?.name ?? "镇上的旧路"}
          affinity={world.player.relationships[dialogueNpc.id]?.affinity ?? 0}
          activeWish={world.quests.find((quest) => quest.giver_id === dialogueNpc.id && quest.status !== "completed")}
          onClose={() => setDialogueId(null)}
          onSend={sendDialogue}
        />
      )}
    </main>
  );
}
