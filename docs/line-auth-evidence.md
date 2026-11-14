# 词元客户轨（`ciyuan-sk`）的生效证据

> 这份文档是**仓内证据**，不属于对外的 `line-manifest.json`。
> 清单的每个字段都会随 `https://lex.finddatatech.cloud/.well-known/line-manifest.json`
> 匿名公开、可被索引，所以清单里只留产品语义（`kind: customer-key` + `accepts: ciyuan-sk`
> + `enforced: true`）。Secret 名、内部代码路径、环境变量名、静默失效形态一律写在这里。

## 生效结论

词元客户轨 **2026-11-14 接通并双向实测**：客户拿一把词元签发的线票（`aud=lex`）
经平台网关 `/api/lines/lex/proxy/*` 直接调到本线工具面，不需要本线的公开域名，
也不需要本线自己的钥匙。

## 链路两侧

| 侧 | 位置 | 说明 |
|---|---|---|
| 网关 | `paas` `gateway/line-proxy.js` | 换票 + 转发；车道位置必须在 `registerLineExchange` 之后、`dispatchToCell` 兜底之前 |
| 上游 | `fd-lex` `console_api/line_auth.py` | `require_console_or_line`：先 Logto，再门 K |
| 声明 | 本仓 `line-manifest.json` | `auth_tracks[kind=customer-key].enforced: true` |
| 路由 | 平台 `LINE_EXCHANGE_LINES` 含 `lex` | 不在名单 = 路由根本不存在 |
| 签发钥 | Secret `line-signing-keys` 的 `LINE_EXCHANGE_KEY_LEX` | 缺键 = 网关拒绝换票 |

## 验签的公钥来源

- 公钥经 `LINE_TOKEN_PUBLIC_KEY_PEM` 注入，Secret 名 `fd-lex-line-token`。
- issuer 与网关签发值逐字相同。

## 一条会静默失效的配置（最要紧的坑）

`verify_line_token()` 只在调用方注入 `jwks_client_factory` 时才走 JWKS 分支，
而 `line_auth` **不注入**。因此：

- 只配 `LINE_TOKEN_JWKS_URI` ⇒ 验签以 `NOT_CONFIGURED: no verification key source`
  **静默失效**（不报错、不 500，只是每条请求都被判未配置）。
- 必须配 `LINE_TOKEN_PUBLIC_KEY_PEM`。

## 实测记录（2026-11-14）

- 平台 pod 内铸 `aud=lex` 票 → 本线 `verify_line_token` 通过，subject / email /
  source / scope / jti 全解析。
- 跨线票（`aud=wire`）被拒，且响应里**没有** `x-fd-line` 头。
- 带票 `POST /api/lines/lex/proxy/mcp` 打 JSON-RPC `initialize` → `200` + `x-fd-line: lex`
  + 真 MCP 握手。

## 一个容易被误读的边界

本服务（`lex-ops-mcp`）**只把进站 Bearer 原样转发给上游，自身不验签**。
所以这条轨的「生效」指的是**整条链路可达**，不是「本服务自己做验签」。

## 相关

- 车道开通三件套与回滚：`openspec/changes/gateway-line-key-exchange/`
- 清单字段闭集：`openspec/changes/converge-line-identity-and-keys/specs/line-manifest/spec.md`
- 可达性闸：`fd-infra-deploy/tools/check_line_key_reach.py`（四档：token_ok / lane_ok /
  usable / usable_via_lane）
