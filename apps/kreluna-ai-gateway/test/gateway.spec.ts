import { setupNetwork } from "@msw/cloudflare";
import { env } from "cloudflare:workers";
import { createExecutionContext, waitOnExecutionContext } from "cloudflare:test";
import { http, HttpResponse } from "msw";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import worker from "../src/index";

const IncomingRequest = Request<unknown, IncomingRequestCfProperties>;
const network = setupNetwork();

type LicenseResult = {
  license: { id: string };
  token: string;
  token_returned_once: boolean;
};

async function dispatch(
  path: string,
  init?: RequestInit<IncomingRequestCfProperties>,
): Promise<Response> {
  const context = createExecutionContext();
  const response = await worker.fetch(
    new IncomingRequest(`https://gateway.test${path}`, init),
    env,
    context,
  );
  await waitOnExecutionContext(context);
  return response;
}

async function createTestLicense(overrides: Record<string, unknown> = {}): Promise<LicenseResult> {
  const suffix = crypto.randomUUID();
  const response = await dispatch("/admin/licenses", {
    method: "POST",
    headers: {
      Authorization: "Bearer test-admin-token-that-is-long-enough",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      tenant_id: `test-${suffix}`,
      tenant_name: `Cliente ${suffix}`,
      ...overrides,
    }),
  });
  expect(response.status).toBe(201);
  return response.json<LicenseResult>();
}

function licensedJson(
  token: string,
  body: Record<string, unknown>,
): RequestInit<IncomingRequestCfProperties> {
  return {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

beforeAll(() => network.enable());
afterEach(() => network.resetHandlers());
afterAll(() => network.disable());

describe("Kreluna managed AI gateway", () => {
  it("fails closed when the admin credential is missing", async () => {
    const response = await dispatch("/admin/licenses", { method: "POST", body: "{}" });
    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toMatchObject({
      error: { code: "admin_authentication" },
    });
  });

  it("returns a license token once and stores only its hash", async () => {
    const created = await createTestLicense();
    expect(created.token).toMatch(/^kreluna_live_/);
    expect(created.token_returned_once).toBe(true);

    const row = await env.DB.prepare(
      "SELECT token_hash, token_prefix FROM licenses WHERE id = ?",
    ).bind(created.license.id).first<{ token_hash: string; token_prefix: string }>();
    expect(row?.token_hash).toMatch(/^[0-9a-f]{64}$/);
    expect(row?.token_hash).not.toContain(created.token);
    expect(row?.token_prefix).toBe(created.token.slice(0, 20));
  });

  it("exposes only the configured Grok model after an authenticated health check", async () => {
    const created = await createTestLicense();
    network.use(http.get("https://api.x.ai/v1/models", () => HttpResponse.json({
      object: "list",
      data: [{ id: "grok-4.6" }, { id: "another-model" }],
    })));

    const response = await dispatch("/v1/models", {
      headers: { Authorization: `Bearer ${created.token}` },
    });
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({
      object: "list",
      data: [{ id: "grok-4.6", object: "model", owned_by: "xai" }],
    });

    const rejected = await dispatch("/v1/models", {
      headers: { Authorization: "Bearer kreluna_live_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" },
    });
    expect(rejected.status).toBe(401);
  });

  it("rejects tools and non-text content without consuming the daily quota", async () => {
    const created = await createTestLicense();
    const response = await dispatch("/v1/chat/completions", licensedJson(created.token, {
      model: "grok-4.6",
      messages: [{ role: "user", content: [{ type: "image_url", image_url: "data:image/png;base64,test" }] }],
      tools: [{ type: "function", function: { name: "shell" } }],
    }));
    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toMatchObject({
      error: { code: "unsupported_capability" },
    });

    const row = await env.DB.prepare(
      "SELECT requests_today FROM licenses WHERE id = ?",
    ).bind(created.license.id).first<{ requests_today: number }>();
    expect(row?.requests_today).toBe(0);
  });

  it("forwards a bounded text request and records usage without storing prompts", async () => {
    const created = await createTestLicense();
    let forwarded: Record<string, unknown> | undefined;
    network.use(http.post("https://api.x.ai/v1/chat/completions", async ({ request }) => {
      forwarded = await request.json() as Record<string, unknown>;
      return HttpResponse.json({
        id: "chat-test",
        created: 123,
        choices: [{ message: { role: "assistant", content: "Risposta sicura" }, finish_reason: "stop" }],
        usage: { prompt_tokens: 12, completion_tokens: 5, total_tokens: 17, cost_in_usd_ticks: 42 },
      });
    }));

    const response = await dispatch("/v1/chat/completions", licensedJson(created.token, {
      model: "grok-4.6",
      messages: [{ role: "user", content: "testo-segreto-che-non-va-salvato" }],
      temperature: 1,
      max_tokens: 9999,
    }));
    expect(response.status).toBe(200);
    expect(forwarded).toMatchObject({ model: "grok-4.6", temperature: 0, max_tokens: 600 });
    expect(forwarded).not.toHaveProperty("tools");

    const usage = await env.DB.prepare(
      `SELECT total_tokens, cost_usd_ticks, error_code FROM usage_events
       WHERE license_id = ? ORDER BY created_at DESC LIMIT 1`,
    ).bind(created.license.id).first<Record<string, unknown>>();
    expect(usage).toEqual({ total_tokens: 17, cost_usd_ticks: 42, error_code: "" });

    const schema = await env.DB.prepare("PRAGMA table_info(usage_events)").all<{ name: string }>();
    const columns = schema.results.map((column) => column.name);
    expect(columns).not.toContain("prompt");
    expect(columns).not.toContain("content");
  });

  it("enforces daily quota and revocation", async () => {
    const created = await createTestLicense({ daily_request_limit: 1 });
    network.use(http.post("https://api.x.ai/v1/chat/completions", () => HttpResponse.json({
      choices: [{ message: { role: "assistant", content: "ok" }, finish_reason: "stop" }],
      usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
    })));
    const body = { model: "grok-4.6", messages: [{ role: "user", content: "ciao" }] };
    expect((await dispatch("/v1/chat/completions", licensedJson(created.token, body))).status).toBe(200);

    const exhausted = await dispatch("/v1/chat/completions", licensedJson(created.token, body));
    expect(exhausted.status).toBe(429);
    await expect(exhausted.json()).resolves.toMatchObject({ error: { code: "quota_exhausted" } });

    const revoked = await dispatch(`/admin/licenses/${created.license.id}/revoke`, {
      method: "POST",
      headers: { Authorization: "Bearer test-admin-token-that-is-long-enough" },
    });
    expect(revoked.status).toBe(200);
    const afterRevocation = await dispatch("/v1/license", {
      headers: { Authorization: `Bearer ${created.token}` },
    });
    expect(afterRevocation.status).toBe(403);
  });
});
