# -*- coding: utf-8 -*-
"""轻量 CSRF 防护：会话内 token + 表单隐藏字段 / 请求头。

不引入 Flask-WTF，保持依赖最小。所有 POST/PUT/PATCH/DELETE 请求须携带
与会话一致的 _csrf_token（表单字段或 X-CSRF-Token 请求头）。
"""
import secrets

from flask import abort, request, session

CSRF_TOKEN_KEY = "_csrf_token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def generate_csrf_token() -> str:
    """获取或生成会话级 CSRF token（模板中作为隐藏字段输出）。"""
    token = session.get(CSRF_TOKEN_KEY)
    if not token:
        token = secrets.token_hex(16)
        session[CSRF_TOKEN_KEY] = token
    return token


def validate_csrf() -> None:
    """before_request 钩子：非安全方法校验 token。"""
    if request.method in SAFE_METHODS:
        return
    token = session.get(CSRF_TOKEN_KEY)
    submitted = request.form.get(CSRF_TOKEN_KEY) or request.headers.get("X-CSRF-Token")
    if not token or not submitted or not secrets.compare_digest(token, submitted):
        abort(400, description="CSRF 校验失败，请刷新页面后重试")
