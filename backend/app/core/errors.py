"""统一异常与错误响应格式。

所有后端错误均返回：
{
  "error": {
    "code": "TRANSFER_LIMIT_EXCEEDED",
    "message": "单日累计转账金额超出限额",
    "detail": {...},
    "trace_id": "..."
  }
}
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    """业务异常基类。"""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "APP_ERROR"
    message: str = "请求处理失败"

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        code: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
        status_code: Optional[int] = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.detail = detail or {}
        self.status_code = status_code or self.status_code
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"
    message = "资源不存在"


class ValidationError(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"
    message = "参数校验失败"


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "PERMISSION_DENIED"
    message = "权限校验未通过"


class UnauthorizedError(AppError):
    """未认证或会话失效。"""

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHORIZED"
    message = "未登录或会话已失效"


class PolicyBlockedError(AppError):
    """被安全策略引擎拦截。"""

    status_code = status.HTTP_403_FORBIDDEN
    code = "POLICY_BLOCKED"
    message = "操作被安全策略拦截"


class ConfirmationRequiredError(AppError):
    """需要用户明确确认（黄色操作）。"""

    status_code = status.HTTP_409_CONFLICT
    code = "CONFIRMATION_REQUIRED"
    message = "该操作需要用户明确确认"


class MFARequiredError(AppError):
    """需要多因子验证（红色操作）。"""

    status_code = status.HTTP_428_PRECONDITION_REQUIRED
    code = "MFA_REQUIRED"
    message = "该操作需要通过多因子身份验证"


class CircuitOpenError(AppError):
    """熔断器打开。"""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "CIRCUIT_OPEN"
    message = "服务暂时不可用，已触发熔断保护"


class IdempotencyConflictError(AppError):
    """幂等键冲突。"""

    status_code = status.HTTP_409_CONFLICT
    code = "IDEMPOTENCY_CONFLICT"
    message = "幂等键已被不同的请求使用"


class LLMUnavailableError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "LLM_UNAVAILABLE"
    message = "模型服务暂时不可用"


def _trace_id(request: Request) -> str:
    return getattr(request.state, "trace_id", None) or uuid.uuid4().hex[:16]


def error_body(
    request: Request,
    code: str,
    message: str,
    detail: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "detail": detail or {},
            "trace_id": _trace_id(request),
        }
    }


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    headers = None
    # 限流错误返回 Retry-After
    if exc.code == "RATE_LIMITED":
        retry_after = exc.detail.get("retry_after") if exc.detail else None
        if retry_after is not None:
            headers = {"Retry-After": str(retry_after)}
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(request, exc.code, exc.message, exc.detail),
        headers=headers,
    )


async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = "HTTP_ERROR"
    message = str(exc.detail) if exc.detail else "请求失败"
    if exc.status_code == 404:
        code = "NOT_FOUND"
    elif exc.status_code == 401:
        code = "UNAUTHORIZED"
    elif exc.status_code == 403:
        code = "PERMISSION_DENIED"
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(request, code, message),
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_body(
            request,
            "VALIDATION_ERROR",
            "参数校验失败",
            {"errors": _jsonable_errors(exc.errors())},
        ),
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_body(request, "INTERNAL_ERROR", "服务内部错误", {"exception": exc.__class__.__name__}),
    )


def _jsonable_errors(errors: Any) -> Any:
    """把 pydantic 校验错误中的非 JSON 类型转成字符串。"""
    cleaned = []
    for item in errors or []:
        entry = {k: v for k, v in item.items() if k != "ctx"}
        ctx = item.get("ctx")
        if ctx:
            entry["ctx"] = {k: str(v) for k, v in ctx.items()}
        cleaned.append(entry)
    return cleaned


__all__ = [
    "AppError",
    "NotFoundError",
    "ValidationError",
    "PermissionDeniedError",
    "UnauthorizedError",
    "PolicyBlockedError",
    "ConfirmationRequiredError",
    "MFARequiredError",
    "CircuitOpenError",
    "IdempotencyConflictError",
    "LLMUnavailableError",
    "app_error_handler",
    "http_error_handler",
    "validation_error_handler",
    "unhandled_error_handler",
    "error_body",
]
