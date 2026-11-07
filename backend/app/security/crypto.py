"""共享密码学原语（与业务无关的纯算法封装）。

本模块**只负责算法，不解析任何密钥**。MFA、会话、限流、审计四条链路各自的
密钥来源与回退链并不相同（见各模块 ``_secret()`` / ``_hmac_key()``），必须继续
由各自模块自行决定，以保证已落库的摘要与既有审计哈希链逐字节兼容。

因此这里只收敛 ``HMAC-SHA256 → 十六进制字符串`` 这一份重复实现，
替换算法或编码时改本文件一处即可。
"""

from __future__ import annotations

import hashlib
import hmac


def hmac_sha256_hex(key: str, data: str) -> str:
    """HMAC-SHA256，返回 64 位小写十六进制摘要。

    与 ``hmac.new(key.encode("utf-8"), data.encode("utf-8"), hashlib.sha256).hexdigest()``
    完全等价；密钥与数据均按 UTF-8 编码。
    """
    return hmac.new(key.encode("utf-8"), data.encode("utf-8"), hashlib.sha256).hexdigest()


__all__ = ["hmac_sha256_hex"]
