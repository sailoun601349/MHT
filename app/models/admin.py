# -*- coding: utf-8 -*-
from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Admin(db.Model, UserMixin):
    __tablename__ = "admins"

    ROLE_SUPER = "super"
    ROLE_ADMIN = "admin"

    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(50), nullable=False, default="")
    # 登录密码哈希（对外语义统一为「登录密码」，字段名保留避免重建表）
    admin_code_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(10), nullable=False, default=ROLE_ADMIN)
    # 专属短码（默认手机号后 4 位，纯数字，全局唯一；超级管理员为空）
    share_code = db.Column(db.String(16), unique=True, nullable=True)
    created_by = db.Column(db.String(20), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    # 首次登录是否强制修改初始密码（超管创建普通管理员时为 True）
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.String(30), nullable=False, default=_now)

    def check_code(self, code: str) -> bool:
        """校验登录密码（哈希比对，不存明文）。"""
        return check_password_hash(self.admin_code_hash, code or "")

    def set_password(self, raw_password: str) -> None:
        """设置登录密码（仅存哈希），并清除「强制改密」标记。"""
        self.admin_code_hash = generate_password_hash(raw_password)
        self.must_change_password = False

    @property
    def is_super(self) -> bool:
        return self.role == self.ROLE_SUPER

    @property
    def role_label(self) -> str:
        return "超级管理员" if self.is_super else "普通管理员"

    @property
    def status_label(self) -> str:
        return "启用" if self.is_active else "停用"

    @property
    def share_path(self):
        """专属链接路径；超级管理员无短码，返回 None。"""
        if self.is_super or not self.share_code:
            return None
        return f"/{self.share_code}"

    def __repr__(self):
        return f"<Admin {self.phone} role={self.role}>"
