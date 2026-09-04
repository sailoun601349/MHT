# -*- coding: utf-8 -*-
"""Flask 扩展实例"""
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
login_manager = LoginManager()
