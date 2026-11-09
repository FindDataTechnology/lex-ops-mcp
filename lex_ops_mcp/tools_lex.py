"""十三工具面（design D2/D3）：导览一 + 账户四 + 凭据三 + 案件五（lex-matter-spine）。

Bearer 从进站 MCP 请求取（get_http_request 原始头——fastmcp 4.1.0 头过滤坑）；
_bearer_or_raise 工具层守卫（家族配方：无凭据不触上游不赌 client）。
案件五件与账户四件同为商业面；mint/revoke 为 internal 分面。
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from .client import MISSING_CREDENTIAL_HINT, LexClient, LexError

# 导览静态事实（与 fd-legal-search-mcp/law-bench 的 tool-surface.json 对齐——
# 上牌口径变更时同步此处；可探测项标注 live）。
LEX_OVERVIEW = {
    "line": "识律（lex）——法律数据·应用·模型",
    "retrieval_mcp": {
        "server": "fd-legal-search-mcp（registry 入口 /fd-legal-search-mcp，已上牌）",
        "groups": {
            "law（commercial）": "law_search / law_read / law_semantic_search / law_reference —— 法条检索、语义检索、条级引用解析（32,275 部法规目录 + Qdrant 语义索引）",
            "case（commercial）": "case_search / case_read —— 类案检索（裁判文书库 ~3,700 万篇）",
            "guide_cases（commercial）": "guide_cases_search / guide_cases_read —— 指导案例检索",
            "legal_docs（internal 骨架）": "legal_docs_search / legal_docs_read —— 五源法律语料（not_wired，诚实报错）",
        },
        "typical_routes": [
            "查法条原文 → law_search，取条级引用 → law_reference",
            "找类案 → case_search（读单案 → case_read）",
            "概念解释/要件拆解 → 装谦面「识律 · 法律检索套件」pack（legal-concept-map 等技能已组合好工具链）",
        ],
    },
    "law_bench_mcp": {
        "server": "law-bench（registry 入口 /law-bench，已上牌：commercial 19 + internal 33）",
        "commercial_surface": "装配/条款读+评审/法条引用/验证审查/合同生成等（52 工具中 19 商业）",
        "notes": "评测/rubric/自愈为 internal 质量基建，不对外售",
    },
    "packs_on_facet": {
        "matrix": [
            "识律 · 法律检索套件（检索研究三件套）",
            "识律 · 诉讼文书套件（起诉状/答辩状/证据目录+要素式格式转换）",
            "识律 · 合同审查套件（五行业审查卡×法条核验）",
            "识律 · 劳动法套件（仲裁全流程+双计算器）",
            "识律 · 刑事辩护套件（认罪认罚/不起诉/庭审发问）",
            "识律 · 民事诉讼套件（请求权基础→要件拆解→争点矩阵六步）",
        ],
        "install": "壹座 → 设置 → 功能集 → 市场搜「识律」；装包即得技能+检索 MCP 接线（registry 凭据）",
    },
    "account_ops(self)": "本 MCP（lex-ops-mcp）：me/usage/billing/quota + 检索凭据 list/mint/revoke——mint 的明文 key 仅返回一次",
    "matter_ops(self)": {
        "summary": "案件脊柱（change lex-matter-spine）：以一个案件归集跨环节产物，形成可逐跳复核的证据链",
        "tools": "lex_matter_create（写）/ lex_matter_list / lex_matter_show / lex_matter_artifact_add（写）/ lex_matter_artifact_list",
        "artifact_contract": "kind + producer{line,server,tool,version} + refs + sha256 + payload；检索类（statute_hit/case_hit）另需 provenance{source,stable_id,as_of}",
        "typical_routes": [
            "开案 → lex_matter_create，拿到 matter_id",
            "检索/类案命中 → lex_matter_artifact_add（kind=statute_hit/case_hit，带 provenance）",
            "写文书或合同 → 登记 doc_draft / elementized / contract_draft（带 sha256）",
            "评审 → 登记 review_report，refs 指向合同与法条产物",
            "签署 → 以合同产物发起（服务端校验 anchor_sha256 与产物 sha256 一致）",
        ],
    },
}


def _current_bearer() -> str | None:
    try:
        from fastmcp.server.dependencies import get_http_request
    except ImportError:
        return None
    req = get_http_request()
    if req is None:
        return None
    auth = (req.headers.get("Authorization") or req.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


def _bearer_or_raise() -> str:
    bearer = _current_bearer()
    if not bearer:
        raise LexError("missing_credential", 401, MISSING_CREDENTIAL_HINT)
    return bearer


def register(mcp: FastMCP, client: LexClient) -> None:
    @mcp.tool
    async def lex_surface_overview() -> Any:
        """识律线全景导览（self-describing）——首次接入识律先调这个。

        返回：检索面（fd-legal-search-mcp 十工具分组+典型作业路由）、law-bench 面、
        六个谦面识律套件矩阵与装包路径、本 MCP 的账户操作面。静态事实+分面口径，
        不编造工具名。
        """
        return LEX_OVERVIEW

    @mcp.tool
    async def lex_me() -> Any:
        """当前身份（GET /api/console/me）——登录身份、客户映射、组织归属。"""
        return await client.request("GET", "/api/console/me", bearer=_bearer_or_raise())

    @mcp.tool
    async def lex_usage() -> Any:
        """用量视图（GET /api/console/usage）——本客户检索调用量与维度。"""
        return await client.request("GET", "/api/console/usage", bearer=_bearer_or_raise())

    @mcp.tool
    async def lex_billing() -> Any:
        """账单视图（GET /api/console/billing）——结算周期与费用构成。"""
        return await client.request("GET", "/api/console/billing", bearer=_bearer_or_raise())

    @mcp.tool
    async def lex_quota() -> Any:
        """配额视图（GET /api/console/quota）——档位配额与余量。"""
        return await client.request(
            "GET", "/api/console/quota", bearer=_bearer_or_raise()
        )

    @mcp.tool
    async def lex_credentials_list() -> Any:
        """检索凭据列表（GET /api/console/credentials）——本客户的长命 PAT（不含明文）。"""
        return await client.request(
            "GET", "/api/console/credentials", bearer=_bearer_or_raise()
        )

    @mcp.tool
    async def lex_credential_mint(label: str | None = None) -> dict[str, Any]:
        """铸造检索凭据（POST /api/console/credentials）——写操作，owner-only（上游判定）。

        返回含一次性明文 key：**仅此一次，立即妥善保存，服务不存副本**。
        """
        body: dict[str, Any] = {}
        if label:
            body["label"] = label
        result = await client.request(
            "POST", "/api/console/credentials", bearer=_bearer_or_raise(), json_body=body
        )
        return {"minted": True, "warning": "明文 key 仅此一次出现，请立即保存", "credential": result}

    @mcp.tool
    async def lex_credential_revoke(key_id: str) -> dict[str, Any]:
        """吊销检索凭据（DELETE /api/console/credentials/{key_id}）——写操作，owner-only。"""
        result = await client.request(
            "DELETE", f"/api/console/credentials/{key_id}", bearer=_bearer_or_raise()
        )
        return {"revoked": True, "result": result}

    # ------------------------------------------------------------ 案件面五件 ----
    # 薄代理 fd-lex 案件 REST；租户判定与产物契约校验由上游权威执行，
    # 本服务不判租户、不缓存案件或产物内容、不落日志（spec lex-ops-mcp）。

    @mcp.tool
    async def lex_matter_create(title: str, cause_code: str | None = None) -> Any:
        """开案（POST /api/console/matter）——写操作。

        案件是识律链路的唯一归集单位：检索命中、类案、要素式文书、合同草稿、
        评审报告与签署任务都登记到同一个 matter 上，形成可逐跳复核的证据链。

        参数：`title` 案件标题（必填，人可读）；`cause_code` 案由码（可缺——
        识别不出案由是常态，不得编造）。
        返回：案件对象（含 id/状态/创建时间）。
        """
        body: dict[str, Any] = {"title": title}
        if cause_code:
            body["cause_code"] = cause_code
        return await client.request(
            "POST", "/api/console/matter", bearer=_bearer_or_raise(), json_body=body
        )

    @mcp.tool
    async def lex_matter_list() -> Any:
        """本案客户的全部案件（GET /api/console/matter）——只读，按创建时间倒序。"""
        return await client.request(
            "GET", "/api/console/matter", bearer=_bearer_or_raise()
        )

    @mcp.tool
    async def lex_matter_show(matter_id: str) -> Any:
        """案件详情（GET /api/console/matter/{matter_id}）——只读，含该案全部产物。

        他人案件与不存在同一语义（404），上游不泄露存在性。
        """
        return await client.request(
            "GET", f"/api/console/matter/{matter_id}", bearer=_bearer_or_raise()
        )

    @mcp.tool
    async def lex_matter_artifact_add(
        matter_id: str, artifact: dict[str, Any]
    ) -> Any:
        """登记一张案卷产物（POST /api/console/matter/{matter_id}/artifact）——写操作。

        `artifact` 必须满足案卷产物契约（`fd-lex/contracts/lex-artifact.schema.json`）：
        - `kind`：statute_hit | case_hit | doc_draft | elementized |
          contract_draft | review_report | esign_task
        - `producer`：`{line, server, tool, version}` 四元（谁产的）
        - `refs`：所引用产物的 id 数组（无依据时传 `[]`，字段必须存在）
        - `sha256`：64 位小写十六进制内容指纹
        - `payload`：该产物自身的结构化内容（不得内联合同/文书全文）
        - `provenance`：检索类（statute_hit / case_hit）**必填**
          `{source, stable_id, as_of}`
        - 可选：`title`、`relation`（cites 默认 | derives_from | supersedes）

        缺任一必填项上游返回 422 并指名字段，本服务原样转述；案件已归档返回 409。
        """
        return await client.request(
            "POST",
            f"/api/console/matter/{matter_id}/artifact",
            bearer=_bearer_or_raise(),
            json_body=artifact,
        )

    @mcp.tool
    async def lex_matter_artifact_list(
        matter_id: str, kind: str | None = None
    ) -> Any:
        """列该案产物（GET /api/console/matter/{matter_id}/artifact）——只读。

        `kind` 可按产物类别过滤；不带则返回全部，按登记顺序。
        """
        params = {"kind": kind} if kind else None
        return await client.request(
            "GET",
            f"/api/console/matter/{matter_id}/artifact",
            bearer=_bearer_or_raise(),
            params=params,
        )

