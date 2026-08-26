from __future__ import annotations

import json

from app.services.remote_access import remote_tunnel

REMOTE_HTTP_PATHS = {
    "/health",
    "/enrollment/redeem",
    "/agent/ingest",
    "/agent/credential-lease",
    "/agent/portal-location",
    "/agent/demo-invoice/prepare",
    "/agent/demo-invoice/submit",
}
REMOTE_WEBSOCKET_PATHS = {"/ws/agent"}


class RemoteAgentOnlyMiddleware:
    """Keep the public tunnel agent-only; the dashboard and Fort Knox remain local."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        scope_type = scope.get("type")
        if scope_type not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        public_host = remote_tunnel.public_hostname()
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        request_host = headers.get(b"host", b"").decode("ascii", "ignore").split(":", 1)[0].lower()
        is_remote = bool(public_host and request_host == public_host)
        path = str(scope.get("path") or "")
        allowed = path in (REMOTE_WEBSOCKET_PATHS if scope_type == "websocket" else REMOTE_HTTP_PATHS)
        if not is_remote or allowed:
            await self.app(scope, receive, send)
            return
        if scope_type == "websocket":
            await send({"type": "websocket.close", "code": 4404, "reason": "REMOTE_AGENT_ONLY"})
            return
        body = json.dumps({"detail": "Endpoint non disponibile sul collegamento Agent"}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 404,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
            }
        )
        await send({"type": "http.response.body", "body": body})
