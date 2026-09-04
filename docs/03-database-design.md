# 数据库设计

## 1. 概述

- 存储引擎：SQLite（单文件），开启 WAL 模式提升并发读
- ORM：Flask-SQLAlchemy 3.x（建表由模型自动完成，本文件为参照 DDL）
- 时间：统一使用服务器本地时间，格式 ISO 字符串

## 2. 实体关系

```
┌──────────┐      ┌──────────────┐      ┌─────────────┐
│  admins  │      │   counters   │      │   orders    │
├──────────┤      ├──────────────┤      ├─────────────┤
│ id       │      │ name (PK)    │      │ id          │
│ phone    │      │ value        │      │ phone       │
│ name     │      └──────────────┘      │ query_code  │
│ code_hash│                           │ receiver_*  │
│ created  │                           │ address     │
└──────────┘                           │ spec_*      │
                                       │ quantity    │
                                       │ total_fee   │
                                       │ status      │
                                       │ express_*   │
                                       │ photo_path  │
                                       │ note        │
                                       │ created_at  │
                                       │ updated_at  │
                                       └─────────────┘
```

- counters 只用于全局顺序号原子自增，单行记录 `order_seq`
- orders.query_code 为「组码」：同一次提交的多地址订单共享一个查询码；展示格式为 `手机号 + 顺序号`
- 组内唯一：`(phone, query_code, sub_no)` 联合唯一，`sub_no` 为组内地址序号 1..N

## 3. 建表 SQL（参照物）

```sql
PRAGMA journal_mode = WAL;

CREATE TABLE admins (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    phone                TEXT    NOT NULL UNIQUE,
    name                 TEXT    NOT NULL DEFAULT '',
    admin_code_hash      TEXT    NOT NULL,              -- 登录密码哈希
    role                 TEXT    NOT NULL DEFAULT 'admin', -- super / admin
    share_code           TEXT,                          -- 专属短码（默认手机号后4位，唯一可空，超管为空）
    created_by           TEXT,                          -- 创建者手机号
    is_active            INTEGER NOT NULL DEFAULT 1,    -- 是否启用
    must_change_password INTEGER NOT NULL DEFAULT 0,    -- 首次登录是否强制改密
    created_at           TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE UNIQUE INDEX uq_admins_share_code ON admins(share_code) WHERE share_code IS NOT NULL;

CREATE TABLE counters (
    name  TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);

INSERT INTO counters (name, value) VALUES ('order_seq', 0);

CREATE TABLE orders (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_admin_id     INTEGER,                         -- 责任管理员 admins.id（可空，迁移回填超管）
    phone              TEXT    NOT NULL,
    query_code         TEXT    NOT NULL,                 -- 组码：全局顺序号 001/002/.../1000
    sub_no             INTEGER NOT NULL DEFAULT 1,       -- 组内地址序号 1..N
    receiver_name      TEXT    NOT NULL,
    receiver_phone     TEXT    NOT NULL,
    address            TEXT    NOT NULL,                  -- 完整收货地址（省市区+街道门牌）
    spec_name          TEXT    NOT NULL,
    spec_price         REAL    NOT NULL,
    quantity           INTEGER NOT NULL,
    total_fee          REAL    NOT NULL,
    status             TEXT    NOT NULL DEFAULT 'created',
    express_company    TEXT    NOT NULL DEFAULT '',
    express_no         TEXT    NOT NULL DEFAULT '',
    express_photo_path TEXT    NOT NULL DEFAULT '',      -- 相对路径 202405/abc.jpg
    note               TEXT    NOT NULL DEFAULT '',
    created_at         TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at         TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(phone, query_code, sub_no)
);

CREATE INDEX idx_orders_phone      ON orders(phone);
CREATE INDEX idx_orders_phone_code ON orders(phone, query_code);
CREATE INDEX idx_orders_status     ON orders(status);
CREATE INDEX idx_orders_created_at ON orders(created_at);
CREATE INDEX idx_orders_owner      ON orders(owner_admin_id);
```

## 4. 字段说明

### orders.status 状态机

```
created ──发货──▶ shipped ──完成──▶ completed
   │                 │  ▲
   │                 │  └──退回待发货──┐
   │                 │                │
   └──取消──▶ cancelled ◀──取消────────┘
```

> 后端强制校验：`completed` / `cancelled` 为终态；取消、退回须填写原因/备注。

| 值 | 含义 | 用户端可见 |
|---|---|---|
| created | 待发货 | 显示"待发货" |
| shipped | 已发货 | 显示快递公司/单号/面单照片 |
| completed | 已完成 | 正常完结 |
| cancelled | 已取消 | 显示"已取消" |

### 全局顺序号（query_code）

- 来源：counters 表 `order_seq` 原子自增（`BEGIN IMMEDIATE` 事务）
- 展示：`f"{value:03d}"`，001 开始，超过 999 自然为 1000，不截断
- 组码：一次提交只分配一次，组内所有订单共享 query_code；唯一性由 `(phone, query_code, sub_no)` 兜底
- 回退：计数不回退（允许空洞），避免并发下重复序号

## 5. 并发与锁

- SQLite 写锁串行化：个人项目低并发完全够用
- gunicorn 部署建议单 worker（-w 1），多线程模式
- 连接参数 `timeout=10` + 引擎 `NullPool`，避免跨线程连接复用问题
- 关键写路径（下单）通过独立连接 `BEGIN IMMEDIATE` 分配序号，再经 ORM 写入订单

## 6. 备份要点

- 备份文件：data/orders.db + uploads/ 目录（WAL 模式下同时备份 -wal/-shm 或使用 `sqlite3 .backup` 命令）
- 推荐每日 cron 打包，详见 05-deployment.md
