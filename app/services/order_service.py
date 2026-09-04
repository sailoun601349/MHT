# -*- coding: utf-8 -*-
"""订单业务：全局顺序号分配 + 单地址/多地址下单 + 状态机 + 查询"""
import sqlite3

from flask import current_app

from ..extensions import db
from ..models.order import Order, OrderLog
from .spec_service import resolve_spec_for_owner


def get_next_order_seq() -> str:
    """原子分配全局顺序号。

    实现：独立 SQLite 连接 + BEGIN IMMEDIATE，写锁串行化，
    保证并发下不产生重复序号。计数不回退（允许空洞）。
    """
    db_path = current_app.config["DATABASE_PATH"]
    conn = sqlite3.connect(str(db_path), timeout=10)
    try:
        conn.isolation_level = None  # 关闭自动事务，手动控制
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE counters SET value = value + 1 WHERE name = 'order_seq'")
        row = conn.execute(
            "SELECT value FROM counters WHERE name = 'order_seq'"
        ).fetchone()
        conn.execute("COMMIT")
        if row is None:
            raise RuntimeError("counters 表中缺少 order_seq 记录，请检查初始化")
        return f"{row[0]:03d}"
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()


def create_order(data: dict, owner_admin_id=None) -> Order:
    """创建单个地址订单（兼容旧调用/单地址场景）。

    data 需包含：phone, receiver_name, receiver_phone, address,
    spec_id, quantity（spec_id 为适用规格 id；价格以服务端 spec.price_fen 为准）。
    """
    phone = data["phone"]
    addr_form = {
        "receiver_name": data["receiver_name"],
        "receiver_phone": data["receiver_phone"],
        "address": data["address"],
        "spec_id": int(data["spec_id"]),
        "quantity": int(data["quantity"]),
    }
    query_code, orders, _group_total = create_order_group(
        phone, [addr_form], owner_admin_id=owner_admin_id
    )
    return orders[0]


def create_order_group(phone: str, addr_forms: list, owner_admin_id=None) -> tuple:
    """一次提交创建一组订单（一码多址）。

    addr_forms: list[dict]，每个 dict 含：
        receiver_name, receiver_phone, address, spec_id, quantity
    owner_admin_id: 责任管理员 id（可为 None，落库时归超级管理员兜底）。
    返回: (query_code, orders, group_total)
    说明：
      - 每次提交只分配一次全局顺序号；
      - 每条地址按 spec_id 校验「适用 + 启用」（resolve_spec_for_owner），
        价格以规格记录当前 price_fen 为准（防前端篡改，服务端计价）；
      - 每条地址生成一行 Order，sub_no=1..N，spec_id/spec_name/spec_price 落库快照；
      - 每行 total_fee 为该地址小计，group_total 为整组总价。
    """
    if not addr_forms:
        raise ValueError("至少需要 1 个收货地址")

    query_code = get_next_order_seq()
    orders = []
    group_total = 0  # 分
    for i, form in enumerate(addr_forms, start=1):
        spec = resolve_spec_for_owner(form["spec_id"], owner_admin_id)
        quantity = int(form["quantity"])
        # 服务端计价：以规格记录 price_fen 为准（整数分，无浮点误差）
        spec_price_fen = spec.price_fen
        total_fee_fen = spec_price_fen * quantity
        group_total += total_fee_fen
        orders.append(
            Order(
                phone=phone,
                query_code=query_code,
                sub_no=i,
                owner_admin_id=owner_admin_id,
                receiver_name=form["receiver_name"],
                receiver_phone=form["receiver_phone"],
                address=form["address"],
                spec_id=spec.id,
                spec_name=spec.name,
                spec_price=spec_price_fen,
                quantity=quantity,
                total_fee=total_fee_fen,
            )
        )
    try:
        db.session.add_all(orders)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return query_code, orders, group_total


def _log(order, action, from_status, to_status, remark, operator_admin_id):
    """写一条订单操作留痕（随主流程在同一事务内提交）。"""
    db.session.add(
        OrderLog(
            order_id=order.id,
            action=action,
            from_status=from_status,
            to_status=to_status,
            remark=remark or "",
            operator_admin_id=operator_admin_id,
        )
    )


def _ship(order: Order, express_company: str, express_no: str, operator_admin_id=None) -> Order:
    """发货核心逻辑（不含 commit）：校验 + 设置字段 + 写日志。"""
    if not order.can_update_express():
        raise ValueError(f"{order.display_code} 当前状态不可发货或更新快递")
    if not order.photos:
        raise ValueError(f"{order.display_code} 请先上传面单照片")
    if not express_company or not express_no:
        raise ValueError("请填写快递公司和快递单号")

    from_status = order.status
    order.express_company = express_company
    order.express_no = express_no
    order.status = Order.STATUS_SHIPPED
    _log(order, OrderLog.ACTION_SHIP, from_status, order.status,
         f"{express_company} {express_no}", operator_admin_id)
    return order


def ship_order(order: Order, express_company: str, express_no: str, operator_admin_id=None) -> Order:
    """发货/更新快递（单个子订单）。

    - 仅 created/shipped 可操作；
    - created -> shipped（首次发货）；
    - shipped -> shipped（更新快递信息，保留 old 状态语义）；
    - 面单照片独立上传（order.photos），发货前需至少上传 1 张。
    """
    order = _ship(order, express_company, express_no, operator_admin_id)
    db.session.commit()
    return order


def ship_group(group_orders, express_company: str, express_no: str, operator_admin_id=None) -> list:
    """整组发货：同一快递公司 + 单号，一次性给整组子订单发货（单事务，任一失败整体回滚）。"""
    if not group_orders:
        raise ValueError("没有可发货的订单")
    for o in group_orders:
        _ship(o, express_company, express_no, operator_admin_id)
    db.session.commit()
    return group_orders


def change_order_status(order: Order, new_status: str, remark: str = "", operator_admin_id=None) -> Order:
    """按状态机矩阵流转订单状态。

    - 非法流转抛出 ValueError；
    - cancelled / 退回待发货(created) 必须填写备注；
    - 备注写入 order.note；每次流转写 order_logs 留痕。
    """
    if new_status == order.status:
        raise ValueError("订单已处于该状态")
    if not order.can_transition_to(new_status):
        raise ValueError(
            f"不允许从「{order.status_label}」变更为「{order.STATUS_LABELS.get(new_status, new_status)}」"
        )
    if new_status in (Order.STATUS_CANCELLED, Order.STATUS_CREATED) and not (remark or "").strip():
        raise ValueError("该操作必须填写原因/备注")
    from_status = order.status
    if remark.strip():
        order.note = remark.strip()
    order.status = new_status
    _log(order, OrderLog.ACTION_STATUS, from_status, new_status, remark, operator_admin_id)
    db.session.commit()
    return order


def get_orders_by_phone_code(phone: str, code: str) -> list:
    """按 手机号 + 查询码 返回整组子订单（按地址序号排序）。"""
    return (
        Order.query.filter_by(phone=phone, query_code=code)
        .order_by(Order.sub_no.asc())
        .all()
    )


def get_super_admin():
    """返回唯一的超级管理员（无则 None）。"""
    from ..models.admin import Admin

    return Admin.query.filter_by(role=Admin.ROLE_SUPER).first()


def resolve_order_owner(ref_admin_id):
    """解析订单责任管理员 id（下单时调用）。

    规则（PRD §8.3）：
      - 访问过有效专属链接且该管理员启用 -> 该管理员 id；
      - 未访问 / 短码无效 / 管理员停用 -> 超级管理员 id。
    """
    from ..models.admin import Admin

    if ref_admin_id is not None:
        admin = db.session.get(Admin, ref_admin_id)
        if admin is not None and admin.is_active:
            return admin.id

    super_admin = get_super_admin()
    return super_admin.id if super_admin is not None else None