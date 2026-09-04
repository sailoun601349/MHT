# -*- coding: utf-8 -*-
"""管理端：登录 / 订单 / 发货 / 状态 / 管理员管理 / 自助改密 / 面单照片管理"""
import csv
from datetime import datetime
from functools import wraps
from io import StringIO

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import or_, tuple_

from ..extensions import db
from ..models.admin import Admin
from ..models.order import Order, OrderLog, OrderPhoto
from ..services.admin_service import (
    create_admin,
    delete_admin,
    share_code_taken,
)
from ..services.upload_service import save_photo
from ..services.order_service import change_order_status, ship_group, ship_order
from ..utils import client_ip, is_valid_phone, is_valid_share_code
from ..utils.ratelimit import LoginThrottle

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

login_throttle = LoginThrottle(max_fails=5, lock_minutes=10)

EXPRESS_COMPANIES = ["顺丰速运", "中通快递", "圆通速递", "韵达快递", "极兔速递", "邮政EMS", "其他"]


def super_required(view):
    """仅超级管理员可访问。"""

    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_super:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def require_order_owner(order):
    """数据隔离：非超级管理员且非订单责任人 -> 403。"""
    if not current_user.is_super and order.owner_admin_id != current_user.id:
        abort(403)


def _min_password_len():
    return int(current_app.config.get("ADMIN_PASSWORD_MIN_LENGTH", 6))


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("admin.orders"))

    if request.method == "POST":
        ip = client_ip(request)
        if login_throttle.is_locked(ip):
            flash("登录失败次数过多，请 10 分钟后再试", "error")
            return render_template("admin/login.html")

        phone = request.form.get("phone", "").strip()
        code = request.form.get("code", "").strip()

        if not is_valid_phone(phone):
            flash("手机号格式不正确", "error")
            return render_template("admin/login.html")

        admin = Admin.query.filter_by(phone=phone).first()
        if admin is not None and admin.is_active and admin.check_code(code):
            session.permanent = True  # 会话时长 = PERMANENT_SESSION_LIFETIME
            login_user(admin)
            login_throttle.reset(ip)
            if admin.must_change_password:
                flash("首次登录，请先修改初始登录密码", "warning")
                return redirect(url_for("admin.change_password"))
            return redirect(url_for("admin.orders"))

        if admin is not None and not admin.is_active:
            flash("该账号已被停用，请联系管理员", "error")
            return render_template("admin/login.html")

        login_throttle.record_fail(ip)
        remaining = login_throttle.max_fails - login_throttle._get(ip)["fails"]
        flash(f"手机号或登录密码错误（剩余 {max(remaining, 0)} 次机会）", "error")

    return render_template("admin/login.html")


@admin_bp.post("/logout")
@login_required
def logout():
    logout_user()
    flash("已退出登录", "info")
    return redirect(url_for("admin.login"))


def _apply_order_filters(q, status, keyword, owner_phone, start_date="", end_date=""):
    """应用订单列表通用筛选（数据隔离 + 状态 + 关键词 + 责任人 + 日期区间）。"""
    if not current_user.is_super:
        q = q.filter(Order.owner_admin_id == current_user.id)
    if status in Order.STATUS_LABELS:
        q = q.filter_by(status=status)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            or_(
                Order.phone.like(like),
                Order.query_code.like(like),
                Order.receiver_name.like(like),
            )
        )
    if owner_phone and current_user.is_super:
        target = Admin.query.filter_by(phone=owner_phone).first()
        if target is not None:
            q = q.filter(Order.owner_admin_id == target.id)
        else:
            q = q.filter(Order.owner_admin_id == -1)
    # 日期区间（created_at 为 "YYYY-MM-DD HH:MM:SS" 字符串，字典序即时间序）
    if start_date:
        q = q.filter(Order.created_at >= start_date + " 00:00:00")
    if end_date:
        q = q.filter(Order.created_at <= end_date + " 23:59:59")
    return q


@admin_bp.get("/orders")
@login_required
def orders():
    status = request.args.get("status", "all")
    keyword = request.args.get("q", "").strip()
    owner_phone = request.args.get("owner", "").strip()
    start_date = request.args.get("start", "").strip()
    end_date = request.args.get("end", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    if per_page not in (20, 50, 100):
        per_page = 20

    # ---- 顶部统计卡片（与列表相同的归属隔离，不受状态/关键词/日期筛选影响） ----
    stat_q = Order.query
    if not current_user.is_super:
        stat_q = stat_q.filter(Order.owner_admin_id == current_user.id)
    today_start = datetime.now().strftime("%Y-%m-%d") + " 00:00:00"
    stats = {
        "today_count": stat_q.filter(Order.created_at >= today_start).count(),
        "pending_count": stat_q.filter(Order.status == Order.STATUS_CREATED).count(),
        "sales_yuan": round(
            (
                stat_q.filter(Order.status != Order.STATUS_CANCELLED)
                .with_entities(db.func.coalesce(db.func.sum(Order.total_fee), 0))
                .scalar()
                or 0
            )
            / 100,
            2,
        ),
        "total_count": stat_q.count(),
    }

    q = _apply_order_filters(Order.query, status, keyword, owner_phone, start_date, end_date)

    pagination = q.order_by(Order.id.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    order_list = pagination.items

    # 预取组大小（一次 GROUP BY），避免模板 o.group_size 触发 N+1 查询
    group_sizes = {}
    if order_list:
        group_keys = list({(o.phone, o.query_code) for o in order_list})
        rows = (
            db.session.query(Order.phone, Order.query_code, db.func.count(Order.id))
            .filter(tuple_(Order.phone, Order.query_code).in_(group_keys))
            .group_by(Order.phone, Order.query_code)
            .all()
        )
        group_sizes = {(phone, code): cnt for phone, code, cnt in rows}

    return render_template(
        "admin/orders.html",
        orders=order_list,
        pagination=pagination,
        current_status=status,
        keyword=keyword,
        owner_phone=owner_phone,
        start_date=start_date,
        end_date=end_date,
        statuses=Order.STATUS_LABELS,
        stats=stats,
        group_sizes=group_sizes,
    )


@admin_bp.get("/orders/export.csv")
@login_required
def export_orders_csv():
    """导出订单为 CSV（复用列表筛选条件，含数据隔离）。"""
    status = request.args.get("status", "all")
    keyword = request.args.get("q", "").strip()
    owner_phone = request.args.get("owner", "").strip()
    start_date = request.args.get("start", "").strip()
    end_date = request.args.get("end", "").strip()

    q = _apply_order_filters(Order.query, status, keyword, owner_phone, start_date, end_date)
    orders = q.order_by(Order.id.desc()).all()

    buf = StringIO()
    writer = csv.writer(buf)
    # BOM 便于 Excel 正确识别 UTF-8 中文
    buf.write("\ufeff")
    writer.writerow([
        "查询码", "下单手机号", "子单", "收货人", "收货电话", "收货地址",
        "规格", "数量", "金额(元)", "状态", "快递公司", "快递单号",
        "责任人", "下单时间",
    ])
    for o in orders:
        writer.writerow([
            o.query_code, o.phone, o.sub_no, o.receiver_name, o.receiver_phone,
            o.address, o.spec_name, o.quantity, f"{o.total_fee / 100:.2f}",
            o.status_label, o.express_company, o.express_no,
            o.owner_phone, o.created_at,
        ])

    filename = f"orders_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        buf.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@admin_bp.get("/orders/<int:order_id>")
@login_required
def order_detail(order_id):
    order = db.get_or_404(Order, order_id)
    require_order_owner(order)
    group_orders = order.group_orders
    group_index = next(
        (i + 1 for i, o in enumerate(group_orders) if o.id == order.id),
        1,
    )
    logs = (
        OrderLog.query.filter_by(order_id=order.id)
        .order_by(OrderLog.id.asc())
        .all()
    )
    return render_template(
        "admin/order_detail.html",
        order=order,
        companies=EXPRESS_COMPANIES,
        group_orders=group_orders,
        group_index=group_index,
        group_size=len(group_orders),
        group_total=round(sum(o.total_fee for o in group_orders) / 100, 2),
        logs=logs,
    )


@admin_bp.post("/orders/<int:order_id>/ship")
@login_required
def ship(order_id):
    order = db.get_or_404(Order, order_id)
    require_order_owner(order)

    company = request.form.get("express_company", "").strip()
    express_no = request.form.get("express_no", "").strip()
    if not company or not express_no:
        flash("请填写快递公司和快递单号", "error")
        return redirect(url_for("admin.order_detail", order_id=order.id))

    try:
        ship_order(order, company, express_no, operator_admin_id=current_user.id)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin.order_detail", order_id=order.id))

    flash("已保存发货信息", "success")
    return redirect(url_for("admin.order_detail", order_id=order.id))


@admin_bp.post("/orders/<int:order_id>/ship-group")
@login_required
def ship_group_route(order_id):
    """整组发货：同一查询码下所有子订单，用同一快递公司 + 单号一次性发货。"""
    order = db.get_or_404(Order, order_id)
    require_order_owner(order)
    group_orders = order.group_orders

    company = request.form.get("express_company", "").strip()
    express_no = request.form.get("express_no", "").strip()
    if not company or not express_no:
        flash("请填写快递公司和快递单号", "error")
        return redirect(url_for("admin.order_detail", order_id=order.id))

    try:
        ship_group(group_orders, company, express_no, operator_admin_id=current_user.id)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin.order_detail", order_id=order.id))

    flash(f"已整组发货（共 {len(group_orders)} 个地址）", "success")
    return redirect(url_for("admin.order_detail", order_id=order.id))


@admin_bp.post("/orders/<int:order_id>/photos")
@login_required
def upload_photos(order_id):
    """上传面单照片（拍照/相册均可，支持多张），数量上限 = 箱子数 × 2。"""
    order = db.get_or_404(Order, order_id)
    require_order_owner(order)

    # 拍照按钮（capture，单文件，name=photo）与相册按钮（multiple，name=photos）合并处理
    files = request.files.getlist("photos")
    single = request.files.get("photo")
    if single is not None and single.filename:
        files = [single] + files
    files = [f for f in files if f is not None and f.filename]

    if not files:
        flash("请先选择要上传的照片", "error")
        return redirect(url_for("admin.order_detail", order_id=order.id))

    max_photos = order.max_photos
    current_count = len(order.photos)
    if current_count + len(files) > max_photos:
        flash(
            f"照片数量已达上限（最多 {max_photos} 张，当前已上传 {current_count} 张）",
            "error",
        )
        return redirect(url_for("admin.order_detail", order_id=order.id))

    saved = 0
    for f in files:
        try:
            path = save_photo(f)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("admin.order_detail", order_id=order.id))
        db.session.add(OrderPhoto(order_id=order.id, path=path))
        saved += 1
    db.session.commit()
    flash(f"已上传 {saved} 张面单照片", "success")
    return redirect(url_for("admin.order_detail", order_id=order.id))


@admin_bp.post("/orders/<int:order_id>/photos/<int:photo_id>/delete")
@login_required
def delete_photo(order_id, photo_id):
    """删除单张面单照片（同时删除磁盘文件），删除后可重新上传。"""
    order = db.get_or_404(Order, order_id)
    require_order_owner(order)

    photo = db.get_or_404(OrderPhoto, photo_id)
    if photo.order_id != order.id:
        abort(404)

    file_path = current_app.config["UPLOAD_DIR"] / photo.path
    try:
        file_path.unlink(missing_ok=True)
    except OSError:
        pass

    db.session.delete(photo)
    db.session.commit()
    flash("已删除照片", "success")
    return redirect(url_for("admin.order_detail", order_id=order.id))


@admin_bp.post("/orders/<int:order_id>/status")
@login_required
def change_status(order_id):
    order = db.get_or_404(Order, order_id)
    require_order_owner(order)
    new_status = request.form.get("status", "")
    remark = request.form.get("remark", "").strip()

    if new_status not in Order.STATUS_LABELS:
        flash("不支持的状态变更", "error")
        return redirect(url_for("admin.order_detail", order_id=order.id))

    try:
        change_order_status(order, new_status, remark, operator_admin_id=current_user.id)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin.order_detail", order_id=order.id))

    flash("订单状态已更新", "success")
    return redirect(url_for("admin.order_detail", order_id=order.id))


# ---- 管理员管理（超级管理员） ----

@admin_bp.get("/admins")
@super_required
def admins():
    admin_list = Admin.query.order_by(Admin.id.asc()).all()
    return render_template("admin/admins.html", admins=admin_list)


@admin_bp.post("/admins")
@super_required
def create_admin_route():
    phone = request.form.get("phone", "").strip()
    password = request.form.get("password", "").strip()
    name = request.form.get("name", "").strip()

    if not is_valid_phone(phone):
        flash("手机号格式不正确", "error")
        return redirect(url_for("admin.admins"))
    if len(password) < _min_password_len():
        flash(f"初始登录密码至少 {_min_password_len()} 位", "error")
        return redirect(url_for("admin.admins"))

    try:
        admin = create_admin(phone, name, password, current_user.phone)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin.admins"))

    flash(
        f"已创建管理员 {admin.phone}，专属短码 {admin.share_code}，"
        f"初始登录密码：{password}（请转告对方）",
        "success",
    )
    return redirect(url_for("admin.admins"))


@admin_bp.post("/admins/<int:admin_id>/reset-password")
@super_required
def reset_admin_password(admin_id):
    admin = db.get_or_404(Admin, admin_id)
    if admin.is_super:
        flash("超级管理员密码请通过「修改密码」自助修改", "error")
        return redirect(url_for("admin.admins"))

    new_password = request.form.get("password", "").strip()
    if len(new_password) < _min_password_len():
        flash(f"新登录密码至少 {_min_password_len()} 位", "error")
        return redirect(url_for("admin.admins"))

    admin.set_password(new_password)
    db.session.commit()
    flash(f"已重置 {admin.phone} 的登录密码：{new_password}（请转告对方）", "success")
    return redirect(url_for("admin.admins"))


@admin_bp.post("/admins/<int:admin_id>/toggle-active")
@super_required
def toggle_admin_active(admin_id):
    admin = db.get_or_404(Admin, admin_id)
    if admin.is_super:
        flash("超级管理员账号不可停用", "error")
        return redirect(url_for("admin.admins"))

    admin.is_active = not admin.is_active
    db.session.commit()
    flash(f"{admin.phone} 已{'启用' if admin.is_active else '停用'}", "success")
    return redirect(url_for("admin.admins"))


@admin_bp.post("/admins/<int:admin_id>/delete")
@super_required
def delete_admin_route(admin_id):
    admin = db.get_or_404(Admin, admin_id)
    try:
        delete_admin(admin)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin.admins"))

    flash(f"已删除 {admin.phone}，其名下订单已转移给超级管理员", "success")
    return redirect(url_for("admin.admins"))


# ---- 自助改密 / 个人设置 / 专属短码 ----

@admin_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current_password = request.form.get("current_password", "").strip()
        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        # 首次登录强制改密时，不要求当前密码
        if not current_user.must_change_password:
            if not current_user.check_code(current_password):
                flash("当前登录密码不正确", "error")
                return render_template("admin/change_password.html")

        if len(new_password) < _min_password_len():
            flash(f"新登录密码至少 {_min_password_len()} 位", "error")
            return render_template("admin/change_password.html")
        if new_password != confirm_password:
            flash("两次输入的新密码不一致", "error")
            return render_template("admin/change_password.html")

        current_user.set_password(new_password)
        db.session.commit()
        logout_user()
        flash("登录密码已修改，请使用新密码重新登录", "success")
        return redirect(url_for("admin.login"))

    return render_template("admin/change_password.html")


@admin_bp.get("/settings")
@login_required
def settings():
    share_url = None
    if not current_user.is_super and current_user.share_code:
        share_url = request.host_url.rstrip("/") + "/" + current_user.share_code
    return render_template("admin/settings.html", share_url=share_url)


@admin_bp.post("/share-code")
@login_required
def update_share_code():
    if current_user.is_super:
        flash("超级管理员使用根路径接单，无需专属短码", "error")
        return redirect(url_for("admin.settings"))

    new_code = request.form.get("share_code", "").strip()
    if not is_valid_share_code(new_code):
        flash("专属短码需为 4-6 位纯数字", "error")
        return redirect(url_for("admin.settings"))
    if share_code_taken(new_code, exclude_admin_id=current_user.id):
        flash("该短码已被占用，请换一个", "error")
        return redirect(url_for("admin.settings"))

    current_user.share_code = new_code
    db.session.commit()
    flash(f"专属短码已更新为 {new_code}", "success")
    return redirect(url_for("admin.settings"))
