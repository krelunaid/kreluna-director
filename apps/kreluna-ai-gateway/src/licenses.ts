import { bearerToken, createLicenseToken, sha256Hex } from "./auth";
import { GatewayError } from "./errors";

export type LicenseRow = {
  id: string;
  token_prefix: string;
  tenant_id: string;
  tenant_name: string;
  status: "active" | "suspended" | "revoked";
  plan: string;
  daily_request_limit: number;
  monthly_token_limit: number;
  requests_today: number;
  tokens_this_month: number;
  current_day: string;
  current_month: string;
  expires_at: string | null;
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
};

type QuotaRow = {
  requests_today: number;
  daily_request_limit: number;
  tokens_this_month: number;
  monthly_token_limit: number;
};

type Usage = {
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  costUsdTicks: number;
};

export type NewLicenseInput = {
  tenant_id: string;
  tenant_name: string;
  plan?: string;
  daily_request_limit?: number;
  monthly_token_limit?: number;
  expires_at?: string | null;
};

function dayAndMonth(now: Date): { day: string; month: string; at: string } {
  const at = now.toISOString();
  return { day: at.slice(0, 10), month: at.slice(0, 7), at };
}

function boundedInteger(value: unknown, fallback: number, minimum: number, maximum: number): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value)) return fallback;
  if (value < minimum || value > maximum) {
    throw new GatewayError(400, "invalid_limit", "Limite licenza non valido.");
  }
  return value;
}

function cleanLicenseInput(input: NewLicenseInput): Required<Omit<NewLicenseInput, "expires_at">> & { expires_at: string | null } {
  const tenantId = typeof input.tenant_id === "string" ? input.tenant_id.trim() : "";
  const tenantName = typeof input.tenant_name === "string" ? input.tenant_name.trim() : "";
  const plan = typeof input.plan === "string" ? input.plan.trim() : "studio";
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(tenantId)) {
    throw new GatewayError(400, "invalid_tenant", "Identificativo cliente non valido.");
  }
  if (!tenantName || tenantName.length > 200 || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$/.test(plan)) {
    throw new GatewayError(400, "invalid_license", "Dati licenza non validi.");
  }
  let expiresAt: string | null = null;
  if (input.expires_at) {
    const parsed = new Date(input.expires_at);
    if (!Number.isFinite(parsed.getTime()) || parsed.getTime() <= Date.now()) {
      throw new GatewayError(400, "invalid_expiration", "Scadenza licenza non valida.");
    }
    expiresAt = parsed.toISOString();
  }
  return {
    tenant_id: tenantId,
    tenant_name: tenantName,
    plan,
    daily_request_limit: boundedInteger(input.daily_request_limit, 500, 1, 10000),
    monthly_token_limit: boundedInteger(input.monthly_token_limit, 2_000_000, 1000, 100_000_000),
    expires_at: expiresAt,
  };
}

export async function createLicense(env: Env, input: NewLicenseInput): Promise<{ license: LicenseRow; token: string }> {
  const clean = cleanLicenseInput(input);
  const token = createLicenseToken();
  const tokenHash = await sha256Hex(token);
  const id = crypto.randomUUID();
  const { day, month, at } = dayAndMonth(new Date());
  await env.DB.prepare(
    `INSERT INTO licenses (
      id, token_hash, token_prefix, tenant_id, tenant_name, status, plan,
      daily_request_limit, monthly_token_limit, requests_today, tokens_this_month,
      current_day, current_month, expires_at, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, 0, 0, ?, ?, ?, ?, ?)`,
  ).bind(
    id,
    tokenHash,
    token.slice(0, 20),
    clean.tenant_id,
    clean.tenant_name,
    clean.plan,
    clean.daily_request_limit,
    clean.monthly_token_limit,
    day,
    month,
    clean.expires_at,
    at,
    at,
  ).run();
  const license = await env.DB.prepare("SELECT * FROM licenses WHERE id = ?").bind(id).first<LicenseRow>();
  if (license === null) throw new GatewayError(500, "license_create_failed", "Licenza non creata.");
  return { license, token };
}

export async function authenticateLicense(env: Env, request: Request): Promise<LicenseRow> {
  const token = bearerToken(request);
  const tokenHash = await sha256Hex(token);
  const license = await env.DB.prepare("SELECT * FROM licenses WHERE token_hash = ?").bind(tokenHash).first<LicenseRow>();
  if (license === null) throw new GatewayError(401, "license_invalid", "Licenza Kreluna non valida.");
  if (license.status !== "active") {
    throw new GatewayError(403, "license_inactive", "Licenza Kreluna sospesa o revocata.");
  }
  if (license.expires_at && Date.parse(license.expires_at) <= Date.now()) {
    throw new GatewayError(403, "license_expired", "Licenza Kreluna scaduta.");
  }
  return license;
}

export async function reserveQuota(env: Env, license: LicenseRow, requestsPerMinute: number): Promise<QuotaRow> {
  const { day, month, at } = dayAndMonth(new Date());
  await env.DB.prepare(
    `UPDATE licenses SET
      requests_today = CASE WHEN current_day = ? THEN requests_today ELSE 0 END,
      tokens_this_month = CASE WHEN current_month = ? THEN tokens_this_month ELSE 0 END,
      current_day = ?, current_month = ?, updated_at = ?
     WHERE id = ?`,
  ).bind(day, month, day, month, at, license.id).run();

  const minute = at.slice(0, 16);
  const rate = await env.DB.prepare(
    `INSERT INTO minute_limits (license_id, minute_bucket, requests) VALUES (?, ?, 1)
     ON CONFLICT (license_id, minute_bucket)
     DO UPDATE SET requests = requests + 1
     RETURNING requests`,
  ).bind(license.id, minute).first<{ requests: number }>();
  if (rate === null || rate.requests > requestsPerMinute) {
    throw new GatewayError(429, "rate_limit", "Troppe richieste ravvicinate. Riprova tra un minuto.", 60);
  }

  const quota = await env.DB.prepare(
    `UPDATE licenses SET requests_today = requests_today + 1, last_used_at = ?, updated_at = ?
     WHERE id = ? AND requests_today < daily_request_limit
       AND tokens_this_month < monthly_token_limit
     RETURNING requests_today, daily_request_limit, tokens_this_month, monthly_token_limit`,
  ).bind(at, at, license.id).first<QuotaRow>();
  if (quota === null) {
    throw new GatewayError(429, "quota_exhausted", "Quota Grok della licenza esaurita.");
  }
  return quota;
}

export async function recordUsage(
  env: Env,
  license: LicenseRow,
  requestId: string,
  model: string,
  status: string,
  usage: Usage,
  latencyMs: number,
  errorCode = "",
): Promise<void> {
  const at = new Date().toISOString();
  await env.DB.batch([
    env.DB.prepare(
      "UPDATE licenses SET tokens_this_month = tokens_this_month + ?, updated_at = ? WHERE id = ?",
    ).bind(usage.totalTokens, at, license.id),
    env.DB.prepare(
      `INSERT INTO usage_events (
        id, license_id, request_id, created_at, provider, model, status,
        input_tokens, output_tokens, total_tokens, cost_usd_ticks, latency_ms, error_code
      ) VALUES (?, ?, ?, ?, 'xai', ?, ?, ?, ?, ?, ?, ?, ?)`,
    ).bind(
      crypto.randomUUID(),
      license.id,
      requestId,
      at,
      model,
      status,
      usage.inputTokens,
      usage.outputTokens,
      usage.totalTokens,
      usage.costUsdTicks,
      latencyMs,
      errorCode,
    ),
  ]);
}

export async function revokeLicense(env: Env, id: string): Promise<boolean> {
  const at = new Date().toISOString();
  const row = await env.DB.prepare(
    `UPDATE licenses SET status = 'revoked', revoked_at = ?, updated_at = ?
     WHERE id = ? AND status != 'revoked' RETURNING id`,
  ).bind(at, at, id).first<{ id: string }>();
  return row !== null;
}

export async function licenseById(env: Env, id: string): Promise<LicenseRow | null> {
  return env.DB.prepare("SELECT * FROM licenses WHERE id = ?").bind(id).first<LicenseRow>();
}

export async function usageSummary(env: Env, license: LicenseRow): Promise<Record<string, unknown>> {
  const totals = await env.DB.prepare(
    `SELECT COUNT(*) AS requests, COALESCE(SUM(input_tokens), 0) AS input_tokens,
       COALESCE(SUM(output_tokens), 0) AS output_tokens,
       COALESCE(SUM(total_tokens), 0) AS total_tokens,
       COALESCE(SUM(cost_usd_ticks), 0) AS cost_usd_ticks
     FROM usage_events WHERE license_id = ? AND created_at >= ?`,
  ).bind(license.id, `${new Date().toISOString().slice(0, 7)}-01T00:00:00.000Z`).first<Record<string, number>>();
  return {
    license_id: license.id,
    tenant_id: license.tenant_id,
    tenant_name: license.tenant_name,
    status: license.status,
    plan: license.plan,
    requests_today: license.requests_today,
    daily_request_limit: license.daily_request_limit,
    tokens_this_month: license.tokens_this_month,
    monthly_token_limit: license.monthly_token_limit,
    month: totals ?? {},
    expires_at: license.expires_at,
  };
}

export async function cleanupMinuteLimits(env: Env): Promise<void> {
  const cutoff = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString().slice(0, 16);
  await env.DB.prepare("DELETE FROM minute_limits WHERE minute_bucket < ?").bind(cutoff).run();
}
