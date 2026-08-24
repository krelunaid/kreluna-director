export type Agent = {
  device_id: string;
  agent_id: string;
  hostname: string;
  display_name: string;
  capabilities: string[];
  status: string;
  presence: string;
  busy: boolean;
  killed: boolean;
  paused: boolean;
  platform: string;
  last_seen_at: string | null;
  connected: boolean;
  job?: string;
  program?: string;
  enrollment_code?: string;
  retired?: boolean;
};

export type Task = {
  id: string;
  goal: string;
  capability: string;
  args: Record<string, unknown>;
  risk: string;
  status: string;
  needs_approval: boolean;
  result: Record<string, unknown>;
  error: string | null;
  created_at: string | null;
  evidence: { id: string; kind: string; sha256: string }[];
};

export type Approval = {
  id: string;
  task_id: string;
  action: string;
  status: string;
  preview: Record<string, unknown>;
  task: Task | null;
};

export type Overview = {
  license_state: string;
  agents_online: number;
  agents_total: number;
  tasks_today: number;
  running: number;
  pending_approvals: number;
  errors: number;
  kill_armed: boolean;
  ai_connected?: boolean;
  ai_model?: string;
};

const TOKEN_KEY = "kreluna.token";

export function token(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(value: string | null) {
  if (value) localStorage.setItem(TOKEN_KEY, value);
  else localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  const current = token();
  if (current) headers.set("Authorization", `Bearer ${current}`);
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export const api = {
  login: (email: string, password: string) =>
    request<{ token: string; user: { name: string; email: string; role: string } }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  health: () => request<{ ok: boolean; version: string }>("/health"),
  updateManifest: () =>
    request<{ manifest: { version: string; notes: string }; signature: string }>("/update/manifest"),
  me: () => request<{ name: string; email: string; role: string; license_state: string }>("/me"),
  overview: () => request<Overview>("/overview"),
  agents: () => request<{ agents: Agent[] }>("/agents"),
  tasks: () => request<{ tasks: Task[] }>("/tasks"),
  approvals: () => request<{ approvals: Approval[] }>("/approvals"),
  chat: (message: string) =>
    request<{ ok: boolean; summary: string; denied?: boolean; deny_reason?: string; source?: string; tasks: Task[] }>(
      "/chat",
      {
        method: "POST",
        body: JSON.stringify({ message }),
      },
    ),
  kill: () => request<{ ok: boolean; stopped_devices: number }>("/kill-switch", { method: "POST" }),
  cancelTask: (id: string) => request<{ ok: boolean; status: string }>(`/tasks/${id}/cancel`, { method: "POST" }),
  resume: (deviceId: string) => request(`/agents/${deviceId}/resume`, { method: "POST" }),
  approve: (id: string) => request(`/approvals/${id}/approve`, { method: "POST", body: JSON.stringify({}) }),
  reject: (id: string) => request(`/approvals/${id}/reject`, { method: "POST", body: JSON.stringify({}) }),
  evidenceUrl: (id: string) => `/evidence/${id}/image`,
};
