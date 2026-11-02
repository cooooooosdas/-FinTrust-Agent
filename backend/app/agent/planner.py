"""任务规划器：把意图 + 参数编排成可执行的 DAG。

每个节点声明依赖关系，执行器按拓扑序推进，并在轨迹中记录每个节点的
开始 / 结束状态与耗时，形成可解释的 DAG 执行轨迹。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from app.agent.nlu import (
    INTENT_ACCOUNT_OVERVIEW,
    INTENT_AUDIT_QUERY,
    INTENT_BILL_ANALYSIS,
    INTENT_CARD_FREEZE,
    INTENT_CARD_LOST,
    INTENT_CARD_QUERY,
    INTENT_CARD_VIRTUAL_APPLY,
    INTENT_HELP,
    INTENT_PAYEE_QUERY,
    INTENT_TRANSFER,
    INTENT_UNKNOWN,
)


@dataclass
class PlanNode:
    """DAG 中的一个节点。"""

    id: str
    title: str
    tool: str
    args: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    optional: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "tool": self.tool,
            "args": self.args,
            "depends_on": self.depends_on,
            "optional": self.optional,
        }


@dataclass
class Plan:
    """一次完整的执行计划。"""

    intent: str
    nodes: List[PlanNode]
    goal: str = ""

    def topological_order(self) -> List[PlanNode]:
        """按依赖关系做拓扑排序（含环检测保护）。"""
        by_id = {node.id: node for node in self.nodes}
        visited: Dict[str, int] = {}
        order: List[PlanNode] = []

        def visit(node_id: str, stack: set[str]) -> None:
            state = visited.get(node_id, 0)
            if state == 2:
                return
            if state == 1:
                # 出现环，跳过该依赖避免死循环
                return
            visited[node_id] = 1
            node = by_id.get(node_id)
            if node is not None:
                for dep in node.depends_on:
                    if dep in by_id:
                        visit(dep, stack)
                visited[node_id] = 2
                order.append(node)

        for node in self.nodes:
            visit(node.id, set())
        return order

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "goal": self.goal,
            "nodes": [node.to_dict() for node in self.topological_order()],
        }


class Planner:
    """基于意图的规则化任务规划器。"""

    def plan(self, intent: str, slots: Dict[str, Any], context: Dict[str, Any]) -> Plan:
        account_id = context.get("account_id", 1)

        if intent == INTENT_TRANSFER:
            return Plan(
                intent=intent,
                goal="完成一次安全可控的转账",
                nodes=[
                    PlanNode("resolve_payee", "解析收款人", "resolve_payee", {"account_id": account_id}),
                    PlanNode(
                        "check_daily_total",
                        "计算当日累计转账金额",
                        "daily_total",
                        {"account_id": account_id},
                        depends_on=["resolve_payee"],
                    ),
                    PlanNode(
                        "evaluate_policy",
                        "安全策略引擎定级",
                        "evaluate_policy",
                        {"account_id": account_id},
                        depends_on=["resolve_payee", "check_daily_total"],
                    ),
                    PlanNode(
                        "prepare_order",
                        "生成转账工单",
                        "prepare_transfer",
                        {"account_id": account_id},
                        depends_on=["evaluate_policy"],
                    ),
                ],
            )

        if intent == INTENT_BILL_ANALYSIS:
            return Plan(
                intent=intent,
                goal="完成账单统计与异常识别",
                nodes=[
                    PlanNode(
                        "fetch_transactions",
                        "拉取交易流水",
                        "fetch_transactions",
                        {"account_id": account_id, "slots": slots},
                    ),
                    PlanNode(
                        "aggregate_categories",
                        "消费分类汇总",
                        "aggregate_categories",
                        {},
                        depends_on=["fetch_transactions"],
                    ),
                    PlanNode(
                        "detect_anomalies",
                        "异常交易识别",
                        "detect_anomalies",
                        {},
                        depends_on=["fetch_transactions"],
                    ),
                    PlanNode(
                        "monthly_trend",
                        "月度趋势计算",
                        "monthly_trend",
                        {"account_id": account_id},
                    ),
                    PlanNode(
                        "compose_summary",
                        "生成账单摘要",
                        "compose_bill_summary",
                        {},
                        depends_on=["aggregate_categories", "detect_anomalies", "monthly_trend"],
                    ),
                ],
            )

        if intent in (INTENT_CARD_QUERY,):
            return Plan(
                intent=intent,
                goal="查询名下银行卡",
                nodes=[
                    PlanNode("list_cards", "查询银行卡列表", "list_cards", {"account_id": account_id}),
                ],
            )

        if intent == INTENT_CARD_VIRTUAL_APPLY:
            return Plan(
                intent=intent,
                goal="申请一张虚拟卡",
                nodes=[
                    PlanNode(
                        "evaluate_policy",
                        "安全策略引擎定级",
                        "evaluate_policy",
                        {"account_id": account_id, "action": "card_apply_virtual"},
                    ),
                    PlanNode(
                        "prepare_card",
                        "生成虚拟卡申请方案",
                        "prepare_virtual_card",
                        {"account_id": account_id, "slots": slots},
                        depends_on=["evaluate_policy"],
                    ),
                ],
            )

        if intent in (INTENT_CARD_LOST, INTENT_CARD_FREEZE):
            return Plan(
                intent=intent,
                goal="完成卡片状态变更",
                nodes=[
                    PlanNode(
                        "locate_card",
                        "定位目标卡片",
                        "locate_card",
                        {"account_id": account_id, "slots": slots},
                    ),
                    PlanNode(
                        "evaluate_policy",
                        "安全策略引擎定级",
                        "evaluate_policy",
                        {"account_id": account_id, "action": intent},
                    ),
                    PlanNode(
                        "prepare_card_action",
                        "生成卡片操作方案",
                        "prepare_card_action",
                        {"account_id": account_id, "slots": slots, "intent": intent},
                        depends_on=["locate_card", "evaluate_policy"],
                    ),
                ],
            )

        if intent == INTENT_ACCOUNT_OVERVIEW:
            return Plan(
                intent=intent,
                goal="汇总账户总览",
                nodes=[
                    PlanNode("load_account", "读取账户信息", "load_account", {"account_id": account_id}),
                    PlanNode("load_cards", "读取银行卡", "list_cards", {"account_id": account_id}),
                    PlanNode(
                        "load_recent",
                        "读取近期交易",
                        "recent_transactions",
                        {"account_id": account_id},
                    ),
                    PlanNode(
                        "load_stats",
                        "计算消费统计",
                        "spending_stats",
                        {"account_id": account_id},
                    ),
                ],
            )

        if intent == INTENT_PAYEE_QUERY:
            return Plan(
                intent=intent,
                goal="查询收款人列表",
                nodes=[
                    PlanNode("list_payees", "查询收款人", "list_payees", {"account_id": account_id}),
                ],
            )

        if intent == INTENT_AUDIT_QUERY:
            return Plan(
                intent=intent,
                goal="查询安全审计日志",
                nodes=[
                    PlanNode("list_audit", "查询审计日志", "list_audit", {"account_id": account_id}),
                ],
            )

        if intent == INTENT_HELP:
            return Plan(
                intent=intent,
                goal="说明系统能力",
                nodes=[PlanNode("capabilities", "输出能力清单", "capabilities", {})],
            )

        return Plan(
            intent=INTENT_UNKNOWN,
            goal="向用户澄清需求",
            nodes=[PlanNode("clarify", "生成澄清提示", "clarify", {})],
        )


planner = Planner()

__all__ = ["Plan", "PlanNode", "Planner", "planner"]
