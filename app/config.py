# -*- coding: utf-8 -*-
"""应用配置"""
import os
from datetime import timedelta
from pathlib import Path

from sqlalchemy.pool import NullPool

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """从项目根目录 .env 加载环境变量（无外部依赖）。

    - .env 不入库（见 .gitignore），用于本地/私有配置（如超级管理员手机号与登录密码、SECRET_KEY）。
    - 已存在的环境变量优先，不覆盖。
    """
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)
    except OSError:
        pass


_load_dotenv()


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

    # 超级管理员（不在仓库内置真实凭据）
    # 通过本地 .env 或环境变量提供 ADMIN_PHONE（手机号）与 ADMIN_CODE（初始登录密码）。
    # 未配置时首次启动不会自动创建超级管理员，可先配置后重启，或运行 flask reset-admin 创建。
    ADMIN_PHONE = os.environ.get("ADMIN_PHONE", "").strip()
    ADMIN_CODE = os.environ.get("ADMIN_CODE", "")
    ADMIN_NAME = os.environ.get("ADMIN_NAME", "管理员")

    # 登录密码最短长度（自助改密 / 创建管理员 / 重置密码均校验）
    ADMIN_PASSWORD_MIN_LENGTH = 6
