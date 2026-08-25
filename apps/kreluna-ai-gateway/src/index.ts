import { bearerToken, timingSafeSecretEqual } from "./auth";
import { GatewayError } from "./errors";
import { jsonResponse, positiveInteger, readJsonLimited } from "./http";
import {
  authenticateLicense,
  cleanupMinuteLimits,
  createLicense,
  licenseById,
  recordUsage,
  reserveQuota,
  revokeLicense,
  usageSummary,
  type NewLicenseInput,
} from "./licenses";
import { fetchChat, fetchModels, safeChatRequest } from "./upstream";

const EMPTY_USAGE = { inputTokens: 0, outputTokens: 0, totalTokens: 0, costUsdTicks: 0 };
const LICENSE_ID_PATTERN = /^[0-9a-f-]{36}$/i;

async function requireAdmin(request: Request, env: Env): Promise<void> {
  const token = bearerToken(request, { admin: true });
  if (!env.ADMIN_TOKEN || !(await timingSafeSecretEqual(token, env.ADMIN_TOKEN))) {
    throw new GatewayError(401, "admin_authentication", "Autorizzazione amministrativa non valida.");
  }
}

function method(request: Request, expected: string): void {
  if (request.method !== expected) throw new GatewayError(405, "method_not_allowed", "Metodo non consentito.");
}

async function handleAdmin(request: Request, env: Env, pathname: string): Promise<Response> {
  await requireAdmin(request, env);
  if (pathname === "/admin/licenses") {
    method(request, "POST");
    const body = await readJsonLimited(request, 8192);
    if (typeof body !== "object" || body === null || Array.isArray(body)) {
      throw new GatewayError(400, "invalid_license", "Dati licenza non validi.");
    }
    const created = await createLicense(env, body as NewLicenseInput);
    return jsonResponse({
      ok: true,
      license: {
        id: created.license.id,
        tenant_id: created.license.tenant_id,
        tenant_name: created.license.tenant_name,
        status: created.license.status,
        plan: created.license.plan,
        daily_request_limit: created.license.daily_request_limit,
        monthly_token_limit: created.license.monthly_token_limit,
        expires_at: created.license.expires_at,
      },
      token: created.token,
      token_returned_once: true,
    }, 201);
  }

  const match = /^\/admin\/licenses\/([^/]+)(?:\/(usage|revoke))?$/.exec(pathname);
  const id = match?.[1] ?? "";
  const action = match?.[2] ?? "usage";
  if (!LICENSE_ID_PATTERN.test(id)) throw new GatewayError(404, "not_found", "Licenza non trovata.");
  if (action === "revoke") {
    method(request, "POST");
    if (!(await revokeLicense(env, id))) throw new GatewayError(404, "not_found", "Licenza non trovata o già revocata.");
    return jsonResponse({ ok: true, state: "revoked" });
  }
  method(request, "GET");
  const license = await licenseById(env, id);
  if (license === null) throw new GatewayError(404, "not_found", "Licenza non trovata.");
  return jsonResponse(await usageSummary(env, license));
}

async function handle(request: Request, env: Env, ctx: ExecutionContext, requestId: string): Promise<Response> {
  const url = new URL(request.url);
  if (url.pathname === "/health") {
    method(request, "GET");
    const configured = Boolean(env.XAI_API_KEY && env.ADMIN_TOKEN);
    return jsonResponse({
      ok: configured,
      service: "kreluna-ai-gateway",
      provider: "xai",
      model: env.GROK_MODEL,
      status: configured ? "configured" : "misconfigured",
    }, configured ? 200 : 503, { "X-Request-Id": requestId });
  }
  if (url.pathname.startsWith("/admin/")) return handleAdmin(request, env, url.pathname);

  if (url.pathname === "/v1/models") {
    method(request, "GET");
    await authenticateLicense(env, request);
    const models = await fetchModels(env);
    return jsonResponse(models, 200, { "X-Request-Id": requestId });
  }
  if (url.pathname === "/v1/license") {
    method(request, "GET");
    const license = await authenticateLicense(env, request);
    return jsonResponse(await usageSummary(env, license), 200, { "X-Request-Id": requestId });
  }
  if (url.pathname === "/v1/chat/completions") {
    method(request, "POST");
    const license = await authenticateLicense(env, request);
    const safeBody = await safeChatRequest(request, env);
    const requestsPerMinute = positiveInteger(env.REQUESTS_PER_MINUTE, 20, 120);
    const quota = await reserveQuota(env, license, requestsPerMinute);
    const started = Date.now();
    try {
      const result = await fetchChat(env, safeBody);
      await recordUsage(env, license, requestId, env.GROK_MODEL, "ok", result.usage, Date.now() - started);
      ctx.waitUntil(cleanupMinuteLimits(env));
      return jsonResponse(result.body, 200, {
        "X-Request-Id": requestId,
        "X-Kreluna-Requests-Remaining": String(Math.max(0, quota.daily_request_limit - quota.requests_today)),
        "X-Kreluna-Tokens-Remaining": String(Math.max(0, quota.monthly_token_limit - quota.tokens_this_month - result.usage.totalTokens)),
      });
    } catch (error) {
      const code = error instanceof GatewayError ? error.code : "provider_error";
      await recordUsage(env, license, requestId, env.GROK_MODEL, "error", EMPTY_USAGE, Date.now() - started, code);
      throw error;
    }
  }
  throw new GatewayError(404, "not_found", "Endpoint non disponibile.");
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const requestId = crypto.randomUUID();
    try {
      return await handle(request, env, ctx, requestId);
    } catch (error) {
      const known = error instanceof GatewayError
        ? error
        : new GatewayError(500, "internal_error", "Errore interno del gateway.");
      console.error(JSON.stringify({
        message: "gateway_request_failed",
        request_id: requestId,
        method: request.method,
        path: new URL(request.url).pathname,
        code: known.code,
        status: known.status,
      }));
      const headers: Record<string, string> = { "X-Request-Id": requestId };
      if (known.retryAfter) headers["Retry-After"] = String(known.retryAfter);
      return jsonResponse({
        error: {
          code: known.code,
          message: known.message,
          request_id: requestId,
        },
      }, known.status, headers);
    }
  },
} satisfies ExportedHandler<Env>;
