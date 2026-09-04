# -*- coding: utf-8 -*-
"""管理员业务：专属短码生成 / 管理员创建 / 删除（订单转移）/ 归属回填"""
from sqlalchemy import update as sa_update

from ..extensions import db
from ..models.admin import Admin
from ..models.order import Order


def generate_share_code(phone: str, exclude_admin_id=None) -> str:
    """生成专属短码：默认 = 手机号后 4 位，碰撞时在末尾追加递增数字。

    规则（PRD D6）：1234 -> 12341 -> 12342 …，纯数字，全局唯一。
    exclude_admin_id: 自定义短码时排除自身，避免与自身旧码判重。
    """
    if not phone or len(phone) < 4:
        raise ValueError("手机号格式不正确，无法生成短码")

    base = phone[-4:]
    q = Admin.query.filter(Admin.share_code.isnot(None))
    if exclude_admin_id is not None:
        q = q.filter(Admin.id != exclude_admin_id)
    existing = {a.share_code for a in q.all()}

    candidate = base
    suffix = 1
    while candidate in existing:
        candidate = base + str(suffix)
        suffix += 1
    return candidate


def share_code_taken(share_code: str, exclude_admin_id=None) -> bool:
    """短码是否已被其他管理员占用。"""
    q = Admin.query.filter(Admin.share_code == share_code)
    if exclude_admin_id is not None:
        q = q.filter(Admin.id != exclude_admin_id)
    return q.first() is not None


def create_admin(phone: str, name: str, password: str, created_by: str) -> Admin:
    """超级管理员创建普通管理员（生成短码 + 初始密码 + 强制首次改密）。"""
    if Admin.query.filter_by(phone=phone).first() is not None:
        raise ValueError("该手机号已存在，请勿重复创建")

    share_code = generate_share_code(phone)
    admin = Admin(
        phone=phone,
        name=name or "",
        role=Admin.ROLE_ADMIN,
        share_code=share_code,
        created_by=created_by,
        is_active=True,
    )
    # set_password 会清除「强制改密」标记（用于自助/代改密），
    # 这里需在设初始密码后重新置回，保证普通管理员首次登录强制改密。
    admin.set_password(password)
    admin.must_change_password = True
    db.session.add(admin)
    db.session.commit()
    return admin


def delete_admin(admin: Admin) -> None:
    """删除管理员：名下订单转移给超级管理员后删除（超级管理员不可删除）。"""
    if admin.is_super:
        raise ValueError("超级管理员账号不可删除")

    from .order_service import get_super_admin

    super_admin = get_super_admin()
    # 兜底：极端情况下无超管时，订单归属清空
    target_id = super_admin.id if super_admin is not None else None
    db.session.execute(
        sa_update(Order)
        .where(Order.owner_admin_id == admin.id)
        .values(owner_admin_id=target_id)
    )
    db.session.delete(admin)
    db.session.commit()
