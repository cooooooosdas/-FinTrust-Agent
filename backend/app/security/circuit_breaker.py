"""异常熔断器。

当 LLM 调用连续失败达到阈值时打开熔断，熔断期间直接走本地降级逻辑，
避免上游故障拖垮整个 Agent 服务。半开状态允许一次探测请求。
"""

from __future__ import annotations

import threading
import time
from enum import Enum
from typing import Callable, Optional, TypeVar

from app.core.config import settings

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "closed"      # 正常
    OPEN = "open"          # 熔断
    HALF_OPEN = "half_open"  # 半开探测


class CircuitBreaker:
    """轻量熔断器（线程安全）。"""

    def __init__(self, name: str, threshold: Optional[int] = None, reset_timeout: Optional[int] = None) -> None:
        self.name = name
        self.threshold = threshold if threshold is not None else settings.circuit_breaker_threshold
        self.reset_timeout = reset_timeout if reset_timeout is not None else settings.circuit_breaker_reset
        self._failures = 0
        self._opened_at: Optional[float] = None
        self._state = CircuitState.CLOSED
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN and self._opened_at is not None:
                if time.time() - self._opened_at >= self.reset_timeout:
                    self._state = CircuitState.HALF_OPEN
            return self._state

    @property
    def is_open(self) -> bool:
        return self.state in (CircuitState.OPEN, CircuitState.HALF_OPEN)

    # ------------------------------------------------------------------
    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._state = CircuitState.CLOSED
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.threshold and self._state != CircuitState.OPEN:
                self._state = CircuitState.OPEN
                self._opened_at = time.time()

    # ------------------------------------------------------------------
    def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """受保护调用。熔断打开时抛出 `CircuitOpenError`。"""
        from app.core.errors import CircuitOpenError

        if self.is_open:
            raise CircuitOpenError(
                f"{self.name} 服务熔断中，暂不受理请求",
                detail={
                    "circuit": self.name,
                    "state": self.state.value,
                    "retry_after": self.reset_timeout,
                },
            )
        try:
            result = func(*args, **kwargs)
        except Exception:
            self.record_failure()
            raise
        self.record_success()
        return result

    # ------------------------------------------------------------------
    def snapshot(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "failures": self._failures,
            "threshold": self.threshold,
        }


circuit_breaker = CircuitBreaker("llm")

__all__ = ["CircuitBreaker", "CircuitState", "circuit_breaker"]
