# -*- coding: utf-8 -*-
"""整组发货（一码多址）功能验证：显示 / 成功 / 事务性回滚 / 单发货回归。

使用独立临时库（TestConfig），不污染真实 data/orders.db。
运行：C:/Users/yang6/.workbuddy/binaries/python/envs/default/Scripts/python.exe tests/test_ship_group.py
"""
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, r"D:\SAiProject\18805-MHT")
os.chdir(r"D:\SAiProject\18805-MHT")

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import Admin, Order, OrderLog

TMP = Path(tempfile.mkdtemp(prefix="mht_shipgroup_"))


class TestConfig(Config):
    DATA_DIR = TMP
    DATABASE_PATH = TMP / "orders.db"
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + DATABASE_PATH.as_posix()
    UPLOAD_DIR = TMP / "uploads"
    ADMIN_PHONE = "13900000000"
    ADMIN_CODE = "testpass888"


app = create_app(TestConfig)

SUPER_PHONE = "13900000000"
SUPER_CODE = "testpass888"

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (f"  | {detail}" if detail else ""))


def csrf(client):
    with client.session_transaction() as s:
        return s.get("_csrf_token")


def login(client, phone=SUPER_PHONE, code=SUPER_CODE):
    client.get("/admin/login")
    t = csrf(client)
    return client.post(
        "/admin/login",
        data={"phone": phone, "code": code, "_csrf_token": t},
    )


# 合法的 PNG 文件头（magic bytes）+ 假数据，通过 upload_service 的 magic bytes 校验
FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"fakepngdata"


def upload(client, order_id, name="p.png"):
    t = csrf(client)
    return client.post(
        f"/admin/orders/{order_id}/photos",
        data={"_csrf_token": t, "photo": (io.BytesIO(FAKE_PNG), name)},
        content_type="multipart/form-data",
    )


def builtin_spec_id(name="5斤装"):
    """按 is_builtin+name 查内置规格 id（不硬编码 id）。"""
    with app.app_context():
        from app.models import Spec

        spec = Spec.query.filter_by(is_builtin=True, name=name).first()
        return spec.id if spec is not None else None


def place_order(client, phone, address_count, ip="10.0.1.1"):
    """下单（支持多地址），返回 group_orders 原始字段列表（独立 app_context 查询）。

    ip 用于区分下单限流（create_limiter 以 IP 为 key，limit=5/60s），
    每次下单传入不同 IP 避免误触限流。
    """
    client.get(f"/order/new?phone={phone}")
    t = csrf(client)
    with client.session_transaction() as s:
        nonce = s.get("order_nonce")

    data = {
        "_csrf_token": t,
        "submit_nonce": nonce,
        "phone": phone,
        "address_count": str(address_count),
    }
    for i in range(address_count):
        data.update({
            f"receiver_name_{i}": f"收货人{i}",
            f"receiver_phone_{i}": f"1390000000{i}",
            f"address_{i}": f"广东省深圳市南山区测试地址{i}号",
            f"spec_id_{i}": builtin_spec_id("5斤装"),
            f"quantity_{i}": "1",
        })
    client.post("/order/create", data=data, headers={"X-Forwarded-For": ip})

    with app.app_context():
        orders = Order.query.filter_by(phone=phone).order_by(Order.sub_no.asc()).all()
        return [
            dict(
                id=o.id, sub_no=o.sub_no, status=o.status,
                express_no=o.express_no, express_company=o.express_company,
                receiver_name=o.receiver_name, address=o.address,
            )
            for o in orders
        ]


def ship_logs(order_id):
    with app.app_context():
        return OrderLog.query.filter_by(order_id=order_id, action="ship").count()


def reload_statuses(orders):
    with app.app_context():
        out = []
        for o in orders:
            fresh = db.session.get(Order, o["id"])
            out.append(dict(id=fresh.id, status=fresh.status, express_no=fresh.express_no))
        return out


print("=" * 70)
print("准备：超级管理员登录")
print("=" * 70)
super_c = app.test_client()
resp = login(super_c)
check("超管登录成功", resp.status_code == 302, f"status={resp.status_code}")

print("=" * 70)
print("1. 多地址显示：详情页含「整组发货」区块")
print("=" * 70)
g = place_order(app.test_client(), "13644440001", address_count=2, ip="10.0.2.1")
check("多地址下单生成 2 个子订单", len(g) == 2, f"count={len(g)}")

resp = super_c.get(f"/admin/orders/{g[0]['id']}")
html = resp.get_data(as_text=True)
check("详情页含「整组发货」", "整组发货" in html)
check("详情页含 ship-group 表单 action", "/ship-group" in html)
check("详情页含 name=\"express_no\"", 'name="express_no"' in html)
check("详情页含 name=\"express_company\"", 'name="express_company"' in html)
check("地址清单含收货人0", g[0]["receiver_name"] in html)
check("地址清单含收货人1", g[1]["receiver_name"] in html)
check("地址清单含地址0", g[0]["address"] in html)
check("地址清单含地址1", g[1]["address"] in html)

print("=" * 70)
print("2. 单地址不显示「整组发货」")
print("=" * 70)
s = place_order(app.test_client(), "13644440002", address_count=1)
check("单地址下单生成 1 个子订单", len(s) == 1, f"count={len(s)}")
resp = super_c.get(f"/admin/orders/{s[0]['id']}")
html = resp.get_data(as_text=True)
check("单地址详情页不含「整组发货」", "整组发货" not in html)

print("=" * 70)
print("3. 整组发货成功")
print("=" * 70)
g2 = place_order(app.test_client(), "13644440003", address_count=2)
upload(super_c, g2[0]["id"], "a.png")
upload(super_c, g2[1]["id"], "b.png")
resp = super_c.post(
    f"/admin/orders/{g2[0]['id']}/ship-group",
    data={"_csrf_token": csrf(super_c), "express_company": "顺丰速运", "express_no": "SF888888"},
)
st = reload_statuses(g2)
check("整组发货返回重定向", resp.status_code == 302, f"status={resp.status_code}")
check("子订单1 status=shipped", st[0]["status"] == "shipped", f"status={st[0]['status']}")
check("子订单2 status=shipped", st[1]["status"] == "shipped", f"status={st[1]['status']}")
check("两子订单 express_no 一致", st[0]["express_no"] == st[1]["express_no"] == "SF888888",
      f"no={st[0]['express_no']},{st[1]['express_no']}")
check("子订单1 新增 1 条 ship 日志", ship_logs(g2[0]["id"]) == 1, f"logs={ship_logs(g2[0]['id'])}")
check("子订单2 新增 1 条 ship 日志", ship_logs(g2[1]["id"]) == 1, f"logs={ship_logs(g2[1]['id'])}")

print("=" * 70)
print("4. 事务性回滚：部分子订单缺照片 -> 整体失败，无部分提交")
print("=" * 70)
g3 = place_order(app.test_client(), "13644440004", address_count=2)
upload(super_c, g3[0]["id"], "a.png")  # 只给第一个子订单上传照片
# 第二个子订单不上传照片
resp = super_c.post(
    f"/admin/orders/{g3[0]['id']}/ship-group",
    data={"_csrf_token": csrf(super_c), "express_company": "顺丰速运", "express_no": "SF999999"},
)
st3 = reload_statuses(g3)
check("整组发货失败返回重定向（error flash）", resp.status_code == 302, f"status={resp.status_code}")
check("子订单1 仍为 created（回滚）", st3[0]["status"] == "created", f"status={st3[0]['status']}")
check("子订单2 仍为 created（回滚）", st3[1]["status"] == "created", f"status={st3[1]['status']}")
check("子订单1 无 ship 日志（未部分提交）", ship_logs(g3[0]["id"]) == 0, f"logs={ship_logs(g3[0]['id'])}")
check("子订单2 无 ship 日志（未部分提交）", ship_logs(g3[1]["id"]) == 0, f"logs={ship_logs(g3[1]['id'])}")

print("=" * 70)
print("5. 单发货回归（/ship 仍正常）")
print("=" * 70)
s2 = place_order(app.test_client(), "13644440005", address_count=1, ip="10.0.2.5")
upload(super_c, s2[0]["id"], "s.png")
resp = super_c.post(
    f"/admin/orders/{s2[0]['id']}/ship",
    data={"_csrf_token": csrf(super_c), "express_company": "中通快递", "express_no": "ZT123456"},
)
st4 = reload_statuses(s2)
check("单发货返回重定向", resp.status_code == 302, f"status={resp.status_code}")
check("单发货后 status=shipped", st4[0]["status"] == "shipped", f"status={st4[0]['status']}")
check("单发货 express_no 正确", st4[0]["express_no"] == "ZT123456", f"no={st4[0]['express_no']}")
check("单发货写 1 条 ship 日志", ship_logs(s2[0]["id"]) == 1, f"logs={ship_logs(s2[0]['id'])}")

print("=" * 70)
print("6. 鉴权隔离：非责任人整组发货被 403 拒绝")
print("=" * 70)
# 创建普通管理员 A
super_c.post(
    "/admin/admins",
    data={"_csrf_token": csrf(super_c), "phone": "13900002025", "name": "管理员A", "password": "pwd123456"},
)
a_c = app.test_client()
login(a_c, "13900002025", "pwd123456")
# A 首次登录强制改密
a_c.post(
    "/admin/change-password",
    data={"_csrf_token": csrf(a_c), "current_password": "", "new_password": "newpass123", "confirm_password": "newpass123"},
)
# A 用新密码重新登录
a_c = app.test_client()
login(a_c, "13900002025", "newpass123")

# 超管名下多地址订单
g4 = place_order(app.test_client(), "13644440006", address_count=2)
resp = a_c.get(f"/admin/orders/{g4[0]['id']}")
check("A 访问他人订单详情 403", resp.status_code == 403, f"status={resp.status_code}")
resp = a_c.post(
    f"/admin/orders/{g4[0]['id']}/ship-group",
    data={"_csrf_token": csrf(a_c), "express_company": "顺丰速运", "express_no": "SF000000"},
)
check("A 对他人订单整组发货 403", resp.status_code == 403, f"status={resp.status_code}")
st5 = reload_statuses(g4)
check("越权后子订单仍为 created", all(o["status"] == "created" for o in st5),
      f"status={[o['status'] for o in st5]}")

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
