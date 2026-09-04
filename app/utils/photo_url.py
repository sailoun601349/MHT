# -*- coding: utf-8 -*-
"""面单照片签名 URL：HMAC 时效签名，防止照片 URL 外泄后长期可访问。

- 每个照片链接带 exp（过期时间戳）+ sig（HMAC-SHA256(SECRET_KEY, "path:exp") 截断）
- 默认 2 小时有效，页面渲染时生成、浏览器即时加载，足够覆盖正常浏览。
"""
import hashlib
import hmac
import time

from flask import current_app, url_for

PHOTO_URL_EXPIRES_IN = 2 * 3600  # 默认有效期 2 小时


def _photo_signature(filename: str, expiry: int) -> str:
    message = f"{filename}:{expiry}".encode("utf-8")
    digest = hmac.new(
        current_app.config["SECRET_KEY"].encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()
    return digest[:24]


def signed_photo_url(filename: str, expires_in: int = PHOTO_URL_EXPIRES_IN) -> str:
    """生成带时效签名的照片访问 URL（模板里替代 url_for('uploaded_file')）。"""
    expiry = int(time.time()) + expires_in
    sig = _photo_signature(filename, expiry)
    return url_for("uploaded_file", filename=filename, exp=expiry, sig=sig)


def verify_photo_signature(filename: str, expiry: int, sig: str) -> bool:
    """校验签名是否匹配且未过期。"""
    if not sig or expiry < int(time.time()):
        return False
    expected = _photo_signature(filename, expiry)
    return hmac.compare_digest(sig, expected)
