import { FormEvent, useEffect, useState } from "react";
import type { SaveInfo, SessionInfo } from "./api";

function dateLabel(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(new Date(value));
}

export function TitleScreen({ session, busy, error, onEnter, onRestart }: {
  session: SessionInfo;
  busy: boolean;
  error: string;
  onEnter: (name: string) => Promise<void>;
  onRestart: (name: string) => Promise<void>;
}) {
  const [name, setName] = useState(session.player_name || "外来者");
  const [confirmRestart, setConfirmRestart] = useState(false);
  useEffect(() => setName(session.player_name || "外来者"), [session.player_name]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    await onEnter(name.trim() || "外来者");
  }

  return (
    <main className="title-screen">
      <div className="title-horizon" />
      <section className="title-card">
        <p className="eyebrow">A SMALL WORLD WAITS / WORLD v0.3.3</p>
        <div className="title-mark">≈</div>
        <h1>INCONNEWT</h1>
        <p className="title-cn">新螈镇</p>
        <p className="title-lead">劫后的日子不会趁你离开时偷偷向前。<br />这座镇只在你回来时醒来。</p>

        {session.recovered && <div className="recovery-note">已凭这台设备留下的旅签，找回你的世界。</div>}
        {session.access_mode === "observer" && (
          <div className="queue-note">当前有 {session.active_worlds} 个世界醒着。你将先以观察者身份进入，空位出现后自动接入。</div>
        )}

        {session.is_new ? (
          <form className="visitor-name" onSubmit={submit}>
            <label htmlFor="visitor-name">镇上的人该怎么称呼你？</label>
            <input id="visitor-name" value={name} onChange={(event) => setName(event.target.value)} maxLength={16} autoFocus />
            <button disabled={busy || !name.trim()}>{busy ? "正在点亮镇灯……" : "走进新螈镇 →"}</button>
          </form>
        ) : (
          <div className="continue-card">
            <small>RETURNING VISITOR</small>
            <strong>{session.player_name}</strong>
            <span>上次留下记录 · {dateLabel(session.updated_at)}</span>
            <button className="primary" disabled={busy} onClick={() => void onEnter(session.player_name)}>
              {busy ? "正在唤醒小镇……" : "继续旅程 →"}
            </button>
            {!confirmRestart ? (
              <button className="text-button" disabled={busy} onClick={() => setConfirmRestart(true)}>重新开始</button>
            ) : (
              <div className="restart-confirm">
                <p>旧世界与三个手动槽都会被废弃，无法撤销。确定从第 1 天清晨重新开始？</p>
                <input value={name} onChange={(event) => setName(event.target.value)} maxLength={16} aria-label="新旅程称呼" />
                <div><button onClick={() => setConfirmRestart(false)}>保留旧旅程</button><button className="danger" disabled={busy} onClick={() => void onRestart(name.trim() || "外来者")}>确认重新开始</button></div>
              </div>
            )}
          </div>
        )}
        {error && <p className="title-error">{error}</p>}
        <footer><span>旅签 {session.world_id.slice(0, 8).toUpperCase()}</span><span>每位访客 · 独立世界</span></footer>
      </section>
    </main>
  );
}

export function SaveManager({ saves, session, busy, onClose, onSave, onLoad, onExport, onImport, onTick, onWeather }: {
  saves: SaveInfo[];
  session: SessionInfo;
  busy: boolean;
  onClose: () => void;
  onSave: (slot: number) => void;
  onLoad: (slot: number, kind: "auto" | "manual") => void;
  onExport: () => void;
  onImport: (file: File) => void;
  onTick: () => void;
  onWeather: (weather: "晴" | "雾") => void;
}) {
  const [pendingLoad, setPendingLoad] = useState<SaveInfo | null>(null);
  const [pendingImport, setPendingImport] = useState<File | null>(null);
  const manual = [1, 2, 3].map((slot) => saves.find((item) => item.kind === "manual" && item.slot === slot));
  const auto = saves.find((item) => item.kind === "auto");

  return (
    <section className="save-overlay" role="dialog" aria-modal="true" aria-label="存档与设置">
      <aside className="save-cabinet">
        <button className="panel-close" onClick={onClose}>×</button>
        <header>
          <p className="eyebrow">TRAVELLER'S ARCHIVE / {session.world_id.slice(0, 8).toUpperCase()}</p>
          <h2>存档与设置</h2>
          <p>世界托管在镇上；这台设备保存一枚旅签，JSON 文件则是你能带走的副本。</p>
        </header>

        {session.access_mode === "observer" && <div className="save-mode-note">观察模式 · 当前只可查看和导出，空位出现后自动恢复操作。</div>}
        {session.ai_budget_exhausted && <div className="save-mode-note ai">今日 AI 额度已用完 · 本世界已无缝切到 Mock 规则模式</div>}

        <div className="save-scroll">
          <section className="auto-save-row">
            <div><small>AUTO / 每 10 TICK</small><h3>自动存档</h3></div>
            {auto ? <p>第 {auto.day} 天 · {String(Math.floor(auto.minute / 60)).padStart(2, "0")}:00<br /><span>{dateLabel(auto.created_at)}</span></p> : <p className="empty">还没有自动记录</p>}
            <button disabled={!auto || busy || session.access_mode === "observer"} onClick={() => auto && setPendingLoad(auto)}>恢复</button>
          </section>

          <section className="manual-slots">
            <header><span>手动存档槽</span><small>MANUAL / 01—03</small></header>
            {manual.map((entry, index) => (
              <article key={index} className={entry ? "filled" : "empty"}>
                <span className="slot-number">{String(index + 1).padStart(2, "0")}</span>
                <div>
                  <small>{entry ? "SCHEMA " + entry.schema_version + " · TICK " + entry.tick_index : "EMPTY SLOT"}</small>
                  <h3>{entry ? "第 " + entry.day + " 天 · " + String(Math.floor(entry.minute / 60)).padStart(2, "0") + ":00" : "尚未留下记录"}</h3>
                  <p>{entry ? dateLabel(entry.created_at) : "保存后会覆盖本槽原有记录"}</p>
                </div>
                <div className="slot-actions">
                  <button disabled={busy || session.access_mode === "observer"} onClick={() => onSave(index + 1)}>{entry ? "覆盖保存" : "保存"}</button>
                  <button disabled={!entry || busy || session.access_mode === "observer"} onClick={() => entry && setPendingLoad(entry)}>恢复</button>
                </div>
              </article>
            ))}
          </section>

          <section className="portable-save">
            <div><small>PORTABLE COPY</small><h3>带走这个世界</h3><p>导出当前世界 JSON；换浏览器或旅签丢失后，可用它还原。</p></div>
            <div><button disabled={busy} onClick={onExport}>导出 JSON ↓</button><label className={busy || session.access_mode === "observer" ? "disabled" : ""}>导入 JSON<input type="file" accept=".json,application/json" disabled={busy || session.access_mode === "observer"} onChange={(event) => setPendingImport(event.target.files?.[0] ?? null)} /></label></div>
          </section>

          <details className="observer-tools">
            <summary>观察者调试工具</summary>
            <p>以下能力仅用于演示，不属于外来者在世界内的行动。</p>
            <div><button disabled={busy || session.access_mode === "observer"} onClick={onTick}>推进一刻</button><button disabled={busy || session.access_mode === "observer"} onClick={() => onWeather("晴")}>直接放晴</button><button disabled={busy || session.access_mode === "observer"} onClick={() => onWeather("雾")}>直接起雾</button></div>
          </details>
        </div>

        {(pendingLoad || pendingImport) && (
          <div className="save-confirm">
            <div>
              <small>OVERWRITE CURRENT WORLD</small>
              <h3>{pendingLoad ? "恢复这份存档？" : "导入这份世界副本？"}</h3>
              <p>当前未另行保存的进度会被覆盖。这个动作无法在完成后撤销。</p>
              <footer>
                <button onClick={() => { setPendingLoad(null); setPendingImport(null); }}>取消</button>
                <button className="danger" onClick={() => {
                  if (pendingLoad) onLoad(pendingLoad.slot, pendingLoad.kind);
                  if (pendingImport) onImport(pendingImport);
                  setPendingLoad(null); setPendingImport(null);
                }}>确认覆盖</button>
              </footer>
            </div>
          </div>
        )}
      </aside>
    </section>
  );
}
