"""API 路由集合。"""

from app.api.routes import accounts, agent, audit, auth, cards, payees, system, transactions, transfers

__all__ = [
    "accounts",
    "agent",
    "audit",
    "auth",
    "cards",
    "payees",
    "system",
    "transactions",
    "transfers",
]
