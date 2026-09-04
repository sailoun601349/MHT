# -*- coding: utf-8 -*-
from datetime import datetime

from ..extensions import db


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Order(db.Model):
    __tablename__ = "orders"

    # 状态
    STATUS_CREATED = "created"
    STATUS_SHIPPED = "shipped"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"

    STATUS_LABELS = {
        STATUS_CREATED: "待发货",
        STATUS_SHIPPED: "已发货",
        STATUS_COMPLETED: "已完成",
        STATUS_CANCELLED: "已取消",
    }
    STATUS_BADGES = {
        STATUS_CREATED: "warning",
        STATUS_SHIPPED: "primary",
        STATUS_COMPLETED: "success",
        STATUS_CANCELLED: "secondary",
    }

    # 状态机：当前状态 -> 允许到达的状态集合（唯一状态裁判）
    STATUS_TRANSITIONS = {
        STATUS_CREATED: {STATUS_SHIPPED, STATUS_CANCELLED},
        STATUS_SHIPPED: {STATUS_SHIPPED, STATUS_COMPLETED, STATUS_CANCELLED, STATUS_CREATED},
        STATUS_COMPLETED: set(),
        STATUS_CANCELLED: set(),
    }

    __table_args__ = (
        db.UniqueConstraint(
            "phone", "query_code", "sub_no", name="uq_orders_phone_code_subno"
        ),
        db.Index("idx_orders_phone_code", "phone", "query_code"),
    )

    id = db.Column(db.Integer, primary_key=True)
    owner_admin_id = db.Column(db.Integer, db.ForeignKey("admins.id"), nullable=True, index=True)  # 责任管理员 id
    phone = db.Column(db.String(20), nullable=False, index=True)          # 下单手机号（组）
    query_code = db.Column(db.String(20), nullable=False)                 # 全局顺序号（组码），不再单独唯一
    sub_no = db.Column(db.Integer, nullable=False, default=1)             # 组内地址序号 1..N
    receiver_name = db.Column(db.String(100), nullable=False)
    receiver_phone = db.Column(db.String(20), nullable=False)
    address = db.Column(db.String(500), nullable=False)   # 完整收货地址（省市区+街道门牌）
    spec_name = db.Column(db.String(50), nullable=False)
    spec_price = db.Column(db.Integer, nullable=False)   # 单价（分）
    quantity = db.Column(db.Integer, nullable=False)
    total_fee = db.Column(db.Integer, nullable=False)    # 本地址小计（分）
    status = db.Column(db.String(20), nullable=False, default=STATUS_CREATED, index=True)
    express_company = db.Column(db.String(50), nullable=False, default="")
    express_no = db.Column(db.String(50), nullable=False, default="")
    note = db.Column(db.String(300), nullable=False, default="")
    created_at = db.Column(db.String(30), nullable=False, default=_now)
    updated_at = db.Column(db.String(30), nullable=False, default=_now, onupdate=_now)

    # 责任管理员（ORM 关系，用于展示「责任人」手机号；历史数据迁移后无空值）
    owner = db.relationship("Admin", foreign_keys=[owner_admin_id], lazy="joined")
    # 面单照片（一单多张，按子订单 quantity 的 2 倍封顶）
    photos = db.relationship("OrderPhoto", backref="order", cascade="all, delete-orphan", lazy="joined")

    @property
    def owner_phone(self) -> str:
        """责任管理员手机号；无归属时回退空串（迁移后不应出现）。"""
        return self.owner.phone if self.owner is not None else ""

    @property
    def spec_price_yuan(self) -> float:
        """单价（元），由整数分换算，用于展示。"""
        return self.spec_price / 100

    @property
    def total_fee_yuan(self) -> float:
        """本地址小计（元），由整数分换算，用于展示。"""
        return self.total_fee / 100

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def status_badge(self):
        return self.STATUS_BADGES.get(self.status, "secondary")

    @property
    def display_code(self):
        """查询码展示：手机号 + 全局顺序号（组码）。"""
        return f"{self.phone} + {self.query_code}"

    @property
    def group_orders(self):
        """同一次提交（同手机号+查询码）的全部子订单，按地址序号排序。"""
        return (
            Order.query.filter_by(phone=self.phone, query_code=self.query_code)
            .order_by(Order.sub_no.asc())
            .all()
        )

    @property
    def group_index(self):
        """该子订单在组内的 1-based 位置；组内 N 条时展示用。"""
        return self.group_orders.index(self) + 1

    @property
    def group_total(self):
        """组总价（分）= 组内所有子订单金额之和。"""
        return sum(o.total_fee for o in self.group_orders)

    @property
    def group_total_yuan(self) -> float:
        """组总价（元）。"""
        return self.group_total / 100

    @property
    def group_size(self):
        return len(self.group_orders)

    def can_transition_to(self, new_status: str) -> bool:
        return new_status in self.STATUS_TRANSITIONS.get(self.status, set())

    def can_update_express(self) -> bool:
        """发货或更新快递：仅待发货/已发货可操作。"""
        return self.status in (self.STATUS_CREATED, self.STATUS_SHIPPED)

    @property
    def available_actions(self):
        """返回当前状态下可展示/可提交的目标状态集合（status 值）。"""
        return self.STATUS_TRANSITIONS.get(self.status, set())

    @property
    def max_photos(self) -> int:
        """面单照片上限 = 箱子数量（quantity）× 2，至少 1 张。"""
        return max(int(self.quantity) * 2, 1)

    def __repr__(self):
        return f"<Order {self.display_code} #{self.sub_no}>"


class OrderPhoto(db.Model):
    """面单照片（一单多张，支持单张删除）。"""

    __tablename__ = "order_photos"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, index=True)
    path = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.String(30), nullable=False, default=_now)

    def __repr__(self):
        return f"<OrderPhoto #{self.id} order={self.order_id}>"


class OrderLog(db.Model):
    """订单操作留痕：发货 / 状态流转记录（from→to、备注、操作人、时间）。"""

    __tablename__ = "order_logs"

    # 动作类型
    ACTION_CREATE = "create"
    ACTION_SHIP = "ship"
    ACTION_STATUS = "status"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, index=True)
    action = db.Column(db.String(30), nullable=False)            # create/ship/status
    from_status = db.Column(db.String(20), nullable=False, default="")
    to_status = db.Column(db.String(20), nullable=False, default="")
    remark = db.Column(db.String(300), nullable=False, default="")
    operator_admin_id = db.Column(db.Integer, db.ForeignKey("admins.id"), nullable=True)
    created_at = db.Column(db.String(30), nullable=False, default=_now)

    operator = db.relationship("Admin", foreign_keys=[operator_admin_id], lazy="joined")

    @property
    def operator_phone(self) -> str:
        return self.operator.phone if self.operator is not None else ""

    @property
    def action_label(self) -> str:
        return {
            self.ACTION_CREATE: "创建",
            self.ACTION_SHIP: "发货",
            self.ACTION_STATUS: "状态变更",
        }.get(self.action, self.action)

    @property
    def from_status_label(self) -> str:
        return Order.STATUS_LABELS.get(self.from_status, self.from_status or "—")

    @property
    def to_status_label(self) -> str:
        return Order.STATUS_LABELS.get(self.to_status, self.to_status or "—")

    def __repr__(self):
        return f"<OrderLog #{self.id} order={self.order_id} {self.action}>"