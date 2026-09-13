"""工具执行域的受控异常。

与规格 §4.1.6 的失败语义一一对应：
    - ``ToolExecutionConfigError``：**装配期**配置错误（缺件 / 非法）——由装配处捕获后记
      error 并返回 ``None``（§4.1.6-3「不拒绝整个服务进程启动」），不携带 HTTP 语义。
    - ``BodyCipherError``：正文密文加解密失败（§4.1.6-1.1），**绝不静默降级为明文**。
    - ``WorkspaceError``：工作卷创建 / 销毁失败（§3.3）。
    - ``ToolExecutionError``：**执行期**受控失败，携带 HTTP 语义与审计动作（§4.1.6-5）。
"""

from __future__ import annotations


class ToolExecutionConfigError(ValueError):
    """装配期配置错误（fail-closed）：拒绝启用真实执行，但不拒绝整个进程启动。"""


class BodyCipherError(ValueError):
    """正文密文加解密失败（fail-closed）。"""


class WorkspaceError(RuntimeError):
    """工作卷创建 / 销毁失败。"""


class ToolExecutionError(RuntimeError):
    """执行期受控失败：携带 HTTP 语义与审计动作，供调用方映射响应。"""

    def __init__(
        self,
        message: str,
        *,
        http_status: int,
        reason_code: object | None = None,
        audit_action: object | None = None,
        keep_approved: bool = True,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.reason_code = reason_code
        self.audit_action = audit_action
        self.keep_approved = keep_approved
