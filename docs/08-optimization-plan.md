# MHT 功能优化细节表（2026-08-27 全量代码审计版）

> 审计范围：`app/` 全部路由、模型、服务层、模板、部署脚本、运行状态（gunicorn 18805、数据库 8 条真实订单、uploads 256K）。
> 优先级：P0 = 数据/安全风险，立即做；P1 = 尽快；P2 = 近期规划；P3 = 锦上添花。
> 工作量：S < 0.5h，M = 0.5~2h，L > 2h。

---

## P0 — 风险项（数据丢失 / 入口裸奔）

| # | 优化项 | 现状（代码依据） | 优化方案 | 工作量 |
|---|---|---|---|---|
| 1 | 备份根本没有在跑 | `deploy/backup.sh` 写好了，但 `crontab -l` 为空；`data/` 下只有 8-17 手动备份一份 | 挂 crontab：`0 3 * * * ~/MyProjects/18805-MHT/deploy/backup.sh >> ~/MyProjects/18805-MHT/logs/backup.log 2>&1`；backup.sh 内 `BASE` 路径从 `/opt/kivi-order` 改为实际目录 | S |
| 2 | 服务无自愈，重启即宕机 | gunicorn 是手动起的（无 systemd 单元，`~/.config/systemd/user/` 无 kivi）；`deploy/kivi-order.service.example` 与实际部署漂移（示例 /opt/kivi-order:8000，实际 ~/MyProjects/18805-MHT:18805） | 按实际路径写 `~/.config/systemd/user/kivi-order.service`（gunicorn -b 127.0.0.1:18805），`loginctl enable-linger ubuntu` 保证开机自启；同步修正 deploy/ 示例 | S |
| 3 | 公网明文 HTTP，登录代码裸奔 | gunicorn 直接 `0.0.0.0:18805`，无反代；nginx（80/443 已在跑其他站）没有 18805 的配置；admin 专属代码、session cookie 明文传输 | gunicorn 改绑 127.0.0.1，nginx 加 server 块反代 18805（可复用已有 443 证书体系或自签）；过渡方案至少先改绑本地 | M |

## P1 — 尽快做

| # | 优化项 | 现状（代码依据） | 优化方案 | 工作量 |
|---|---|---|---|---|
| 4 | 管理端无 CSRF 防护 | 全站表单纯 POST，无 flask-wtf/token；07 号文档当时决策"不做"，但 ship/status/login 均可被跨站伪造 | 引入 Flask-WTF CSRF（仅管理端蓝图启用即可），或最小代价：校验 `Origin/Referer` 同源 | M |
| 5 | 金额用 Float 存，有精度隐患 | `Order.spec_price/total_fee = db.Float`（order.py），累计/退款场景会出现 0.30000000000000004 | 改为「整数分」存储（int，展示层 /100），或 Numeric(10,2)；迁移走既有 `migration.py` 重建表流程 | M |
| 6 | 备注互相覆盖，操作无留痕 | `change_order_status()` 直接 `order.note = remark`（order_service.py），每次流转把上一次取消/退回原因抹掉 | 新增 `order_logs` 表（order_id/action/from/to/remark/at），07 号文档本来就建议做；note 保留最近一次即可 | M |
| 7 | 下单可重复提交 | `new.html` 提交按钮无 disable/loading 逻辑，手机双击 = 两个查询码两单 | JS：submit 时禁用按钮 + 文案"提交中…"；后端可选加同 phone 10 秒去重 | S |
| 8 | 代码无版本控制 | `git status` → not a git repository；服务器是唯一副本 | `git init + add + commit`（.gitignore 已备好），有 GitHub 就推远程，没有就定期 tar 进备份 | S |
| 9 | 管理员凭据弱默认且公开 | `ADMIN_CODE` 默认 `sailoun`、手机号写在 README/config；运行进程 env 里也是默认值 | `flask reset-admin` 换强代码；service 单元里只留 SECRET_KEY，管理员信息走 CLI 重置 | S |

## P2 — 近期规划（管理效率 / 性能 / 加固）

| # | 优化项 | 现状（代码依据） | 优化方案 | 工作量 |
|---|---|---|---|---|
| 10 | 订单列表 N+1 查询 | `orders.html` 每行调 `o.group_size` → 每行一次 `group_orders` 查询；20 行/页 = 20+ 次 SQL（当前量小无感，量大会拖垮） | 列表 SQL 一次 `GROUP BY phone,query_code` 取组大小，或子查询注到行对象；详情页 `group_index` 的 `.index(self)` 同步优化 | M |
| 11 | 面单照片任何人可看 | `/uploads/<path>` 无鉴权（`__init__.py`），仅靠 uuid 文件名遮羞 | 该路由加 `@login_required`（用户端查询页本来就直接嵌管理端图……需权衡：改为用户端仅登录态管理员可见，或查询页只展示快递信息不展示面单原图） | S |
| 12 | 查询码可被穷举 | 查询码仅 3-6 位数字 + 手机号可枚举；现仅按 IP 限流 10 次/分，攻击者换 IP 即绕过 | 限流 key 从 IP 改为 `IP + phone` 组合；连续失败 N 次锁定该手机号查询 15 分钟 | S |
| 13 | 上传仅看扩展名 | `upload_service.py` 白名单只查后缀，改名 polyglot 可绕过；响应无安全头 | 读文件头 magic bytes（jpg/png/webp 签名）再收；nginx 加 `X-Content-Type-Options: nosniff` 等安全头 | S |
| 14 | 管理端缺日期筛选与统计 | `admin/orders` 仅状态 + 关键词筛选，无时间维度，无待发货汇总 | 加日期区间筛选（created_at 字符串排序可用）+ 顶部统计卡（今日单量/待发货/已发货/金额合计） | M |
| 15 | 无导出功能 | README 路线图已列 Excel 导出 | 加 `/admin/orders/export.csv`（同筛选条件），csv 模块即可，先 CSV 后 Excel | S |
| 16 | 多址组无整组操作 | 一码多址后每条子订单要逐个发货 | 详情页加「整组发货」（同快递公司/单号可选不同单号，循环调 `ship_order`，事务包住） | M |
| 17 | 物流单号无跳转 | 查询页快递单号纯文本展示（query.html:53-57） | 单号一键复制 + 按快递公司跳快递100/官网查询链接 | S |

## P3 — 锦上添花

| # | 优化项 | 现状 | 优化方案 | 工作量 |
|---|---|---|---|---|
| 18 | OCR 快递单号 | `/admin/ocr` 返回 501 桩接口 | 接入腾讯/百度 OCR（有免费额度），发货页拍照识别回填单号 | M |
| 19 | 省市区手填易错 | 下单页省/市/区为纯文本框 | 换省市区级联选择器（行政区划数据一份 JSON 即可，无外部依赖） | M |
| 20 | 时间字段为字符串 | `created_at/updated_at` 存 "YYYY-MM-DD HH:MM:SS" 字符串 | 保持现状也可；若做导出/统计增强，迁移为 ISO8601 或 datetime | M |
| 21 | 无健康检查 | 无 /healthz | 加轻量端点（查 DB pragma + 返回 ok），供日后监控探活 | S |
| 22 | 无任何测试 | 项目无 tests/ | 优先补状态机矩阵与 `create_order_group` 单测（pytest + 内存 SQLite），这两处是业务核心 | M |
| 23 | 目录卫生 | `venv.win-backup/`、根级 `__pycache__/` 残留 | 清理（trash 而非 rm），.gitignore 补条目 | S |
| 24 | 下单成功页易丢码 | 查询码只在 success 页展示一次，无短信 | 低成本兜底：成功页加"截图保存查询码"醒目提示 + 图文引导；短信通知属付费项另议 | S |

---

## 已做得好、无需动的部分（审计确认）

- 状态机后端强制（`STATUS_TRANSITIONS` 矩阵 + 服务层校验），伪造直发/跳转一律拒绝
- 服务端计价（`find_spec` 以配置价格为准，防前端篡改）
- 全局顺序号独立连接 + `BEGIN IMMEDIATE` 原子分配，并发安全
- SQLite WAL + `PRAGMA user_version` 幂等迁移（带备份，失败中止）
- 登录失败锁定（5 次/10 分钟）、下单/查询滑动窗口限流
- 上传随机文件名 + 按月分目录 + 扩展名白名单 + 10MB 上限

## 建议实施顺序

1. **今天就做**（全是 S 级）：#1 备份 crontab → #8 git init → #2 systemd → #9 重置管理员代码
2. **本周**：#3 nginx/HTTPS → #7 防重复提交 → #12 查询限流加固
3. **下周迭代**：#4 CSRF → #5 金额整数化 → #6 操作日志 → #14/#15 管理端筛选导出
4. **有空再排**：P2 剩余项与 P3
