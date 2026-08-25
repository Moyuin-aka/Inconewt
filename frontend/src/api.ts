export type ActionSource = "mock" | "deepseek";

export interface Location {
  id: string; name: string; description: string; tone: string; symbol: string; x: number; y: number;
}

export interface PlanItem {
  id: string; start_minute: number; label: string; action: string; target: string | null;
  activity_id: string | null; completed: boolean;
}

export interface NPC {
  id: string;
  profile: {
    name: string; role: string; codename: string; home: string; personality: string; backstory: string;
    color: string; tags: string[]; weights: Record<string, number>;
    activities: Array<{ id: string; label: string; location: string; narratives: string[] }>;
  };
  state: {
    location: string;
    action: { type: string; target: string | null; activity_id: string | null; say: string; reason: string; source: ActionSource };
    needs: { energy: number; hunger: number; social: number };
    mood: string;
    following_player: boolean;
    intent_queue: Array<{ verb: string; args: Record<string, string>; because: string }>;
  };
  memory: {
    short_term: string[]; diary: string[];
    action_history: Array<{ day: number; minute: number; type: string; reason: string }>;
  };
  plan: { day: number; summary: string; items: PlanItem[]; source: ActionSource };
  relationships: Record<string, { affinity: number; impression: string }>;
}

export interface WorldEvent {
  id: string; at: string; kind: string; text: string; participants: string[];
}

export interface InventoryItem {
  id: string; name: string; description: string; symbol: string;
}

export interface PlayerRelationship { affinity: number; impression: string; }

export interface PlayerState {
  name: string; appearance: "moss" | "ember" | "slate"; location: string; x: number; y: number;
  pocket: InventoryItem[];
  journal: Array<{ id: string; title: string; text: string; source: string; unlocked_at: string }>;
  relationships: Record<string, PlayerRelationship>;
  carried_messages: Array<{ id: string; quest_id: string; from_npc_id: string; to_npc_id: string; text: string }>;
  weather_cooldown_until: number;
}

export interface WishQuest {
  id: string; giver_id: string; type: "fetch" | "message" | "company"; title: string; description: string;
  target_npc_id: string | null; required_item_id: string | null; message: string | null;
  reward: string; secret_id: string | null; status: "offered" | "accepted" | "completed"; source: ActionSource;
}

export interface ScavengePoint {
  id: string; label: string; location: string; x: number; y: number; item: InventoryItem; available: boolean;
}

export interface World {
  schema_version: number; tick_index: number; day: number; minute: number; weather: string;
  announcement: string; locations: Location[]; npcs: NPC[]; player: PlayerState; quests: WishQuest[];
  scavenge_points: ScavengePoint[]; recent_events: WorldEvent[]; updated_at: string;
}

export interface Health { status: string; ai_mode: ActionSource; model: string; }

export interface SessionInfo {
  world_id: string; is_new: boolean; recovered: boolean; player_name: string; updated_at: string;
  access_mode: "interactive" | "observer"; active_worlds: number; max_active_worlds: number;
  ai_mode: ActionSource; ai_budget_exhausted: boolean; ai_calls_today: number; ai_daily_limit: number;
}

export interface SaveInfo {
  id: number; slot: number; kind: "auto" | "manual"; created_at: string;
  schema_version: number; day: number; minute: number; tick_index: number;
}

const WORLD_ID_KEY = "inconewt.world_id";

function recoveryHeader(): Record<string, string> {
  const saved = window.localStorage.getItem(WORLD_ID_KEY);
  return saved ? { "X-World-Id": saved } : {};
}

export function rememberWorldId(worldId: string) {
  window.localStorage.setItem(WORLD_ID_KEY, worldId);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...recoveryHeader(), ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `请求失败（${response.status}）`);
  }
  return response.json() as Promise<T>;
}

async function chatStream(
  npcId: string,
  message: string,
  onDelta: (delta: string) => void,
): Promise<{ reply: string; source: ActionSource; fallbackReason?: string; affinityDelta: number; impression?: string; completedQuestId?: string; revealedSecretId?: string }> {
  const response = await fetch(`/api/chat/${npcId}/stream`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", ...recoveryHeader() },
    body: JSON.stringify({ message }),
  });
  if (!response.ok || !response.body) throw new Error(`对话连接失败（${response.status}）`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "", reply = "";
  let source: ActionSource = "mock";
  let fallbackReason: string | undefined;
  let affinityDelta = 0;
  let impression: string | undefined;
  let completedQuestId: string | undefined;
  let revealedSecretId: string | undefined;
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? "";
    for (const chunk of chunks) {
      const line = chunk.split("\n").find((item) => item.startsWith("data: "));
      if (!line) continue;
      const event = JSON.parse(line.slice(6));
      if (event.type === "meta") {
        source = event.source;
        fallbackReason = event.fallback_reason || undefined;
        affinityDelta = event.affinity_delta ?? 0;
        impression = event.impression || undefined;
        completedQuestId = event.completed_quest_id || undefined;
        revealedSecretId = event.revealed_secret_id || undefined;
      } else if (event.type === "delta") {
        reply += event.delta;
        onDelta(event.delta);
      }
    }
    if (done) break;
  }
  return { reply, source, fallbackReason, affinityDelta, impression, completedQuestId, revealedSecretId };
}

export const api = {
  session: () => request<SessionInfo>("/api/session"),
  startSession: (name: string) => request<World>("/api/session/start", {
    method: "POST", body: JSON.stringify({ name }),
  }),
  restartSession: (name: string) => request<SessionInfo>("/api/session/restart", {
    method: "POST", body: JSON.stringify({ name }),
  }),
  world: () => request<World>("/api/world"),
  health: () => request<Health>("/api/health"),
  tick: () => request<World>("/api/world/tick", { method: "POST" }),
  chatStream,
  worldAction: (action: string, value: string, npcId?: string) => request<World>("/api/world/actions", {
    method: "POST", body: JSON.stringify({ action, value, npc_id: npcId }),
  }),
  movePlayer: (x: number, y: number, location: string) => request<World>("/api/player/move", {
    method: "POST", body: JSON.stringify({ x, y, location }),
  }),
  setAppearance: (appearance: PlayerState["appearance"]) => request<World>("/api/player/appearance", {
    method: "POST", body: JSON.stringify({ appearance }),
  }),
  acceptQuest: (questId: string) => request<World>(`/api/quests/${questId}/accept`, { method: "POST" }),
  scavenge: (pointId: string) => request<World>("/api/player/scavenge", {
    method: "POST", body: JSON.stringify({ point_id: pointId }),
  }),
  gift: (npcId: string, itemId: string) => request<World>("/api/player/gift", {
    method: "POST", body: JSON.stringify({ npc_id: npcId, item_id: itemId }),
  }),
  postBoard: (text: string) => request<World>("/api/board", {
    method: "POST", body: JSON.stringify({ text }),
  }),
  wishWeather: (weather: "晴" | "雾") => request<World>("/api/wish-weather", {
    method: "POST", body: JSON.stringify({ weather }),
  }),
  saves: () => request<{ saves: SaveInfo[] }>("/api/world/saves"),
  save: (slot: number) => request<{ message: string; save_id: number; slot: number }>("/api/world/save", {
    method: "POST", body: JSON.stringify({ slot }),
  }),
  load: (slot: number, kind: "auto" | "manual" = "manual") => request<World>("/api/world/load", {
    method: "POST", body: JSON.stringify({ slot, kind }),
  }),
  exportWorld: async () => {
    const response = await fetch("/api/world/export", { credentials: "include", headers: recoveryHeader() });
    if (!response.ok) throw new Error("导出存档失败");
    return response.blob();
  },
  importWorld: (bundle: unknown) => request<World>("/api/world/import", {
    method: "POST", body: JSON.stringify(bundle),
  }),
};
