"""应用配置。

所有敏感信息（LLM API Key）只存在于后端环境变量中，绝不下发到前端。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """从 backend/.env 或环境变量读取配置。"""

    model_config = SettingsConfigDict(
        env_file=(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- 运行环境 ----------
    app_env: str = "development"
    app_name: str = "金枢 FinTrust Agent"
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # ---------- 数据库 ----------
    database_url: str = f"sqlite:///{(BACKEND_ROOT / 'data' / 'fintrust.db').as_posix()}"

    # ---------- LLM ----------
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout: int = 30
    llm_max_retries: int = 2

    # ---------- 安全阈值（单位：元） ----------
    # 赛事口径（P0）：黄色 = 写操作且执行后日累计 ≤ 1000 元；
    # 红色 = 执行后日累计 > 1000 元，或挂失 / 密码修改等敏感操作。
    # 日累计为**唯一主判定轴**；单笔金额仅作辅助升红因子，不替代日累计判断。
    policy_yellow_daily_max: float = 1000.0     # 日累计 ≤ 此值 → 黄色（写操作）
    policy_red_daily_min: float = 1000.0        # 日累计 > 此值 → 红色（需 MFA）
    policy_red_single_min: float = 10000.0      # 单笔辅助升红阈值（不替代日累计）
    policy_red_daily_total: float = 100000.0    # 风控硬红线（阻断）
    circuit_breaker_threshold: int = 5
    circuit_breaker_reset: int = 60

    # ---------- 业务时区 ----------
    # 日累计以「交易发生日」为准，默认 Asia/Shanghai。
    business_timezone: str = "Asia/Shanghai"

    # ---------- 认证 / 会话 / MFA ----------
    session_ttl_minutes: int = 720          # Session 有效期（默认 12 小时）
    transfer_order_ttl_minutes: int = 15    # 转账工单默认过期时间（分钟）
    mfa_ttl_seconds: int = 300              # MFA 挑战默认有效期（秒）
    mfa_max_attempts: int = 5               # MFA 最大错误尝试次数
    mfa_secret_key: str = ""                # MFA 验证码 HMAC 服务端密钥（环境变量注入）
    auth_session_secret: str = ""           # Session token 哈希盐（环境变量注入）
    audit_hmac_key: str = ""                # 审计完整性 HMAC 密钥（环境变量注入）
    demo_user_1_password: str = "Demo1234!"  # 演示账号密码（环境变量可覆盖，勿在生产硬编码）
    demo_user_2_password: str = "Demo1234!"

    # ---------- 请求限流 ----------
    rate_limit_login_per_minute: int = 10      # 登录：单 IP 10次/分钟
    rate_limit_login_fail_window: int = 15     # 登录失败：用户名+IP 5次/15分钟
    rate_limit_login_fail_max: int = 5
    rate_limit_mfa_create_per_10min: int = 3   # MFA 挑战创建：3次/10分钟
    rate_limit_agent_per_minute: int = 30      # Agent Chat：30次/分钟/用户
    rate_limit_transfer_preview_per_minute: int = 10   # 转账预览：10次/分钟/账户
    rate_limit_transfer_execute_per_minute: int = 10   # 转账执行：10次/分钟/账户
    rate_limit_audit_per_minute: int = 60      # 审计查询：60次/分钟/用户
    rate_limiter_enabled: bool = True          # 限流总开关

    # ---------- Agent 安全约束 ----------
    agent_max_dag_nodes: int = 12              # 最大 DAG 节点数
    agent_max_tool_calls: int = 10             # 最大工具调用次数
    agent_max_execution_seconds: int = 30      # 整体任务最大执行时间（秒）

    # ---------- 演示模式 ----------
    force_demo_mode: bool = False
    simulation_tag: str = "模拟交易"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origin_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_demo_mode(self) -> bool:
        """未配置 API Key 或被强制开启时，进入本地演示模式。"""
        return self.force_demo_mode or not self.llm_api_key.strip()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def llm_enabled(self) -> bool:
        return not self.is_demo_mode

    def ensure_database_dir(self) -> None:
        """SQLite 文件所在目录不存在时创建。"""
        if self.database_url.startswith("sqlite"):
            raw = self.database_url.split("///", 1)[-1]
            db_path = Path(raw)
            if not db_path.is_absolute():
                db_path = (BACKEND_ROOT / db_path).resolve()
            db_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_database_dir()
    return settings


settings = get_settings()

__all__ = ["settings", "get_settings", "Settings", "BACKEND_ROOT"]
