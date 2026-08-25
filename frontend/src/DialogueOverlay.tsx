import { FormEvent, useState } from "react";
import type { NPC } from "./api";

export type DialogueLine = { from: "player" | "npc" | "system"; text: string; source?: string };

export function DialogueOverlay({ npc, lines, busy, onClose, onSend }: {
  npc: NPC;
  lines: DialogueLine[];
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
  const latestNpc = [...lines].reverse().find((line) => line.from === "npc");
  return (
    <section className={`dialogue-overlay mood-${npc.state.mood}`}>
      <div className="dialogue-vignette" />
      <button className="dialogue-close" onClick={onClose}>结束交谈 ×</button>
      <div className={`dialogue-portrait resident-art resident-${npc.id}`} />
      <div className="dialogue-scene-label"><span>LOCATION</span><p>{npc.profile.role} · {npc.state.mood}</p></div>
      <div className="dialogue-box">
        <header><strong>{npc.profile.name}</strong><span>{npc.profile.codename}</span><small>{latestNpc?.source ?? npc.state.action.source}</small></header>
        <div className="dialogue-copy">
          {latestNpc ? latestNpc.text : <i>她停下手里的事，朝你看过来。</i>}
          {busy && <b className="type-caret" />}
        </div>
        <div className="dialogue-history">
          {lines.slice(-5, -1).map((line, index) => <p key={index} className={line.from}><span>{line.from === "player" ? "你" : line.from === "npc" ? npc.profile.name : "系统"}</span>{line.text}</p>)}
        </div>
        <form onSubmit={submit}>
          <span>PLAYER INPUT</span>
          <input value={message} onChange={(event) => setMessage(event.target.value)} placeholder="问问她今天的计划，或者刚才遇见了谁……" maxLength={500} autoFocus />
          <button disabled={busy || !message.trim()}>{busy ? "回应正在抵达" : "说出这句话 →"}</button>
        </form>
      </div>
    </section>
  );
}
