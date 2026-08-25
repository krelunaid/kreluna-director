import { GatewayError } from "./errors";

const SECURITY_HEADERS = {
  "Cache-Control": "no-store",
  "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
} as const;

export function jsonResponse(
  body: unknown,
  status = 200,
  extraHeaders: Record<string, string> = {},
): Response {
  return Response.json(body, {
    status,
    headers: { ...SECURITY_HEADERS, ...extraHeaders },
  });
}

export async function readJsonLimited(request: Request, maxBytes: number): Promise<unknown> {
  const contentType = request.headers.get("content-type")?.split(";", 1)[0]?.trim();
  if (contentType !== "application/json") {
    throw new GatewayError(415, "content_type", "È richiesto Content-Type application/json.");
  }
  const declared = Number(request.headers.get("content-length") || "0");
  if (Number.isFinite(declared) && declared > maxBytes) {
    throw new GatewayError(413, "request_too_large", "La richiesta supera il limite consentito.");
  }
  if (request.body === null) {
    throw new GatewayError(400, "invalid_json", "Il corpo JSON è mancante.");
  }
  const reader = request.body.getReader();
  const decoder = new TextDecoder();
  let total = 0;
  let text = "";
  while (true) {
    const item = await reader.read();
    if (item.done) break;
    total += item.value.byteLength;
    if (total > maxBytes) {
      await reader.cancel();
      throw new GatewayError(413, "request_too_large", "La richiesta supera il limite consentito.");
    }
    text += decoder.decode(item.value, { stream: true });
  }
  text += decoder.decode();
  try {
    return JSON.parse(text);
  } catch {
    throw new GatewayError(400, "invalid_json", "Il corpo JSON non è valido.");
  }
}

export async function readResponseJsonLimited(response: Response, maxBytes: number): Promise<unknown> {
  const declared = Number(response.headers.get("content-length") || "0");
  if (Number.isFinite(declared) && declared > maxBytes) {
    throw new GatewayError(502, "provider_response_too_large", "Risposta IA troppo grande.");
  }
  if (response.body === null) {
    throw new GatewayError(502, "provider_invalid_response", "Risposta IA vuota.");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let total = 0;
  let text = "";
  while (true) {
    const item = await reader.read();
    if (item.done) break;
    total += item.value.byteLength;
    if (total > maxBytes) {
      await reader.cancel();
      throw new GatewayError(502, "provider_response_too_large", "Risposta IA troppo grande.");
    }
    text += decoder.decode(item.value, { stream: true });
  }
  text += decoder.decode();
  try {
    return JSON.parse(text);
  } catch {
    throw new GatewayError(502, "provider_invalid_response", "Risposta IA non valida.");
  }
}

export function positiveInteger(value: string, fallback: number, maximum: number): number {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isSafeInteger(parsed) || parsed <= 0) return fallback;
  return Math.min(parsed, maximum);
}
