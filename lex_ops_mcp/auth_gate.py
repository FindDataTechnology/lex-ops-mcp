"""HTTP 层鉴权门（家族「无 Bearer 拒/有 Bearer 放行」变体；上游权威）。"""

from __future__ import annotations

import hashlib
import time


class AuthGate:
    def __init__(self, ttl_seconds: float = 60.0):
        self._ttl = ttl_seconds
        self._cache: dict[str, tuple[float, bool]] = {}

    def _key(self, bearer: str) -> str:
        return hashlib.sha256(bearer.encode()).hexdigest()

    async def check(self, bearer: str | None) -> bool:
        if not bearer:
            return False
        key = self._key(bearer)
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit and now - hit[0] < self._ttl:
            return hit[1]
        self._cache[key] = (now, True)
        return True


class AuthGateMiddleware:
    def __init__(self, app, gate: AuthGate):
        self.app = app
        self.gate = gate

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        path = (scope.get("path") or "").lstrip("/")
        if path != "mcp" and not path.endswith("/mcp"):
            await self.app(scope, receive, send)
            return
        bearer = _bearer_from_scope(scope)
        if await self.gate.check(bearer):
            await self.app(scope, receive, send)
            return
        while True:
            msg = await receive()
            if msg.get("type") == "http.disconnect":
                return
            if msg.get("type") == "http.request" and not msg.get("more_body", False):
                break
        await send(
            {"type": "http.response.start", "status": 401,
             "headers": [(b"content-type", b"application/json")]}
        )
        await send({"type": "http.response.body", "body": b'{"error": "Authentication required"}'})


#: Headers a bearer may arrive in. `authorization` is the standard one; the MCP
#: gateway in front of us forwards the caller's token upstream as
#: `x-authorization` (mcpgw `_get_registry_headers`) and advertises support for
#: both. Reading only the standard header rejected EVERY proxied call with
#: `401 {"error": "Authentication required"}` while a direct request passed —
#: live 2026-11-09: the wire/lex servers were dark behind the gateway and 17
#: packs declaring their tools could not run.
_BEARER_HEADERS = (b"authorization", b"x-authorization")


def _bearer_from_scope(scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name not in _BEARER_HEADERS:
            continue
        text = value.decode("latin-1")
        if text.lower().startswith("bearer "):
            token = text[7:].strip()
            if token:
                return token
    return None
