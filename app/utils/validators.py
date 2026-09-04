# -*- coding: utf-8 -*-
"""输入校验工具"""
import re

PHONE_RE = re.compile(r"^1[3-9]\d{9}$")
QUERY_CODE_RE = re.compile(r"^\d{3,6}$")
SHARE_CODE_RE = re.compile(r"^\d{4,6}$")


def is_valid_phone(value) -> bool:
    """中国大陆手机号：1 开头 11 位。"""
    return bool(PHONE_RE.match((value or "").strip()))


def is_valid_query_code(value) -> bool:
    """查询码：3-6 位数字。"""
    return bool(QUERY_CODE_RE.match((value or "").strip()))


def is_valid_share_code(value) -> bool:
    """专属短码：4-6 位纯数字。"""
    return bool(SHARE_CODE_RE.match((value or "").strip()))


def client_ip(request) -> str:
    """获取客户端真实 IP（兼容 Nginx 反代）。

    优先读 X-Real-IP（nginx 由 $remote_addr 设置，覆盖客户端伪造值，可信）；
    其次 X-Forwarded-For（取第一个）；最后 remote_addr。
    """
    real_ip = request.headers.get("X-Real-IP", "").strip()
    if real_ip:
        return real_ip
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"
