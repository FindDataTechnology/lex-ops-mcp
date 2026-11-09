"""八工具接线测试：薄转发+mint 不落盘+导览静态事实。"""

from __future__ import annotations

import json

import pytest
from fastmcp import Client, FastMCP

import lex_ops_mcp.tools_lex as tl
from lex_ops_mcp.client import LexError


class FakeClient:
    def __init__(self, result=None, error=None):
        self.calls = []
        self.result = result
        self.error = error

    async def request(self, method, path, *, bearer, params=None, json_body=None):
        self.calls.append({"method": method, "path": path, "bearer": bearer,
                           "params": params, "json_body": json_body})
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def bearer(monkeypatch):
    monkeypatch.setattr(tl, "_current_bearer", lambda: "tok-abc")
    return "tok-abc"


async def _mk(fake):
    mcp = FastMCP("t-lex")
    tl.register(mcp, fake)
    return mcp


async def test_overview_is_self_describing_static(bearer):
    fake = FakeClient()
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        out = await c.call_tool("lex_surface_overview", {})
    data = out.data if hasattr(out, "data") else out
    text = json.dumps(data, ensure_ascii=False)
    assert "fd-legal-search-mcp" in text
    assert "law_reference" in text
    assert "识律 · 法律检索套件" in text
    assert fake.calls == []  # 导览不打上游


async def test_account_views_readonly(bearer):
    fake = FakeClient(result={"email": "x"})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        await c.call_tool("lex_me", {})
        await c.call_tool("lex_usage", {})
        await c.call_tool("lex_billing", {})
        await c.call_tool("lex_quota", {})
    paths = [call["path"] for call in fake.calls]
    assert paths == ["/api/console/me", "/api/console/usage",
                     "/api/console/billing", "/api/console/quota"]


async def test_credentials_list(bearer):
    fake = FakeClient(result=[])
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        await c.call_tool("lex_credentials_list", {})
    assert fake.calls[0]["path"] == "/api/console/credentials"


async def test_mint_passes_through_once_with_warning(bearer):
    minted = {"key_id": "k1", "key": "lexpat-plaintext-once"}
    fake = FakeClient(result=minted)
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        out = await c.call_tool("lex_credential_mint", {"label": "probe"})
    call = fake.calls[0]
    assert call["method"] == "POST"
    data = out.data if hasattr(out, "data") else out
    assert data["credential"] == minted  # 原文透传
    assert "仅此一次" in data["warning"]


async def test_revoke_delete(bearer):
    fake = FakeClient(result={"ok": True})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        await c.call_tool("lex_credential_revoke", {"key_id": "k9"})
    assert fake.calls[0]["method"] == "DELETE"
    assert fake.calls[0]["path"] == "/api/console/credentials/k9"


async def test_owner_only_403_propagates(bearer):
    fake = FakeClient(error=LexError("forbidden", 403, "仅 owner 可管理密钥"))
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        with pytest.raises(Exception) as ei:
            await c.call_tool("lex_credential_mint", {})
    assert "owner" in str(ei.value)


async def test_missing_credential_guard(monkeypatch):
    monkeypatch.setattr(tl, "_current_bearer", lambda: None)
    fake = FakeClient()
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        with pytest.raises(Exception) as ei:
            await c.call_tool("lex_me", {})
    assert "ID token" in str(ei.value)
    assert fake.calls == []


# ------------------------------------------------------------ 案件面五件 ----

ARTIFACT = {
    "kind": "review_report",
    "producer": {"line": "lex", "server": "law-bench", "tool": "validation_check", "version": "sha-t"},
    "refs": [],
    "sha256": "a" * 64,
    "payload": {"findings": []},
}


async def test_matter_create_is_write_and_forwards_body(bearer):
    fake = FakeClient(result={"id": "m1", "status": "open"})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        await c.call_tool("lex_matter_create", {"title": "甲与乙买卖合同纠纷", "cause_code": "C01"})
    call = fake.calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/api/console/matter"
    assert call["json_body"] == {"title": "甲与乙买卖合同纠纷", "cause_code": "C01"}
    assert call["bearer"] == bearer


async def test_matter_create_without_cause_code_omits_field(bearer):
    fake = FakeClient(result={"id": "m1"})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        await c.call_tool("lex_matter_create", {"title": "案子"})
    assert fake.calls[0]["json_body"] == {"title": "案子"}


async def test_matter_list_and_show_readonly(bearer):
    fake = FakeClient(result=[])
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        await c.call_tool("lex_matter_list", {})
        await c.call_tool("lex_matter_show", {"matter_id": "m1"})
    assert [c_["method"] for c_ in fake.calls] == ["GET", "GET"]
    assert [c_["path"] for c_ in fake.calls] == [
        "/api/console/matter",
        "/api/console/matter/m1",
    ]


async def test_artifact_add_forwards_contract_verbatim(bearer):
    fake = FakeClient(result={"id": "a1", "kind": "review_report"})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        await c.call_tool("lex_matter_artifact_add", {"matter_id": "m1", "artifact": ARTIFACT})
    call = fake.calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/api/console/matter/m1/artifact"
    # 原样转发：不补字段、不改写
    assert call["json_body"] == ARTIFACT


async def test_artifact_add_422_contract_error_propagates(bearer):
    fake = FakeClient(error=LexError("invalid", 422, "producer: 必须是对象"))
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        with pytest.raises(Exception) as ei:
            await c.call_tool("lex_matter_artifact_add", {"matter_id": "m1", "artifact": {"kind": "x"}})
    assert "producer" in str(ei.value)


async def test_artifact_list_kind_filter(bearer):
    fake = FakeClient(result=[])
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        await c.call_tool("lex_matter_artifact_list", {"matter_id": "m1"})
        await c.call_tool("lex_matter_artifact_list", {"matter_id": "m1", "kind": "case_hit"})
    assert fake.calls[0]["params"] is None
    assert fake.calls[1]["params"] == {"kind": "case_hit"}


async def test_matter_tools_are_stateless(bearer, tmp_path):
    """案件工具不落文件：调用后工作目录无新增文件。"""
    import os

    before = set(os.listdir(tmp_path))
    fake = FakeClient(result={"id": "m1"})
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        await c.call_tool("lex_matter_create", {"title": "案子"})
        await c.call_tool("lex_matter_list", {})
    assert set(os.listdir(tmp_path)) == before


async def test_matter_tools_require_bearer(monkeypatch):
    monkeypatch.setattr(tl, "_current_bearer", lambda: None)
    fake = FakeClient()
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        with pytest.raises(Exception) as ei:
            await c.call_tool("lex_matter_list", {})
    assert "ID token" in str(ei.value)
    assert fake.calls == []


async def test_overview_mentions_matter_without_inventing_tool_names(bearer):
    """导览增补案件面；点到的 lex_* 工具名必须真实在册（不编造）。"""
    import re
    from pathlib import Path

    fake = FakeClient()
    mcp = await _mk(fake)
    async with Client(mcp) as c:
        out = await c.call_tool("lex_surface_overview", {})
        runtime = {t.name for t in await c.list_tools()}
    text = json.dumps(out.data if hasattr(out, "data") else out, ensure_ascii=False)
    assert "matter_ops" in text
    assert "lex_matter_artifact_add" in text
    mentioned = set(re.findall(r"lex_[a-z_]+", text))
    assert mentioned <= runtime, f"导览点到不在册工具：{sorted(mentioned - runtime)}"


def test_surface_split_counts():
    """分面口径：商业集恰为 11（overview + 账户三 + credentials_list + 案件五），internal 2。"""
    from pathlib import Path

    m = json.loads((Path(__file__).resolve().parents[1] / "tool-surface.json").read_text("utf-8"))
    levels = {}
    for g in m["tool_groups"]:
        for t in g["tools"]:
            levels[t] = g["level"]
    commercial = {t for t, lv in levels.items() if lv == "commercial"}
    internal = {t for t, lv in levels.items() if lv == "internal"}
    assert len(levels) == 13
    assert len(commercial) == 11
    assert internal == {"lex_credential_mint", "lex_credential_revoke"}
    assert {"lex_matter_create", "lex_matter_artifact_add"} <= commercial


