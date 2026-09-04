# 🥝 猕猴桃订单管理系统

轻量级个人订单系统：用户手机号下单 → 获取全局查询码 → 查询订单；管理员发货上传快递面单。

- 技术栈：Flask + SQLite + Bootstrap 5（手机优先，管理员电脑可用）
- 适配 4C4G 个人服务器，内存占用 < 300MB

## 快速开始（开发）

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
python run.py                 # 打开 http://127.0.0.1:5000
```

首次启动自动创建数据库与默认**超级管理员**（手机号 `13185020250`，初始登录密码 `sailoun`）。数据库已生成后改配置不会更新已有管理员，修改凭据请用下方 reset-admin 命令。

## 配置（环境变量）

| 变量 | 默认值 | 说明 |
|---|---|---|
| SECRET_KEY | 开发默认值 | 生产必须随机生成 |
| ADMIN_PHONE | 13185020250 | 超级管理员手机号（写死） |
| ADMIN_CODE | sailoun | 超级管理员初始登录密码（仅首启/重置用） |
| SESSION_HOURS | 8 | 管理员会话时长 |

重置管理员：

```bash
flask --app run reset-admin --phone 13185020250 --code sailoun
```

## 商品规格配置

编辑 `app/config.py` 中 `SPECS` 列表（名称 + 单价），下单页下拉与计价自动跟随。

## 核心规则

- 查询码 = **下单手机号 + 全局顺序号**（001 起，全局递增；一个查询码可对应多个地址）
- 多地址下单：一次提交多个地址生成**一个查询码**、后台多条订单，用户查询时可左右/上下切换
- 用户查询：手机号 + 查询码；下单：仅需手机号
- 管理员：手机号 + 登录密码登录，发货时上传面单照片并录入快递单号
- 状态机：待发货 → 已发货 → 已完成/已取消，取消与退回必须填写原因；非法流转后端拒绝
- 多管理员：超级管理员（`13185020250`）+ 多个普通管理员；普通管理员经专属链接 `/<短码>` 获客下单，订单按责任人隔离，超级管理员可见全部

## 部署

详见 `docs/05-deployment.md`（systemd / Docker Compose / Nginx / 备份）。

## 目录结构

```
├── run.py                  # 入口
├── app/
│   ├── config.py           # 配置 + 规格
│   ├── extensions.py       # db / login_manager
│   ├── models/             # Admin / Order / Counter
│   ├── routes/             # main / order / admin
│   ├── services/           # 下单 / 顺序号 / 上传
│   ├── utils/              # 校验 / 限流
│   ├── templates/          # Jinja2 页面
│   └── static/             # css / js
├── data/                   # SQLite（运行时生成）
├── uploads/                # 面单照片（运行时生成）
├── deploy/                 # nginx / systemd / backup 示例
└── docs/                   # 设计文档 01-06
```

## 许可证

本项目使用 [MIT License](LICENSE)。

## 功能路线

- ✅ 下单 / 查询码 / 订单查询 / 管理发货
- ⏳ OCR 快递单号（已预留 /admin/ocr 接口，待接入第三方服务）
- 未来可扩展：支付、短信通知、Excel 导出、小程序
