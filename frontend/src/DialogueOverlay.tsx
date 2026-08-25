import { FormEvent, useEffect, useRef, useState } from "react";
import type { NPC, WishQuest } from "./api";

export type DialogueLine = { from: "player" | "npc" | "system"; text: string; source?: string };

function sourceLabel(source?: string) {
  if (source === "deepseek") return "AI / DEEPSEEK";
  if (source === "mock") return "MOCK";
  return "SESSION";
}

function contextualTopics(npc: NPC, locationName: string, activeWish?: WishQuest) {
  const pendingPlan = npc.plan.items.find((item) => !item.completed);
  const topics = [
    pendingPlan ? `你接下来还要去${pendingPlan.label}吗？` : "今天的计划都做完了吗？",
    `你刚才为什么会想：${npc.state.action.reason.replace(/[。！？]+$/, "")}？`,
    `在${locationName}，你现在最留意什么？`,
  ];
  if (activeWish) topics.unshift(`再说说「${activeWish.title}」那件事吧。`);
  return topics.slice(0, 4);
}

export function DialogueOverlay({ npc, lines, busy, context, locationName, affinity, activeWish, onClose, onSend }: {
  npc: NPC;
  lines: DialogueLine[];
  busy: boolean;
  context: string;
  locationName: string;
  affinity: number;
  activeWish?: WishQuest;
  onClose: () => void;
  onSend: (message: string) => Promise<void>;
}) {
  const [message, setMessage] = useState("");
  const [backlogOpen, setBacklogOpen] = useState(false);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const topics = contextualTopics(npc, locationName, activeWish);
  let latestNpcIndex = -1;
  lines.forEach((line, index) => { if (line.from === "npc") latestNpcIndex = index; });

  useEffect(() => {
    const node = transcriptRef.current;
    if (node) node.scrollTo({ top: node.scrollHeight, behavior: "smooth" });
  }, [lines, busy]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      if (backlogOpen) setBacklogOpen(false);
      else onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [backlogOpen, onClose]);

  async function send(text: string) {
    const value = text.trim();
    if (!value || busy) return;
    setMessage("");
    await onSend(value);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    await send(message);
  }

  return (
    <section className={`dialogue-overlay mood-${npc.state.mood}`}>
      <div className="dialogue-vignette" />
      <div className={`dialogue-portrait resident-art resident-${npc.id}`} />
      <div className="dialogue-scene-label"><span>HERE / NOW</span><p>{context}</p></div>

      <section className="dialogue-box" aria-label={`与${npc.profile.name}交谈`}>
        <header className="dialogue-status">
          <div className="dialogue-speaker"><strong>{npc.profile.name}</strong><span>{npc.profile.codename}</span></div>
          <p><b>好感 {affinity}</b><span>{context}</span></p>
          <div className="dialogue-controls"><button onClick={() => setBacklogOpen(true)}>记录</button><button onClick={onClose}>结束交谈 ×</button></div>
        </header>

        <div className="dialogue-transcript" ref={transcriptRef} aria-live="polite">
          {lines.length === 0 && <div className="dialogue-empty"><small>SCENE 01</small><p>{npc.profile.name}停下手里的事，朝你看过来。</p></div>}
          {lines.map((line, index) => (
            <article key={`${line.from}-${index}`} className={`script-line ${line.from} ${index === latestNpcIndex ? "latest" : ""}`}>
              {line.from === "npc" && <div className={`script-avatar resident-art resident-${npc.id}`} />}
              <div>
                <header><b>{line.from === "player" ? "你" : line.from === "npc" ? npc.profile.name : "小镇记录"}</b><small>{line.from === "npc" ? sourceLabel(line.source) : line.from === "player" ? "PLAYER" : "SYSTEM"}</small></header>
                <p>{line.text || (busy && line.from === "npc" ? "正在组织语言……" : "")}{busy && index === latestNpcIndex && <i className="type-caret" />}</p>
              </div>
            </article>
          ))}
        </div>

        <div className="dialogue-topics" aria-label="情境话题"><small>此刻可以聊</small><div>{topics.map((topic) => <button key={topic} disabled={busy} onClick={() => void send(topic)}>{topic}</button>)}</div></div>

        <form onSubmit={submit}>
          <label htmlFor="dialogue-input">PLAYER INPUT</label>
          <input id="dialogue-input" value={message} onChange={(event) => setMessage(event.target.value)} placeholder={`对${npc.profile.name}说些什么……`} maxLength={500} autoFocus />
          <button disabled={busy || !message.trim()}>{busy ? "回应正在抵达" : "说出这句话 →"}</button>
        </form>
      </section>

      {backlogOpen && <div className="dialogue-backlog" role="dialog" aria-modal="true" aria-label="本次对话记录" onClick={() => setBacklogOpen(false)}>
        <section onClick={(event) => event.stopPropagation()}>
          <header><div><small>SESSION ARCHIVE</small><h2>与{npc.profile.name}的对话记录</h2></div><button onClick={() => setBacklogOpen(false)}>返回对话 ×</button></header>
          <div>
            {lines.length === 0 && <p className="backlog-empty">这次会面还没有留下台词。</p>}
            {lines.map((line, index) => <article key={index} className={line.from}><header><b>{line.from === "player" ? "你" : line.from === "npc" ? npc.profile.name : "系统"}</b><small>{line.from === "npc" ? sourceLabel(line.source) : line.from.toUpperCase()}</small></header><p>{line.text || "……"}</p></article>)}
          </div>
        </section>
      </div>}
    </section>
  );
}
