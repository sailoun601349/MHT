# 🥝 猕猴桃订单管理系统

轻量级个人订单系统：用户手机号下单 → 获取全局查询码 → 查询订单；管理员发货上传快递面单。

- 技术栈：Flask + SQLite + Bootstrap 5（手机优先，管理员电脑可用）

## 快速开始（开发）

```bash
cp .env.example .env        # 按需修改超级管理员等私有配置
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
python run.py                 # 打开 http://127.0.0.1:18805
```

超级管理员手机号与登录密码通过根目录 `.env` 提供（见下）；未配置时首次启动不自动创建，
可运行 `flask --app run reset-admin` 手动创建。

## 配置（本地 .env）

私有配置（超级管理员、密钥等）一律放在根目录 `.env`（已被 `.gitignore` 忽略，不入库），
参考 `.env.example`。也可直接用环境变量覆盖。

| 变量 | 说明 |
|---|---|
| SECRET_KEY | Flask 会话密钥，生产必须随机生成（如 `openssl rand -hex 32`） |
| ADMIN_PHONE | 超级管理员手机号（首次启动自动创建，仅 `reset-admin` 可改） |
| ADMIN_CODE | 超级管理员初始登录密码（仅首启/重置用） |
| SESSION_HOURS | 管理员会话时长（小时，默认 8） |

重置管理员：

```bash
flask --app run reset-admin --phone <手机号> --code <登录密码>
```

## 商品规格配置

编辑 `app/config.py` 中 `SPECS` 列表（名称 + 单价），下单页下拉与计价自动跟随。

## 核心规则

- 查询码 = **下单手机号 + 全局顺序号**（001 起，全局递增；一个查询码可对应多个地址）
- 多地址下单：一次提交多个地址生成**一个查询码**、后台多条订单，用户查询时可左右/上下切换
- 用户查询：手机号 + 查询码；下单：仅需手机号
- 管理员：手机号 + 登录密码登录，发货时上传面单照片并录入快递单号
- 状态机：待发货 → 已发货 → 已完成/已取消，取消与退回必须填写原因；非法流转后端拒绝
- 多管理员：1 个超级管理员（手机号来自 `.env` 配置）+ 多个普通管理员；普通管理员经专属链接 `/<短码>` 获客下单，订单按责任人隔离，超级管理员可见全部

## 部署

详见 `docs/05-deployment.md`（systemd / Docker Compose / Nginx / 备份）。

## 目录结构

```
├── run.py                  # 入口
├── .env.example            # 私有配置模板（真实值放 .env，不入库）
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
└── docs/                   # 设计文档 01-11
```

## 许可证

本项目使用 [MIT License](LICENSE)。

## 功能

- 下单 / 全局查询码 / 订单查询
- 一码多址（一次下单多个收货地址）、多管理员与订单归属隔离
- 管理端：发货上传面单照片（拍照/相册、单张删除）、整组发货、日期筛选、CSV 导出
