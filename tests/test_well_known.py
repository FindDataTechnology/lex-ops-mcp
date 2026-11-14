"""线自描述端点：`/.well-known/line-manifest.json`（公开、免鉴权、零网络）。

判据源=change converge-line-identity-and-keys 的 specs/line-manifest：
清单是运行期契约 —— 缺失=404（配置事实），不可解析=500（缺陷，不伪装 404），
响应体 SHALL 与仓内源逐字段一致（不内联第二份，避免漂移）。
"""

from __future__ import annotations

import json
import re
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


def test_source_manifest_has_no_free_text() -> None:
    """清单的每个字符串都会匿名公开 ⇒ 不许有自由文本说明（`note` 一族）。

    2026-11-15 实测：`auth_tracks[1].note` 有 540 字符，公开载荷里如实包含
    Secret 名、内部代码路径、`LINE_TOKEN_*` 环境变量名，以及一条静默失效形态
    ——对外销售的产品线上，这不叫注释，叫侦察指南。证据已移到
    `docs/line-auth-evidence.md`。

    判据是**键的闭集**而不是长度：一段 20 字的 note 一样能写出 Secret 名。
    """
    doc = json.loads(SOURCE.read_text(encoding="utf-8"))

    allowed = {
        "schema", "line", "public_base_url", "internal_base_url",
        "identity.issuer", "identity.jwks_uri", "identity.jit_policy",
        "billing.plane", "billing.evidence_url", "billing.evidence_path",
        "auth_tracks[].name", "auth_tracks[].kind", "auth_tracks[].accepts",
        "auth_tracks[].migration_task", "scopes[]",
    }

    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                yield from walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(node, list):
            for v in node:
                yield from walk(v, path + "[]")
        elif isinstance(node, str):
            yield path, node

    stray = [p for p, _ in walk(doc) if p not in allowed]
    assert not stray, f"清单里出现自由文本键（会随投影公开）: {stray}；证据请写进 docs/"

    # 内容侧：即使落在允许的字段里，凭据标识 / 内部地址 / 代码路径也不许出现。
    body = json.dumps({k: v for k, v in doc.items() if k != "internal_base_url"}, ensure_ascii=False)
    for pattern, what in (
        (r"fd-[a-z0-9][a-z0-9-]*-(?:token|key)", "Secret 名"),
        (r"\b[A-Z][A-Z0-9_]{2,}(?:TOKEN|SECRET|PASSWORD|PEM)\b", "凭据类环境变量"),
        (r"(?:[\w.-]+/)+[\w.-]+\.(?:py|js|ts|sh|ya?ml)", "内部代码路径"),
    ):
        hit = re.search(pattern, body)
        assert hit is None, f"清单里出现{what}: {hit.group(0)!r}"


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
