#!/usr/bin/env python3
"""Create, inspect, or revoke one Kreluna managed-AI customer license."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_GATEWAY = "https://kreluna-ai-gateway.krelunaid.workers.dev"


def request_json(method: str, path: str, *, body: dict | None = None) -> dict:
    admin_token = os.environ.get("KRELUNA_GATEWAY_ADMIN_TOKEN", "").strip()
    if not admin_token:
        admin_token = getpass.getpass("Token amministrativo Kreluna: ").strip()
    if len(admin_token) < 32:
        raise SystemExit("Token amministrativo mancante o non valido.")
    gateway = os.environ.get("KRELUNA_GATEWAY_URL", DEFAULT_GATEWAY).rstrip("/")
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        gateway + path,
        data=payload,
        method=method,
        headers={
            "Authorization": f"Bearer {admin_token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.load(exc).get("error", {}).get("message", "")
        except (AttributeError, json.JSONDecodeError):
            detail = ""
        raise SystemExit(detail or f"Operazione rifiutata dal gateway ({exc.code}).") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SystemExit(f"Gateway non raggiungibile: {exc.reason}") from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gestione licenze IA Kreluna")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="crea il codice per un cliente")
    create.add_argument("tenant_id", help="identificativo stabile, ad esempio studio-rossi")
    create.add_argument("tenant_name", help="nome visuale del cliente")
    create.add_argument("--plan", default="studio")
    create.add_argument("--daily-requests", type=int, default=500)
    create.add_argument("--monthly-tokens", type=int, default=2_000_000)
    create.add_argument("--expires-at", default=None, help="data ISO 8601 opzionale")
    status = commands.add_parser("status", help="legge utilizzo e stato")
    status.add_argument("license_id")
    revoke = commands.add_parser("revoke", help="revoca immediatamente una licenza")
    revoke.add_argument("license_id")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "create":
        body = {
            "tenant_id": args.tenant_id,
            "tenant_name": args.tenant_name,
            "plan": args.plan,
            "daily_request_limit": args.daily_requests,
            "monthly_token_limit": args.monthly_tokens,
            "expires_at": args.expires_at,
        }
        result = request_json("POST", "/admin/licenses", body=body)
        license_id = result["license"]["id"]
        activation_code = result["token"]
        print(f"Licenza: {license_id}")
        print(f"Cliente: {result['license']['tenant_name']}")
        print(f"Codice di attivazione (mostrato una sola volta): {activation_code}")
        print("Il cliente lo inserisce in Impostazioni → IA Kreluna.")
        return 0
    if args.command == "status":
        result = request_json("GET", f"/admin/licenses/{args.license_id}/usage")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    result = request_json("POST", f"/admin/licenses/{args.license_id}/revoke")
    print("Licenza revocata." if result.get("state") == "revoked" else "Revoca non confermata.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
