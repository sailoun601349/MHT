# -*- coding: utf-8 -*-
"""面单照片功能回归：多张上传（拍照/相册）、数量上限、单张删除、发货校验。

运行：C:/Users/yang6/.workbuddy/binaries/python/envs/default/Scripts/python.exe tests/test_photos.py
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
from app.models import Order, OrderPhoto

TMP = Path(tempfile.mkdtemp(prefix="mht_photo_"))


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
            "spec_name_0": "5斤装", "quantity_0": str(quantity),
        },
    )
    with app.app_context():
        o = Order.query.filter_by(phone=phone).order_by(Order.id.desc()).first()
        return dict(id=o.id, quantity=o.quantity, max_photos=o.max_photos)


def photo_count(order_id):
    with app.app_context():
        return OrderPhoto.query.filter_by(order_id=order_id).count()


# 合法的 PNG 文件头（magic bytes），后续填充假数据即可通过 magic bytes 校验
FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"fakepngdata"


def upload(client, order_id, names, field="photos"):
    t = csrf(client)
    if field == "photo":
        data = {"_csrf_token": t, "photo": (io.BytesIO(FAKE_PNG), names[0])}
    else:
        data = {"_csrf_token": t, "photos": [(io.BytesIO(FAKE_PNG), n) for n in names]}
    return client.post(
        f"/admin/orders/{order_id}/photos", data=data, content_type="multipart/form-data"
    )


print("=" * 70)
print("准备：下单（quantity=2 -> max_photos=4）+ 超管登录")
print("=" * 70)

cust = app.test_client()
o = place_order(cust, "13633330001", quantity=2)
check("下单 quantity=2", o["quantity"] == 2)
check("max_photos = quantity*2 = 4", o["max_photos"] == 4, f"max={o['max_photos']}")

super_c = app.test_client()
super_c.get("/admin/login")
super_c.post("/admin/login", data={"phone": "13900000000", "code": "testpass888", "_csrf_token": csrf(super_c)})

order_id = o["id"]

print("=" * 70)
print("照片上传（相册多张 / 拍照单张）")
print("=" * 70)

upload(super_c, order_id, ["a.png", "b.png"], field="photos")
check("相册上传 2 张 -> order_photos=2", photo_count(order_id) == 2, f"count={photo_count(order_id)}")

upload(super_c, order_id, ["c.png"], field="photo")
check("拍照上传 1 张 -> order_photos=3", photo_count(order_id) == 3, f"count={photo_count(order_id)}")

print("=" * 70)
print("数量上限（最多 4 张）")
print("=" * 70)

# 当前 3 张，再传 2 张 = 5 > 4，应拒绝
upload(super_c, order_id, ["d.png", "e.png"], field="photos")
check("超上限（3+2>4）被拒绝，仍为 3 张", photo_count(order_id) == 3, f"count={photo_count(order_id)}")

# 当前 3 张，再传 1 张 = 4，应成功
upload(super_c, order_id, ["d.png"], field="photo")
check("补满至上限 4 张成功", photo_count(order_id) == 4, f"count={photo_count(order_id)}")

print("=" * 70)
print("单张删除 + 删除后可重新上传")
print("=" * 70)

with app.app_context():
    first_photo_id = OrderPhoto.query.filter_by(order_id=order_id).order_by(OrderPhoto.id.asc()).first().id

super_c.post(f"/admin/orders/{order_id}/photos/{first_photo_id}/delete", data={"_csrf_token": csrf(super_c)})
check("删除 1 张 -> 剩 3 张", photo_count(order_id) == 3, f"count={photo_count(order_id)}")

upload(super_c, order_id, ["f.png"], field="photo")
check("删除后重新上传 -> 4 张", photo_count(order_id) == 4, f"count={photo_count(order_id)}")

print("=" * 70)
print("发货校验（需有照片）")
print("=" * 70)

# 有照片 -> 发货成功
super_c.post(
    f"/admin/orders/{order_id}/ship",
    data={"_csrf_token": csrf(super_c), "express_company": "顺丰速运", "express_no": "SF123456"},
)
with app.app_context():
    o_shipped = db.session.get(Order, order_id)
    shipped_status = o_shipped.status
check("有照片发货成功（created->shipped）", shipped_status == "shipped", f"status={shipped_status}")

# 新订单（无照片）发货 -> 拒绝
o2 = place_order(app.test_client(), "13633330002", quantity=1)
super_c.post(
    f"/admin/orders/{o2['id']}/ship",
    data={"_csrf_token": csrf(super_c), "express_company": "顺丰速运", "express_no": "SF999"},
)
with app.app_context():
    o2_status = db.session.get(Order, o2["id"]).status
check("无照片发货被拒（仍为 created）", o2_status == "created", f"status={o2_status}")

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
