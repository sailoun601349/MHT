# -*- coding: utf-8 -*-
"""Flask 应用工厂"""
import os

import click
from flask import Flask, render_template, send_from_directory
from sqlalchemy import event
from sqlalchemy.engine import Engine
from werkzeug.routing import BaseConverter

from .config import Config
from .extensions import db, login_manager
from .utils.csrf import generate_csrf_token, validate_csrf


class ShareCodeConverter(BaseConverter):
    """专属短码路径转换器：4-6 位纯数字，与 /admin /order /enter 等字母路径不冲突。"""

    regex = r"\d{4,6}"


def _set_sqlite_pragma(dbapi_conn, _record):
    """SQLite 开启 WAL，提升并发读性能。"""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def _seed(app):
    """首次启动：初始化全局顺序号计数器与写死的超级管理员。"""
    from werkzeug.security import generate_password_hash

    from .models import Admin, Counter

    if db.session.get(Counter, "order_seq") is None:
        db.session.add(Counter(name="order_seq", value=0))

    admin_phone = app.config["ADMIN_PHONE"]
    admin = Admin.query.filter_by(phone=admin_phone).first()
    if admin is None:
        admin = Admin(
            phone=admin_phone,
            name=app.config["ADMIN_NAME"],
            admin_code_hash=generate_password_hash(app.config["ADMIN_CODE"]),
            role=Admin.ROLE_SUPER,
            is_active=True,
        )
        db.session.add(admin)
    else:
        # 写死的超级管理员始终为 super 且启用，且不占用专属短码
        admin.role = Admin.ROLE_SUPER
        admin.is_active = True
        admin.share_code = None
    db.session.commit()


def register_cli(app):
    @app.cli.command("reset-admin")
    @click.option("--phone", required=True)
    @click.option("--code", required=True)
    @click.option("--name", default="管理员")
    def reset_admin(phone, code, name):
        """重置管理员手机号与登录密码（新手机号自动创建）。"""
        from .models import Admin
        from .services.admin_service import generate_share_code
        from .utils import is_valid_phone

        if not is_valid_phone(phone):
            click.echo("手机号格式不正确（需 1 开头的 11 位数字）")
            return
        admin = Admin.query.filter_by(phone=phone).first()
        if admin is None:
            admin = Admin(phone=phone, name=name)
            db.session.add(admin)
        admin.name = name
        admin.set_password(code)
        if phone == app.config["ADMIN_PHONE"]:
            admin.role = Admin.ROLE_SUPER
            admin.is_active = True
            admin.share_code = None
        else:
            if admin.role != Admin.ROLE_SUPER:
                admin.role = Admin.ROLE_ADMIN
            if not admin.share_code:
                admin.share_code = generate_share_code(phone)
        db.session.commit()
        click.echo(f"管理员已设置: {phone}")


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # 专属短码转换器（须在注册蓝图前就位）
    app.url_map.converters["share_code"] = ShareCodeConverter

    # 确保数据目录存在
    app.config["DATA_DIR"].mkdir(parents=True, exist_ok=True)
    app.config["UPLOAD_DIR"].mkdir(parents=True, exist_ok=True)

    event.listen(Engine, "connect", _set_sqlite_pragma)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "admin.login"
    login_manager.login_message = "请先登录管理员账号"
    login_manager.login_message_category = "warning"

    from .models import Admin

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Admin, int(user_id))

    # CSRF：模板注入 token + 非安全方法全局校验
    @app.context_processor
    def inject_globals():
        return {"csrf_token": generate_csrf_token}

    @app.before_request
    def _csrf_check():
        validate_csrf()

    # 蓝图
    from .routes.admin import admin_bp
    from .routes.main import main_bp
    from .routes.order import order_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(order_bp)
    app.register_blueprint(admin_bp)

    # 面单照片访问
    @app.route("/uploads/<path:filename>")
    def uploaded_file(filename):
        return send_from_directory(app.config["UPLOAD_DIR"], filename)

    # 初始化数据库
    with app.app_context():
        db.create_all()
        from .services.migration import run_schema_migrations

        run_schema_migrations(app)
        _seed(app)
        if not os.environ.get("ADMIN_CODE"):
            app.logger.warning("未通过环境变量 ADMIN_CODE 提供超级管理员初始登录密码，当前使用配置文件内置默认值，生产环境建议用 flask reset-admin 修改！")

    # 错误页
    @app.errorhandler(404)
    def not_found(_e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(400)
    def bad_request(e):
        return render_template("errors/400.html", message=getattr(e, "description", "请求无效")), 400

    @app.errorhandler(500)
    def server_error(_e):
        db.session.rollback()
        app.logger.exception("服务器内部错误")
        return render_template("errors/500.html"), 500

    @app.errorhandler(413)
    def file_too_large(_e):
        return render_template("errors/413.html"), 413

    register_cli(app)
    return app
