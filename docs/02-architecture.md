# 架构设计

## 1. 系统架构图

```
┌─────────────────────────────────────────────────────┐
│                    客户端层                           │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │
│  │  用户手机端   │  │ 管理员手机端  │  │ 管理员PC端 │ │
│  │ (Bootstrap 5)│  │ (Bootstrap 5)│  │(Bootstrap 5│ │
│  └──────┬───────┘  └──────┬───────┘  └─────┬──────┘ │
└─────────┼──────────────────┼────────────────┼────────┘
          │                  │                │
          └──────────────────┴────────────────┘
                             │
                    ┌────────▼────────┐
                    │   Nginx / Caddy │
                    │  (反向代理+静态) │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │   Gunicorn      │
                    │  (WSGI Server)  │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Flask App      │
                    │  (单体应用)      │
                    │                 │
                    │ ┌─────────────┐ │
                    │ │  路由层      │ │
                    │ │  (Blueprint)│ │
                    │ ├─────────────┤ │
                    │ │  业务逻辑层  │ │
                    │ │  (Service)  │ │
                    │ ├─────────────┤ │
                    │ │  数据访问层  │ │
                    │ │  (DAO)      │ │
                    │ └──────┬──────┘ │
                    └────────┼────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼───┐  ┌──────▼─────┐  ┌────▼────────┐
     │  SQLite DB │  │  uploads/  │  │  logs/      │
     │  (订单数据) │  │  (面单照片) │  │  (运行日志)  │
     └────────────┘  └────────────┘  └─────────────┘
```

## 2. 应用内部分层

```
app/
├── __init__.py          # Flask app 工厂函数
├── config.py            # 配置（数据库路径、上传路径、密钥等）
├── extensions.py        # 扩展初始化（db, login_manager 等）
│
├── models/              # 数据模型层
│   ├── __init__.py
│   ├── admin.py         # Admin 模型
│   ├── order.py         # Order 模型
│   └── counter.py       # Counter 模型（全局顺序号）
│
├── routes/              # 路由层（Blueprint）
│   ├── __init__.py
│   ├── main.py          # 首页路由
│   ├── order.py         # 用户下单 & 查询
│   └── admin.py         # 管理员功能
│
├── services/            # 业务逻辑层
│   ├── __init__.py
│   ├── order_service.py # 下单、查询、顺序号生成
│   └── upload_service.py# 图片上传处理
│
├── templates/           # Jinja2 模板
│   ├── base.html        # 基础布局（含 Bootstrap 5 CDN）
│   ├── index.html       # 首页
│   ├── order/
│   │   ├── new.html     # 下单页
│   │   ├── success.html # 下单成功页
│   │   └── query.html   # 订单查询页
│   └── admin/
│       ├── login.html   # 管理员登录
│       ├── orders.html  # 订单列表
│       └── order_detail.html # 订单详情/发货
│
└── static/              # 静态资源
    ├── css/
    │   └── custom.css   # 自定义样式
    └── js/
        └── main.js      # 前端交互（费用计算等）
```

## 3. 请求处理流程

### 3.1 用户下单流程

```
用户输入手机号
      │
      ▼
  首页判断 ──→ 只填手机号 ──→ GET /order/new?phone=xxx
      │
      └──→ 填手机号+查询码 ──→ GET /order/query?phone=xxx&code=001
                                    │
                                    ▼
                              查询数据库
                                    │
                          ┌─────────┴─────────┐
                          │                   │
                     找到订单              未找到
                          │                   │
                     显示订单详情         提示错误
```

### 3.2 下单提交流程

```
POST /order/create
      │
      ▼
  表单校验（手机号格式、必填项）
      │
      ▼
  开启事务 ──→ 获取全局顺序号（原子自增）
      │
      ▼
  计算总费用 = 单价 × 数量
      │
      ▼
  插入订单记录
      │
      ├──→ 成功 ──→ 提交事务 ──→ 跳转成功页（显示查询码）
      │
      └──→ 失败 ──→ 回滚事务 ──→ 提示错误
```

### 3.3 管理员发货流程

```
管理员登录 ──→ 订单列表 ──→ 点击待发货订单
                                    │
                                    ▼
                          填写快递信息 + 上传照片
                                    │
                                    ▼
                          POST /admin/orders/{id}/ship
                                    │
                                    ▼
                          更新订单状态为 shipped
                                    │
                                    ▼
                          返回列表页
```

## 4. 安全设计

### 4.1 认证与授权

| 角色 | 认证方式 | 会话管理 |
|---|---|---|
| 普通用户 | 手机号 + 查询码（无状态） | 每次查询都需输入，不存 session |
| 管理员 | 手机号 + 登录密码 | Flask-Login session，有效期 8 小时 |

### 4.2 输入校验

```python
# 手机号校验
PHONE_REGEX = r'^1[3-9]\d{9}$'

# 查询码校验
QUERY_CODE_REGEX = r'^\d{3,}$'

# 上传文件校验
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
```

### 4.3 频率限制

| 接口 | 限制 |
|---|---|
| 订单查询 | 同一 IP 每分钟最多 10 次 |
| 管理员登录 | 同一 IP 连续失败 5 次，锁定 10 分钟 |
| 下单接口 | 同一 IP 每分钟最多 5 次 |

### 4.4 密码存储

```python
# 使用 bcrypt 哈希
from werkzeug.security import generate_password_hash, check_password_hash

admin.admin_code_hash = generate_password_hash(admin_code)
# 校验时
check_password_hash(admin.admin_code_hash, input_code)
```

## 5. 数据库设计

详见 `03-database-design.md`

## 6. 接口设计

详见 `04-api-design.md`

## 7. 部署架构

详见 `05-deployment.md`
