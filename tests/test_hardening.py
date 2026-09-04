# -*- coding: utf-8 -*-
"""加固项回归：金额整数化 / order_logs 留痕 / 下单防重复提交。

运行：C:/Users/yang6/.workbuddy/binaries/python/envs/default/Scripts/python.exe tests/test_hardening.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, r"D:\SAiProject\18805-MHT")
os.chdir(r"D:\SAiProject\18805-MHT")

from app import create_app
from app.config import Config
from app.models import Admin, Order, OrderLog

TMP = Path(tempfile.mkdtemp(prefix="mht_harden_"))


class TestConfig(Config):
    DATA_DIR = TMP
    DATABASE_PATH = TMP / "orders.db"
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + DATABASE_PATH.as_posix()
    UPLOAD_DIR = TMP / "uploads"
    ADMIN_PHONE = "13900000000"
    ADMIN_CODE = "testpass888"


app = create_app(TestConfig)

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (f"  | {detail}" if detail else ""))


def csrf(client):
    with client.session_transaction() as s:
        return s.get("_csrf_token")


def get_order(phone):
    with app.app_context():
        o = Order.query.filter_by(phone=phone).order_by(Order.id.desc()).first()
        if o is None:
            return None
        return dict(id=o.id, total_fee=o.total_fee, total_fee_yuan=o.total_fee_yuan,
                    spec_price=o.spec_price, quantity=o.quantity)


def order_count():
    with app.app_context():
        return Order.query.count()


def builtin_spec_id(name="5斤装"):
    """按 is_builtin+name 查内置规格 id（不硬编码 id）。"""
    with app.app_context():
        from app.models import Spec

        spec = Spec.query.filter_by(is_builtin=True, name=name).first()
        return spec.id if spec is not None else None


def place_order(client, phone, quantity=2):
    client.get(f"/order/new?phone={phone}")
    t = csrf(client)
    with client.session_transaction() as s:
        nonce = s.get("order_nonce")
    client.post(
        "/order/create",
        data={
            "_csrf_token": t, "submit_nonce": nonce, "phone": phone,
            "address_count": "1", "receiver_name_0": "收货人", "receiver_phone_0": "13900000001",
            "address_0": "省市区地址",
            "spec_id_0": builtin_spec_id("5斤装"), "quantity_0": str(quantity),
        },
    )
    return get_order(phone)


print("=" * 70)
print("金额整数化（Float -> 整数分）")
print("=" * 70)

cust = app.test_client()
o = place_order(cust, "13611110001", quantity=2)
check("金额: total_fee 为整数分 10000（5斤装50元×2）", o["total_fee"] == 10000, f"total_fee={o['total_fee']}")
check("金额: spec_price 为整数分 5000", o["spec_price"] == 5000, f"spec_price={o['spec_price']}")
check("金额: total_fee_yuan 换算为 100.0 元", o["total_fee_yuan"] == 100.0, f"yuan={o['total_fee_yuan']}")
check("金额: total_fee 为 int 类型", isinstance(o["total_fee"], int))

print("=" * 70)
print("order_logs 操作留痕")
print("=" * 70)

# 超管登录
super_c = app.test_client()
super_c.get("/admin/login")
super_c.post("/admin/login", data={"phone": "13900000000", "code": "testpass888", "_csrf_token": csrf(super_c)})

order_id = o["id"]
# 状态变更 created -> cancelled（带备注）
super_c.post(
    f"/admin/orders/{order_id}/status",
    data={"_csrf_token": csrf(super_c), "status": "cancelled", "remark": "测试取消"},
)

with app.app_context():
    logs = OrderLog.query.filter_by(order_id=order_id).order_by(OrderLog.id.asc()).all()
    check("留痕: 状态变更写 1 条日志", len(logs) == 1, f"logs={len(logs)}")
    if logs:
        lg = logs[0]
        check("留痕: action=status", lg.action == "status", f"action={lg.action}")
        check("留痕: from=created", lg.from_status == "created", f"from={lg.from_status}")
        check("留痕: to=cancelled", lg.to_status == "cancelled", f"to={lg.to_status}")
        check("留痕: remark 记录", lg.remark == "测试取消", f"remark={lg.remark}")
        check("留痕: 操作人为超管", lg.operator_admin_id == Admin.query.filter_by(phone="13900000000").first().id)

print("=" * 70)
print("下单防重复提交（幂等 nonce）")
print("=" * 70)

cust2 = app.test_client()
cust2.get("/order/new?phone=13622220002")
t = csrf(cust2)
with cust2.session_transaction() as s:
    nonce = s.get("order_nonce")

payload = {
    "_csrf_token": t, "submit_nonce": nonce, "phone": "13622220002",
    "address_count": "1", "receiver_name_0": "收货人", "receiver_phone_0": "13900000002",
    "address_0": "省市区地址",
    "spec_id_0": builtin_spec_id("5斤装"), "quantity_0": "1",
}
before = order_count()
r1 = cust2.post("/order/create", data=payload)
after_first = order_count()
check("防重复: 第一次提交成功生成 1 单", after_first == before + 1, f"{before}->{after_first}")

r2 = cust2.post("/order/create", data=payload)  # 同 nonce 二次提交
after_second = order_count()
check("防重复: 二次提交被拦截，无新单", after_second == after_first, f"{after_first}->{after_second}")

print("=" * 70)
passed = sum(1 for _, ok, _ in results if ok)
failed = len(results) - passed
print(f"总计 {len(results)} 项，通过 {passed} 项，失败 {failed} 项")
if failed:
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}  | {detail}")

shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if failed else 0)
