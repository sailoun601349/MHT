#!/usr/bin/env bash
# 猕猴桃订单系统 - 一键启动（Linux/macOS）
set -e
cd "$(dirname "$0")"

if [ ! -d venv ]; then
  echo "[1/3] 创建虚拟环境..."
  python3 -m venv venv
fi
source venv/bin/activate

echo "[2/3] 安装依赖..."
pip install -r requirements.txt -q

echo "[3/3] 启动服务: http://127.0.0.1:5000"
echo "管理员登录: http://127.0.0.1:5000/admin/login"
exec python run.py
