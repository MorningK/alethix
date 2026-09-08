"""统一异常与错误码。

错误码规则：{HTTP 状态码 3 位}{业务模块 1 位}{序号 2 位}
    模块：1=文档、2=通用/限流、3=问答、4=会话、9=系统内部

错误响应结构见 prd/05-api-spec.md §1.5。
"""

from __future__ import annotations

from typing import Any

# ---------------- 错误码常量 ----------------
ERR_DOC_PARAM = "4001001"  # 文档相关请求参数校验失败
ERR_DOC_NO_FILE = "4001002"  # 缺少 file 字段
ERR_DOC_TYPE_OR_SIZE = "4001003"  # 文件类型不支持或超过大小限制
ERR_DOC_UNREADABLE = "4001004"  # 文档为空/损坏/无可提取文本
ERR_DOC_QUOTA = "4001005"  # 文档数量超出配额

ERR_RATE_LIMITED = "4002001"  # 请求频率超限（HTTP 429）

ERR_ASK_DOC_FORBIDDEN = "4003001"  # document_ids 含无权访问的文档
ERR_ASK_DOC_NOT_READY = "4003002"  # document_ids 含未处理完成的文档
ERR_ASK_TOO_MANY_DOCS = "4003003"  # 指定文档数超过 20
ERR_ASK_BAD_MAX_ITER = "4003004"  # max_iterations 超出 1~10
ERR_ASK_BAD_QUESTION = "4003005"  # question 为空或超长

ERR_SESSION_PARAM = "4004001"  # 会话参数校验失败

ERR_UNAUTHORIZED = "4010001"  # 未认证或缺少 X-User-Id

ERR_DOC_NOT_FOUND = "4041001"  # 文档不存在（越权也返回此码）
ERR_SESSION_NOT_FOUND = "4044001"  # 会话不存在

ERR_DOC_DELETE_BUSY = "4091002"  # 文档处理中，无法删除

ERR_AGENT_FAILED = "5003001"  # 智能体执行失败
ERR_ANSWER_FAILED = "5003002"  # 答案生成失败
ERR_INTERNAL = "5009001"  # 内部服务错误

ERR_LLM_UNAVAILABLE = "5032001"  # LLM 服务不可用
ERR_VECTORDB_UNAVAILABLE = "5032002"  # 向量库不可用


class ApiError(Exception):
    """业务异常，由全局异常处理器转换为统一错误响应。"""

    def __init__(
        self,
        code: str,
        message: str,
        status: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details


def error_response(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """构造 prd/05-api-spec.md §1.5 定义的错误响应体。"""
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "trace_id": trace_id,
        }
    }
