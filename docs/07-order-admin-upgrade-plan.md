# 订单管理升级改造计划（状态流转 / 多地址下单 / 一码多址查询）

> 目标：在现有猕猴桃订单系统（Flask + SQLite + Bootstrap 5）上完成三件事：
> 1. 优化管理员订单管理规则与流程，尤其是**状态流转**；
> 2. 用户下单支持**多个收货地址**，每个地址一个表单，**最后统一测算价格**；
> 3. 同一用户一次提交多个地址时返回**一个查询码**，后台按**多条订单**展示，用户用查询码查询时可**左右/上下切换**查看自己的多个地址订单。

> 状态：✅ 已按本计划实施（2026-08-17）；决策点按文档推荐执行，包含 shipped→created 退回待发货。

---

## 1. 现状诊断（重要，改动前必须理解）

### 1.1 当前数据模型

- `orders.query_code` 当前为 **UNIQUE**（`app/models/order.py:35` + SQLite 表约束）。
- 因此**一个查询码只能对应一行订单**，这是「一码多址」的根本障碍，必须改造。
- `counters.order_seq` 全局自增，下单时分配一次（`app/services/order_service.py:11-37`）。
- 展示格式：`手机号 + 顺序号`（如 `13100000001 + 001`）。

### 1.2 当前状态流转的问题

`docs/03-database-design.md` 画的状态机是：

```
created ──发货──▶ shipped ──完成──▶ completed
   │                 │
   └──取消──▶ cancelled   └──取消──▶ cancelled
```

但代码**没有落实这个状态机**：

| 位置 | 问题 |
|---|---|
| `app/routes/admin.py:111-143` `ship()` | 不校验当前状态：`cancelled`、`completed` 订单也能被直接写入发货信息并置为 `shipped`（模板隐藏了按钮，但后端不设防，伪造 POST 即可） |
| `app/routes/admin.py:146-157` `change_status()` | 只校验目标值 ∈ {completed, cancelled}，**不校验来源状态**：`created` 可跳步直接 `completed`；`completed` 可再被 `cancelled`；`cancelled` 可再被 `completed` |
| `app/models/order.py` | 没有状态转移矩阵，状态规则散落在模板 `if` 里，前后端不一致 |
| `order.note` | 有字段（`app/models/order.py:50`）但全项目无任何录入入口；取消无原因、改单无备注 |
| 列表 | `app/routes/admin.py:89` 全量 `.all()` 加载，无分页 |

### 1.3 当前下单/查询流程的问题

- 下单页（`app/templates/order/new.html`）只有**一套地址 + 一套规格数量**，不支持多地址。
- 查询页（`app/templates/order/query.html`）只渲染**单个 `order` 对象**。
- 成功页（`app/templates/order/success.html`）只展示单条订单。

---

## 2. 总体设计决策（先读这里）

### 2.1 查询码语义升级：从「单订单号」变为「组码（批次码）」

- **保留** `查询码 = 手机号 + 全局顺序号` 的形式，用户感知不变。
- 新语义：**一个查询码代表一次提交的一组订单**。
  - 单地址提交：组内 1 条订单（行为与旧版完全一致）。
  - 多地址提交：组内 N 条订单，每条对应一个收货地址。
- `orders` 表新增 `sub_no`（组内序号 1..N），唯一约束改为 `UNIQUE(phone, query_code, sub_no)`。
- `orders.query_code` **不再单独唯一**，改为普通索引（与 phone 组合查询）。

### 2.2 后台展示：每地址一条订单

- 后台订单列表直接列出每一个子订单（每地址一行），并在行内显示组内序号徽章（`#1`、`#2`…）和「多址」标记。
- 后台详情页可查看当前子订单，并提供**同组其它子订单**的快速切换。
- 每个子订单独立发货、独立流转状态（个人项目，不做「整组一键发货」，可在后续扩展）。

### 2.3 多地址价格模式：每个地址一个完整表单，最后统一计价

- 下单页**每个地址一张卡片**，卡片内包含：收货人、收货电话、省/市/区、详细地址、**规格、数量**（与旧版单地址表单字段一致）。
- 前端实时显示每地址小计，**底部统一测算总价 = Σ(各地址小计)**。
- 一次提交：分配一次全局顺序号（一个查询码），生成 N 行订单，金额分别为各地址小计；成功页与查询页展示组总价。

### 2.4 状态机重新定义并落到后端强制校验

- 后端以 `Order.STATUS_TRANSITIONS` 矩阵为唯一裁判，模板按钮只是 UI 表现。
- 取消必须填写原因；发货必须校验状态；完成/取消为终态（默认不可逆）。

---

## 3. 任务一：管理员订单管理与状态流转优化

### 3.1 目标状态机

```
              ┌─────────────────────────────────────┐
              │                                     │
  created ────ship────▶ shipped ────complete────▶ completed
     │                    │  ▲
     │                    │  └──(可选)退回待发货──┐
     │                    │                      │
     └────cancel────────▶ cancelled ◀──cancel────┘
```

### 3.2 状态转移矩阵（服务端强制）

| 当前状态 | 允许操作 | 目标状态 | 前置条件 |
|---|---|---|---|
| `created` 待发货 | 发货 `ship` | `shipped` | 快递公司、快递单号、面单照片必填 |
| `created` | 取消 `cancel` | `cancelled` | 取消原因必填 |
| `shipped` 已发货 | 更新快递 `update_express` | `shipped`（保持） | 快递公司、快递单号必填；照片可留旧 |
| `shipped` | 标记完成 `complete` | `completed` | — |
| `shipped` | 取消 `cancel` | `cancelled` | 取消原因必填（建议二次确认） |
| `shipped` | 退回待发货 `cancel_ship`（**可选**） | `created` | 原因必填；保留原快递信息供追溯 |
| `completed` 已完成 | —（终态，只读） | — | — |
| `cancelled` 已取消 | —（终态，只读） | — | — |

> `completed` / `cancelled` 设计为**不可逆终态**（保持轻量、避免纠纷）。若后续需要「重开」，全部通过 `flask reset-order-status` CLI 类命令处理，不在页面上开放。

### 3.3 代码落点

#### 3.3.1 `app/models/order.py`

```python
class Order(db.Model):
    __table_args__ = (
        db.UniqueConstraint("phone", "query_code", "sub_no",
                            name="uq_orders_phone_code_subno"),
    )

    # 新增列
    sub_no = db.Column(db.Integer, nullable=False, default=1)  # 组内序号 1..N

    # 状态转移矩阵（唯一状态裁判）
    STATUS_TRANSITIONS = {
        STATUS_CREATED:   {STATUS_SHIPPED, STATUS_CANCELLED},
        STATUS_SHIPPED:   {STATUS_SHIPPED, STATUS_COMPLETED, STATUS_CANCELLED},  # shipped→shipped=更新快递
        STATUS_COMPLETED: set(),
        STATUS_CANCELLED: set(),
    }

    def can_transition_to(self, new_status) -> bool: ...
    def can_update_express(self) -> bool:
        return self.status in (self.STATUS_CREATED, self.STATUS_SHIPPED)
    @property
    def available_actions(self) -> set: ...
    @property
    def group_orders(self) -> list:  # 同组所有子订单
        ...
```

可选项：若需要「退回待发货」，在矩阵中给 `STATUS_SHIPPED` 增加 `STATUS_CREATED`。

#### 3.3.2 `app/services/order_service.py`

新增两个业务函数（路由层不再散落状态判断）：

```python
def ship_order(order, express_company, express_no, photo_path) -> Order:
    """仅 created/shipped 可发货/更新快递；created→shipped，shipped→保持 shipped。"""
    if not order.can_update_express():
        raise ValueError("当前状态不可发货或更新快递")
    # 写 express_*、photo_path（photo_path 为 None 时保留旧图，但 created 必须已有/新传）
    order.status = Order.STATUS_SHIPPED
    db.session.commit()
    return order

def change_order_status(order, new_status, remark="") -> Order:
    """按 STATUS_TRANSITIONS 校验后流转；取消/退回强制备注。"""
    if new_status not in order.STATUS_TRANSITIONS.get(order.status, set()):
        raise ValueError("不允许从「{}」变更为「{}」".format(order.status_label, new_status))
    if new_status == Order.STATUS_CANCELLED and not (remark or "").strip():
        raise ValueError("取消订单必须填写原因")
    if remark.strip():
        order.note = remark.strip()          # 复用 note 存原因/备注
    order.status = new_status
    db.session.commit()
    return order
```

`create_order` 保留（单地址兼容），另加 `create_order_group`（见第 4 节）。

#### 3.3.3 `app/routes/admin.py`

- `ship()`：解析参数 → 调 `ship_order()`；`except ValueError` → flash 错误。
- `change_status()`：接收 `status` + `remark` → 调 `change_order_status()`；`except ValueError` → flash 错误。
- 页面渲染时把 `order.available_actions` 传给模板。

#### 3.3.4 `app/templates/admin/order_detail.html`

- 按钮渲染改为由 `order.available_actions` 驱动（Jinja 仍可用 `{% if 'shipped' in order.available_actions %}` 等）。
- 取消操作前弹 JS `confirm`，且展开一个 `remark` 必填输入框。
- `created` / `shipped` 显示发货表单；`shipped` 文案改为「更新快递信息」。
- 终态显示「该订单已完结/已取消，不可变更」提示。

### 3.4 管理端流程配套优化

| 优化项 | 说明 | 优先级 |
|---|---|---|
| 状态操作后 flash 明确结果 | 如「订单已取消（原因已记录）」 | 必须 |
| 取消原因必填并展示 | 复用 `note`；详情页显示 | 必须 |
| 列表分页 | `Query.paginate(page=page, per_page=20)`，简单分页条 | 建议（订单量增大后必需） |
| 操作日志 `order_logs` 表 | 记录 action/from/to/operator/remark/时间 | 可选，审计留痕 |
| 退回待发货（shipped→created） | 发错快递后撤回重发 | 可选，推荐 |
| 批量操作（批量发货/导出） | 个人项目暂不做 | 不做 |

---

## 4. 任务二：多地址下单（每地址一个表单，统一计价）

### 4.1 交互流程

```
首页输入手机号 → 进入 /order/new?phone=xxx
  ┌────────────────────────────────────────────┐
  │  下单手机号：138...（disabled）             │
  │                                            │
  │  ┌─ 地址 1 表单 ────────────────────────┐  │
  │  │ 收货人 / 电话 / 省市区 / 地址        │  │
  │  │ 规格下拉 / 数量 / 小计(自动)         │  │
  │  └──────────────────────────────────────┘  │
  │  [+ 添加地址]（每地址卡片自带规格数量）   │
  │                                            │
  │  ───────────────────────────────────────   │
  │  总费用（统一测算）：¥xxx.xx = Σ小计       │
  │  [提交订单]                                │
  └────────────────────────────────────────────┘
        │ POST /order/create（一次提交）
        ▼
  生成 1 个查询码 + N 条订单（sub_no 1..N）
        ▼
  /order/success?phone=..&code=..  展示查询码 + 总价 + 地址清单
```

### 4.2 前端字段命名（重要约定）

采用**序号后缀**命名，避免 `getlist` 顺序错位问题：

- `address_count`：提交时卡片数（1..20，上限 20）
- 第 `i` 张卡片字段：`receiver_name_{i}`、`receiver_phone_{i}`、`province_{i}`、`city_{i}`、`district_{i}`、`address_{i}`、`spec_name_{i}`、`quantity_{i}`
- JS 在增删卡片后必须 `reindex()` 重新编号（0 起连续）；后端按 `address_count` 循环读取。
- 初始渲染 1 张卡片（`i=0`）。

### 4.3 前端交互（`app/templates/order/new.html` + `app/static/js/main.js`）

1. 卡片模板：用 `<template>` 隐藏节点，克隆后 `replace` 其中 `__I__` 为真实序号。
2. 每个卡片内置规格下拉（带 `data-price`）和数量输入。
3. `addAddress()`：克隆模板插入 `#address-list`，自动刷新底部总价。
4. `removeAddress(i)`：至少保留 1 张；删除后 `reindex()` + 刷新总价。
5. `updateTotals()`：遍历卡片，计算 `卡片小计 = price_i × qty_i`，底部 `总价 = Σ小计`，`address_count` 同步。
6. 提交前校验：至少 1 张卡片、每张卡片必填与长度符合约束（浏览器 required + JS 兜底）。

### 4.4 后端改动（`app/routes/order.py` + `app/services/order_service.py`）

`POST /order/create` 流程：

```
1) 限流（同 IP 5 次/分钟，整组按 1 次计）
2) 解析 phone、address_count
3) 校验 phone 合法；1 <= address_count <= 20
4) 循环 i in 0..address_count-1：
     - 读取 receiver_name_i / receiver_phone_i / province_i / city_i /
       district_i / address_i / spec_name_i / quantity_i
     - 逐项校验（规则同现状单地址：姓名<=100、电话正则、地址<=300、
       省市区<=50 可空、规格在 SPECS、数量 1..99）
     - spec = find_spec(spec_name_i)，小计 = round(price × quantity, 2)
5) 组总价 = round(sum(小计), 2)
6) 若全部合法 → create_order_group()
7) 302 到 success 页
```

`create_order_group(phone, addr_forms)`：

```python
def create_order_group(phone, addr_forms):
    query_code = get_next_order_seq()      # 只分配一次
    orders = [
        Order(phone=phone, query_code=query_code, sub_no=i+1, ...,
              spec_name=..., spec_price=..., quantity=..., total_fee=小计)
        for i, f in enumerate(addr_forms)
    ]
    db.session.add_all(orders)
    db.session.commit()                    # 失败 rollback，允许序号空洞
    return query_code, orders, group_total
```

> 说明：`get_next_order_seq` 使用独立连接分配序号，与 ORM 事务可继续并存；若 ORM 写入失败，序号空洞可接受（现行设计已允许）。

### 4.5 成功页（`/order/success`）

- 路由改为 `GET /order/success?phone=..&code=..`（展示整组）。
- 保留 `GET /order/success/<int:order_id>` 作兼容：查到该订单后 302 到新地址。
- 页面展示：
  - 醒目的**一个查询码**（复制按钮复用现有 JS）。
  - 组总价（大写数字 + 元）、地址数量。
  - 地址清单小表：每地址一行（#序号、收货人、地址、规格×数量、小计）。
  - 按钮：查看订单（去 /order/query）、再下一单、返回首页。

---

## 5. 任务三：一码多址——后台多条展示 + 用户端切换查询

### 5.1 数据模型改造

`orders` 表变化：

| 项 | 旧 | 新 |
|---|---|---|
| `query_code` | `VARCHAR(20) NOT NULL UNIQUE` | `VARCHAR(20) NOT NULL`（去掉 UNIQUE） |
| 新增 `sub_no` | — | `INTEGER NOT NULL DEFAULT 1`（组内序号） |
| 表约束 | `UNIQUE(query_code)` | `UNIQUE(phone, query_code, sub_no)` |
| 索引 | `idx_orders_phone` | 保留；另加 `idx_orders_phone_code (phone, query_code)` |

`app/models/order.py` 相应更新（见 3.3.1）。

### 5.2 SQLite 迁移方案（必须幂等、带备份）

SQLite 不支持 `DROP UNIQUE`，采用**重建表**：

1. 用 `PRAGMA user_version` 作为 schema 版本号（当前默认 0，目标 `1`）。
2. 新增 `app/services/migration.py`，`run_schema_migrations(app)`：
   - 读 `PRAGMA user_version`；
   - 若 `>= 1` 且 `PRAGMA table_info(orders)` 含 `sub_no` → 跳过；
   - 迁移前备份：复制 `data/orders.db` 到 `data/backups/orders-YYYYmmddHHMMSS.db`（备份失败则中止迁移，**不要裸迁**）；
   - `ALTER TABLE orders RENAME TO orders_legacy_v0`；
   - 用 `Order.__table__.create(db.engine)` 建新表（含新索引/约束）；
   - `INSERT INTO orders (..., sub_no) SELECT ..., 1 FROM orders_legacy_v0;`（旧数据全部按单地址组处理）；
   - `DROP TABLE orders_legacy_v0`；
   - `PRAGMA user_version = 1`。
3. 在 `app/__init__.py` 的 `create_app` 中：`db.create_all()` 之后调用 `run_schema_migrations(app)`，保证旧库/新库/首次启动三条路径都正确。
4. 首次启动新库：`db.create_all()` 直接建新表 → 设置 `PRAGMA user_version = 1`。

> 迁移涉及 `WAL` 模式，备份时如条件允许直接用 `flask` CLI 在停机窗口执行最佳；脚本内仍做文件复制备份兜底。

### 5.3 用户查询页：一码查多单 + 左右/上下切换

`GET /order/query?phone=&code=`：

- 查询变为 `Order.query.filter_by(phone=phone, query_code=code).order_by(Order.sub_no.asc()).all()`。
- 0 条 → 现有错误提示；N 条 → 渲染组对象。

`app/templates/order/query.html`：

- 顶部组信息卡：查询码 + 「共 N 个地址 · 组总价 ¥xxx」。
- **移动端（<768px）：Bootstrap 5 Carousel 左右滑动**：
  - 每个 `.carousel-item` 放一个地址订单详情卡；
  - 支持手指滑动 + 左右箭头 + 底部指示点；
  - 标题显示「第 x/N 个地址」。
- **桌面端（>=768px）：同组订单上下排列 + 顶部左右切换按钮（上一个/下一个滚动/高亮）**，可保留同一套「上一单/下一单」按钮逻辑，保证两种终端都能用。
- 每个子订单详情屏/卡内容：地址序号、收货人/电话、完整地址、规格×数量、小计、状态徽章、物流信息（已发货则显示公司/单号/面单照片，未发货显示待发货）、下单时间。
- N=1 时隐藏切换控件（外观与旧版一致）。

### 5.4 后台：按多条订单展示 + 组内导航

`GET /admin/orders`：

- 列表仍按「每子订单一行」展示（这是用户要求的多条展示）。
- 每行增加：组内序号徽章（`#1`/`#2`）；`sub_no > 1` 或同码多行时加「多址」小徽章。
- 搜索 `phone`/`query_code`/`receiver_name` 逻辑保留（按 phone 或 code 搜索自然返回整组所有子订单）。
- 增加简单分页（`page` 参数，每页 20），迁移自现 `.all()`。

`GET /admin/orders/<id>`：

- 显示当前子订单完整信息（含 `第 sub_no/N 个地址`）。
- 组内导航条：同组其它子订单链接（`sub_no` 排序），方便管理员在地址间切换。
- 每个子订单独立发货/取消/完成（状态按钮按 3.3.4 的矩阵渲染）。

---

## 6. 接口变更汇总

| 方法 | 路径 | 变化 |
|---|---|---|
| GET | `/order/new?phone=` | 页面改为多地址卡片表单（不改 URL） |
| POST | `/order/create` | 接收多地址字段（`address_count` + 序号后缀），统一计价 |
| GET | `/order/success?phone=&code=` | 新：展示整组订单结果 |
| GET | `/order/success/<int:id>` | 兼容：302 到新地址 |
| GET | `/order/query?phone=&code=` | 返回一组订单，前端支持切换 |
| GET | `/admin/orders` | 列表分页 + 组内序号徽章 |
| GET | `/admin/orders/<id>` | 组内导航 |
| POST | `/admin/orders/<id>/ship` | 服务端状态校验（仅 created/shipped） |
| POST | `/admin/orders/<id>/status` | 严格状态机校验 + 取消原因必填 |
| POST | `/admin/ocr` | 不变 |

---

## 7. 文件改动清单（交接开发用）

| 文件 | 改动内容 | 量级 |
|---|---|---|
| `app/models/order.py` | 增加 `sub_no`、`__table_args__` 组合唯一、状态矩阵与 `can_*`/`available_actions`/组助手 | M |
| `app/services/migration.py`（新） | schema 迁移 v0→v1，重建 orders，幂等，备份 | M |
| `app/services/order_service.py` | `create_order_group`、`ship_order`、`change_order_status`、`get_orders_by_phone_code` | M |
| `app/routes/order.py` | `create` 多地址解析校验、`success` 组展示、`query` 组查询 | M |
| `app/routes/admin.py` | 分页、状态机经服务层、列表/详情传组数据 | M |
| `app/templates/order/new.html` | 地址卡片容器 + template 模板 + 各卡片规格/数量/小计 + 总价条 | L |
| `app/templates/order/success.html` | 整组查询码、总价、地址清单 | S |
| `app/templates/order/query.html` | 组信息 + 移动端 Carousel + 桌面端上下/左右切换 | L |
| `app/templates/admin/orders.html` | 分页条 + `sub_no`/多址徽章 | M |
| `app/templates/admin/order_detail.html` | 矩阵驱动按钮、取消原因、组内导航、更新快递文案 | M |
| `app/static/js/main.js` | 地址增删/reindex/合计统一测算/查询页切换逻辑 | L |
| `app/__init__.py` | 启动时调用 `run_schema_migrations` | S |
| `docs/01/03/04/06` | 同步查询码语义、状态机、接口、验收清单 | S |
| `README.md` | 更新核心规则说明 | S |

---

## 8. 建议实施顺序（供后续模型逐阶段执行）

1. **阶段 1：模型与迁移** — `order.py` 模型改造 + `migration.py` + `__init__` 接入；先在旧库副本上验证迁移。
2. **阶段 2：服务层** — `order_service.py` 三个新函数；单测/手工验证状态矩阵。
3. **阶段 3：用户端多地址下单** — `new.html` + `main.js` 卡片增删统一计价 → `create` 多地址 → `success` 组展示；先验证单地址（`address_count=1`）行为与旧版一致。
4. **阶段 4：用户端查询切换** — `query` 组查询 + `query.html` Carousel/切换。
5. **阶段 5：管理端** — `admin.py` 分页/状态机/组导航 + `orders.html`/`order_detail.html`。
6. **阶段 6：打磨与验收** — 按第 9 节清单回归，同步 docs 与 README。

---

## 9. 验收测试清单（新增部分）

```text
[多地址下单]
1. 单地址提交 → 生成 1 个查询码 + 1 条订单，行为与旧版完全一致
2. 3 个地址提交 → 成功页展示同一个查询码 + 3 条地址清单 + 总价 = 各小计之和
3. 添加地址再删除 → 序号重排正确、总价实时刷新
4. 某卡片缺少必填项 → 后端拒绝并回显错误，不产生任何订单
5. address_count 为 0 或 >20 → 拒绝
6. 各地址可选不同规格与数量，小计各自正确

[一码多址查询]
7. 用户输入手机号+查询码 → 移动端 Carousel 可左右滑动切换 3 个地址
8. 桌面端可上下排列或按钮切换查看 3 个地址
9. 组总价、地址数、子订单状态/物流分别正确显示
10. 后台订单列表出现 3 条记录，sub_no 显示 #1/#2/#3，多址徽章正确
11. 后台搜索该手机号/查询码 → 3 条都出现
12. 后台详情页可组内切换其余子订单

[状态流转]
13. created → 发货 → shipped；shipped → 更新快递保持 shipped；shipped → 完成 → completed
14. 伪造直发 created→completed、completed→cancelled、cancelled→shipped → 一律被后端拒绝
15. 取消任意可取消状态 → 不填原因被拒绝；填原因成功且详情可见
16. cancelled/completed 详情页无发货与状态操作按钮
17. 老数据迁移后 sub_no=1，用户查询/后台列表/详情均正常
```

---

## 10. 风险与兼容性

- **迁移风险**：SQLite 重建表必须「备份 → rename → create → insert → drop」，任一步失败不得继续；上线前先在开发库演练。
- **WAL 模式**：备份除 `.db` 外最好同时考虑 `-wal/-shm`，或选择无写操作的时间窗执行迁移。
- **查询码语义变化**：所有「查询码唯一」的旧文档/文案必须同步更新。
- **同码多行的展示**：后台原先假设 `query_code` 唯一，改造后所有按 `query_code` 单条查询（如有）都应改为 `filter_by(phone, query_code)` 列表处理。
- **限流**：多地址一次提交只扣一次限流额度，属合理设定，文档中注明即可。
- **不做 CSRF token**：保持现有同源表单 POST 方案不变（不引入新依赖）。

---

## 11. 待确认决策点（已含推荐，默认按推荐执行）

1. **每地址规格数量**：推荐「每地址卡片内独立选规格和数量，最后一并计价」（更贴近需求原文「按表单不同添加」）。若改「全组统一规格数量」可简化前端，但灵活度低。
2. **退货/退回待发货（shipped→created）**：推荐**做**，作为矩阵内可选操作（发错快递很常见）。若不做，shipped 状态的快递修改仍可通过「更新快递」完成。
3. **取消是否可在 shipped 状态发生**：推荐允许，但必须填原因并二次确认。
4. **分组上限**：推荐 20 个地址/次，防滥用，也可改为 10/30。
5. **操作日志表 `order_logs`**：推荐做（轻量一张表 + 服务层一行记录），不做的风险是状态流转不可审计。