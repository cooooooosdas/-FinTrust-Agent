"""P2-T3 审计完整性篡改模拟测试。"""

from __future__ import annotations

import pytest

from app.core.database import SessionLocal, engine
from app.models import AuditLog
from app.security.audit_integrity import verify_integrity
from app.security.audit import write_audit_log


def _drop_triggers():
    """模拟攻击者绕过数据库触发器（移除防篡改触发器）。"""
    with engine.connect() as conn:
        conn.exec_driver_sql("DROP TRIGGER IF EXISTS trg_audit_no_update")
        conn.exec_driver_sql("DROP TRIGGER IF EXISTS trg_audit_no_delete")
        conn.commit()


def _restore_triggers():
    """恢复防篡改触发器。"""
    from scripts.migrate_v040 import TRIGGER_STATEMENTS

    with engine.connect() as conn:
        for stmt in TRIGGER_STATEMENTS:
            conn.exec_driver_sql(stmt)
        conn.commit()


@pytest.fixture(autouse=True)
def _clean_audit():
    """每个测试前清空审计表，保证哈希链从零开始，测试相互独立。"""
    _drop_triggers()
    db = SessionLocal()
    try:
        db.query(AuditLog).delete()
        db.commit()
    finally:
        db.close()
    yield
    _restore_triggers()


def _write_n_audit(n: int) -> None:
    db = SessionLocal()
    try:
        for i in range(n):
            write_audit_log(
                db,
                action="integrity.test",
                decision="allow",
                risk_level="green",
                reason=f"完整性测试事件 {i}",
                actor="test-user",
                target_type="test",
                target_id=str(i),
            )
    finally:
        db.close()


def test_normal_verify_passes():
    _write_n_audit(10)
    db = SessionLocal()
    try:
        ok, summary, detail = verify_integrity(db)
        assert ok is True
        assert summary == "AUDIT INTEGRITY: PASS"
        assert detail["checked"] >= 10
    finally:
        db.close()


def test_tamper_record_detected():
    """修改一条记录 → 验证失败。"""
    _write_n_audit(5)
    db = SessionLocal()
    try:
        target = db.query(AuditLog).filter(AuditLog.sequence_id.isnot(None)).order_by(AuditLog.sequence_id).first()
        assert target is not None
        target.reason = "被篡改的内容"
        db.commit()

        ok, summary, detail = verify_integrity(db)
        assert ok is False
        assert summary == "AUDIT INTEGRITY: FAILED"
        assert detail["audit_id"] == target.id
    finally:
        db.close()


def test_delete_record_detected():
    """删除一条记录 → 验证失败。"""
    db = SessionLocal()
    try:
        for i in range(5):
            write_audit_log(db, action="integrity.del", decision="allow", risk_level="green", reason=f"del {i}", actor="t")
        logs = db.query(AuditLog).filter(AuditLog.sequence_id.isnot(None)).order_by(AuditLog.sequence_id).all()
        db.delete(logs[1])
        db.commit()

        ok, summary, _ = verify_integrity(db)
        assert ok is False
        assert summary == "AUDIT INTEGRITY: FAILED"
    finally:
        db.close()


def test_reorder_record_detected():
    """篡改 sequence_id 顺序（跳号）→ 验证失败。"""
    db = SessionLocal()
    try:
        for i in range(5):
            write_audit_log(db, action="integrity.reorder", decision="allow", risk_level="green", reason=f"r {i}", actor="t")
        logs = db.query(AuditLog).filter(AuditLog.sequence_id.isnot(None)).order_by(AuditLog.sequence_id).all()
        # 把第 2 条 sequence_id 改成不连续的值（模拟重排/插入中间态）
        logs[1].sequence_id = 100
        db.commit()

        ok, summary, _ = verify_integrity(db)
        assert ok is False
        assert summary == "AUDIT INTEGRITY: FAILED"
    finally:
        db.close()


def test_verify_recovers_after_clean():
    """干净数据再次验证通过。"""
    _write_n_audit(5)
    db = SessionLocal()
    try:
        ok, summary, _ = verify_integrity(db)
        assert ok is True
        assert summary == "AUDIT INTEGRITY: PASS"
    finally:
        db.close()


def test_legacy_records_skipped():
    """迁移前历史记录（sequence_id 为 NULL）不参与哈希链，验证通过。"""
    db = SessionLocal()
    try:
        # 写入一条未签名记录（模拟迁移前历史）
        legacy = AuditLog(
            actor="legacy",
            action="legacy.record",
            decision="allow",
            risk_level="green",
            reason="迁移前历史记录",
            sequence_id=None,
            event_hash="",
            previous_hash="",
        )
        db.add(legacy)
        db.commit()

        # 再写一条已签名记录
        write_audit_log(db, action="integrity.after", decision="allow", risk_level="green", reason="签名后", actor="t")

        ok, summary, _ = verify_integrity(db)
        assert ok is True
        assert summary == "AUDIT INTEGRITY: PASS"
    finally:
        db.close()


def test_wrong_key_detected():
    """密钥不一致 → 验证失败（HMAC 不匹配）。"""
    _write_n_audit(3)
    db = SessionLocal()
    try:
        # 篡改一条记录的 event_hash（模拟密钥错误）
        target = db.query(AuditLog).filter(AuditLog.sequence_id.isnot(None)).order_by(AuditLog.sequence_id).first()
        target.event_hash = "0" * 64
        db.commit()

        ok, summary, _ = verify_integrity(db)
        assert ok is False
    finally:
        db.close()


def test_trigger_blocks_direct_update():
    """数据库触发器阻止直接 UPDATE 已签名审计记录。"""
    _restore_triggers()
    _write_n_audit(3)
    db = SessionLocal()
    try:
        target = db.query(AuditLog).filter(AuditLog.sequence_id.isnot(None)).order_by(AuditLog.sequence_id).first()
        target.reason = "尝试篡改"
        import pytest as _pytest

        with _pytest.raises(Exception):
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_trigger_blocks_direct_delete():
    """数据库触发器阻止直接 DELETE 已签名审计记录。"""
    _restore_triggers()
    _write_n_audit(3)
    db = SessionLocal()
    try:
        target = db.query(AuditLog).filter(AuditLog.sequence_id.isnot(None)).order_by(AuditLog.sequence_id).first()
        db.delete(target)
        import pytest as _pytest

        with _pytest.raises(Exception):
            db.commit()
        db.rollback()
    finally:
        db.close()
