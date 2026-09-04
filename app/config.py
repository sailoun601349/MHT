# -*- coding: utf-8 -*-
"""应用配置"""
import os
from datetime import timedelta
from pathlib import Path

from sqlalchemy.pool import NullPool

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    # 基础
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    SESSION_HOURS = int(os.environ.get("SESSION_HOURS", "8"))
    PERMANENT_SESSION_LIFETIME = timedelta(hours=SESSION_HOURS)

    # 数据库（SQLite 单文件）
    DATA_DIR = BASE_DIR / "data"
    DATABASE_PATH = DATA_DIR / "orders.db"
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + DATABASE_PATH.as_posix()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": NullPool,
        "connect_args": {"timeout": 10, "check_same_thread": False},
    }

    # 上传
    UPLOAD_DIR = BASE_DIR / "uploads"
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10MB
    ALLOWED_UPLOAD_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}

    # 多地址下单，同一次提交可添加的收货地址数量上限
    MAX_ADDRESSES = 20

    # 商品规格（名称 + 单价），下单页下拉与计价自动跟随
    SPECS = [
        {"name": "5斤装", "price": 50},
        {"name": "10斤装", "price": 100},
    ]

    # 管理员（默认值仅便于首次启动，上线必须修改）
    # ADMIN_PHONE 为写死的超级管理员手机号；ADMIN_CODE 为其初始登录密码（仅首启/重置用）
    ADMIN_PHONE = os.environ.get("ADMIN_PHONE", "13185020250")
    ADMIN_CODE = os.environ.get("ADMIN_CODE", "sailoun")
    ADMIN_NAME = os.environ.get("ADMIN_NAME", "管理员")

    # 登录密码最短长度（自助改密 / 创建管理员 / 重置密码均校验）
    ADMIN_PASSWORD_MIN_LENGTH = 6
