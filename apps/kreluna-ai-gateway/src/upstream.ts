import { GatewayError } from "./errors";
import { readJsonLimited, readResponseJsonLimited } from "./http";

type TextMessage = { role: "system" | "user" | "assistant"; content: string };
const MAX_MESSAGE_CHARACTERS = 12_000;
const MAX_CONVERSATION_CHARACTERS = 24_000;
type SafeChatRequest = {
  model: string;
  messages: TextMessage[];
  temperature: number;
  max_tokens: number;
  reasoning_effort: "low";
  response_format?: { type: "json_object" };
};

export type Usage = {
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  costUsdTicks: number;
};

export type ChatResult = {
  body: Record<string, unknown>;
  usage: Usage;
};

function objectValue(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function numberValue(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? Math.trunc(value) : 0;
}

function upstreamUrl(env: Env, path: string): string {
  let base: URL;
  try {
    base = new URL(env.XAI_BASE_URL);
  } catch {
    throw new GatewayError(503, "gateway_misconfigured", "Servizio IA non configurato.");
  }
  if (base.protocol !== "https:" || base.hostname !== "api.x.ai") {
    throw new GatewayError(503, "gateway_misconfigured", "Indirizzo provider non attendibile.");
  }
  return base.toString().replace(/\/$/, "") + path;
}

function providerError(response: Response): GatewayError {
  if (response.status === 401 || response.status === 403) {
    return new GatewayError(503, "provider_authentication", "Collegamento xAI non autorizzato.");
  }
  if (response.status === 429) {
    return new GatewayError(503, "provider_rate_limit", "xAI ha raggiunto il proprio limite temporaneo.", 30);
  }
  if (response.status >= 500) {
    return new GatewayError(503, "provider_unavailable", "xAI non è disponibile.");
  }
  return new GatewayError(502, "provider_rejected", `xAI ha rifiutato la richiesta (${response.status}).`);
}

function parseMessages(payload: Record<string, unknown>): TextMessage[] {
  if (!Array.isArray(payload.messages) || payload.messages.length < 1 || payload.messages.length > 16) {
    throw new GatewayError(400, "invalid_messages", "Sono richiesti da 1 a 16 messaggi testuali.");
  }
  let totalCharacters = 0;
  const messages: TextMessage[] = [];
  for (const raw of payload.messages) {
    const message = objectValue(raw);
    const role = message?.role;
    const content = message?.content;
    if (!message || !["system", "user", "assistant"].includes(String(role)) || typeof content !== "string") {
      throw new GatewayError(400, "text_only", "Il gateway accetta soltanto messaggi di testo.");
    }
    if (!content || content.length > MAX_MESSAGE_CHARACTERS) {
      throw new GatewayError(400, "message_size", "Un messaggio supera il limite consentito.");
    }
    totalCharacters += content.length;
    if (totalCharacters > MAX_CONVERSATION_CHARACTERS) {
      throw new GatewayError(400, "conversation_size", "La conversazione supera il limite consentito.");
    }
    messages.push({ role: role as TextMessage["role"], content });
  }
  return messages;
}

export async function safeChatRequest(request: Request, env: Env): Promise<SafeChatRequest> {
  const maximumBytes = Number.parseInt(env.MAX_REQUEST_BYTES, 10) || 65_536;
  const raw = objectValue(await readJsonLimited(request, Math.min(maximumBytes, 262_144)));
  if (raw === null) throw new GatewayError(400, "invalid_request", "Richiesta IA non valida.");
  for (const forbidden of ["tools", "tool_choice", "functions", "function_call", "stream", "modalities"] as const) {
    if (forbidden in raw) {
      throw new GatewayError(400, "unsupported_capability", "Strumenti, immagini e streaming non sono consentiti.");
    }
  }
  const requestedModel = typeof raw.model === "string" ? raw.model.trim() : "";
  if (requestedModel && requestedModel !== env.GROK_MODEL) {
    throw new GatewayError(400, "model_not_allowed", "Il modello richiesto non è previsto dalla licenza.");
  }
  const maxAllowed = Math.min(Number.parseInt(env.MAX_RESPONSE_TOKENS, 10) || 600, 2000);
  const requestedMax = typeof raw.max_tokens === "number" ? Math.trunc(raw.max_tokens) : maxAllowed;
  if (requestedMax < 1) throw new GatewayError(400, "invalid_max_tokens", "Limite risposta non valido.");
  const responseFormat = objectValue(raw.response_format);
  if (responseFormat !== null && responseFormat.type !== "json_object") {
    throw new GatewayError(400, "invalid_response_format", "Formato risposta non consentito.");
  }
  const safe: SafeChatRequest = {
    model: env.GROK_MODEL,
    messages: parseMessages(raw),
    temperature: 0,
    max_tokens: Math.min(requestedMax, maxAllowed),
    reasoning_effort: "low",
  };
  if (responseFormat?.type === "json_object") safe.response_format = { type: "json_object" };
  return safe;
}

export async function fetchModels(env: Env): Promise<Record<string, unknown>> {
  if (!env.XAI_API_KEY) throw new GatewayError(503, "gateway_misconfigured", "Chiave xAI non configurata sul server.");
  const response = await fetch(upstreamUrl(env, "/models"), {
    headers: { Authorization: `Bearer ${env.XAI_API_KEY}`, Accept: "application/json" },
    signal: AbortSignal.timeout(12_000),
  });
  if (!response.ok) throw providerError(response);
  const payload = objectValue(await readResponseJsonLimited(response, 1_000_000));
  const rows = Array.isArray(payload?.data) ? payload.data : [];
  const configured = rows.some((raw) => {
    const row = objectValue(raw);
    return row?.id === env.GROK_MODEL;
  });
  if (!configured) {
    throw new GatewayError(503, "provider_model_unavailable", "Il modello Grok configurato non è disponibile.");
  }
  return {
    object: "list",
    data: [{ id: env.GROK_MODEL, object: "model", owned_by: "xai" }],
  };
}

export async function fetchChat(env: Env, body: SafeChatRequest): Promise<ChatResult> {
  if (!env.XAI_API_KEY) throw new GatewayError(503, "gateway_misconfigured", "Chiave xAI non configurata sul server.");
  const response = await fetch(upstreamUrl(env, "/chat/completions"), {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.XAI_API_KEY}`,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(35_000),
  });
  if (!response.ok) throw providerError(response);
  const payload = objectValue(await readResponseJsonLimited(response, 1_000_000));
  const choices = Array.isArray(payload?.choices) ? payload.choices : [];
  const first = objectValue(choices[0]);
  const message = objectValue(first?.message);
  if (typeof message?.content !== "string") {
    throw new GatewayError(502, "provider_invalid_response", "xAI non ha restituito testo valido.");
  }
  const usageRaw = objectValue(payload?.usage) ?? {};
  const usage: Usage = {
    inputTokens: numberValue(usageRaw.prompt_tokens ?? usageRaw.input_tokens),
    outputTokens: numberValue(usageRaw.completion_tokens ?? usageRaw.output_tokens),
    totalTokens: numberValue(usageRaw.total_tokens),
    costUsdTicks: numberValue(usageRaw.cost_in_usd_ticks),
  };
  if (usage.totalTokens === 0) usage.totalTokens = usage.inputTokens + usage.outputTokens;
  return {
    body: {
      id: typeof payload?.id === "string" ? payload.id : crypto.randomUUID(),
      object: "chat.completion",
      created: numberValue(payload?.created),
      model: env.GROK_MODEL,
      choices: [{
        index: 0,
        message: { role: "assistant", content: message.content },
        finish_reason: typeof first?.finish_reason === "string" ? first.finish_reason : "stop",
      }],
      usage: {
        prompt_tokens: usage.inputTokens,
        completion_tokens: usage.outputTokens,
        total_tokens: usage.totalTokens,
        cost_in_usd_ticks: usage.costUsdTicks,
      },
    },
    usage,
  };
}
