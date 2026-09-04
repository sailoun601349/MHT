# -*- coding: utf-8 -*-
"""商品规格（specs）与规格 × 适用管理员（spec_admins）。

- Spec：规格记录（允许重名，按 id 区分）；内置 5斤装/10斤装由启动 seed 保证，
  名称/价格锁定、不可删除；自定义规格由超管/管理员创建维护。
- SpecAdmin：一条记录 = 该规格对该管理员「可见可售」；
  创建者与自己的规格必有一条适用记录（删除规格前不可移除）。
"""
from datetime import datetime

from ..extensions import db


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Spec(db.Model):
    __tablename__ = "specs"

    id = db.Column(db.Integer, primary_key=True)
    # 规格名（允许重名，非唯一；下单/计价以 id 为准）
    name = db.Column(db.String(50), nullable=False)
    # 单价（分）；内置固定 5000 / 10000，改价接口对内置一律拒绝
    price_fen = db.Column(db.Integer, nullable=False)
    # 是否内置（5斤装 / 10斤装）：名称/价格锁定 + 每个启用管理员默认适用
    is_builtin = db.Column(db.Boolean, nullable=False, default=False)
    # 是否启用；下架 = 下单页隐藏且不适用新单，适用关系保留
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    # 创建者；内置规格指向超管
    created_by_admin_id = db.Column(
        db.Integer, db.ForeignKey("admins.id"), nullable=True, index=True
    )
    created_at = db.Column(db.String(30), nullable=False, default=_now)
    updated_at = db.Column(
        db.String(30), nullable=False, default=_now, onupdate=_now
    )

    creator = db.relationship("Admin", foreign_keys=[created_by_admin_id], lazy="joined")

    @property
    def price_yuan(self) -> float:
        """单价（元），由整数分换算，用于展示。"""
        return self.price_fen / 100

    @property
    def creator_phone(self) -> str:
        """创建者手机号；无创建者时回退空串。"""
        return self.creator.phone if self.creator is not None else ""

    @property
    def status_label(self) -> str:
        return "启用" if self.is_active else "下架"

    def __repr__(self):
        return f"<Spec #{self.id} {self.name} fen={self.price_fen} builtin={self.is_builtin}>"


class SpecAdmin(db.Model):
    """规格 × 适用管理员（多对多，联合主键）。"""

    __tablename__ = "spec_admins"
    __table_args__ = (db.Index("idx_spec_admins_admin_id", "admin_id"),)

    spec_id = db.Column(
        db.Integer, db.ForeignKey("specs.id"), primary_key=True, nullable=False
    )
    admin_id = db.Column(
        db.Integer, db.ForeignKey("admins.id"), primary_key=True, nullable=False
    )
    created_at = db.Column(db.String(30), nullable=False, default=_now)

    spec = db.relationship("Spec", foreign_keys=[spec_id], lazy="joined")
    admin = db.relationship("Admin", foreign_keys=[admin_id], lazy="joined")

    @property
    def admin_phone(self) -> str:
        return self.admin.phone if self.admin is not None else ""

    def __repr__(self):
        return f"<SpecAdmin spec={self.spec_id} admin={self.admin_id}>"
