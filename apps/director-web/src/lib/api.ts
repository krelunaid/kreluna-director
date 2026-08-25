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
  active_task_id?: string | null;
  connected: boolean;
  job?: string;
  program?: string;
  enrollment_code?: string;
  retired?: boolean;
  needs_update?: boolean;
  supported_platforms?: Array<"macos" | "windows">;
};

export type Task = {
  id: string;
  goal: string;
  capability: string;
  args: Record<string, unknown>;
  risk: string;
  status: string;
  needs_approval: boolean;
  assigned_device_id?: string | null;
  result: Record<string, unknown>;
  error: string | null;
  error_state?: "active" | "historical" | null;
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
  active_errors: number;
  historical_errors: number;
  kill_armed: boolean;
  ai_connected?: boolean;
  ai_model?: string;
  ai_provider?: "grok" | "ollama" | "openai";
  ai_provider_label?: string;
  ai_status?: string;
  ai_detail?: string;
};

export type AIProviderOption = {
  provider: "grok" | "ollama" | "openai";
  label: string;
  model: string;
  configured: boolean;
  key_saved: boolean;
  managed: boolean;
  configurable: boolean;
};

export type AIHealth = {
  provider: "grok" | "ollama" | "openai";
  label: string;
  model: string;
  configured: boolean;
  connected: boolean;
  status: string;
  detail: string;
  managed: boolean;
  configurable: boolean;
};

export type UpdateStatus = {
  state: "available" | "current" | "unavailable";
  available: boolean;
  current_version: string;
  latest_version: string;
  notes: string;
  platform: "macos" | "windows" | "unknown";
  download_url: string;
  checksum_url: string;
  release_url: string;
  published_at: string;
};

export type VaultCredential = {
  id: string;
  client_name: string;
  portal: string;
  credential_label: string;
  secret_kind: string;
  username_masked: string;
  status: "ready" | "error";
  updated_at: string | null;
};

export type VaultPreview = {
  recognized: number;
  rows: Array<{
    row_number: number;
    client_name: string;
    portal: string;
    username_masked: string;
    secret_kind: string;
    credential_label: string;
  }>;
  warnings: Array<{ row_number: number; message: string }>;
  truncated: boolean;
  processed_locally: boolean;
  sent_to_ai: boolean;
};

const TOKEN_KEY = "kreluna.token";

export function token(): string | null {
  return sessionStorage.getItem(TOKEN_KEY) || localStorage.getItem(TOKEN_KEY);
}

export function tokenIsPersistent(): boolean {
  return Boolean(localStorage.getItem(TOKEN_KEY));
}

export function setToken(value: string | null, persistent = true) {
  localStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(TOKEN_KEY);
  if (!value) return;
  (persistent ? localStorage : sessionStorage).setItem(TOKEN_KEY, value);
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

async function upload<T>(path: string, file: File): Promise<T> {
  const headers = new Headers();
  const current = token();
  if (current) headers.set("Authorization", `Bearer ${current}`);
  const body = new FormData();
  body.set("file", file, file.name);
  const response = await fetch(path, { method: "POST", headers, body });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = payload.detail || JSON.stringify(payload);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

async function authenticatedBlob(path: string): Promise<Blob> {
  const headers = new Headers();
  const current = token();
  if (current) headers.set("Authorization", `Bearer ${current}`);
  const response = await fetch(path, { headers });
  if (!response.ok) throw new Error("Download non riuscito");
  return response.blob();
}

export const api = {
  login: (email: string, password: string, rememberDevice = true) =>
    request<{ token: string; expires_in: number; user: { name: string; email: string; role: string } }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password, remember_device: rememberDevice }),
    }),
  refreshSession: (rememberDevice = true) =>
    request<{ token: string; expires_in: number }>("/auth/refresh", {
      method: "POST",
      body: JSON.stringify({ remember_device: rememberDevice }),
    }),
  health: () => request<{ ok: boolean; version: string }>("/health"),
  updateStatus: () => request<UpdateStatus>("/update/status"),
  updateManifest: () =>
    request<{ manifest: { version: string; notes: string }; signature: string }>("/update/manifest"),
  installUpdate: () =>
    request<{ ok: boolean; state: "restarting"; version: string }>("/update/install", {
      method: "POST",
    }),
  me: () => request<{ name: string; email: string; role: string; license_state: string }>("/me"),
  overview: () => request<Overview>("/overview"),
  aiProviders: () => request<{ selected: string; providers: AIProviderOption[] }>("/ai/providers"),
  vaultCredentials: () =>
    request<{ credentials: VaultCredential[]; count: number }>("/vault/credentials"),
  previewVaultCsv: (file: File) => upload<VaultPreview>("/vault/import/preview", file),
  importVaultCsv: (file: File) =>
    upload<{
      ok: boolean;
      created: number;
      updated: number;
      rejected: number;
      warnings: Array<{ row_number: number; message: string }>;
      source_file_retained: boolean;
      sent_to_ai: boolean;
    }>("/vault/import", file),
  checkVaultCredential: (id: string) =>
    request<{ ok: boolean; state: string; detail: string }>(`/vault/credentials/${id}/check`, {
      method: "POST",
    }),
  revokeVaultCredential: (id: string) =>
    request<{ ok: boolean; state: string }>(`/vault/credentials/${id}`, { method: "DELETE" }),
  vaultTemplate: () => authenticatedBlob("/vault/template.csv"),
  chooseAIProvider: (provider: string) =>
    request<AIHealth>("/ai/provider", {
      method: "POST",
      body: JSON.stringify({ provider }),
    }),
  configureAI: (provider: string, model: string, apiKey: string) =>
    request<AIHealth>("/ai/configure", {
      method: "POST",
      body: JSON.stringify({ provider, model, api_key: apiKey || null }),
    }),
  agents: () => request<{ agents: Agent[] }>("/agents"),
  issueAgentEnrollment: (agentId: string) =>
    request<{
      agent_id: string;
      enrollment_code: string;
      expires_at: string;
      single_use: true;
    }>(`/agents/${agentId}/enrollment`, { method: "POST" }),
  tasks: () => request<{ tasks: Task[] }>("/tasks"),
  approvals: () => request<{ approvals: Approval[] }>("/approvals"),
  chat: (message: string, history: Array<{ role: "user" | "assistant"; content: string }> = []) =>
    request<{
      ok: boolean;
      summary: string;
      denied?: boolean;
      deny_reason?: string;
      source?: string;
      diagnostic?: { code: string; detail: string } | null;
      tasks: Task[];
    }>(
      "/chat",
      {
        method: "POST",
        body: JSON.stringify({ message, history: history.slice(-8) }),
      },
    ),
  resetChat: () => request<{ ok: boolean }>("/chat/reset", { method: "POST" }),
  kill: () => request<{ ok: boolean; stopped_devices: number }>("/kill-switch", { method: "POST" }),
  cancelTask: (id: string) => request<{ ok: boolean; status: string }>(`/tasks/${id}/cancel`, { method: "POST" }),
  pause: (deviceId: string) => request<{ ok: boolean; requeued_tasks: number }>(`/agents/${deviceId}/pause`, { method: "POST" }),
  resume: (deviceId: string) => request(`/agents/${deviceId}/resume`, { method: "POST" }),
  approve: (id: string) => request(`/approvals/${id}/approve`, { method: "POST", body: JSON.stringify({}) }),
  reject: (id: string) => request(`/approvals/${id}/reject`, { method: "POST", body: JSON.stringify({}) }),
  evidenceUrl: (id: string) => `/evidence/${id}/image`,
};
