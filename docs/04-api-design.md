# 接口 / 路由设计

服务端渲染（Flask + Jinja2），表单提交为主，少量 JSON。

## 1. 路由总表

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| GET | / | 首页：手机号入口 / 手机号+查询码入口 | 公开 |
| POST | /enter | 首页提交：路由到下单页或订单查询页 | 公开 |
| GET | /order/new?phone=xxx | 下单填写页（按归属管理员过滤「适用且启用」规格，隐藏 spec_id radio） | 公开 |
| POST | /order/create | 提交订单（支持多地址；每地址按 spec_id 校验适用+启用，服务端计价） | 公开 |
| GET | /order/success?phone=&code= | 下单成功页，展示组查询码与地址清单 | 公开 |
| GET | /order/success/<id> | 兼容旧链接，302 到新成功页 | 公开 |
| GET | /order/query?phone=&code= | 订单组查询（一码多址，可切换） | 公开 |
| GET | /admin/login | 管理员登录页 | 公开 |
| POST | /admin/login | 登录校验 | 公开 |
| POST | /admin/logout | 退出登录 | 管理员 |
| GET | /admin/orders | 订单管理列表（筛选/搜索） | 管理员 |
| GET | /admin/orders/<id> | 订单详情 + 发货操作 | 管理员 |
| POST | /admin/orders/<id>/ship | 保存发货信息（快递+照片） | 管理员 |
| POST | /admin/orders/<id>/status | 标记完成/取消 | 管理员 |
| GET | /admin/specs | 规格管理页（超管全量 / 管理员两区块） | 登录管理员 |
| POST | /admin/specs/create | 新建自定义规格（名称+价格元） | 登录管理员 |
| POST | /admin/specs/<id>/price | 改价（内置一律拒绝；超管任意自定义；普通仅自己的） | 登录管理员 |
| POST | /admin/specs/<id>/toggle | 下架/上架自定义规格（内置恒启用） | 登录管理员 |
| POST | /admin/specs/<id>/delete | 删除自定义规格（内置不可删；先清适用关系） | 登录管理员 |
| POST | /admin/specs/<id>/admins | 设置适用管理员勾选数组（创建者强制包含） | 仅超管 |
| GET | /admin/admins | 管理员管理 | 仅超管 |
| POST | /admin/admins | 创建普通管理员（自动同步内置规格适用） | 仅超管 |
| POST | /admin/admins/<id>/reset-password | 重置登录密码 | 仅超管 |
| POST | /admin/admins/<id>/toggle-active | 停用/启用 | 仅超管 |
| POST | /admin/admins/<id>/delete | 删除管理员（订单+自定义规格移交超管，清适用关系） | 仅超管 |
| GET | /admin/change-password | 自助改密 | 管理员 |
| GET | /admin/settings | 个人设置/专属短码 | 管理员 |
| POST | /admin/share-code | 更新专属短码 | 管理员 |
| GET | /uploads/<path> | 面单照片访问 | 公开 |
| GET | /static/<path> | 静态资源 | 公开 |

## 2. 关键接口说明

### POST /enter

```
请求: phone=13800000001&code=（可选）
- 仅 phone → 302 /order/new?phone=...
- phone + code → 302 /order/query?phone=...&code=001
参数校验失败 → flash 错误 + 302 /
```

### POST /order/create

```
字段: phone, address_count=1..20,
      每地址 receiver_name_{i}, receiver_phone_{i},
            address_{i}, spec_id_{i}, quantity_{i}
服务端校验（每地址）:
  - phone / receiver_phone 匹配 ^1[3-9]\d{9}$
  - receiver_name / address 非空且长度 ≤ 100 / ≤ 500
  - spec_id > 0 且须属于 owner（resolve_order_owner 解析的责任管理员）「适用且启用」
  - quantity 整数 1..99
  - address_count 1..20
计价: 每地址价格 = 该规格记录当前 price_fen（服务端计价，防前端篡改）
流程:
  1) 限流检查（同 IP 5 次/分钟，一组按 1 次计）
  2) BEGIN IMMEDIATE 分配一次全局顺序号（组码）
  3) 每地址 total_fee = spec.price_fen × quantity
  4) group_total = Σ 各地址小计
  5) 插入 N 条订单（sub_no=1..N，共享 query_code；落 spec_id/spec_name/spec_price 快照）
  6) 302 /order/success?phone=..&code=..
```

### GET /order/query

```
参数: phone, code
- 限流：同 IP 10 次/分钟
- 查询: phone + query_code 联合匹配，无结果 → flash + 302 /
- 命中 → 渲染订单详情（含状态、快递信息、面单照片）
```

### POST /admin/orders/<id>/ship

```
字段: express_company, express_no, photo(文件，可选但已有照片可省略)
校验: 快递公司/单号必填；照片仅 jpg/jpeg/png/webp ≤10MB
行为: 仅 created/shipped 可操作；created→shipped，shipped→保持 shipped 更新快递
      非法状态→ flash 拒绝，不改变订单
```

### POST /admin/orders/<id>/status

```
字段: status ∈ 当前状态允许的目标集合 {completed, cancelled, created(退回)}
      remark（取消/退回必填，写入 note）
行为: 按 Order.STATUS_TRANSITIONS 矩阵校验后流转 → 302 详情页
```

## 3. 限流策略（内存实现，重启清零）

| 接口 | 限制 | 维度 |
|---|---|---|
| /order/create | 5 次/分钟 | IP |
| /order/query | 10 次/分钟 | IP |
| /admin/login | 连续失败 5 次锁定 10 分钟 | IP |

说明：Nginx 反代时读取 X-Forwarded-For 作为客户端 IP。

## 4. 认证与会话

- 管理员：Flask-Login cookie 会话，默认 8 小时
- 普通用户：无会话，每次查询均需手机号+查询码
