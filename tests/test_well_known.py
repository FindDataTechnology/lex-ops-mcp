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

#: 顶层键的**完整**集合。多一个键就等于把内部信息投影出去，所以这里是精确相等
#: 而不是子集断言。`internal_base_url` 是 line-manifest/v1 里被 sanction 的可选投影
#: 字段（converge-line-identity-and-keys 的 `line-manifest` delta：平台网关据此把请求
#: 与线票送到线的内部上游；因为它随 `/.well-known` 对外可见，所以只许 mesh/ClusterIP
#: 形态、禁带凭据）。加它不是放宽守卫——新键必须先在 schema delta 里被写下来。
EXPECTED_TOP_LEVEL = {
    "schema", "line", "public_base_url", "internal_base_url", "identity",
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


def test_manifest_path_falls_back_to_cwd_when_package_is_installed(monkeypatch, tmp_path):
    """pip 装的包在 site-packages 时，`__file__` 祖先里没有清单——必须退到 CWD。

    真机实证（2026-11-11）：镜像 pid1 是 console script，`__file__` 落 site-packages，
    `parents[1]` 不是仓根，于是 /app/line-manifest.json 明明在却回 404。源码运行
    （`python -m lex_ops_mcp.cli`）验不出这个差异，只有装成包才会。
    """
    from lex_ops_mcp import server

    monkeypatch.delenv(server.LINE_MANIFEST_ENV, raising=False)
    # 模拟"包目录里没有清单、CWD 里有"：
    fake_pkg = tmp_path / "site-packages" / "lex_ops_mcp"
    fake_pkg.mkdir(parents=True)
    monkeypatch.setattr(server, "__file__", str(fake_pkg / "server.py"))
    cwd = tmp_path / "app"
    cwd.mkdir()
    (cwd / "line-manifest.json").write_text('{"schema": "line-manifest/v1", "line": "lex"}')
    monkeypatch.chdir(cwd)

    assert server.manifest_path() == cwd / "line-manifest.json"
    assert server.manifest_response()[0] == 200


def test_manifest_path_prefers_env_override(monkeypatch, tmp_path):
    """显式给了 LINE_MANIFEST_PATH 就只认它——配置比搜索链更可信。"""
    from lex_ops_mcp import server

    target = tmp_path / "explicit.json"
    target.write_text('{"schema": "line-manifest/v1", "line": "lex"}')
    monkeypatch.setenv(server.LINE_MANIFEST_ENV, str(target))
    assert server.manifest_candidates() == [target]
    assert server.manifest_path() == target


def test_missing_manifest_is_404_not_500(monkeypatch, tmp_path):
    """三个候选全不存在 = 404（配置事实），不许伪装成 5xx 让运维以为服务坏了。"""
    from lex_ops_mcp import server

    monkeypatch.delenv(server.LINE_MANIFEST_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(server, "__file__", str(tmp_path / "pkg" / "server.py"))
    status, body, _ = server.manifest_response()
    assert status == 404
    assert b"not published" in body
