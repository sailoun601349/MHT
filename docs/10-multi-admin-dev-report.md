# 多管理员体系 + 专属链接下单 — 开发与验收报告

> 依据：`docs/09-multi-admin-spec.md`（决策锁定版）
> 状态：已完成开发 + 迁移 + 端到端回归通过
> 日期：2026-09-01

---

## 一、审计结论（开发前现状）

| 项 | 开发前状态 |
|---|---|
| `admins` 表 | 无 `role/share_code/created_by/is_active/must_change_password`，仅 1 个管理员 |
| `orders` 表 | 无 `owner_admin_id`，现存 8 条订单，`PRAGMA user_version=1` |
| 专属链接 | 无落地路由、无数据隔离、无「登录密码」术语统一 |
| 管理端安全 | 无 CSRF 防护（PRD §1.2 明确要求本次一并处理） |

---

## 二、已实现改动

### 数据模型与迁移
- `app/models/admin.py`：新增 `role`（super/admin）、`share_code`、`created_by`、`is_active`、`must_change_password`；新增 `set_password`、`is_super`、`role_label`、`status_label`、`share_path`。
- `app/models/order.py`：新增 `owner_admin_id`（外键、索引）、`owner` 关系、`owner_phone` 属性。
- `app/services/migration.py`：升级 `SCHEMA_VERSION=2`，`_migrate_v2()` 逐列 `ALTER TABLE` 加列、建部分唯一索引 `uq_admins_share_code`（`WHERE share_code IS NOT NULL`）、回填超管与既有订单归属；迁移前自动备份。

### 服务层
- `app/services/admin_service.py`（新建）：`generate_share_code`（默认手机号后 4 位，碰撞末尾追加递增数字 1234→12341→12342…）、`create_admin`（生成短码 + 初始密码 + 强制首次改密）、`delete_admin`（名下订单转超管后删除，超管禁删）。
- `app/services/order_service.py`：`create_order_group` 落库写入 `owner_admin_id`；新增 `get_super_admin`、`resolve_order_owner`（有效且启用→该管理员，否则→超管）。

### 安全与路由
- `app/utils/csrf.py`（新建）：轻量 CSRF（会话 token + 表单/请求头校验，`before_request` 全局校验非安全方法）。
- `app/utils/validators.py`：新增 `SHARE_CODE_RE`、`is_valid_share_code`。
- `app/__init__.py`：`ShareCodeConverter`（regex `\d{4,6}`）注册 `/＜短码＞`；`context_processor` 注入 `csrf_token`；`before_request` 校验；`_seed` 保证超管写死 super/active；新增 400/403 handler。
- `app/routes/main.py`：`/＜share_code:code＞` 落地路由（有效启用记 `session["ref_admin_id"]`，无效清空并提示）。
- `app/routes/order.py`：下单前 `resolve_order_owner` 解析归属。
- `app/routes/admin.py`：全量重写 — 登录校验 `is_active` + `must_change_password` 跳改密；订单列表按角色隔离 + 责任人筛选；详情/发货/状态加 owner 鉴权（403）；管理员 CRUD + 代改密 + 停用/启用 + 删除 + 自助改密 + 个人设置 + 自定义短码。

### 模板
- `base.html`（CSRF meta + 角色徽章/导航/退出表单）、`admin/login.html`（「登录密码」+ CSRF）、`admin/orders.html`（责任人列/筛选）、`admin/order_detail.html`（责任人行）、`index.html`/`order/new.html`（表单 CSRF）。
- 新建 `admin/admins.html`、`admin/change_password.html`、`admin/settings.html`、`errors/403.html`、`errors/400.html`。
- `app/static/js/main.js`：OCR fetch 加 `X-CSRF-Token` 请求头。

### 文档与部署
- `README.md`、`docs/01~06`、`deploy/kivi-order.service.example` 术语统一为「登录密码/超级管理员初始登录密码」；`docs/03` 同步新字段与索引。

---

## 三、迁移验证结果

在真实库 `data/orders.db` 上执行 v2 迁移（迁移前已备份 `data/orders.db.pre_v2_20260901105518.bak`）：

- ✅ `user_version = 2`
- ✅ `admins` 新增 5 列；超管回填 `role=super, is_active=1, share_code=NULL`
- ✅ `orders` 新增 `owner_admin_id`；8 条既有订单全部回填 `owner_admin_id=1`（超管）
- ✅ 唯一索引 `uq_admins_share_code` 已建

---

## 四、端到端回归结果（`tests/test_multi_admin.py`）

独立临时库运行，**47 项全部通过**，覆盖：

| 验收项 | 结果 |
|---|---|
| CSRF | 无 token 的 POST 被 400 拒绝 |
| R1 超管写死 | `13185020250`/`sailoun` 登录成功，role=super |
| R2 术语统一 | 登录页「登录密码」，无「专属代码/口令」 |
| R3 管理员管理 | 创建/重复拒绝/超管不可删除停用/停用启用/删除转单 |
| R4 专属短码 | 后 4 位、碰撞追加 2025→20251、自定义后旧码失效、超管无短码框 |
| R5 归属 | 经 A/B 短码各归其主、无链接归超管、无效短码提示 |
| R6 数据隔离 | 普通管理员 403 访问他人订单、列表仅见自己 |
| R7 责任人展示 | 列表/详情显示责任人手机号 |
| R8 自助改密 | 当前密码错拒绝、改密后旧密码失效、超管可自助改密 |
| R10 责任人筛选 / R11 强制改密 | 均通过 |

### 修复的缺陷
- `create_admin` 中 `set_password()` 会清除 `must_change_password`，导致普通管理员首登不强制改密 —— 已修复为设密码后重新置回 `True`。

---

## 五、技术债加固（第二批，PRD §1.2 P1 + §13 P0）

完成多管理员主功能后，继续落地 PRD 已列明的并行技术债：

### 金额整数化（P1 #5）
- `Order.spec_price/total_fee` 由 `Float` 改为 `Integer`（单位：分），消除浮点精度隐患。
- 配置 `SPECS.price` 仍为元，服务层 `int(round(price*100))` 边界转换；新增 `spec_price_yuan` / `total_fee_yuan` / `group_total_yuan` 展示属性。
- 迁移 v3：重建 orders 表，`ROUND(值*100)` 元→分；真实库已迁移（8 条订单正确转分）。

### 订单操作留痕（P1 #6）
- 新增 `order_logs` 表（order_id / action / from_status / to_status / remark / operator_admin_id / created_at）。
- `ship_order`、`change_order_status` 写日志；详情页新增「操作记录」区块。

### 下单防重复提交（P1 #7）
- 前端：提交按钮禁用 + 「提交中…」。
- 后端：`submit_nonce` 幂等令牌，同一表单仅成功提交一次。

### 部署加固（P0 #1/#2/#3）
- `deploy/backup.sh`：路径对齐实际部署 `/home/ubuntu/MyProjects/18805-MHT`。
- `deploy/kivi-order.service.example`：用户级 systemd + gunicorn 绑 `127.0.0.1:18805` + 去除弱凭据硬编码。
- `deploy/nginx.conf.example`：80 跳 HTTPS + 443 反代 + 安全头。

## 六、面单照片功能改造（第三批：去 OCR + 多照片）

### 去掉 OCR
- 删除 `/admin/ocr` 路由、详情页 OCR 按钮与提示、`main.js` OCR 逻辑；快递单号改为纯输入框（可输入、可粘贴）。

### 面单照片多张化
- 新增 `order_photos` 表（order_id / path / created_at）+ `Order.photos` 关系（级联删除），删除单字段 `express_photo_path`。
- 照片上限 `Order.max_photos = quantity × 2`（如 5斤装×1 → 最多 2 张）。
- 上传入口：`📷 拍照上传`（`capture="environment"` 调相机）+ `🖼 选择照片`（`multiple` 调相册），选择后即提交。
- 单张删除：详情页照片网格右上角 × 按钮，删除记录同时删磁盘文件，删除后可重新上传。
- 发货校验改为「至少上传 1 张面单照片」（`order.photos` 非空）。
- 用户端查询页遍历展示多张面单照片。

### 迁移 v4
- 历史 `orders.express_photo_path` 迁入 `order_photos`（真实库 2 条已迁），`user_version=4`。
- 回归：`tests/test_photos.py` 10 项全通过。

## 七、验证环境

- 隔离 venv：`C:/Users/yang6/.workbuddy/binaries/python/envs/default`（Flask 3.1.3 / Flask-SQLAlchemy 3.1.1 / Flask-Login 0.6.3）
- 全部 Python 文件 `py_compile` 通过；`flask --app run routes` 路由注册完整
- 真实服务器启动验证：首页/登录页 200，专属链接 `/9999` 302

---

## 八、遗留事项

- **P0（配置已就绪，待服务器实际部署）**：挂 crontab 备份、安装 systemd 单元、申请 HTTPS 证书启用 nginx 反代。
- **P1（剩余）**：git 初始化、生产环境 `flask reset-admin` 更换弱默认凭据。
- **P2（未做）**：列表 N+1 查询、`/uploads/` 鉴权、查询码穷举加固、`client_ip` 盲信 X-Forwarded-For 可被伪造绕过限流、上传 magic bytes 校验、日期筛选与导出。
