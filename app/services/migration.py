# -*- coding: utf-8 -*-
"""SQLite schema 迁移：v0 -> v1（一码多址） -> v2（多管理员） -> v3（金额整数化） -> v4（面单照片多张化） -> v5（去省市区）。

- v0：orders.query_code UNIQUE，无 sub_no
- v1：query_code 不再唯一；新增 sub_no；UNIQUE(phone, query_code, sub_no)
- v2：admins 新增 role/share_code/created_by/is_active/must_change_password；
      orders 新增 owner_admin_id；回填超级管理员与既有订单归属。
- v3：orders.spec_price/total_fee 由 Float（元）改 Integer（分），重建表。
- v4：面单照片由 orders.express_photo_path 单字段改为 order_photos 多张表。
- v5：orders 去掉 province/city/district 三列，地址统一由 address 承载，重建表。

迁移策略：
- SQLite 不支持删除 UNIQUE 约束，因此 v0->v1 重建 orders 表。
- v1->v2 仅 ALTER TABLE 加列（SQLite 支持，无需重建表）。
- v3 金额改类型需重建 orders 表。
- v4 仅把历史 express_photo_path 迁入 order_photos 表（不重建）。
- v5 去掉省市区三列需重建 orders 表。
- 使用 PRAGMA user_version 记录 schema 版本。
- 迁移前自动把 data/orders.db 复制到 data/backups/，备份失败会中止。
- 迁移幂等：新库/旧库/多次启动均安全；若上次迁移中断（残留
  orders_legacy_v0 / orders_legacy_v2 / orders_legacy_v4），先恢复再重试。
"""
import shutil
from datetime import datetime
from pathlib import Path

from flask import current_app

from ..extensions import db

SCHEMA_VERSION = 5


def read_user_version(engine) -> int:
    with engine.connect() as conn:
        row = conn.exec_driver_sql("PRAGMA user_version").fetchone()
        return int(row[0] if row else 0)


def set_user_version(engine, version: int) -> None:
    with engine.connect() as conn:
        conn.exec_driver_sql(f"PRAGMA user_version = {int(version)}")
        conn.commit()


def table_columns(engine, table: str) -> set:
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
        return {row[1] for row in rows}


def table_names(engine) -> set:
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        return {row[0] for row in rows}


def table_has_rows(engine, table: str) -> bool:
    with engine.connect() as conn:
        row = conn.exec_driver_sql(f"SELECT COUNT(*) FROM {table}").fetchone()
        return bool(row and row[0])


def _backup_db() -> Path:
    db_path = Path(current_app.config["DATABASE_PATH"])
    if not db_path.exists():
        return db_path
    backup_dir = Path(current_app.config["DATA_DIR"]) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = backup_dir / f"orders-{stamp}.db"
    shutil.copy2(db_path, backup_path)
    current_app.logger.info("数据库迁移备份: %s", backup_path)
    return backup_path


def _drop_user_indexes(conn, table: str) -> None:
    """删除表上非自动索引，避免重建同名索引时冲突。"""
    rows = conn.exec_driver_sql(f"PRAGMA index_list({table})").fetchall()
    for row in rows:
        name = row[1]
        origin = row[2] if len(row) > 2 else "c"
        # sqlite_autoindex_* 为自动索引，不可删除
        if not str(name).startswith("sqlite_autoindex_"):
            conn.exec_driver_sql(f"DROP INDEX IF EXISTS {name}")


def _recover_interrupted_migration(engine) -> None:
    """若上次迁移中断（orders_legacy_v0 残留），恢复为 v0 再重试。"""
    names = table_names(engine)
    if "orders_legacy_v0" not in names:
        return
    current_app.logger.warning("检测到中断迁移残留，自动恢复 orders 表")
    with engine.begin() as conn:
        if "orders" in names:
            conn.exec_driver_sql("DROP TABLE orders")
        conn.exec_driver_sql("ALTER TABLE orders_legacy_v0 RENAME TO orders")


def _migrate_orders_table(engine) -> None:
    """旧 orders 表重建为新结构（增加 sub_no、去掉 query_code 唯一）。"""
    current_app.logger.info("开始重建 orders 表（v0 -> v1）")
    legacy_table = "orders_legacy_v0"
    with engine.begin() as conn:
        # 先删旧用户索引，避免新建同名索引冲突
        _drop_user_indexes(conn, "orders")
        conn.exec_driver_sql(f"ALTER TABLE orders RENAME TO {legacy_table}")
        # 由当前 SQLAlchemy 模型定义创建新表（含约束/索引）
        from ..models.order import Order

        Order.__table__.create(conn)

        cols = [
            "id", "phone", "query_code", "receiver_name", "receiver_phone",
            "address", "spec_name", "spec_price",
            "quantity", "total_fee", "status", "express_company", "express_no",
            "note", "created_at", "updated_at",
        ]
        col_sql = ", ".join(cols)
        # 旧数据全部视为独立单地址组：sub_no = 1
        conn.exec_driver_sql(
            f"INSERT INTO orders ({col_sql}, sub_no) "
            f"SELECT {col_sql}, 1 FROM {legacy_table}"
        )
        conn.exec_driver_sql(f"DROP TABLE {legacy_table}")
    current_app.logger.info("orders 表迁移完成")


def _migrate_v2(engine) -> bool:
    """v1 -> v2：多管理员加列 + 回填（幂等，逐列检查）。返回是否有实际加列。"""
    admin_cols = table_columns(engine, "admins")
    order_cols = table_columns(engine, "orders")
    changed = False

    with engine.begin() as conn:
        if "role" not in admin_cols:
            conn.exec_driver_sql(
                "ALTER TABLE admins ADD COLUMN role VARCHAR(10) NOT NULL DEFAULT 'admin'"
            )
            changed = True
        if "share_code" not in admin_cols:
            conn.exec_driver_sql("ALTER TABLE admins ADD COLUMN share_code VARCHAR(16)")
            changed = True
        if "created_by" not in admin_cols:
            conn.exec_driver_sql("ALTER TABLE admins ADD COLUMN created_by VARCHAR(20)")
            changed = True
        if "is_active" not in admin_cols:
            conn.exec_driver_sql(
                "ALTER TABLE admins ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"
            )
            changed = True
        if "must_change_password" not in admin_cols:
            conn.exec_driver_sql(
                "ALTER TABLE admins ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT 0"
            )
            changed = True

        # 短码全局唯一（允许超管/未分配为 NULL，多个 NULL 共存）
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_admins_share_code "
            "ON admins(share_code) WHERE share_code IS NOT NULL"
        )

        if "owner_admin_id" not in order_cols:
            conn.exec_driver_sql("ALTER TABLE orders ADD COLUMN owner_admin_id INTEGER")
            changed = True
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_orders_owner_admin_id ON orders(owner_admin_id)"
        )

        # 回填：写死的超级管理员置为 super 且启用
        admin_phone = current_app.config["ADMIN_PHONE"]
        conn.exec_driver_sql(
            "UPDATE admins SET role='super', is_active=1 WHERE phone = ?", (admin_phone,)
        )
        # 回填：既有订单归属超级管理员（无归属 -> 超管）
        super_row = conn.exec_driver_sql(
            "SELECT id FROM admins WHERE phone = ?", (admin_phone,)
        ).fetchone()
        if super_row is not None:
            conn.exec_driver_sql(
                "UPDATE orders SET owner_admin_id = ? WHERE owner_admin_id IS NULL",
                (super_row[0],),
            )
    return changed


def _migrate_v3(engine) -> bool:
    """v2 -> v3：金额 Float（元）-> Integer（分），重建 orders 表。

    说明：SQLite 无法直接改列类型，沿用 v0->v1 的重建表模式。
    spec_price/total_fee 由元转分（*100 后取整）。
    """
    names = table_names(engine)
    legacy = "orders_legacy_v2"

    # 自愈：上次 v3 迁移中断残留 legacy 表，先恢复再重试
    if legacy in names:
        current_app.logger.warning("检测到 v3 迁移中断残留，恢复 orders 表")
        with engine.begin() as conn:
            if "orders" in names:
                conn.exec_driver_sql("DROP TABLE orders")
            conn.exec_driver_sql(f"ALTER TABLE {legacy} RENAME TO orders")

    order_cols = table_columns(engine, "orders")
    if "total_fee" not in order_cols:
        return False

    current_app.logger.info("开始重建 orders 表（v2 -> v3，金额整数化）")
    with engine.begin() as conn:
        _drop_user_indexes(conn, "orders")
        conn.exec_driver_sql(f"ALTER TABLE orders RENAME TO {legacy}")
        from ..models.order import Order

        Order.__table__.create(conn)

        cols = [
            "id", "owner_admin_id", "phone", "query_code", "sub_no",
            "receiver_name", "receiver_phone",
            "address", "spec_name", "quantity", "status", "express_company",
            "express_no", "note", "created_at", "updated_at",
        ]
        col_sql = ", ".join(cols)
        # 金额两列由元转分：ROUND(值*100) 后取整，避免浮点误差
        conn.exec_driver_sql(
            f"INSERT INTO orders ({col_sql}, spec_price, total_fee) "
            f"SELECT {col_sql}, "
            f"CAST(ROUND(spec_price*100) AS INTEGER), "
            f"CAST(ROUND(total_fee*100) AS INTEGER) "
            f"FROM {legacy}"
        )
        conn.exec_driver_sql(f"DROP TABLE {legacy}")
    current_app.logger.info("orders 表金额整数化完成")
    return True


def _migrate_v4(engine) -> bool:
    """v3 -> v4：历史面单照片（orders.express_photo_path）迁入 order_photos 表。

    模型已删除 express_photo_path，但旧库的 orders 表仍残留该列与数据；
    新库无此列，直接跳过。
    """
    order_cols = table_columns(engine, "orders")
    if "express_photo_path" not in order_cols:
        return False
    if "order_photos" not in table_names(engine):
        return False

    with engine.begin() as conn:
        rows = conn.exec_driver_sql(
            "SELECT id, express_photo_path FROM orders "
            "WHERE express_photo_path IS NOT NULL AND express_photo_path != ''"
        ).fetchall()
        if not rows:
            return False
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for oid, path in rows:
            conn.exec_driver_sql(
                "INSERT INTO order_photos (order_id, path, created_at) VALUES (?, ?, ?)",
                (oid, path, now),
            )
        # 清空旧字段，避免重复迁移
        conn.exec_driver_sql("UPDATE orders SET express_photo_path = ''")
    current_app.logger.info("已迁移 %d 条历史面单照片到 order_photos", len(rows))
    return True


def _migrate_v5(engine) -> bool:
    """v4 -> v5：orders 去掉 province/city/district 三列，地址统一由 address 承载。

    历史省市区数据合并进 address（空格拼接，空段忽略），避免信息丢失。
    """
    names = table_names(engine)
    legacy = "orders_legacy_v4"

    # 自愈：上次 v5 迁移中断残留 legacy 表，先恢复再重试
    if legacy in names:
        current_app.logger.warning("检测到 v5 迁移中断残留，恢复 orders 表")
        with engine.begin() as conn:
            if "orders" in names:
                conn.exec_driver_sql("DROP TABLE orders")
            conn.exec_driver_sql(f"ALTER TABLE {legacy} RENAME TO orders")

    order_cols = table_columns(engine, "orders")
    # 已无省市区三列 -> 无需迁移
    if not {"province", "city", "district"} & order_cols:
        return False

    current_app.logger.info("开始重建 orders 表（v4 -> v5，去掉省市区）")
    with engine.begin() as conn:
        _drop_user_indexes(conn, "orders")
        conn.exec_driver_sql(f"ALTER TABLE orders RENAME TO {legacy}")
        from ..models.order import Order

        Order.__table__.create(conn)

        cols = [
            "id", "owner_admin_id", "phone", "query_code", "sub_no",
            "receiver_name", "receiver_phone", "spec_name", "spec_price",
            "quantity", "total_fee", "status", "express_company",
            "express_no", "note", "created_at", "updated_at",
        ]
        col_sql = ", ".join(cols)
        # 省市区合并进 address：若 address 已以「省」开头（历史完整地址），
        # 直接保留 address，避免重复；否则把 省/市/区 前缀拼接到 address 前。
        merged_address = (
            "CASE WHEN province != '' AND address LIKE province || '%' THEN address "
            "ELSE TRIM(COALESCE(NULLIF(province,''),'') || ' ' || "
            "COALESCE(NULLIF(city,''),'') || ' ' || "
            "COALESCE(NULLIF(district,''),'') || ' ' || address) END"
        )
        conn.exec_driver_sql(
            f"INSERT INTO orders ({col_sql}, address) "
            f"SELECT {col_sql}, {merged_address} FROM {legacy}"
        )
        conn.exec_driver_sql(f"DROP TABLE {legacy}")
    current_app.logger.info("orders 表去省市区完成")
    return True


def run_schema_migrations(app) -> None:
    """幂等执行 schema 迁移，在 db.create_all() 之后调用。"""
    with app.app_context():
        engine = db.engine
        _recover_interrupted_migration(engine)
        version = read_user_version(engine)
        cols = table_columns(engine, "orders")

        # ---- v0 -> v1 ----
        if version < 1:
            if "sub_no" not in cols:
                # 旧版数据库：备份后重建
                db_path = Path(current_app.config["DATABASE_PATH"])
                if db_path.exists():
                    _backup_db()
                _migrate_orders_table(engine)
            # 新库已由 db.create_all() 建成新结构，仅补版本号
            set_user_version(engine, 1)
            version = 1
            current_app.logger.info("schema 已迁移至 user_version=1")
        elif "sub_no" not in cols:
            # 版本号高于结构时视为异常，保守重建避免崩溃
            db_path = Path(current_app.config["DATABASE_PATH"])
            if db_path.exists():
                _backup_db()
            _migrate_orders_table(engine)
            current_app.logger.warning("user_version=%s 但缺 sub_no，已重建 orders", version)

        # ---- v1 -> v2 ----
        if version < 2:
            # 有真实数据的库才备份（全新库无需备份空壳）
            if table_has_rows(engine, "admins"):
                _backup_db()
            _migrate_v2(engine)
            set_user_version(engine, 2)
            version = 2
            current_app.logger.info("schema 已迁移至 user_version=2")
        else:
            # 版本已到位但列缺失时补齐（自愈部分中断）
            _migrate_v2(engine)

        # ---- v2 -> v3 ----
        if version < 3:
            if table_has_rows(engine, "orders"):
                _backup_db()
            _migrate_v3(engine)
            set_user_version(engine, 3)
            version = 3
            current_app.logger.info("schema 已迁移至 user_version=3")

        # ---- v3 -> v4 ----
        if version < 4:
            _migrate_v4(engine)
            set_user_version(engine, 4)
            version = 4
            current_app.logger.info("schema 已迁移至 user_version=4")

        # ---- v4 -> v5 ----
        if version < 5:
            if table_has_rows(engine, "orders"):
                _backup_db()
            _migrate_v5(engine)
            set_user_version(engine, SCHEMA_VERSION)
            current_app.logger.info("schema 已迁移至 user_version=%s", SCHEMA_VERSION)