"""AI 助手路由。"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.agent import agent_orchestrator
from app.agent.llm import llm_client
from app.api.deps import current_user, db_session
from app.core.config import settings
from app.models import AgentMessage, AgentSession, User
from app.schemas import (
    AgentChatRequest,
    AgentMessageOut,
    AgentResponse,
    AgentSessionDetail,
    AgentSessionOut,
    TraceStep,
)
from app.services import auth_service

router = APIRouter(prefix="/agent", tags=["agent"])


def _msg_out(m: AgentMessage) -> AgentMessageOut:
    try:
        trace = json.loads(m.trace_json or "[]")
    except json.JSONDecodeError:
        trace = []
    return AgentMessageOut(
        id=m.id,
        role=m.role,
        content=m.content,
        intent=m.intent,
        risk_level=m.risk_level,
        demo_mode=m.demo_mode,
        trace=[TraceStep(**s) for s in trace],
        created_at=m.created_at,
    )


@router.post("/chat", response_model=AgentResponse, summary="AI 对话")
def chat(
    payload: AgentChatRequest,
    request: Request,
    db: Session = Depends(db_session),
    user: User = Depends(current_user),
) -> AgentResponse:
    from app.security.rate_limiter import check_and_increment

    # Agent Chat 限流（30次/分钟/用户）
    check_and_increment(
        db, scope="agent_chat", identifier=f"user:{user.username}",
        limit=settings.rate_limit_agent_per_minute, window_seconds=60,
    )
    # 账户归属校验：Agent 对话只能操作当前用户被授权的账户
    auth_service.ensure_account_access(db, user, payload.account_id)
    result = agent_orchestrator.chat(
        db,
        message=payload.message,
        session_id=payload.session_id,
        account_id=payload.account_id,
        actor=user.username,
        auth_ctx={
            "user_id": user.id,
            "username": user.username,
            "authorized_account_ids": auth_service.account_ids_for_user(db, user.id),
        },
    )
    return AgentResponse(**result)


@router.get("/sessions", response_model=list[AgentSessionOut], summary="会话列表")
def sessions(
    db: Session = Depends(db_session),
    user: User = Depends(current_user),
) -> list[AgentSessionOut]:
    allowed = set(auth_service.account_ids_for_user(db, user.id))
    rows = db.execute(
        select(AgentSession).order_by(desc(AgentSession.updated_at)).limit(30)
    ).scalars()
    return [
        AgentSessionOut(
            session_id=s.session_id,
            title=s.title,
            message_count=s.message_count,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in rows
        if s.account_id is None or s.account_id in allowed
    ]


@router.get("/sessions/{session_id}", response_model=AgentSessionDetail, summary="会话详情")
def session_detail(
    session_id: str,
    db: Session = Depends(db_session),
    user: User = Depends(current_user),
) -> AgentSessionDetail:
    session = db.execute(
        select(AgentSession).where(AgentSession.session_id == session_id)
    ).scalar_one_or_none()
    if session is None:
        from app.core.errors import NotFoundError

        raise NotFoundError(f"会话 {session_id} 不存在")

    # 会话归属校验
    if session.account_id is not None:
        auth_service.ensure_account_access(db, user, session.account_id)

    messages = db.execute(
        select(AgentMessage)
        .where(AgentMessage.session_id == session.id)
        .order_by(AgentMessage.id)
    ).scalars()

    return AgentSessionDetail(
        session=AgentSessionOut(
            session_id=session.session_id,
            title=session.title,
            message_count=session.message_count,
            created_at=session.created_at,
            updated_at=session.updated_at,
        ),
        messages=[_msg_out(m) for m in messages],
    )


@router.get("/capabilities", summary="Agent 能力与运行模式")
def capabilities() -> dict:
    from app.agent.tools import list_tools
    from app.security.circuit_breaker import circuit_breaker

    return {
        "demo_mode": not llm_client.enabled,
        "demo_mode_notice": llm_client.demo_notice,
        "llm_model": settings.llm_model if llm_client.enabled else "本地规则引擎",
        "llm_base_url": settings.llm_base_url if llm_client.enabled else None,
        "tools": list_tools(),
        "circuit_breaker": circuit_breaker.snapshot(),
        "intents": [
            "transfer",
            "bill_analysis",
            "card_query",
            "card_virtual_apply",
            "card_lost",
            "card_freeze",
            "account_overview",
            "payee_query",
            "audit_query",
            "help",
        ],
    }
