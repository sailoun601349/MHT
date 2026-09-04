# -*- coding: utf-8 -*-
"""用户端：下单 / 成功页 / 订单查询（支持一码多址）"""
import secrets

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from ..extensions import db
from ..models.order import Order
from ..services.order_service import (
    create_order_group,
    get_orders_by_phone_code,
    resolve_order_owner,
)
from ..services.spec_service import get_applicable_specs
from ..utils import client_ip, is_valid_phone, is_valid_query_code
from ..utils.ratelimit import SlidingWindowLimiter

order_bp = Blueprint("order", __name__, url_prefix="/order")

create_limiter = SlidingWindowLimiter(limit=5, window_seconds=60)
query_limiter = SlidingWindowLimiter(limit=10, window_seconds=60)


@order_bp.get("/new")
def new_order():
    phone = request.args.get("phone", "").strip()
    if not is_valid_phone(phone):
        flash("手机号不正确，请从首页重新进入", "error")
        return redirect(url_for("main.index"))
    # 幂等提交令牌：同一表单只能成功提交一次，防止双击/重复提交
    order_nonce = secrets.token_hex(8)
    session["order_nonce"] = order_nonce
    # 提前解析归属管理员，只渲染其「适用且启用」的规格
    owner_admin_id = resolve_order_owner(session.get("ref_admin_id"))
    specs = get_applicable_specs(owner_admin_id, active_only=True)
    return render_template(
        "order/new.html",
        phone=phone,
        specs=specs,
        owner_admin_id=owner_admin_id,
        max_addresses=current_app.config["MAX_ADDRESSES"],
        order_nonce=order_nonce,
    )


@order_bp.post("/create")
def create():
    phone = request.form.get("phone", "").strip()
    ip = client_ip(request)

    if not create_limiter.allow(ip):
        flash("操作太频繁，请稍后再试", "error")
        return redirect(url_for("main.index"))

    # 幂等提交校验：同一表单令牌只允许成功一次，拦截双击/重复提交
    submit_nonce = request.form.get("submit_nonce", "")
    expected_nonce = session.get("order_nonce")
    if not submit_nonce or not expected_nonce or not secrets.compare_digest(submit_nonce, expected_nonce):
        flash("请勿重复提交订单", "error")
        return redirect(url_for("main.index"))
    session.pop("order_nonce", None)

    if not is_valid_phone(phone):
        flash("下单手机号不正确", "error")
        return redirect(url_for("main.index"))

    try:
        address_count = int(request.form.get("address_count", "1"))
    except (TypeError, ValueError):
        address_count = 0

    max_addresses = current_app.config["MAX_ADDRESSES"]
    if not 1 <= address_count <= max_addresses:
        flash(f"收货地址数量需在 1-{max_addresses} 之间", "error")
        return redirect(url_for("order.new_order", phone=phone))

    addr_forms = []
    for i in range(address_count):
        receiver_name = request.form.get(f"receiver_name_{i}", "").strip()
        receiver_phone = request.form.get(f"receiver_phone_{i}", "").strip()
        address = request.form.get(f"address_{i}", "").strip()
        try:
            spec_id = int(request.form.get(f"spec_id_{i}", "") or "0")
        except (TypeError, ValueError):
            spec_id = 0
        try:
            quantity = int(request.form.get(f"quantity_{i}", ""))
        except (TypeError, ValueError):
            quantity = 0

        # ---- 逐地址校验 ----
        if not receiver_name or len(receiver_name) > 100:
            flash(f"第 {i + 1} 个地址：请填写收货人姓名（100 字以内）", "error")
            return redirect(url_for("order.new_order", phone=phone))
        if not is_valid_phone(receiver_phone):
            flash(f"第 {i + 1} 个地址：收货电话不正确", "error")
            return redirect(url_for("order.new_order", phone=phone))
        if not address or len(address) > 500:
            flash(f"第 {i + 1} 个地址：请填写完整收货地址（500 字以内）", "error")
            return redirect(url_for("order.new_order", phone=phone))
        if not 1 <= quantity <= 99:
            flash(f"第 {i + 1} 个地址：数量需在 1-99 之间", "error")
            return redirect(url_for("order.new_order", phone=phone))
        if spec_id <= 0:
            flash(f"第 {i + 1} 个地址：请选择规格", "error")
            return redirect(url_for("order.new_order", phone=phone))

        addr_forms.append(
            {
                "receiver_name": receiver_name,
                "receiver_phone": receiver_phone,
                "address": address,
                "spec_id": spec_id,
                "quantity": quantity,
            }
        )

    # ---- 落库 ----
    owner_admin_id = resolve_order_owner(session.get("ref_admin_id"))
    try:
        query_code, orders, group_total = create_order_group(
            phone, addr_forms, owner_admin_id=owner_admin_id
        )
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("order.new_order", phone=phone))
    except Exception:
        current_app.logger.exception("下单失败")
        flash("下单失败，请稍后重试", "error")
        return redirect(url_for("order.new_order", phone=phone))

    return redirect(url_for("order.success", phone=phone, code=query_code))


@order_bp.get("/success")
def success():
    phone = request.args.get("phone", "").strip()
    code = request.args.get("query_code", "").strip() or request.args.get("code", "").strip()

    if not is_valid_phone(phone) or not is_valid_query_code(code):
        flash("查询码参数不正确", "error")
        return redirect(url_for("main.index"))

    orders = get_orders_by_phone_code(phone, code)
    if not orders:
        flash("未找到订单，请检查手机号和查询码", "error")
        return redirect(url_for("main.index"))

    group_total = round(sum(o.total_fee for o in orders) / 100, 2)
    return render_template(
        "order/success.html",
        phone=phone,
        query_code=code,
        orders=orders,
        group_total=group_total,
    )


@order_bp.get("/success/<int:order_id>")
def success_legacy(order_id):
    """兼容旧版下单成功页链接 /order/success/<id>。"""
    order = db.get_or_404(Order, order_id)
    return redirect(
        url_for("order.success", phone=order.phone, code=order.query_code)
    )


@order_bp.get("/query")
def query():
    phone = request.args.get("phone", "").strip()
    code = request.args.get("code", "").strip()

    # 限流 key 用「IP + 手机号」组合，防止换 IP 穷举同一手机号
    if not query_limiter.allow(f"{client_ip(request)}:{phone}"):
        flash("查询太频繁，请稍后再试", "error")
        return redirect(url_for("main.index"))

    if not is_valid_phone(phone) or not is_valid_query_code(code):
        flash("手机号或查询码不正确", "error")
        return redirect(url_for("main.index"))

    orders = get_orders_by_phone_code(phone, code)
    if not orders:
        flash("未找到订单，请检查手机号和查询码", "error")
        return redirect(url_for("main.index"))

    group_total = round(sum(o.total_fee for o in orders) / 100, 2)
    return render_template(
        "order/query.html",
        phone=phone,
        query_code=code,
        orders=orders,
        group_total=group_total,
    )