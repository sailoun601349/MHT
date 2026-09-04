# -*- coding: utf-8 -*-
"""多管理员 + 专属链接下单 端到端回归（docs/09-multi-admin-spec.md §6 验收清单）。

使用独立临时库（TestConfig），不污染真实 data/orders.db。
注意：不要用外层 app.app_context() 包裹 test_client 交互——会造成 current_user 会话串扰。
运行：C:/Users/yang6/.workbuddy/binaries/python/envs/default/Scripts/python.exe tests/test_multi_admin.py
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
from app.models import Admin, Order

TMP = Path(tempfile.mkdtemp(prefix="mht_test_"))


class TestConfig(Config):
    DATA_DIR = TMP
    DATABASE_PATH = TMP / "orders.db"
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + DATABASE_PATH.as_posix()
    UPLOAD_DIR = TMP / "uploads"


app = create_app(TestConfig)

SUPER_PHONE = "13185020250"
SUPER_CODE = "sailoun"
A_PHONE = "13900002025"   # 后4位 2025
B_PHONE = "13800002025"   # 后4位 2025 -> 碰撞 -> 20251
C_PHONE = "13700008888"   # 后4位 8888

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (f"  | {detail}" if detail else ""))


def csrf(client):
    with client.session_transaction() as s:
        return s.get("_csrf_token")


def login(client, phone, code, ip="10.0.0.1"):
    client.get("/admin/login")
    t = csrf(client)
    return client.post(
        "/admin/login",
        data={"phone": phone, "code": code, "_csrf_token": t},
        headers={"X-Forwarded-For": ip},
    )


# ---- DB 查询（独立 app_context，返回原生值，避免 detached 对象） ----

def admin_fields(phone):
    with app.app_context():
        a = Admin.query.filter_by(phone=phone).first()
        if a is None:
            return None
        return dict(
            id=a.id, role=a.role, is_super=a.is_super, share_code=a.share_code,
            is_active=a.is_active, must_change_password=a.must_change_password,
        )


def check_password(phone, pw):
    with app.app_context():
        a = Admin.query.filter_by(phone=phone).first()
        return a is not None and a.check_code(pw)


def admin_count():
    with app.app_context():
        return Admin.query.count()


def order_owner(phone):
    with app.app_context():
        o = Order.query.filter_by(phone=phone).order_by(Order.id.desc()).first()
        return None if o is None else dict(id=o.id, owner_admin_id=o.owner_admin_id)


def place_order(client, phone, ip="10.0.1.1"):
    """经当前会话（可能已访问短码）下单，返回 (order_id, owner_admin_id)。"""
    client.get(f"/order/new?phone={phone}")
    t = csrf(client)
    with client.session_transaction() as s:
        nonce = s.get("order_nonce")
    client.post(
        "/order/create",
        data={
            "_csrf_token": t,
            "submit_nonce": nonce,
            "phone": phone,
            "address_count": "1",
            "receiver_name_0": "测试收货人",
            "receiver_phone_0": "13900000001",
            "address_0": "广东省深圳市南山区测试地址1号",
            "spec_name_0": "5斤装",
            "quantity_0": "2",
        },
        headers={"X-Forwarded-For": ip},
    )
    return order_owner(phone)


print("=" * 70)
print("R1 / R2 / CSRF / 基础登录")
print("=" * 70)

# CSRF：无 token 的 POST 应 400
c = app.test_client()
resp = c.post("/admin/login", data={"phone": SUPER_PHONE, "code": SUPER_CODE})
check("CSRF: 无 token 的 POST 被 400 拒绝", resp.status_code == 400, f"status={resp.status_code}")

# 术语统一：登录页
resp = c.get("/admin/login")
html = resp.get_data(as_text=True)
check("R2: 登录页含「登录密码」", "登录密码" in html)
check("R2: 登录页无「专属代码/口令」", ("专属代码" not in html) and ("口令" not in html))

# 超级管理员登录
super_c = app.test_client()
resp = login(super_c, SUPER_PHONE, SUPER_CODE)
check("R1: 超级管理员 sailoun 登录成功", resp.status_code == 302, f"status={resp.status_code}")
super_id = admin_fields(SUPER_PHONE)["id"]
check("R1: 超管 role=super", admin_fields(SUPER_PHONE)["is_super"])

print("=" * 70)
print("R3: 管理员管理（创建 / 重复 / 超管保护）")
print("=" * 70)

# 创建 A
t = csrf(super_c)
super_c.post(
    "/admin/admins",
    data={"_csrf_token": t, "phone": A_PHONE, "name": "管理员A", "password": "pwd123456"},
)
a = admin_fields(A_PHONE)
check("R3: 创建普通管理员 A 成功", a is not None)
check("R3: A 角色=admin", a is not None and not a["is_super"])
check("R3: A 初始强制改密=True", a is not None and a["must_change_password"])

# 创建 B（短码碰撞）
super_c.post(
    "/admin/admins",
    data={"_csrf_token": t, "phone": B_PHONE, "name": "管理员B", "password": "pwd123456"},
)
b = admin_fields(B_PHONE)
check("R4: A 短码=手机号后4位 2025", a["share_code"] == "2025", f"got={a['share_code']}")
check("R4: B 后4位碰撞自动追加 -> 20251", b["share_code"] == "20251", f"got={b['share_code']}")

# 重复手机号拒绝
before = admin_count()
super_c.post(
    "/admin/admins",
    data={"_csrf_token": t, "phone": A_PHONE, "name": "重复", "password": "pwd123456"},
)
check("R3: 重复手机号被拒绝", admin_count() == before, f"count={admin_count()}")

# 超管不可删除/停用
super_c.post(f"/admin/admins/{super_id}/delete", data={"_csrf_token": t})
check("R3: 超管不可删除", admin_fields(SUPER_PHONE) is not None)
super_c.post(f"/admin/admins/{super_id}/toggle-active", data={"_csrf_token": t})
check("R3: 超管不可停用", admin_fields(SUPER_PHONE)["is_active"] is True)

print("=" * 70)
print("R5: 专属链接下单归属 + 无链接兜底")
print("=" * 70)

a_id = admin_fields(A_PHONE)["id"]
b_id = admin_fields(B_PHONE)["id"]

# 经 A 短码下单
cust_a = app.test_client()
cust_a.get(f"/{a['share_code']}")  # 访问 2025
o_a = place_order(cust_a, "13600000001")
check("R5: 经 A 短码下单归属 A", o_a["owner_admin_id"] == a_id, f"owner={o_a['owner_admin_id']} vs A={a_id}")

# 经 B 短码下单
cust_b = app.test_client()
cust_b.get(f"/{b['share_code']}")  # 访问 20251
o_b = place_order(cust_b, "13600000002")
check("R5: 经 B 短码下单归属 B", o_b["owner_admin_id"] == b_id, f"owner={o_b['owner_admin_id']} vs B={b_id}")

# 无链接下单 -> 超管
cust_none = app.test_client()
cust_none.get("/")
o_none = place_order(cust_none, "13600000003")
check("R5: 无链接下单归属超管", o_none["owner_admin_id"] == super_id, f"owner={o_none['owner_admin_id']} vs super={super_id}")

# 无效短码 -> 链接无效 + 归超管
cust_bad = app.test_client()
resp = cust_bad.get("/9999")
check("R5: 无效短码提示链接无效", resp.status_code == 302)
o_bad = place_order(cust_bad, "13600000004")
check("R5: 无效短码下单归超管", o_bad["owner_admin_id"] == super_id, f"owner={o_bad['owner_admin_id']}")

print("=" * 70)
print("R6: 数据隔离 / R7: 责任人展示 / R11 强制改密")
print("=" * 70)

# 管理员 A 登录（首次强制改密）
a_c = app.test_client()
resp = login(a_c, A_PHONE, "pwd123456")
check("R11: A 首次登录跳转改密", "/change-password" in (resp.headers.get("Location") or ""), f"loc={resp.headers.get('Location')}")

# A 强制改密（不要求当前密码）
a_c.get("/admin/change-password")
t = csrf(a_c)
a_c.post(
    "/admin/change-password",
    data={"_csrf_token": t, "current_password": "", "new_password": "newpass123", "confirm_password": "newpass123"},
)
check("R8: A 首次强制改密成功", check_password(A_PHONE, "newpass123"))

# 用新密码重新登录 A
a_c = app.test_client()
resp = login(a_c, A_PHONE, "newpass123")
check("R8: A 用新密码登录成功", resp.status_code == 302)

# A 访问管理员管理 -> 403
resp = a_c.get("/admin/admins")
check("R6: 普通管理员访问管理员管理 403", resp.status_code == 403, f"status={resp.status_code}")

# A 订单列表：看不到 B 的订单手机号
resp = a_c.get("/admin/orders")
a_html = resp.get_data(as_text=True)
check("R6: A 列表可见自己的订单", "13600000001" in a_html)
check("R6: A 列表看不到 B 的订单", "13600000002" not in a_html)
check("R7: A 列表显示责任人为自己手机号", A_PHONE in a_html)

# A 访问 B 订单详情 -> 403
resp = a_c.get(f"/admin/orders/{o_b['id']}")
check("R6: A 访问 B 订单详情 403", resp.status_code == 403, f"status={resp.status_code}")

# A 访问自己订单详情 -> 200 且显示责任人
resp = a_c.get(f"/admin/orders/{o_a['id']}")
check("R6: A 访问自己订单详情 200", resp.status_code == 200)
check("R7: 详情页显示责任人", A_PHONE in resp.get_data(as_text=True))

# 超管可见全部
resp = super_c.get("/admin/orders")
s_html = resp.get_data(as_text=True)
check("R6: 超管可见 A 的订单", "13600000001" in s_html)
check("R6: 超管可见 B 的订单", "13600000002" in s_html)

# 超管责任人筛选
resp = super_c.get("/admin/orders?owner=" + A_PHONE)
f_html = resp.get_data(as_text=True)
check("R10: 责任人筛选 A -> 见 A 不见 B", ("13600000001" in f_html) and ("13600000002" not in f_html))

print("=" * 70)
print("R4: 自定义短码 / R3: 停用启用")
print("=" * 70)

# A 自定义短码 2025 -> 8889
a_c.get("/admin/settings")
t = csrf(a_c)
a_c.post("/admin/share-code", data={"_csrf_token": t, "share_code": "8889"})
check("R4: A 自定义短码为 8889", admin_fields(A_PHONE)["share_code"] == "8889")

# 旧短码失效
cust_old = app.test_client()
cust_old.get("/2025")
with cust_old.session_transaction() as s:
    ref_after_old = s.get("ref_admin_id")
check("R4: 自定义后旧短码 2025 失效", ref_after_old is None, f"ref={ref_after_old}")

# 新短码有效
cust_new = app.test_client()
cust_new.get("/8889")
with cust_new.session_transaction() as s:
    ref_after_new = s.get("ref_admin_id")
check("R4: 新短码 8889 生效", ref_after_new == a_id, f"ref={ref_after_new}")

# 超管 settings 无专属短码输入框（仅提示「使用根路径接单」）
resp = super_c.get("/admin/settings")
s_set = resp.get_data(as_text=True)
check("R4: 超管 settings 无短码输入框", 'name="share_code"' not in s_set)
check("R4: 超管 settings 提示使用根路径接单", "根路径接单" in s_set)

# 停用 A -> 无法登录 + 短码失效
super_c.post(f"/admin/admins/{a_id}/toggle-active", data={"_csrf_token": csrf(super_c)})
check("R3: 停用 A 成功", admin_fields(A_PHONE)["is_active"] is False)

resp = login(app.test_client(), A_PHONE, "newpass123", ip="10.0.9.9")
check("R3: 停用后 A 无法登录", "停用" in resp.get_data(as_text=True))

cust_dis = app.test_client()
cust_dis.get("/8889")
with cust_dis.session_transaction() as s:
    ref_dis = s.get("ref_admin_id")
check("R3: 停用后短码 8889 失效", ref_dis is None, f"ref={ref_dis}")

# 启用 A 恢复
super_c.post(f"/admin/admins/{a_id}/toggle-active", data={"_csrf_token": csrf(super_c)})
check("R3: 启用 A 恢复", admin_fields(A_PHONE)["is_active"] is True)
resp = login(app.test_client(), A_PHONE, "newpass123", ip="10.0.9.10")
check("R3: 启用后 A 可登录", resp.status_code == 302)

print("=" * 70)
print("R3: 删除管理员（订单转移）/ R8: 自助改密校验")
print("=" * 70)

# 创建 C 并下单，删除 C 后订单归超管
super_c.post(
    "/admin/admins",
    data={"_csrf_token": csrf(super_c), "phone": C_PHONE, "name": "管理员C", "password": "pwd123456"},
)
c_admin = admin_fields(C_PHONE)
cust_c = app.test_client()
cust_c.get(f"/{c_admin['share_code']}")
o_c = place_order(cust_c, "13600000005")
check("R5: 经 C 短码下单归属 C", o_c["owner_admin_id"] == c_admin["id"])

super_c.post(f"/admin/admins/{c_admin['id']}/delete", data={"_csrf_token": csrf(super_c)})
check("R3: 删除 C 成功", admin_fields(C_PHONE) is None)
check("R3: C 名下订单转移给超管", order_owner("13600000005")["owner_admin_id"] == super_id, f"owner={order_owner('13600000005')['owner_admin_id']} vs super={super_id}")

# R8 自助改密：当前密码错被拒
a2 = app.test_client()
login(a2, A_PHONE, "newpass123")
a2.get("/admin/change-password")
t = csrf(a2)
a2.post(
    "/admin/change-password",
    data={"_csrf_token": t, "current_password": "wrongpass", "new_password": "finalpass456", "confirm_password": "finalpass456"},
)
check("R8: 当前密码错误被拒（密码未变）", check_password(A_PHONE, "newpass123"))

# 正确改密
a2.post(
    "/admin/change-password",
    data={"_csrf_token": t, "current_password": "newpass123", "new_password": "finalpass456", "confirm_password": "finalpass456"},
)
check("R8: 自助改密成功（旧密码失效）", (not check_password(A_PHONE, "newpass123")) and check_password(A_PHONE, "finalpass456"))

# 超管自助改密
super_c.get("/admin/change-password")
t = csrf(super_c)
super_c.post(
    "/admin/change-password",
    data={"_csrf_token": t, "current_password": SUPER_CODE, "new_password": "supernew789", "confirm_password": "supernew789"},
)
check("R8: 超管自助改密成功", check_password(SUPER_PHONE, "supernew789"))

print("=" * 70)
passed = sum(1 for _, ok, _ in results if ok)
failed = len(results) - passed
print(f"总计 {len(results)} 项，通过 {passed} 项，失败 {failed} 项")
if failed:
    print("失败项：")
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}  | {detail}")

shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if failed else 0)
