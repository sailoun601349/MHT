# -*- coding: utf-8 -*-
from ..extensions import db


class Counter(db.Model):
    """全局顺序号计数器，单行记录 order_seq。"""

    __tablename__ = "counters"

    name = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Integer, nullable=False, default=0)

    def __repr__(self):
        return f"<Counter {self.name}={self.value}>"
