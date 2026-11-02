"""审计完整性验证工具（P2-T3）。

验证审计哈希链的完整性，检测记录修改 / 删除 / 重排。

用法：
    cd backend
    python scripts/verify_audit_integrity.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import SessionLocal  # noqa: E402
from app.security.audit_integrity import verify_integrity  # noqa: E402


def main() -> int:
    db = SessionLocal()
    try:
        ok, summary, detail = verify_integrity(db)
        print(summary)
        if ok:
            print(f"  已签名事件：{detail.get('total', 0)} 条，校验通过 {detail.get('checked', 0)} 条")
            return 0
        print(f"  首个异常：{detail}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
