"""FastMCP 组装 + ASGI 布线（鉴权门 + /health + /.well-known/line-manifest.json）。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import SERVER_NAME, tools_lex
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

from fd_open_data_protocol.line_ops import assemble as _assemble
from fd_open_data_protocol.line_ops.auth_gate import (  # noqa: F401  (tests monkeypatch server.AuthGateMiddleware)
    AuthGateMiddleware,
    AuthGate,
)
from fd_open_data_protocol.line_ops.wellknown import (
    LINE_MANIFEST_ENV,
    WELL_KNOWN_PATH,
)

#: 清单定位必须锚在本仓 `server.py`，不能锚在 protocol 包里——共享实现的
#: `__file__` 指向 fd_open_data_protocol 的目录，算出来的仓根是错的
#: （2026-11-25 实测：五个消费仓的 manifest_path() 全指到 protocol 包里）。
#: **每次调用读本模块的 `__file__`（不缓存成常量）**：测试会 monkeypatch
#: `server.__file__` 模拟「pip 装的包在 site-packages」，缓存常量会让它打不中。
def _anchor():
    return globals()["__file__"]


def manifest_candidates() -> list:
    from fd_open_data_protocol.line_ops.wellknown import manifest_candidates as _f
    return _f(_anchor())


def manifest_path():
    from fd_open_data_protocol.line_ops.wellknown import manifest_path as _f
    return _f(_anchor())


def manifest_response():
    from fd_open_data_protocol.line_ops.wellknown import manifest_response as _f
    return _f(_anchor())


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
    """完整 ASGI 应用：/health 与线自描述免门；其余（/mcp）走鉴权门（无 Bearer 拒）。

    ASGI 布线由 `fd_open_data_protocol.line_ops.assemble` 提供（openspec:
    enforce-mcp-supply-contract / line-ops-runtime-core）。
    """
    settings_ = settings or Settings.from_env()
    return _assemble(
        lambda: create_server(settings_),
        auth_cache_ttl_seconds=settings_.auth_cache_ttl_seconds,
        gate_cls=AuthGateMiddleware,
        manifest_anchor=_anchor(),
        enable_surface_report=False,
    )
