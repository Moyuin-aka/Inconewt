export type ActionSource = "mock" | "deepseek";

export interface Location {
  id: string;
  name: string;
  description: string;
  tone: string;
}

export interface NPC {
  id: string;
  profile: {
    name: string;
    role: string;
    personality: string;
    backstory: string;
    color: string;
    weights: Record<string, number>;
  };
  state: {
    location: string;
    action: {
      type: string;
      target: string | null;
      say: string;
      reason: string;
      source: ActionSource;
    };
    needs: { energy: number; hunger: number; social: number };
    mood: string;
  };
  memory: { short_term: string[]; diary: string[] };
  relationships: Record<string, { affinity: number; impression: string }>;
}

export interface WorldEvent {
  id: string;
  at: string;
  kind: string;
  text: string;
}

export interface World {
  day: number;
  minute: number;
  weather: string;
  announcement: string;
  locations: Location[];
  npcs: NPC[];
  recent_events: WorldEvent[];
  updated_at: string;
}

export interface Health {
  status: string;
  ai_mode: ActionSource;
  model: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `请求失败（${response.status}）`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  world: () => request<World>("/api/world"),
  health: () => request<Health>("/api/health"),
  tick: () => request<World>("/api/world/tick", { method: "POST" }),
  chat: (npcId: string, message: string) =>
    request<{ reply: string; source: ActionSource; fallback_reason?: string }>(`/api/chat/${npcId}`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),
  worldAction: (action: string, value: string, npcId?: string) =>
    request<World>("/api/world/actions", {
      method: "POST",
      body: JSON.stringify({ action, value, npc_id: npcId }),
    }),
  save: () => request<{ message: string; save_id: number }>("/api/world/save", { method: "POST" }),
  load: () => request<World>("/api/world/load", { method: "POST" }),
};
