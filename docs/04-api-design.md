# 接口 / 路由设计

服务端渲染（Flask + Jinja2），表单提交为主，少量 JSON。

## 1. 路由总表

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| GET | / | 首页：手机号入口 / 手机号+查询码入口 | 公开 |
| POST | /enter | 首页提交：路由到下单页或订单查询页 | 公开 |
| GET | /order/new?phone=xxx | 下单填写页 | 公开 |
| POST | /order/create | 提交订单（支持多地址，生成一个组查询码） | 公开 |
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
| POST | /admin/ocr | OCR 识别快递单号（预留桩） | 管理员 |
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
            address_{i}, spec_name_{i}, quantity_{i}
服务端校验（每地址）:
  - phone / receiver_phone 匹配 ^1[3-9]\d{9}$
  - receiver_name / address 非空且长度 ≤ 100 / ≤ 500
  - spec_name 必须在配置 SPECS 中存在（价格以服务端配置为准）
  - quantity 整数 1..99
  - address_count 1..20
流程:
  1) 限流检查（同 IP 5 次/分钟，一组按 1 次计）
  2) BEGIN IMMEDIATE 分配一次全局顺序号（组码）
  3) 每地址 total_fee = spec_price × quantity（round 2 位）
  4) group_total = Σ 各地址小计
  5) 插入 N 条订单（sub_no=1..N，共享 query_code）
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

### POST /admin/ocr（预留）

```
返回 501 JSON: {"ok": false, "message": "OCR 功能待接入第三方服务"}
后续接入百度/腾讯/阿里云 OCR 后，前端自动回填快递单号
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
