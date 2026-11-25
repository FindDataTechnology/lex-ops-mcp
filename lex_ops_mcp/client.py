"""共享客户端的本仓适配（openspec: enforce-mcp-supply-contract / line-ops-runtime-core）。

公共逻辑（httpx、超时、状态码归类、不可达）在
`fd_open_data_protocol.line_ops.client`；本模块保留线自己的错误类名 `LexError`
（工具层与测试按名字捕获它）与上游文案。凭据只经手不落盘。
"""

from __future__ import annotations

from fd_open_data_protocol.line_ops.client import LineClient, LineError


class LexError(LineError):
    """结构化错误：kind + status + 上游 detail 原文（继承共享 LineError，签名不变）。"""


MISSING_CREDENTIAL_HINT = (
    "缺少凭据：识律 console 需要 Bearer Logto ID token（壹座同租户登录后获取；"
    "须已开通识律客户身份）"
)


class LexClient(LineClient):
    """Bearer 原样转发；错误类抛 `LexError`，不可达文案用「识律服务」。"""

    def __init__(self, base_url: str, timeout_seconds: float = 20.0, transport=None):
        super().__init__(
            base_url,
            timeout_seconds,
            transport,
            error_cls=LexError,
            service_label="识律",
            missing_hint=MISSING_CREDENTIAL_HINT,
        )
