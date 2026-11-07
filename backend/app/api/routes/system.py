"""系统信息与元数据路由。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import __version__
from app.agent.llm import llm_client
from app.api.deps import db_session
from app.core.config import settings
from app.schemas import HealthResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse, summary="健康检查")
def health(db: Session = Depends(db_session)) -> HealthResponse:
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        db_status = "error"

    return HealthResponse(
        status="ok" if db_status == "connected" else "degraded",
        app=settings.app_name,
        version=__version__,
        environment=settings.app_env,
        demo_mode=settings.is_demo_mode,
        demo_mode_notice=llm_client.demo_notice,
        llm_configured=llm_client.enabled,
        database=db_status,
        time=datetime.now(timezone.utc),
    )


@router.get("/meta/simulation-notice", summary="模拟交易声明")
def simulation_notice() -> dict:
    return {
        "tag": settings.simulation_tag,
        "notice": (
            f"{settings.simulation_tag}：本系统为竞赛演示环境，所有账户、余额、卡片与交易均为本地模拟数据，"
            "不连接任何真实银行账户，不执行任何真实资金交易。"
        ),
        "force_demo_mode": settings.force_demo_mode,
    }
