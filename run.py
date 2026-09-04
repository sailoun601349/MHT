# -*- coding: utf-8 -*-
"""猕猴桃订单管理系统 - 启动入口

开发:  python run.py
生产:  gunicorn -w 1 -t 120 -b 127.0.0.1:18805 run:app
"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=18805, debug=False)
