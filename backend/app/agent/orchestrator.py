"""Agent 编排器：意图识别 → 任务规划 → DAG 执行 → 答复生成 → 轨迹落库。"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.agent.llm import llm_client
from app.agent.nlu import (
    INTENT_ACCOUNT_OVERVIEW,
    INTENT_AUDIT_QUERY,
    INTENT_BILL_ANALYSIS,
    INTENT_CARD_FREEZE,
    INTENT_CARD_LOST,
    INTENT_CARD_QUERY,
    INTENT_CARD_VIRTUAL_APPLY,
    INTENT_HELP,
    INTENT_LABELS,
    INTENT_PAYEE_QUERY,
    INTENT_TRANSFER,
    INTENT_UNKNOWN,
    parse_intent,
)
from app.agent.planner import planner
from app.agent.tools import ToolResult, get_tool
from app.core.config import settings
from app.core.errors import LLMUnavailableError
from app.models import AgentMessage, AgentSession, utcnow
from app.security.audit import write_audit_log
from app.security.policy import ActionType


class TraceBuilder:
    """构建 DAG 执行轨迹。"""

    def __init__(self) -> None:
        self.steps: List[Dict[str, Any]] = []

    def add(
        self,
        node: str,
        title: str,
        status: str,
        detail: str = "",
        duration_ms: int = 0,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.steps.append(
            {
                "step": len(self.steps) + 1,
                "node": node,
                "title": title,
                "status": status,
                "detail": detail,
                "duration_ms": duration_ms,
                "payload": payload or {},
            }
        )

    def as_list(self) -> List[Dict[str, Any]]:
        return list(self.steps)


class AgentOrchestrator:
    """智能体主流程。"""

    # ------------------------------------------------------------------
    def ensure_session(self, db: Session, session_id: Optional[str], account_id: int = 1) -> AgentSession:
        if session_id:
            session = db.execute(
                AgentSession.__table__.select().where(AgentSession.__table__.c.session_id == session_id)
            ).first()
            if session is not None:
                obj = db.get(AgentSession, session.id)
                if obj is not None:
                    return obj
        new_session = AgentSession(
            session_id=session_id or f"sess_{uuid.uuid4().hex[:16]}",
            title="新的对话",
            account_id=account_id,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(new_session)
        db.commit()
        db.refresh(new_session)
        return new_session

    # ------------------------------------------------------------------
    def chat(
        self,
        db: Session,
        *,
        message: str,
        session_id: Optional[str] = None,
        account_id: int = 1,
        actor: str = "demo-user",
        auth_ctx: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        trace = TraceBuilder()
        started = time.perf_counter()

        session = self.ensure_session(db, session_id, account_id)

        # ---------- 节点 1：意图识别 ----------
        t0 = time.perf_counter()
        intent_result = parse_intent(message)
        trace.add(
            "intent_recognition",
            "意图识别与参数抽取",
            "success",
            f"{intent_result.label}（置信度 {intent_result.confidence:.2f}）— {intent_result.reason}",
            int((time.perf_counter() - t0) * 1000),
            {
                "intent": intent_result.intent,
                "confidence": intent_result.confidence,
                "slots": intent_result.slots,
                "source": intent_result.source,
            },
        )

        # ---------- 节点 2：任务规划（含 DAG 安全约束） ----------
        t0 = time.perf_counter()
        plan = planner.plan(intent_result.intent, intent_result.slots, {"account_id": account_id})
        ordered = plan.topological_order()

        # 安全约束：DAG 节点数上限
        if len(ordered) > settings.agent_max_dag_nodes:
            ordered = ordered[: settings.agent_max_dag_nodes]
        trace.add(
            "task_planning",
            "任务规划（生成 DAG）",
            "success",
            f"规划 {len(ordered)} 个执行节点：{' → '.join(n.id for n in ordered)}",
            int((time.perf_counter() - t0) * 1000),
            plan.to_dict(),
        )

        # ---------- 节点 3：DAG 执行（含工具调用约束 + 身份上下文） ----------
        # 身份上下文：从认证上下文获取，绝不接受 LLM 生成的身份字段
        auth = auth_ctx or {}
        ctx: Dict[str, Any] = {
            "slots": intent_result.slots,
            "self_account_no": self._self_account_no(db, account_id),
            "auth": {
                "actor": actor,
                "user_id": auth.get("user_id"),
                "username": auth.get("username", actor),
                "authorized_account_ids": auth.get("authorized_account_ids", [account_id]),
                "current_account_id": account_id,
            },
        }
        actions: List[Dict[str, Any]] = []
        failed = False
        tool_call_count = 0

        for node in ordered:
            # 工具调用次数上限
            tool_call_count += 1
            if tool_call_count > settings.agent_max_tool_calls:
                trace.add(node.id, node.title, "skipped", "超过工具调用次数上限", 0, {})
                failed = True
                break
            # 整体超时
            if (time.perf_counter() - started) > settings.agent_max_execution_seconds:
                trace.add(node.id, node.title, "skipped", "超过任务执行时间上限", 0, {})
                failed = True
                break

            fn = get_tool(node.tool)
            if fn is None:
                # 未知工具：白名单拒绝
                trace.add(node.id, node.title, "skipped", f"工具 {node.tool} 未注册", 0, {})
                failed = True
                break
            t0 = time.perf_counter()
            try:
                result: ToolResult = fn(db, dict(node.args, **{}), ctx)
                duration = int((time.perf_counter() - t0) * 1000)
                if result.error:
                    failed = True
                    trace.add(
                        node.id, node.title, "failed", result.error, duration, result.data
                    )
                    actions.extend(result.actions)
                    break
                trace.add(
                    node.id,
                    node.title,
                    "success",
                    result.detail,
                    duration,
                    result.data,
                )
                actions.extend(result.actions)
            except Exception as exc:  # 单个工具异常不应中断整个 Agent
                failed = True
                trace.add(
                    node.id,
                    node.title,
                    "failed",
                    f"{exc.__class__.__name__}: {exc}",
                    int((time.perf_counter() - t0) * 1000),
                )
                break

        # ---------- 节点 4：答复生成 ----------
        t0 = time.perf_counter()
        reply, reply_source = self._compose_reply(intent_result, ctx, message, failed)
        trace.add(
            "response_generation",
            "答复生成",
            "success",
            f"{'模型生成' if reply_source == 'llm' else '模板生成（本地演示模式）'}，耗时 {int((time.perf_counter() - t0) * 1000)}ms",
            int((time.perf_counter() - t0) * 1000),
            {"source": reply_source},
        )

        total_ms = int((time.perf_counter() - started) * 1000)
        trace.add(
            "pipeline_done",
            "执行完成",
            "success",
            f"总耗时 {total_ms}ms",
            total_ms,
        )

        # ---------- 持久化 ----------
        demo_mode = not llm_client.enabled
        user_msg = AgentMessage(
            session_id=session.id,
            role="user",
            content=message,
            intent=intent_result.intent,
            confidence=intent_result.confidence,
            risk_level=ctx.get("policy", {}).get("level", "green"),
            trace_json="[]",
            demo_mode=demo_mode,
            created_at=utcnow(),
        )
        db.add(user_msg)

        assistant_msg = AgentMessage(
            session_id=session.id,
            role="assistant",
            content=reply,
            intent=intent_result.intent,
            confidence=intent_result.confidence,
            risk_level=ctx.get("policy", {}).get("level", "green"),
            trace_json=json.dumps(trace.as_list(), ensure_ascii=False, default=str),
            demo_mode=demo_mode,
            created_at=utcnow(),
        )
        db.add(assistant_msg)

        session.message_count += 2
        if session.title == "新的对话":
            session.title = message[:24] + ("…" if len(message) > 24 else "")
        session.updated_at = utcnow()
        db.commit()
        db.refresh(assistant_msg)

        # ---------- 审计 ----------
        write_audit_log(
            db,
            action="agent.chat",
            decision="allow",
            risk_level=ctx.get("policy", {}).get("level", "green"),
            reason=f"意图 {intent_result.intent}：{intent_result.reason}",
            actor=actor,
            target_type="agent_session",
            target_id=session.session_id,
            detail={
                "intent": intent_result.intent,
                "confidence": intent_result.confidence,
                "demo_mode": demo_mode,
                "duration_ms": total_ms,
                "nodes": [n.id for n in ordered],
            },
        )

        return {
            "session_id": session.session_id,
            "message_id": assistant_msg.id,
            "reply": reply,
            "intent": intent_result.intent,
            "intent_label": INTENT_LABELS.get(intent_result.intent, intent_result.intent),
            "confidence": intent_result.confidence,
            "risk_level": ctx.get("policy", {}).get("level", "green"),
            "demo_mode": demo_mode,
            "demo_mode_notice": llm_client.demo_notice,
            "trace": trace.as_list(),
            "actions": actions,
            "data": self._public_data(intent_result.intent, ctx),
            "created_at": assistant_msg.created_at,
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _self_account_no(db: Session, account_id: int) -> Optional[str]:
        from app.services.account_service import get_account

        try:
            return get_account(db, account_id).account_no
        except Exception:
            return None

    # ------------------------------------------------------------------
    def _public_data(self, intent: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """整理给前端使用的结构化数据（已脱敏）。"""
        data: Dict[str, Any] = {}
        if intent == INTENT_TRANSFER and ctx.get("transfer_preview"):
            data["transfer"] = ctx["transfer_preview"]
        if intent == INTENT_BILL_ANALYSIS:
            data["bill"] = {
                "total_expense": ctx.get("bill_summary", {}).get("total_expense", 0),
                "total_income": ctx.get("bill_summary", {}).get("total_income", 0),
                "count": ctx.get("bill_summary", {}).get("count", 0),
                "categories": ctx.get("categories", []),
                "anomalies": ctx.get("anomalies", []),
                "trend": ctx.get("trend", []),
            }
        if intent == INTENT_CARD_QUERY:
            data["cards"] = [
                {
                    "id": c.id,
                    "masked_card_no": mask(c.card_no),
                    "card_type": c.card_type,
                    "card_name": c.card_name,
                    "status": c.status,
                    "daily_limit": round(c.daily_limit_cents / 100, 2),
                }
                for c in ctx.get("cards", [])
            ]
        if intent == INTENT_CARD_VIRTUAL_APPLY and ctx.get("virtual_card_preview"):
            data["virtual_card"] = ctx["virtual_card_preview"]
        if intent in (INTENT_CARD_LOST, INTENT_CARD_FREEZE) and ctx.get("target_card"):
            data["card"] = ctx["target_card"]
        if intent == INTENT_PAYEE_QUERY:
            data["payees"] = [
                {
                    "id": p.id,
                    "name": p.name,
                    "masked_account_no": f"{p.account_no[:4]}****{p.account_no[-4:]}"
                    if len(p.account_no) > 8
                    else "****",
                    "is_frequent": p.is_frequent,
                    "total_count": p.total_count,
                }
                for p in ctx.get("payees", [])
            ]
        if intent == INTENT_AUDIT_QUERY:
            data["audit"] = [
                {
                    "id": log.id,
                    "action": log.action,
                    "risk_level": log.risk_level,
                    "decision": log.decision,
                    "reason": log.reason,
                    "created_at": log.created_at.isoformat(),
                }
                for log in ctx.get("audit_logs", [])
            ]
        if intent == INTENT_ACCOUNT_OVERVIEW:
            account = ctx.get("account")
            stats = ctx.get("stats", {})
            if account is not None:
                data["overview"] = {
                    "balance": round(account.balance_cents / 100, 2),
                    "holder": account.holder_name,
                    "total_expense": stats.get("total_expense", 0),
                    "card_count": len(ctx.get("cards", [])),
                }
        return data

    # ------------------------------------------------------------------
    def _compose_reply(
        self,
        intent_result,
        ctx: Dict[str, Any],
        user_message: str,
        failed: bool,
    ) -> tuple[str, str]:
        """生成答复。配置了模型时用模型润色（数据完全来自后端工具结果）。"""
        intent = intent_result.intent
        fallback = self._template_reply(intent, ctx, user_message, failed)

        if not llm_client.enabled:
            return fallback, "template"

        prompt = self._llm_prompt(intent, ctx, user_message, fallback)
        try:
            text = llm_client.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是金枢银行的智能助手「金枢」。请基于给定的事实数据用简洁、专业、"
                            "可信的中文回答用户问题。要求：只使用【事实数据】中的数字，不得编造；"
                            "涉及金额时保留两位小数；不要输出 Markdown 表格；回复控制在 200 字以内。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=600,
            )
            text = text.strip()
            return (text if text else fallback), "llm"
        except LLMUnavailableError:
            return fallback, "template"

    # ------------------------------------------------------------------
    @staticmethod
    def _llm_prompt(intent, ctx, user_message, fallback) -> str:
        facts = {
            "intent": intent,
            "slots": ctx.get("slots", {}),
            "policy": ctx.get("policy", {}),
            "transfer_preview": ctx.get("transfer_preview"),
            "bill_summary": ctx.get("bill_summary"),
            "categories": ctx.get("categories", [])[:6],
            "anomalies": (ctx.get("anomalies") or [])[:3],
            "trend": ctx.get("trend", []),
            "cards": [
                {"masked": mask(c.card_no), "type": c.card_type, "status": c.status}
                for c in ctx.get("cards", [])
            ],
            "overview": ctx.get("overview"),
            "reference_answer": fallback,
        }
        payload = json.dumps(facts, ensure_ascii=False, default=str)
        return (
            f"用户原话：{user_message}\n\n"
            f"【事实数据】\n{payload}\n\n"
            "请据此生成答复。"
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _template_reply(intent, ctx, user_message, failed) -> str:
        """本地模板式答复（演示模式使用）。"""
        if failed:
            err_steps = [s for s in ctx.get("_trace_fail", []) if s.get("status") == "failed"]
            msg = err_steps[0]["detail"] if err_steps else "执行过程中出现异常"
            return f"抱歉，本次操作未能完成：{msg}。请调整指令后重试，或到「安全审计中心」查看详情。"

        if intent == INTENT_TRANSFER:
            preview = ctx.get("transfer_preview")
            if not preview:
                return "我需要知道转账金额与收款人才能继续。例如：「给张三转 500 元，备注还房贷」。"
            risk = preview["risk"]
            lines = [
                f"已为你生成转账方案（**{risk['label']}**）：",
                f"- 收款人：{preview['payee_name']}（{preview['masked_payee_account_no']}）",
                f"- 金额：¥ {preview['amount']:.2f}",
                f"- 备注：{preview['remark'] or '无'}",
                f"- 当日累计：¥ {preview['daily_total_after']:.2f}（风控红线 ¥ {preview['daily_limit_remaining'] + preview['daily_total_after']:.2f}）",
                f"- 工单号：{preview['order_no']}",
                f"判定依据：{risk['reason']}",
            ]
            if preview["requires_mfa"]:
                lines.append("该操作需要完成多因子身份验证后才能执行，请在「智能转账」页完成验证。")
            elif preview["requires_confirmation"]:
                lines.append("该操作需要你在「智能转账」页确认明细后才会执行。")
            else:
                lines.append("该操作符合绿色自动执行规则，可直接确认执行。")
            return "\n".join(lines)

        if intent == INTENT_BILL_ANALYSIS:
            summary = ctx.get("bill_summary", {})
            if not summary:
                return "暂未查询到账单数据。"
            cats = ctx.get("categories", []) or []
            anomalies = ctx.get("anomalies", []) or []
            lines = [
                f"本月共 {summary.get('count', 0)} 笔交易，支出合计 ¥ {summary.get('total_expense', 0):.2f}，"
                f"收入 ¥ {summary.get('total_income', 0):.2f}。",
            ]
            if cats:
                top = "、".join(
                    f"{c['category']} ¥{c['amount']:.2f}（{c['ratio'] * 100:.1f}%）" for c in cats[:3]
                )
                lines.append(f"支出前三分类：{top}。")
            else:
                lines.append("本月暂无支出记录。")
            if anomalies:
                lines.append(f"识别到 {len(anomalies)} 笔可疑交易，最高风险分 {anomalies[0]['score']}（{anomalies[0]['reason']}）。")
            else:
                lines.append("未发现显著异常交易。")
            return "\n".join(lines)

        if intent == INTENT_CARD_QUERY:
            cards = ctx.get("cards", [])
            if not cards:
                return "当前账户下还没有银行卡。"
            lines = [f"您名下共有 {len(cards)} 张卡："]
            for c in cards:
                lines.append(
                    f"- {mask(c.card_no)}｜{c.card_name or c.card_type}｜状态 {c.status}｜单日限额 ¥ {c.daily_limit_cents / 100:,.2f}"
                )
            return "\n".join(lines)

        if intent == INTENT_CARD_VIRTUAL_APPLY:
            preview = ctx.get("virtual_card_preview", {})
            summary = preview.get("summary", {})
            return (
                "已为您准备虚拟卡申请方案：\n"
                f"- 卡片名称：{summary.get('卡片名称', '金枢虚拟卡')}\n"
                f"- 单日限额：¥ {summary.get('单日限额', 0):,.2f}\n"
                f"- 有效期：{summary.get('有效期', '2029/12')}\n"
                "该操作属于黄色权限，请在「智能银行卡」页确认后提交。"
            )

        if intent in (INTENT_CARD_LOST, INTENT_CARD_FREEZE):
            target = ctx.get("target_card")
            policy = ctx.get("policy", {})
            if not target:
                return "未能定位到目标卡片，请补充卡片尾号，例如「把尾号 8888 的卡挂失」。"
            action = "挂失" if intent == INTENT_CARD_LOST else "冻结/解冻"
            level = {"green": "绿色", "yellow": "黄色", "red": "红色"}.get(policy.get("level", ""), policy.get("level", ""))
            return (
                f"已定位卡片 {target['masked_card_no']}（当前状态 {target['status']}），准备执行「{action}」。\n"
                f"权限等级：**{level}** —— {policy.get('reason', '')}\n"
                "请在「智能银行卡」页完成后续确认或多因子验证。"
            )

        if intent == INTENT_ACCOUNT_OVERVIEW:
            account = ctx.get("account")
            stats = ctx.get("stats", {})
            if account is None:
                return "暂时无法读取账户信息。"
            return (
                f"{account.holder_name}，您当前账户（{account.account_no[-4:]}）余额为 "
                f"¥ {account.balance_cents / 100:,.2f}，名下有 {len(ctx.get('cards', []))} 张卡。\n"
                f"{stats.get('month', '')} 支出合计 ¥ {stats.get('total_expense', 0):,.2f}，日均 ¥ {stats.get('daily_average', 0):,.2f}。"
            )

        if intent == INTENT_PAYEE_QUERY:
            payees = ctx.get("payees", [])
            if not payees:
                return "目前还没有登记任何收款人。"
            lines = [f"您共有 {len(payees)} 位收款人："]
            for p in payees[:8]:
                lines.append(
                    f"- {p.name}｜{p.account_no[:4]}****{p.account_no[-4:]}｜"
                    f"{'常用' if p.is_frequent else '一般'}｜历史 {p.total_count} 次"
                )
            return "\n".join(lines)

        if intent == INTENT_AUDIT_QUERY:
            logs = ctx.get("audit_logs", [])
            if not logs:
                return "暂无审计记录。"
            lines = [f"最近 {len(logs)} 条安全审计记录："]
            for log in logs[:8]:
                lines.append(f"- {log.created_at.strftime('%m-%d %H:%M')}｜{log.action}｜{log.risk_level}｜{log.decision}")
            return "\n".join(lines)

        if intent == INTENT_HELP:
            return (
                "我是金枢银行智能助手，可以帮您完成三件事：\n"
                "1. **智能转账**：例如「给张三转 500 元，备注还房贷」\n"
                "2. **智能账单分析**：例如「本月餐饮花了多少，有异常交易吗」\n"
                "3. **智能银行卡管理**：例如「申请一张虚拟卡」「把尾号 8888 的卡挂失」\n"
                "所有写操作都会经过后端安全策略引擎定级（绿 / 黄 / 红），我无法自行决定权限。"
            )

        return (
            "我暂时没能理解您的需求。可以试试这样问我：\n"
            "- 「给张三转 500 元，备注还房贷」\n"
            "- 「本月餐饮消费统计」\n"
            "- 「我有几张银行卡」"
        )


def mask(card_no: str) -> str:
    if len(card_no) <= 8:
        return "*" * len(card_no)
    return f"{card_no[:4]} **** **** {card_no[-4:]}"


agent_orchestrator = AgentOrchestrator()

__all__ = ["AgentOrchestrator", "TraceBuilder", "agent_orchestrator"]
