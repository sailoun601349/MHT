# -*- coding: utf-8 -*-
"""首页：手机号入口 / 手机号+查询码入口 / 专属链接落地"""
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from ..models.admin import Admin
from ..utils import is_valid_phone, is_valid_query_code

main_bp = Blueprint("main", __name__)


@main_bp.get("/")
def index():
    return render_template("index.html")


@main_bp.post("/enter")
def enter():
    """智能路由：仅手机号 -> 下单页；手机号+查询码 -> 订单查询页。"""
    phone = request.form.get("phone", "").strip()
    code = request.form.get("code", "").strip()

    if not is_valid_phone(phone):
        flash("请输入正确的 11 位手机号", "error")
        return redirect(url_for("main.index"))

    if code:
        if not is_valid_query_code(code):
            flash("查询码格式不正确（3-6 位数字）", "error")
            return redirect(url_for("main.index"))
        return redirect(url_for("order.query", phone=phone, code=code))

    return redirect(url_for("order.new_order", phone=phone))


@main_bp.get("/<share_code:code>")
def share_landing(code):
    """专属链接落地：校验短码（有效且管理员启用）-> 记归属 -> 302 首页。"""
    admin = Admin.query.filter(
        Admin.share_code == code, Admin.is_active.is_(True)
    ).first()
    if admin is None:
        # 短码无效 / 管理员已停用：清归属，按「无链接」归超级管理员
        session.pop("ref_admin_id", None)
        flash("链接无效，已返回首页", "warning")
        return redirect(url_for("main.index"))

    session["ref_admin_id"] = admin.id
    return redirect(url_for("main.index"))
