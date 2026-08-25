import { GatewayError } from "./errors";

const TOKEN_PATTERN = /^kreluna_live_[A-Za-z0-9_-]{40,80}$/;

function base64Url(value: Uint8Array): string {
  let binary = "";
  for (const byte of value) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

export function createLicenseToken(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return `kreluna_live_${base64Url(bytes)}`;
}

export async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function timingSafeSecretEqual(provided: string, expected: string): Promise<boolean> {
  const [providedHash, expectedHash] = await Promise.all([
    crypto.subtle.digest("SHA-256", new TextEncoder().encode(provided)),
    crypto.subtle.digest("SHA-256", new TextEncoder().encode(expected)),
  ]);
  return crypto.subtle.timingSafeEqual(providedHash, expectedHash);
}

export function bearerToken(request: Request, options: { admin?: boolean } = {}): string {
  const admin = options.admin === true;
  const header = request.headers.get("authorization") || "";
  const match = /^Bearer ([^\s]+)$/.exec(header);
  if (!match?.[1]) {
    throw new GatewayError(401, admin ? "admin_authentication" : "license_missing", "Autorizzazione mancante.");
  }
  const token = match[1];
  if (!admin && !TOKEN_PATTERN.test(token)) {
    throw new GatewayError(401, "license_invalid", "Licenza Kreluna non valida.");
  }
  if (admin && (token.length < 32 || token.length > 256)) {
    throw new GatewayError(401, "admin_authentication", "Autorizzazione amministrativa non valida.");
  }
  return token;
}
