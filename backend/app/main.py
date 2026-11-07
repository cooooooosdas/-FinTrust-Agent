"""金枢 FinTrust Agent —— FastAPI 应用入口。

启动：
    cd backend && uvicorn app.main:app --reload --port 8000
或：
    cd backend && python run.py
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.agent.llm import llm_client
from app.api.routes import accounts, agent, audit, auth, cards, payees, system, transactions, transfers
from app.core.config import settings
from app.core.database import init_db
from app.core.errors import (
    AppError,
    app_error_handler,
    http_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("fintrust")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_database_dir()
    init_db()
    logger.info("数据库已就绪：%s", settings.database_url)
    _bootstrap_demo_users()
    _expire_stale_orders()
    if llm_client.enabled:
        logger.info("LLM 已配置：%s (%s)", settings.llm_model, settings.llm_base_url)
    else:
        logger.info("未配置 LLM_API_KEY —— Agent 运行在本地演示模式（规则引擎）")
    yield
    logger.info("服务已关闭")


def _bootstrap_demo_users() -> None:
    """启动时确保演示用户存在并绑定账户（幂等，不重置余额与流水）。"""
    from app.core.database import SessionLocal
    from app.models import Account
    from app.services import auth_service

    db = SessionLocal()
    try:
        accounts = db.query(Account).order_by(Account.id).all()
        if not accounts:
            logger.warning("无账户数据，跳过演示用户创建")
            return
        auth_service.create_demo_user(db, "demo_user_1", settings.demo_user_1_password, accounts[0].id)
        if len(accounts) >= 2:
            auth_service.create_demo_user(db, "demo_user_2", settings.demo_user_2_password, accounts[1].id)
        logger.info("演示用户已就绪（demo_user_1 / demo_user_2）")
    except Exception as exc:  # pragma: no cover
        logger.warning("演示用户创建失败：%s", exc)
    finally:
        db.close()


def _expire_stale_orders() -> None:
    """启动时清理过期工单（无需调度框架）。"""
    from app.core.database import SessionLocal
    from app.services import transfer_service

    db = SessionLocal()
    try:
        n = transfer_service.expire_stale_orders(db)
        if n:
            logger.info("已过期 %d 个转账工单", n)
    except Exception as exc:  # pragma: no cover
        logger.warning("过期工单清理失败：%s", exc)
    finally:
        db.close()


app = FastAPI(
    title=settings.app_name,
    description=(
        "面向银行业务的可信 AI 智能体系统。内置三级权限策略引擎（绿 / 黄 / 红），"
        "权限判定完全在服务端执行，模型无法自行决定操作范围。"
    ),
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# ----------------------------------------------------------------------
# CORS
# ----------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Trace-Id"],
)

# ----------------------------------------------------------------------
# 中间件：Trace ID + 访问日志
# ----------------------------------------------------------------------
@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    trace_id = request.headers.get("X-Trace-Id") or uuid.uuid4().hex[:16]
    request.state.trace_id = trace_id
    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = int((time.perf_counter() - started) * 1000)
    response.headers["X-Trace-Id"] = trace_id
    response.headers["X-Response-Time"] = f"{duration_ms}ms"
    if request.url.path.startswith(settings.api_prefix):
        logger.info(
            "%s %s -> %s (%dms) [%s]",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            trace_id,
        )
    return response


# ----------------------------------------------------------------------
# 统一异常处理
# ----------------------------------------------------------------------
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(StarletteHTTPException, http_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)


# ----------------------------------------------------------------------
# 路由注册
# ----------------------------------------------------------------------
for module in (system, accounts, cards, transactions, payees, transfers, agent, audit, auth):
    app.include_router(module.router, prefix=settings.api_prefix)


@app.get("/", include_in_schema=False)
def root() -> JSONResponse:
    return JSONResponse(
        {
            "app": settings.app_name,
            "version": __version__,
            "docs": "/docs",
            "api": settings.api_prefix,
            "demo_mode": not llm_client.enabled,
            "notice": llm_client.demo_notice,
        }
    )


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
