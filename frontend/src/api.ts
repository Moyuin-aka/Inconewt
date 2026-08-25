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

export interface World {
  schema_version: number; tick_index: number; day: number; minute: number; weather: string;
  announcement: string; locations: Location[]; npcs: NPC[]; recent_events: WorldEvent[]; updated_at: string;
}

export interface Health { status: string; ai_mode: ActionSource; model: string; }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
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
): Promise<{ reply: string; source: ActionSource; fallbackReason?: string }> {
  const response = await fetch(`/api/chat/${npcId}/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!response.ok || !response.body) throw new Error(`对话连接失败（${response.status}）`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "", reply = "";
  let source: ActionSource = "mock";
  let fallbackReason: string | undefined;
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
      } else if (event.type === "delta") {
        reply += event.delta;
        onDelta(event.delta);
      }
    }
    if (done) break;
  }
  return { reply, source, fallbackReason };
}

export const api = {
  world: () => request<World>("/api/world"),
  health: () => request<Health>("/api/health"),
  tick: () => request<World>("/api/world/tick", { method: "POST" }),
  chatStream,
  worldAction: (action: string, value: string, npcId?: string) => request<World>("/api/world/actions", {
    method: "POST", body: JSON.stringify({ action, value, npc_id: npcId }),
  }),
  save: () => request<{ message: string; save_id: number }>("/api/world/save", { method: "POST" }),
  load: () => request<World>("/api/world/load", { method: "POST" }),
};
