"""意图识别与结构化参数抽取。

两级策略
--------
1. **本地规则引擎**（始终可用）：中文分词式匹配 + 数字解析，覆盖演示模式。
2. **LLM 增强**（配置了 API Key 时）：在本地规则结果之上做纠错与泛化，
   失败或超时自动降级回本地规则，保证 Agent 永不因模型故障而不可用。

无论走哪条路径，输出结构完全一致：`IntentResult(intent, confidence, slots, source)`。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.agent.llm import llm_client
from app.core.errors import LLMUnavailableError

# ----------------------------------------------------------------------
# 意图定义
# ----------------------------------------------------------------------
INTENT_TRANSFER = "transfer"
INTENT_BILL_ANALYSIS = "bill_analysis"
INTENT_CARD_QUERY = "card_query"
INTENT_CARD_VIRTUAL_APPLY = "card_virtual_apply"
INTENT_CARD_LOST = "card_lost"
INTENT_CARD_FREEZE = "card_freeze"
INTENT_ACCOUNT_OVERVIEW = "account_overview"
INTENT_PAYEE_QUERY = "payee_query"
INTENT_AUDIT_QUERY = "audit_query"
INTENT_HELP = "help"
INTENT_UNKNOWN = "unknown"

INTENT_LABELS = {
    INTENT_TRANSFER: "智能转账",
    INTENT_BILL_ANALYSIS: "智能账单分析",
    INTENT_CARD_QUERY: "银行卡查询",
    INTENT_CARD_VIRTUAL_APPLY: "虚拟卡申请",
    INTENT_CARD_LOST: "银行卡挂失",
    INTENT_CARD_FREEZE: "卡片冻结 / 解冻",
    INTENT_ACCOUNT_OVERVIEW: "账户总览",
    INTENT_PAYEE_QUERY: "收款人查询",
    INTENT_AUDIT_QUERY: "安全审计",
    INTENT_HELP: "功能指引",
    INTENT_UNKNOWN: "未识别",
}

#: 需要写操作确认 / MFA 的意图（仅供展示，实际执行仍由策略引擎判定）
WRITE_INTENTS = {INTENT_TRANSFER, INTENT_CARD_VIRTUAL_APPLY, INTENT_CARD_LOST, INTENT_CARD_FREEZE}

# ----------------------------------------------------------------------
# 中文数字解析
# ----------------------------------------------------------------------
CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "壹": 1, "二": 2, "两": 2, "贰": 2, "三": 3, "叁": 3,
    "四": 4, "肆": 4, "五": 5, "伍": 5, "六": 6, "陆": 6, "七": 7, "柒": 7,
    "八": 8, "捌": 8, "九": 9, "玖": 9,
}
CN_UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000, "万": 10000, "亿": 100000000}


def cn_number_to_int(text: str) -> Optional[int]:
    """把中文数字串转成整数，例如「三千五百」-> 3500。"""
    if not text:
        return None
    total = 0
    section = 0
    digit: Optional[int] = None
    for ch in text:
        if ch in CN_DIGITS:
            digit = CN_DIGITS[ch]
        elif ch in CN_UNITS:
            unit = CN_UNITS[ch]
            if unit == 10000:
                section = (section + (digit or 0)) * unit
                total += section
                section = 0
            elif unit == 100000000:
                section = (section + (digit or 0)) * unit
                total = (total + section) * unit
                section = 0
            else:
                section += (digit if digit is not None else 1) * unit
            digit = None
        else:
            return None
    total += section + (digit or 0)
    return total or None


AMOUNT_RE = re.compile(
    r"(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>万|千|百|元|块|圆|人民币)?"
)
CN_AMOUNT_RE = re.compile(
    r"(?P<num>[零〇一壹二两贰三叁四肆五伍六陆七柒八捌九玖十拾百佰千仟万]+)\s*(?P<unit>万|千|百|元|块|圆)?"
)


#: 这些前缀后面的数字不应被当作金额（卡号 / 尾号 / 账号等）
NON_AMOUNT_PREFIX = re.compile(r"(?:尾号|卡号|账号|账户|工单|订单|序号|编号)\s*$")


def extract_amount(text: str) -> Optional[float]:
    """从自然语言中抽取金额（返回元）。

    优先级：带「万」的阿拉伯数字 > 带货币单位的中文数字 > 带货币单位的阿拉伯数字
    > 裸数字（需排除卡号 / 尾号等场景）。
    """
    # 1) X 万
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*万", text):
        return float(m.group(1)) * 10000

    # 2) 中文数字 + 货币单位
    for m in CN_AMOUNT_RE.finditer(text):
        unit = m.group("unit")
        if not unit:
            continue
        val = cn_number_to_int(m.group("num"))
        if not val:
            continue
        if unit == "万":
            val *= 10000
        return float(val)

    # 3) 阿拉伯数字 + 货币单位
    for m in AMOUNT_RE.finditer(text):
        unit = m.group("unit")
        if unit in (None, "万", "千", "百"):
            continue
        try:
            return float(m.group("num"))
        except ValueError:
            continue

    # 4) 裸数字：排除卡号 / 尾号 / 账号等
    for m in re.finditer(r"(?<![\d.])(\d+(?:\.\d+)?)(?![\d.])", text):
        prefix = text[: m.start()]
        if NON_AMOUNT_PREFIX.search(prefix):
            continue
        try:
            value = float(m.group(1))
        except ValueError:
            continue
        if value <= 0:
            continue
        return value

    return None


def extract_remark(text: str) -> str:
    """抽取备注：识别「备注/说明/用途/原因」后的内容。"""
    m = re.search(r"(?:备注|说明|用途|原因是|用途是)\s*[:：]?\s*([^\s，,。；;]{1,30})", text)
    return m.group(1).strip() if m else ""


# ----------------------------------------------------------------------
# 结果结构
# ----------------------------------------------------------------------
@dataclass
class IntentResult:
    intent: str
    confidence: float
    slots: Dict[str, Any] = field(default_factory=dict)
    source: str = "rule"  # rule / llm / llm+rule
    reason: str = ""

    @property
    def label(self) -> str:
        return INTENT_LABELS.get(self.intent, self.intent)


# ----------------------------------------------------------------------
# 本地规则引擎
# ----------------------------------------------------------------------
TRANSFER_KEYWORDS = ["转账", "汇款", "转钱", "打钱", "付给", "给.*转", "划转", "转一笔", "转过去"]
BILL_KEYWORDS = ["账单", "消费", "花了多少", "支出", "收入", "统计", "明细", "花了", "开销", "账单分析", "哪笔"]
CARD_QUERY_KEYWORDS = ["我的卡", "有哪些卡", "银行卡", "卡片", "卡号", "信用卡", "借记卡", "查卡"]
VIRTUAL_APPLY_KEYWORDS = ["申请虚拟卡", "开虚拟卡", "虚拟卡", "申请一张卡", "开个卡"]
LOST_KEYWORDS = ["挂失", "丢了", "遗失", "被偷", "丢了卡"]
FREEZE_KEYWORDS = ["冻结", "解冻", "暂停", "恢复", "锁卡", "禁用"]
OVERVIEW_KEYWORDS = ["余额", "总览", "多少钱", "账户", "概览", "看看账户", "我的账户"]
PAYEE_KEYWORDS = ["收款人", "联系人", "常联系人", "转给谁"]
AUDIT_KEYWORDS = ["审计", "日志", "操作记录", "安全记录", "谁操作过"]
HELP_KEYWORDS = ["你能做什么", "帮助", "怎么用", "功能", "会什么", "介绍一下你"]


def _match(text: str, keywords: List[str]) -> bool:
    """关键词匹配。支持包含 ``.*`` 的正则式关键词（如「给.*转」）。"""
    for kw in keywords:
        if ".*" in kw:
            if re.search(kw, text):
                return True
        elif kw in text:
            return True
    return False


def rule_based_intent(text: str) -> IntentResult:
    """基于关键词与句式的本地意图识别。"""
    t = text.strip()

    # 意图判定顺序很重要：先匹配更具体的
    if _match(t, LOST_KEYWORDS):
        return IntentResult(
            intent=INTENT_CARD_LOST,
            confidence=0.93,
            reason="命中「挂失/丢失」等敏感操作关键词",
        )
    if _match(t, VIRTUAL_APPLY_KEYWORDS):
        return IntentResult(
            intent=INTENT_CARD_VIRTUAL_APPLY,
            confidence=0.9,
            reason="命中「申请虚拟卡」类关键词",
        )
    if _match(t, FREEZE_KEYWORDS) and _match(t, CARD_QUERY_KEYWORDS):
        return IntentResult(
            intent=INTENT_CARD_FREEZE,
            confidence=0.86,
            reason="命中「冻结/解冻 + 卡片」组合",
        )
    if _match(t, TRANSFER_KEYWORDS):
        return IntentResult(INTENT_TRANSFER, 0.92, reason="命中「转账/汇款」关键词")
    if _match(t, AUDIT_KEYWORDS):
        return IntentResult(INTENT_AUDIT_QUERY, 0.88, reason="命中「审计/日志」关键词")
    if _match(t, PAYEE_KEYWORDS):
        return IntentResult(INTENT_PAYEE_QUERY, 0.85, reason="命中「收款人/联系人」关键词")
    if _match(t, CARD_QUERY_KEYWORDS):
        return IntentResult(INTENT_CARD_QUERY, 0.87, reason="命中「银行卡查询」关键词")
    if _match(t, BILL_KEYWORDS):
        return IntentResult(INTENT_BILL_ANALYSIS, 0.84, reason="命中「账单/消费统计」关键词")
    if _match(t, OVERVIEW_KEYWORDS):
        return IntentResult(INTENT_ACCOUNT_OVERVIEW, 0.82, reason="命中「余额/账户总览」关键词")
    if _match(t, HELP_KEYWORDS):
        return IntentResult(INTENT_HELP, 0.8, reason="命中「帮助/功能」关键词")

    return IntentResult(
        intent=INTENT_UNKNOWN,
        confidence=0.25,
        reason="未匹配到明确意图关键词",
    )


def rule_based_slots(text: str, intent: str) -> Dict[str, Any]:
    """基于规则抽取结构化参数。"""
    slots: Dict[str, Any] = {}
    if intent == INTENT_TRANSFER:
        amount = extract_amount(text)
        if amount is not None:
            slots["amount"] = amount
        slots["remark"] = extract_remark(text)
        # 收款人：优先匹配「给XXX转」「向XXX」
        m = re.search(r"(?:给|向|转给|付给)\s*([一-龥A-Za-z0-9]{2,10}?)\s*(?:转|汇|付|打)", text)
        if m:
            slots["payee_name"] = m.group(1)
        # 卡号
        m2 = re.search(r"\b(\d{4,19})\b", text)
        if m2 and not (m2.group(1).isdigit() and len(m2.group(1)) in (4, 5)):
            slots["payee_account_no"] = m2.group(1)
        # 卡片
        m3 = re.search(r"(?:尾号|卡号后四位|后四位)\s*(\d{4})", text)
        if m3:
            slots["card_last4"] = m3.group(1)
    elif intent == INTENT_BILL_ANALYSIS:
        if any(k in text for k in ("餐饮", "吃饭", "外卖", "美食")):
            slots["category"] = "餐饮美食"
        elif any(k in text for k in ("交通", "打车", "加油", "地铁")):
            slots["category"] = "交通出行"
        elif any(k in text for k in ("购物", "网购", "买")):
            slots["category"] = "购物消费"
        elif any(k in text for k in ("缴费", "水电", "物业", "话费")):
            slots["category"] = "生活缴费"
        elif any(k in text for k in ("娱乐", "电影", "游戏", "健身")):
            slots["category"] = "娱乐休闲"
        if any(k in text for k in ("本月", "这个月", "当月")):
            slots["period"] = "current_month"
        elif any(k in text for k in ("上月", "上个月")):
            slots["period"] = "last_month"
        if any(k in text for k in ("异常", "可疑", "大额消费")):
            slots["focus"] = "anomaly"
        if any(k in text for k in ("收入", "工资", "进账")):
            slots["direction"] = "income"
        elif any(k in text for k in ("支出", "花了", "消费")):
            slots["direction"] = "expense"
    elif intent == INTENT_CARD_VIRTUAL_APPLY:
        m = re.search(r"(?:叫|命名为|名字是|用途是)\s*([一-龥A-Za-z0-9]{2,16})", text)
        if m:
            slots["card_name"] = m.group(1)
        amount = extract_amount(text)
        if amount is not None:
            slots["daily_limit"] = amount
    elif intent in (INTENT_CARD_LOST, INTENT_CARD_FREEZE):
        m = re.search(r"(?:尾号|卡号后四位|后四位)\s*(\d{4})", text)
        if m:
            slots["card_last4"] = m.group(1)
        m2 = re.search(r"(\d{4,19})", text)
        if m2:
            slots["account_no"] = m2.group(1)
    return slots


# ----------------------------------------------------------------------
# LLM 增强
# ----------------------------------------------------------------------
LLM_SYSTEM_PROMPT = """你是银行智能助手「金枢」的语义解析器。任务是把用户的中文诉求解析成结构化 JSON。
只输出 JSON，不要任何解释文字或代码块标记。

输出格式：
{
  "intent": "transfer | bill_analysis | card_query | card_virtual_apply | card_lost | card_freeze | account_overview | payee_query | audit_query | help | unknown",
  "confidence": 0.0-1.0,
  "reason": "一句话说明判断依据",
  "slots": {}
}

slots 说明：
- transfer: {"amount": 数字(元), "payee_name": "收款人姓名", "payee_account_no": "收款账号", "remark": "备注", "card_last4": "四位尾号"}
- bill_analysis: {"category": "分类", "period": "current_month|last_month|recent_7d", "direction": "income|expense", "focus": "anomaly"}
- card_virtual_apply: {"card_name": "卡片名称", "daily_limit": 数字(元)}
- card_lost / card_freeze: {"card_last4": "四位尾号", "account_no": "卡号"}
- payee_query: {"name": "姓名关键词"}
未提及的字段不要出现在 slots 中。金额必须换算成"元"为单位的纯数字。
"""


def llm_intent(text: str) -> IntentResult:
    """调用 LLM 做意图识别与参数抽取。失败会抛 LLMUnavailableError。"""
    payload = llm_client.chat_json(
        [
            {"role": "system", "content": LLM_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        temperature=0.0,
        max_tokens=600,
    )
    intent = str(payload.get("intent", INTENT_UNKNOWN))
    if intent not in INTENT_LABELS:
        intent = INTENT_UNKNOWN
    slots = payload.get("slots") or {}
    if not isinstance(slots, dict):
        slots = {}
    try:
        confidence = float(payload.get("confidence", 0.7))
    except (TypeError, ValueError):
        confidence = 0.7
    return IntentResult(
        intent=intent,
        confidence=max(0.0, min(1.0, confidence)),
        slots=slots,
        source="llm",
        reason=str(payload.get("reason", "模型语义解析")),
    )


# ----------------------------------------------------------------------
# 对外主入口
# ----------------------------------------------------------------------
def parse_intent(text: str, *, allow_llm: bool = True) -> IntentResult:
    """解析意图与参数。

    规则引擎永远先跑，保证可用性；配置了模型时再用 LLM 结果做融合。
    """
    rule = rule_based_intent(text)
    rule_slots = rule_based_slots(text, rule.intent)

    if not allow_llm or not llm_client.enabled:
        rule.slots = rule_slots
        return rule

    try:
        llm = llm_intent(text)
    except LLMUnavailableError:
        rule.slots = rule_slots
        rule.reason = f"{rule.reason}（模型不可用，已回退本地规则）"
        return rule

    # 融合策略：模型意图与规则意图一致 → 采信模型并合并参数；
    # 不一致时，若模型置信度明显更高则采信模型，否则保留规则结果。
    merged_slots = {**llm.slots}
    for key, value in rule_slots.items():
        merged_slots.setdefault(key, value)

    if llm.intent == rule.intent:
        intent = llm.intent
        confidence = min(1.0, max(llm.confidence, rule.confidence))
        reason = f"{llm.reason}（与本地规则一致）"
    elif llm.confidence >= rule.confidence + 0.15:
        intent = llm.intent
        confidence = llm.confidence
        reason = f"{llm.reason}（模型纠正了本地规则的判断）"
    else:
        intent = rule.intent
        confidence = max(llm.confidence, rule.confidence)
        reason = f"{rule.reason}（模型判断置信度不足，采信本地规则）"

    return IntentResult(
        intent=intent,
        confidence=confidence,
        slots=merged_slots,
        source="llm+rule",
        reason=reason,
    )


__all__ = [
    "parse_intent",
    "rule_based_intent",
    "rule_based_slots",
    "llm_intent",
    "extract_amount",
    "extract_remark",
    "cn_number_to_int",
    "IntentResult",
    "INTENT_LABELS",
    "INTENT_TRANSFER",
    "INTENT_BILL_ANALYSIS",
    "INTENT_CARD_QUERY",
    "INTENT_CARD_VIRTUAL_APPLY",
    "INTENT_CARD_LOST",
    "INTENT_CARD_FREEZE",
    "INTENT_ACCOUNT_OVERVIEW",
    "INTENT_PAYEE_QUERY",
    "INTENT_AUDIT_QUERY",
    "INTENT_HELP",
    "INTENT_UNKNOWN",
]
