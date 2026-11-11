"""FastMCP 组装 + ASGI 布线（鉴权门 + /health + /.well-known/line-manifest.json）。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import SERVER_NAME, tools_lex
from .auth_gate import AuthGate, AuthGateMiddleware
from .client import LexClient
from .config import Settings

INSTRUCTIONS = (
    "识律线操作助手：先读 lex_surface_overview 拿全景（检索面怎么用、装什么套件），"
    "再操作账户面（身份/用量/账单/配额）与检索凭据生命周期（列表/铸造/吊销）。"
    "每个调用以你的识律凭据（Logto ID token）执行，组织门禁与 owner-only 上游判定。"
    "铸造的 key 明文仅此一次——提醒用户立即保存。错误如实透传（401=未登录/未开通、"
    "403=门禁或非 owner、404=无此凭据）；空结果如实为空，绝不编造。"
)

_HEALTH_OK = b'{"status":"ok"}'

WELL_KNOWN_PATH = "/.well-known/line-manifest.json"
LINE_MANIFEST_ENV = "LINE_MANIFEST_PATH"
#: 清单是运行期契约，改一次要生效但不能让边缘缓存长期撒谎。
_MANIFEST_CACHE_CONTROL = "public, max-age=300"


def manifest_path() -> Path:
    """仓根 `line-manifest.json`（`LINE_MANIFEST_PATH` 可覆盖）。

    镜像里 `WORKDIR=/app` 且清单随 `COPY line-manifest.json ./` 落到仓根，
    故默认路径在源码运行与容器内都成立（`__file__` 在 `<root>/lex_ops_mcp/`）。
    """
    override = os.environ.get(LINE_MANIFEST_ENV)
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[1] / "line-manifest.json"


def manifest_response() -> tuple[int, bytes, list[tuple[bytes, bytes]]]:
    """(status, body, extra_headers) —— 不读网络、不建会话。

    缺失=404（该线未发布清单，属配置事实）；存在但不可解析=500（属缺陷，
    不能伪装成 404 让调用方以为"本来就没有"）。
    """
    json_headers = [(b"content-type", b"application/json; charset=utf-8")]
    path = manifest_path()
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return 404, b'{"detail":"line-manifest not published"}', json_headers
    except OSError as exc:
        return 500, json.dumps(
            {"detail": f"line-manifest unreadable: {type(exc).__name__}"}).encode(), json_headers
    try:
        json.loads(raw)
    except ValueError:
        return 500, b'{"detail":"line-manifest is not valid JSON"}', json_headers
    return 200, raw, json_headers + [
        (b"cache-control", _MANIFEST_CACHE_CONTROL.encode()),
    ]


def create_server(settings: Settings | None = None) -> "FastMCP":
    from fastmcp import FastMCP

    settings = settings or Settings.from_env()
    mcp = FastMCP(SERVER_NAME, instructions=INSTRUCTIONS)
    client = LexClient(settings.base_url, timeout_seconds=settings.timeout_seconds)
    tools_lex.register(mcp, client)
    mcp._lex_ops_client = client
    mcp._lex_ops_settings = settings
    return mcp


def build_app(settings: Settings | None = None):
    mcp = create_server(settings)
    settings_: Settings = mcp._lex_ops_settings
    mcp_app = mcp.http_app(path="/mcp")
    gate = AuthGateMiddleware(mcp_app, AuthGate(settings_.auth_cache_ttl_seconds))

    async def app(scope, receive, send):
        if scope.get("type") == "http":
            path = (scope.get("path") or "").rstrip("/")
            if path == "/health":
                await send({"type": "http.response.start", "status": 200,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": _HEALTH_OK})
                return
            # 线自描述：公开元数据，必须在鉴权门之前应答（与 /health 同理），
            # 否则平台/客户在未持有本线凭据时连"这条线认哪些钥匙"都读不到。
            if path == WELL_KNOWN_PATH.rstrip("/"):
                status, body, headers = manifest_response()
                await send({"type": "http.response.start", "status": status,
                            "headers": headers + [(b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return
        await gate(scope, receive, send)

    return app
