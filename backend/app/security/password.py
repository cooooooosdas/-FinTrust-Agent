"""密码哈希（PBKDF2-HMAC-SHA256 + 随机盐）。

不引入额外依赖，使用标准库 hashlib 实现成熟的密钥派生方案。
禁止使用普通 SHA256 直接保存密码。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from app.security.crypto import hmac_sha256_hex

#: PBKDF2 迭代次数（SHA256）
PBKDF2_ITERATIONS = 260_000
#: 盐长度（字节）
SALT_BYTES = 16


def hash_password(password: str) -> str:
    """返回 ``pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>``。"""
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    """校验密码是否匹配已存储的哈希（恒定时间比较）。"""
    try:
        algo, iterations_str, salt_hex, hash_hex = encoded.split("$")
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iterations_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(digest, expected)


def token_hash(token: str, secret: str) -> str:
    """对 Session Token 做 HMAC 摘要（服务端仅存摘要，不存明文）。"""
    return hmac_sha256_hex(secret, token)


__all__ = ["hash_password", "verify_password", "token_hash", "PBKDF2_ITERATIONS"]
