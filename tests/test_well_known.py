"""线自描述端点：`/.well-known/line-manifest.json`（公开、免鉴权、零网络）。

判据源=change converge-line-identity-and-keys 的 specs/line-manifest：
清单是运行期契约 —— 缺失=404（配置事实），不可解析=500（缺陷，不伪装 404），
响应体 SHALL 与仓内源逐字段一致（不内联第二份，避免漂移）。
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

import lex_ops_mcp.server as server

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "line-manifest.json"

EXPECTED_TOP_LEVEL = {
    "schema", "line", "public_base_url", "identity",
    "auth_tracks", "scopes", "billing", "surfaces",
}


def _get(app, path: str) -> httpx.Response:
    async def _run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            return await c.get(path)

    return _run()


def test_source_manifest_is_the_projection() -> None:
    """仓内清单只含投影字段：多一个内部键就等于把内部信息公开出去。"""
    doc = json.loads(SOURCE.read_text(encoding="utf-8"))
    assert doc["schema"] == "line-manifest/v1"
    assert set(doc) == EXPECTED_TOP_LEVEL, f"多出/缺少顶层键: {set(doc) ^ EXPECTED_TOP_LEVEL}"
    assert not any(k.startswith("_") for k in doc)


@pytest.mark.asyncio
async def test_well_known_served_without_auth_and_equals_source() -> None:
    app = server.build_app()
    resp = await _get(app, "/.well-known/line-manifest.json")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert "max-age=" in resp.headers.get("cache-control", "")
    # 逐字段等于仓内源（唯一事实源，不另存一份）
    assert resp.json() == json.loads(SOURCE.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_well_known_missing_is_404(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(server.LINE_MANIFEST_ENV, str(tmp_path / "absent.json"))
    app = server.build_app()
    resp = await _get(app, "/.well-known/line-manifest.json")
    assert resp.status_code == 404
    assert "not published" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_well_known_corrupt_is_500_not_404(monkeypatch, tmp_path: Path) -> None:
    corrupt = tmp_path / "line-manifest.json"
    corrupt.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv(server.LINE_MANIFEST_ENV, str(corrupt))
    app = server.build_app()
    resp = await _get(app, "/.well-known/line-manifest.json")
    assert resp.status_code == 500
    assert "not valid JSON" in resp.json()["detail"]


def test_manifest_path_defaults_to_repo_root(monkeypatch) -> None:
    monkeypatch.delenv(server.LINE_MANIFEST_ENV, raising=False)
    assert server.manifest_path() == SOURCE
