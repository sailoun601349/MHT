# -*- coding: utf-8 -*-
"""规格与价格管理（规格 × 适用管理员）端到端验收（docs/12 §11 阶段 6 回归清单）。

使用独立临时库（TestConfig），不污染真实 data/orders.db。
覆盖：内置 seed / 管理员自动同步 / 创建配额 / 改价（内置锁定）/ 下架上架 /
删除（内置拒绝）/ 适用勾选（创建者不可移除、内置可删到 <2）/ 下单按 spec_id
归属校验与快照 / 删除管理员规格移交 / 普通管理员两区块。
运行：C:/Users/yang6/.workbuddy/binaries/python/envs/default/Scripts/python.exe tests/test_spec_management.py
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
from app.extensions import db
from app.models import Admin, Order, Spec, SpecAdmin

TMP = Path(tempfile.mkdtemp(prefix="mht_specmgmt_"))


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
A_PHONE = "13900002025"
A_CODE = "pwd123456"

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (f"  | {detail}" if detail else ""))


def csrf(client):
    with client.session_transaction() as s:
        return s.get("_csrf_token")


def login(client, phone, code, ip="10.0.1.1"):
    client.get("/admin/login")
    t = csrf(client)
    return client.post(
        "/admin/login",
        data={"phone": phone, "code": code, "_csrf_token": t},
        headers={"X-Forwarded-For": ip},
    )


# ---- DB 查询（独立 app_context，返回原生值，避免 detached 对象） ----

def admin_id(phone):
    with app.app_context():
        a = Admin.query.filter_by(phone=phone).first()
        return a.id if a is not None else None


def builtin_spec(name):
    with app.app_context():
        s = Spec.query.filter_by(is_builtin=True, name=name).first()
        return None if s is None else dict(id=s.id, price_fen=s.price_fen, is_active=s.is_active)


def spec_by_name(name, is_builtin=False):
    with app.app_context():
        s = Spec.query.filter_by(is_builtin=is_builtin, name=name).order_by(Spec.id.desc()).first()
        if s is None:
            return None
        return dict(id=s.id, price_fen=s.price_fen, is_active=s.is_active,
                    created_by=s.created_by_admin_id)


def spec_price(spec_id):
    with app.app_context():
        s = db_get(Spec, spec_id)
        return None if s is None else s.price_fen


def db_get(model, pk):
    from app.extensions import db
    return db.session.get(model, pk)


def applicable_of_spec(spec_id):
    with app.app_context():
        return sorted(r[0] for r in db.session.query(SpecAdmin.admin_id)
                      .filter(SpecAdmin.spec_id == spec_id).all())


def spec_ids_applicable_to(admin_pk):
    with app.app_context():
        return sorted(r[0] for r in db.session.query(SpecAdmin.spec_id)
                      .filter(SpecAdmin.admin_id == admin_pk).all())


def admin_sa_count(admin_pk):
    with app.app_context():
        return SpecAdmin.query.filter_by(admin_id=admin_pk).count()


def order_owner_snapshot(phone):
    with app.app_context():
        o = Order.query.filter_by(phone=phone).order_by(Order.id.desc()).first()
        if o is None:
            return None
        return dict(id=o.id, spec_id=o.spec_id, spec_name=o.spec_name,
                    spec_price=o.spec_price, owner_admin_id=o.owner_admin_id,
                    total_fee=o.total_fee)


def create_spec_via(client, name, price_yuan):
    return client.post(
        "/admin/specs/create",
        data={"_csrf_token": csrf(client), "name": name, "price_yuan": price_yuan},
    )


def place_order(client, phone, spec_id, quantity=1, ip="10.0.80.1"):
    """先访问归属链接（当前会话可能已带 ref），再打开下单页并提交。"""
    client.get(f"/order/new?phone={phone}")
    t = csrf(client)
    with client.session_transaction() as s:
        nonce = s.get("order_nonce")
    return client.post(
        "/order/create",
        data={
            "_csrf_token": t, "submit_nonce": nonce, "phone": phone,
            "address_count": "1", "receiver_name_0": "收货人", "receiver_phone_0": "13900000001",
            "address_0": "广东省深圳市南山区测试地址1号",
            "spec_id_0": str(spec_id), "quantity_0": str(quantity),
        },
        headers={"X-Forwarded-For": ip},
    )


print("=" * 70)
print("内置 seed：5斤装/10斤装 存在且默认适用全部启用管理员")
print("=" * 70)

b5 = builtin_spec("5斤装")
b10 = builtin_spec("10斤装")
check("内置 5斤装 存在 price=5000", b5 is not None and b5["price_fen"] == 5000, f"b5={b5}")
check("内置 10斤装 存在 price=10000", b10 is not None and b10["price_fen"] == 10000, f"b10={b10}")
super_pk = admin_id(SUPER_PHONE)
check("超级管理员存在", super_pk is not None)
check("内置默认适用超管（2 条）", set(spec_ids_applicable_to(super_pk)) == {b5["id"], b10["id"]},
      f"specs={spec_ids_applicable_to(super_pk)}")

# 超管登录
super_c = app.test_client()
resp = login(super_c, SUPER_PHONE, SUPER_CODE)
check("超管登录成功", resp.status_code == 302)

# 超管规格管理页渲染（全量表 + 内置徽章/锁定 + 新建 + 适用管理入口）
s_html = super_c.get("/admin/specs").get_data(as_text=True)
check("超管规格页含内置 5斤装/10斤装", ("5斤装" in s_html) and ("10斤装" in s_html))
check("超管规格页含「内置」「锁定」徽章", ("内置" in s_html) and ("锁定" in s_html))
check("超管规格页含「新建规格」与配额提示", ("新建规格" in s_html) and ("还可创建" in s_html))

print("=" * 70)
print("创建普通管理员 A：自动同步内置适用")
print("=" * 70)

t = csrf(super_c)
super_c.post("/admin/admins", data={"_csrf_token": t, "phone": A_PHONE, "name": "管理员A", "password": A_CODE})
a_pk = admin_id(A_PHONE)
check("管理员 A 创建成功", a_pk is not None)
check("A 自动同步内置适用（2 条）", set(spec_ids_applicable_to(a_pk)) == {b5["id"], b10["id"]},
      f"specs={spec_ids_applicable_to(a_pk)}")

print("=" * 70)
print("超管建自定义规格：默认仅自己适用 + 配额")
print("=" * 70)

resp = create_spec_via(super_c, "翠香3斤", "30")
s1 = spec_by_name("翠香3斤")
check("超管创建「翠香3斤」成功", s1 is not None and s1["price_fen"] == 3000, f"s1={s1}")
check("自定义默认仅超管适用", applicable_of_spec(s1["id"]) == [super_pk], f"applied={applicable_of_spec(s1['id'])}")
resp = create_spec_via(super_c, "3斤2", "20")
s2 = spec_by_name("3斤2")
check("名称正则允许斤后数字「3斤2」", s2 is not None and s2["price_fen"] == 2000, f"s2={s2}")

with app.app_context():
    from app.services.spec_service import quota_left
    srv_super = db.session.get(Admin, super_pk)
    left = quota_left(srv_super)
check("超管配额提示：已建 2 个自定义，剩余 18", left == 18, f"left={left}")

print("=" * 70)
print("改价：自定义成功 / 内置拒绝（含超管）")
print("=" * 70)

resp = super_c.post(
    f"/admin/specs/{s1['id']}/price",
    data={"_csrf_token": csrf(super_c), "price_yuan": "35"},
)
check("超管改自定义「翠香3斤」35 元成功", spec_by_name("翠香3斤")["price_fen"] == 3500,
      f"price={spec_by_name('翠香3斤')['price_fen']}")

resp = super_c.post(
    f"/admin/specs/{b5['id']}/price",
    data={"_csrf_token": csrf(super_c), "price_yuan": "60"},
)
check("内置 5斤装 改价被拒（仍 5000）", builtin_spec("5斤装")["price_fen"] == 5000,
      f"price={builtin_spec('5斤装')['price_fen']}")

print("=" * 70)
print("下架 / 上架：下单页即时隐藏与恢复")
print("=" * 70)

resp = super_c.post(f"/admin/specs/{s1['id']}/toggle", data={"_csrf_token": csrf(super_c)})
check("下架自定义规格成功", spec_by_name("翠香3斤")["is_active"] is False)

root_c = app.test_client()  # 未访问任何短码 -> 归属超管
html = root_c.get("/order/new?phone=13600000001").get_data(as_text=True)
check("下架后超管下单页不显示「翠香3斤」", "翠香3斤" not in html)
check("下单页仍显示内置 5斤装", "5斤装" in html)

resp = super_c.post(f"/admin/specs/{s1['id']}/toggle", data={"_csrf_token": csrf(super_c)})
check("重新上架成功", spec_by_name("翠香3斤")["is_active"] is True)
html = root_c.get("/order/new?phone=13600000001").get_data(as_text=True)
check("上架后下单页恢复显示「翠香3斤」", "翠香3斤" in html)

resp = super_c.post(f"/admin/specs/{b5['id']}/toggle", data={"_csrf_token": csrf(super_c)})
check("内置 5斤装 不可下架（仍启用）", builtin_spec("5斤装")["is_active"] is True)

print("=" * 70)
print("适用勾选：超管增删 / 创建者不可移除 / 内置可删到 <2")
print("=" * 70)

# 自定义 s1：给 A 增加适用
super_c.post(
    f"/admin/specs/{s1['id']}/admins",
    data={"_csrf_token": csrf(super_c), "admin_ids": [str(a_pk)]},
)
check("超管给 A 开放自定义 s1", applicable_of_spec(s1["id"]) == sorted([super_pk, a_pk]),
      f"applied={applicable_of_spec(s1['id'])}")

# 仅提交 A（不带创建者超管）——创建者强制包含
super_c.post(
    f"/admin/specs/{s1['id']}/admins",
    data={"_csrf_token": csrf(super_c), "admin_ids": [str(a_pk)]},
)
check("创建者超管不可移除（服务端强制包含）", applicable_of_spec(s1["id"]) == sorted([super_pk, a_pk]),
      f"applied={applicable_of_spec(s1['id'])}")

# 内置 b5：清空适用（决策③：内置可删到 <2，含移除超管自己）
super_c.post(
    f"/admin/specs/{b5['id']}/admins",
    data={"_csrf_token": csrf(super_c), "admin_ids": []},
)
check("内置 5斤装 适用可清空（<2 无下限）", applicable_of_spec(b5["id"]) == [], f"applied={applicable_of_spec(b5['id'])}")

# 恢复 b5 适用为超管 + A
super_c.post(
    f"/admin/specs/{b5['id']}/admins",
    data={"_csrf_token": csrf(super_c), "admin_ids": [str(super_pk), str(a_pk)]},
)
check("内置 5斤装 适用恢复为 超管+A", applicable_of_spec(b5["id"]) == sorted([super_pk, a_pk]),
      f"applied={applicable_of_spec(b5['id'])}")

print("=" * 70)
print("普通管理员：登录 / 页面两区块 / 权限边界")
print("=" * 70)

# 超管再建一个不与任何帮助文案/内置重名的私有规格（不开放给 A）
create_spec_via(super_c, "徐香15斤", "55")
s_pv = spec_by_name("徐香15斤")

# A 首次登录强制改密
a_c = app.test_client()
resp = login(a_c, A_PHONE, A_CODE)
check("A 首次登录跳转改密", "/change-password" in (resp.headers.get("Location") or ""))
a_c.get("/admin/change-password")
a_c.post(
    "/admin/change-password",
    data={"_csrf_token": csrf(a_c), "current_password": "", "new_password": "newpass123", "confirm_password": "newpass123"},
)
a_c = app.test_client()
resp = login(a_c, A_PHONE, "newpass123")
check("A 新密码登录成功", resp.status_code == 302)

resp = a_c.get("/admin/specs")
a_html = resp.get_data(as_text=True)
check("A 规格页含「我创建的」区块", "我创建的" in a_html)
check("A 规格页含「我适用的」区块", "我适用的" in a_html)
check("A「我适用的」含内置 5斤装 + 默认适用", ("5斤装" in a_html) and ("默认适用" in a_html))
check("A「我适用的」含超管开放的 s1", ("翠香3斤" in a_html) and ("由超管开放" in a_html))
# A 看不到与自己无关的私有规格 徐香15斤（仅超管适用）
check("A 看不到私有规格「徐香15斤」", "徐香15斤" not in a_html)

# A 无权设置适用管理员（仅超管）
before_s1 = applicable_of_spec(s1["id"])
resp = a_c.post(f"/admin/specs/{s1['id']}/admins", data={"_csrf_token": csrf(a_c), "admin_ids": []})
check("A 设置适用管理员被拒（仅超管）", resp.status_code == 302 and applicable_of_spec(s1["id"]) == before_s1)

print("=" * 70)
print("A 创建规格 / 改价 / 越权保护")
print("=" * 70)

resp = create_spec_via(a_c, "A特供5斤", "45")
as1 = spec_by_name("A特供5斤")
check("A 创建「A特供5斤」成功 price=4500", as1 is not None and as1["price_fen"] == 4500, f"as1={as1}")
check("A 的规格默认仅 A 适用", applicable_of_spec(as1["id"]) == [a_pk], f"applied={applicable_of_spec(as1['id'])}")

a_c.post(f"/admin/specs/{as1['id']}/price", data={"_csrf_token": csrf(a_c), "price_yuan": "46"})
check("A 改自己规格价成功 46 元", spec_by_name("A特供5斤")["price_fen"] == 4600,
      f"price={spec_by_name('A特供5斤')['price_fen']}")

# A 改超管私有 s2 -> 拒绝
before_s2 = spec_by_name("3斤2")["price_fen"]
a_c.post(f"/admin/specs/{s2['id']}/price", data={"_csrf_token": csrf(a_c), "price_yuan": "88"})
check("A 改超管私有规格被拒（价格未变）", spec_by_name("3斤2")["price_fen"] == before_s2)

# A 删除/下架超管私有 s2 -> 拒绝
a_c.post(f"/admin/specs/{s2['id']}/toggle", data={"_csrf_token": csrf(a_c)})
check("A 下架超管规格被拒", spec_by_name("3斤2") is not None and spec_by_name("3斤2")["is_active"] is True)
a_c.post(f"/admin/specs/{s2['id']}/delete", data={"_csrf_token": csrf(a_c)})
check("A 删除超管规格被拒", spec_by_name("3斤2") is not None)

# A 对内置改价/下架/删除 -> 全部拒绝
b5_price = builtin_spec("5斤装")["price_fen"]
a_c.post(f"/admin/specs/{b5['id']}/price", data={"_csrf_token": csrf(a_c), "price_yuan": "66"})
a_c.post(f"/admin/specs/{b5['id']}/toggle", data={"_csrf_token": csrf(a_c)})
a_c.post(f"/admin/specs/{b5['id']}/delete", data={"_csrf_token": csrf(a_c)})
check("A 对内置改价被拒", builtin_spec("5斤装")["price_fen"] == b5_price)
check("A 对内置下架被拒", builtin_spec("5斤装")["is_active"] is True)
check("A 对内置删除被拒", builtin_spec("5斤装") is not None)

print("=" * 70)
print("下单按 spec_id 归属校验 + 快照落库")
print("=" * 70)

# 超管再建一个「徐香5斤」私有规格（不开放给 A）
create_spec_via(super_c, "徐香5斤", "55")
s3 = spec_by_name("徐香5斤")

# A 下单页：能看到适用的（内置 + s1 + as1），看不到私有 s3 / s2
a_cust = app.test_client()
a_cust.get(f"/2025")  # A 的专属短码
html = a_cust.get("/order/new?phone=13600110001").get_data(as_text=True)
check("A 下单页含内置 5斤装", "5斤装" in html)
check("A 下单页含适用自定义 s1", "翠香3斤" in html)
check("A 下单页含自己创建 as1", "A特供5斤" in html)
check("A 下单页不含他人私有规格 s3", "徐香5斤" not in html)
check("A 下单页不含他人私有规格 s2", "3斤2" not in html)

# A 尝试用私有 s3 下单 -> 拒绝，无订单
r = place_order(a_cust, "13600110002", s3["id"], ip="10.0.80.2")
with app.app_context():
    no_order = Order.query.filter_by(phone="13600110002").count() == 0
check("A 用他人私有规格下单被拒", r.status_code == 302 and no_order)

# A 用内置 b5 下单成功 -> 快照 spec_id/name/price + 归属 A
r = place_order(a_cust, "13600110003", b5["id"], quantity=2, ip="10.0.80.3")
o1 = order_owner_snapshot("13600110003")
check("A 下单成功（内置 5斤装）", o1 is not None and o1["spec_name"] == "5斤装")
check("A 订单快照 spec_id 落库", o1 is not None and o1["spec_id"] == b5["id"])
check("A 订单快照 spec_price=5000 & total=10000", o1 is not None and o1["spec_price"] == 5000 and o1["total_fee"] == 10000,
      f"snap={o1}")
check("A 订单归属 A", o1 is not None and o1["owner_admin_id"] == a_pk, f"owner={o1 and o1['owner_admin_id']}")

# A 用 s1（已按 35 元改价）下单 -> 快照 3500
r = place_order(a_cust, "13600110004", s1["id"], quantity=1, ip="10.0.80.4")
o2 = order_owner_snapshot("13600110004")
check("A 用 s1 下单快照 price=3500（改价后服务端计价）", o2 is not None and o2["spec_price"] == 3500 and o2["spec_id"] == s1["id"],
      f"snap={o2}")

print("=" * 70)
print("删除：自定义成功 / 内置拒绝")
print("=" * 70)

# 超管删除私有 s2（3斤2）
super_c.post(f"/admin/specs/{s2['id']}/delete", data={"_csrf_token": csrf(super_c)})
check("超管删除自定义「3斤2」成功", spec_by_name("3斤2") is None)
check("删除后适用关系已清除", applicable_of_spec(s2["id"]) == [])

# 超管删除内置 -> 拒绝
super_c.post(f"/admin/specs/{b5['id']}/delete", data={"_csrf_token": csrf(super_c)})
check("内置 5斤装 删除被拒", builtin_spec("5斤装") is not None)

print("=" * 70)
print("删除管理员：自定义规格移交超管 + 清除适用关系")
print("=" * 70)

# A 再建一个「A删除转移5斤」用于转移验证
create_spec_via(a_c, "A删除转移5斤", "60")
ad_spec = spec_by_name("A删除转移5斤")
check("A 创建待转移规格", ad_spec is not None and applicable_of_spec(ad_spec["id"]) == [a_pk],
      f"applied={applicable_of_spec(ad_spec['id']) if ad_spec else None}")

# 超管删除 A
super_c.post(f"/admin/admins/{a_pk}/delete", data={"_csrf_token": csrf(super_c)})
check("A 已删除", admin_id(A_PHONE) is None)

# A 的自定义规格全部移交超管
check("A 的 as1 移交超管", spec_by_name("A特供5斤")["created_by"] == super_pk,
      f"creator={spec_by_name('A特供5斤')['created_by']}")
check("A 的 ad_spec 移交超管", spec_by_name("A删除转移5斤")["created_by"] == super_pk)
check("移交后超管作为新创建者默认适用 as1", applicable_of_spec(as1["id"]) == [super_pk],
      f"applied={applicable_of_spec(as1['id'])}")
check("移交后超管作为新创建者默认适用 ad_spec", applicable_of_spec(ad_spec["id"]) == [super_pk],
      f"applied={applicable_of_spec(ad_spec['id'])}")
check("A 的全部 spec_admins 已清除（0 条）", admin_sa_count(a_pk) == 0, f"count={admin_sa_count(a_pk)}")
# A 名下订单（13600110003）转移给超管
o_after = order_owner_snapshot("13600110003")
check("A 名下订单转移给超管", o_after is not None and o_after["owner_admin_id"] == super_pk,
      f"owner={o_after and o_after['owner_admin_id']}")

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
