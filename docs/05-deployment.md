# 部署方案

## 1. 服务器要求

- 低配个人服务器即可（轻量级 Flask + SQLite 单体）
- OS：Ubuntu/Debian/CentOS 均可
- Python 3.10+
- 域名 + HTTPS（推荐 Caddy 自动证书，或 Nginx + certbot）

## 2. 目录结构（部署后）

```
/opt/kivi-order/
├── run.py
├── app/                 # 应用包
├── venv/                # Python 虚拟环境
├── data/orders.db       # SQLite 数据库（WAL 模式）
├── uploads/202405/      # 面单照片
├── logs/                # gunicorn 日志
└── requirements.txt
```

## 3. 方式 A：systemd + gunicorn（推荐）

```bash
# 1. 安装依赖
cd /opt/kivi-order
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. 配置环境变量
export SECRET_KEY="$(openssl rand -hex 24)"
export ADMIN_PHONE="你的手机号"
export ADMIN_CODE="超级管理员初始登录密码"

# 3. 启动（先重置管理员，再启动服务）
flask --app run reset-admin --phone "${ADMIN_PHONE}" --code "${ADMIN_CODE}"
venv/bin/gunicorn -w 1 -t 120 -b 127.0.0.1:8000 \
  --access-logfile logs/access.log --error-logfile logs/error.log run:app
```

systemd 单元示例见 `deploy/kivi-order.service.example`。

## 4. 方式 B：Docker Compose

```bash
docker compose up -d --build
```

- 数据目录挂载到宿主机 `./data` 与 `./uploads`，便于备份
- 见仓库根 `docker-compose.yml` 与 `Dockerfile`

## 5. Nginx 反代（HTTP → gunicorn）

示例见 `deploy/nginx.conf.example`。要点：

- 反代 127.0.0.1:8000
- `client_max_body_size 10m`
- `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for`（用于限流取真实 IP）
- 上传目录不走 Nginx 直接静态服务（由 Flask 路由校验后返回）

## 6. HTTPS

- Caddy 2 一行配置即可自动申请 Let's Encrypt 证书
- 或 Nginx + certbot：`certbot --nginx -d 你的域名`

## 7. 备份（cron 每日 3 点）

```bash
# /etc/cron.d/kivi-backup
0 3 * * * root /opt/kivi-order/deploy/backup.sh
```

```bash
#!/usr/bin/env bash
# deploy/backup.sh
set -euo pipefail
STAMP=$(date +%F)
DB=/opt/kivi-order/data/orders.db
DEST=/opt/kivi-order/backup
mkdir -p "$DEST"
sqlite3 "$DB" ".backup '$DEST/orders_$STAMP.db'"
tar -czf "$DEST/uploads_$STAMP.tar.gz" -C /opt/kivi-order uploads
find "$DEST" -name "*.db" -o -name "*.tar.gz" | xargs -r ls -t | tail -n +31 | xargs -r rm -f
```

（保留最近 30 天备份；本地 + 可选 rclone 同步到对象存储）

## 8. 上线检查清单

- [ ] 修改默认 SECRET_KEY / ADMIN_PHONE / ADMIN_CODE
- [ ] HTTPS 生效，手机与电脑均可访问
- [ ] 首页下单 → 成功页查询码正确
- [ ] 手机号+查询码可查到订单
- [ ] 管理员登录 → 发货上传照片 → 用户端可见快递信息
- [ ] 上传大小限制与文件类型拦截生效
- [ ] 备份 cron 执行成功一次
