# -*- coding: utf-8 -*-
"""规格与价格管理服务（规格 × 适用管理员）。

权限模型（docs/12 §4）：
- 内置规格（5斤装/10斤装）：价格/名称完全锁定（任何人含超管不可改）、不可删除、不可下架；
  超管可任意增删其适用管理员（不设下限，默认 seed 保证每个启用管理员至少 2 个）。
- 自定义规格：创建者天然适用自己的规格且不可被移除；超管可管理任意规格；
  普通管理员只能管理自己创建的规格。
- 创建配额（不含内置 2 个）：超管名下自定义 ≤ 20、普通管理员名下 ≤ 10；
  适用上限（含内置）：任一管理员适用的规格合计 ≤ 20。

校验口径（决策锁定）：
- 名称正则 ^[\\u4e00-\\u9fa5a-zA-Z0-9]*\\d+斤[\\u4e00-\\u9fa5a-zA-Z0-9]*$（允许斤后数字如 3斤2）；
  另校验显示宽度（汉字/全角 2 单位、半角 1 单位）≤ 20（≈10 汉字）；长度 ≤ 50 字符。
- 价格 0 < 价 ≤ 9999 元，两位小数粒度，内部一律存分。
"""
import re
from decimal import Decimal, InvalidOperation

from flask import current_app

from ..extensions import db
from ..models.admin import Admin
from ..models.spec import Spec, SpecAdmin

# 内置规格（名称 + 单价分）；定位内置只用 is_builtin + name 常量，绝不硬编码 id
BUILTIN_SPECS = (("5斤装", 5000), ("10斤装", 10000))
# 创建配额（自定义规格，不含内置 2 个）
QUOTA_SUPER = 20
QUOTA_ADMIN = 10
# 任一管理员「适用」规格合计上限（含内置）
MAX_APPLICABLE = 20
# 价格上限（元）
MAX_PRICE_YUAN = Decimal("9999")

_SPEC_NAME_RE = re.compile(
    r"^[\u4e00-\u9fa5a-zA-Z0-9]*\d+斤[\u4e00-\u9fa5a-zA-Z0-9]*$"
)
_MAX_NAME_WIDTH = 20
_MAX_NAME_LEN = 50


def _display_width(name: str) -> int:
    """显示宽度：汉字/全角按 2 单位，半角按 1 单位。"""
    return sum(2 if not ch.isascii() else 1 for ch in name)


def _find_builtin(name: str):
    """按 内置标志 + 名称 定位内置规格（绝不硬编码 id=1/2）。"""
    return Spec.query.filter_by(is_builtin=True, name=name).first()


def validate_spec_name(name: str) -> str:
    """校验规格名称（决策②锁定口径），返回去空格后的名称。

    规则：仅中英文/数字，须含「数字+斤」段（斤后可带数字，如 3斤2）；
    显示宽度 ≤ 20（≈10 汉字）；字符串长度 ≤ 50。
    非法抛 ValueError（路由 flash）。
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("请输入规格名称")
    if len(name) > _MAX_NAME_LEN:
        raise ValueError(f"规格名称过长（最多 {_MAX_NAME_LEN} 个字符）")
    if not _SPEC_NAME_RE.match(name):
        raise ValueError("规格名称只能包含中英文与数字，且必须含「数字+斤」段（如 5斤装、翠香3斤）")
    width = _display_width(name)
    if width > _MAX_NAME_WIDTH:
        raise ValueError("规格名称过长（显示宽度不超过 10 个汉字）")
    return name


def parse_price_yuan_to_fen(price_yuan) -> int:
    """价格（元）-> 分。0 < 价 ≤ 9999，最多两位小数；非法抛 ValueError。"""
    if isinstance(price_yuan, Decimal):
        text = str(price_yuan)
    else:
        text = str(price_yuan or "").strip()
    if not text:
        raise ValueError("请输入价格")
    try:
        val = Decimal(text)
    except (InvalidOperation, ValueError):
        raise ValueError("价格格式不正确") from None
    if not val.is_finite():
        raise ValueError("价格格式不正确")
    if val <= 0:
        raise ValueError("价格需大于 0 元")
    if val > MAX_PRICE_YUAN:
        raise ValueError(f"价格不能超过 {MAX_PRICE_YUAN} 元")
    if val != val.quantize(Decimal("0.01")):
        raise ValueError("价格最多两位小数")
    return int((val * 100).to_integral_value())


def _quota_of(actor) -> int:
    """该管理员的创建配额。"""
    return QUOTA_SUPER if actor.is_super else QUOTA_ADMIN


def quota_left(actor) -> int:
    """还可创建自定义规格数（不含内置）。"""
    used = Spec.query.filter_by(
        created_by_admin_id=actor.id, is_builtin=False
    ).count()
    return max(_quota_of(actor) - used, 0)


def get_applicable_specs(admin_id, active_only: bool = True) -> list:
    """某管理员适用（且启用）的规格列表；下单页专用。

    注意：admin_id 可为 None（无归属兜底），此时返回空列表。
    """
    if admin_id is None:
        return []
    q = (
        Spec.query.join(SpecAdmin, Spec.id == SpecAdmin.spec_id)
        .filter(SpecAdmin.admin_id == admin_id)
    )
    if active_only:
        q = q.filter(Spec.is_active.is_(True))
    return q.order_by(Spec.is_builtin.desc(), Spec.id.asc()).all()


def resolve_spec_for_owner(spec_id, owner_admin_id):
    """校验「spec_id 属于 owner 适用范围且启用」，返回 Spec；否则 ValueError。

    服务端计价唯一入口：下单必须以本函数返回的 spec.price_fen 为准。
    """
    if not isinstance(spec_id, int) or spec_id <= 0:
        raise ValueError("请选择规格")
    spec = db.session.get(Spec, spec_id)
    if spec is None or not spec.is_active:
        raise ValueError("规格不存在或已下架，请刷新页面后重试")
    if owner_admin_id is None:
        raise ValueError("未匹配到责任管理员，请刷新页面后重试")
    row = SpecAdmin.query.filter_by(
        spec_id=spec.id, admin_id=owner_admin_id
    ).first()
    if row is None:
        raise ValueError("所选规格不适用当前下单归属，请刷新页面后重试")
    return spec


def list_specs_for_page(actor) -> dict:
    """按角色返回规格管理页数据。

    - 超管：全量规格 + 每规格适用管理员 + 全部管理员（适用勾选面板用）。
    - 普通管理员：「我创建的」（含下架，可管理）与「我适用的」（启用，只读）。
    """
    if actor.is_super:
        specs = Spec.query.order_by(Spec.is_builtin.desc(), Spec.id.asc()).all()
        admins = Admin.query.order_by(Admin.id.asc()).all()
        applicable_map = {}
        for spec_id, admin_id in db.session.query(
            SpecAdmin.spec_id, SpecAdmin.admin_id
        ).all():
            applicable_map.setdefault(spec_id, []).append(admin_id)

        rows = []
        for spec in specs:
            applied = sorted(applicable_map.get(spec.id, []))
            rows.append(
                {
                    "id": spec.id,
                    "name": spec.name,
                    "is_builtin": spec.is_builtin,
                    "is_active": spec.is_active,
                    "price_fen": spec.price_fen,
                    "creator_phone": spec.creator_phone,
                    "creator_id": spec.created_by_admin_id,
                    "applied": applied,
                    "applied_count": len(applied),
                    # 适用面板中锁定不可取消的创建者（仅自定义规格；内置全部可增删）
                    "locked": None if spec.is_builtin else spec.created_by_admin_id,
                }
            )
        return {
            "rows": rows,
            "admins": [
                {
                    "id": a.id,
                    "phone": a.phone,
                    "name": a.name,
                    "is_active": a.is_active,
                }
                for a in admins
            ],
            "quota_left": quota_left(actor),
            "quota_total": QUOTA_SUPER,
        }

    # ---- 普通管理员 ----
    created = (
        Spec.query.filter_by(created_by_admin_id=actor.id, is_builtin=False)
        .order_by(Spec.id.desc())
        .all()
    )
    # 我适用的 = 适用于我且启用；排除自己创建的（已在「我创建的」区块，避免重复）
    applicable = (
        Spec.query.join(SpecAdmin, Spec.id == SpecAdmin.spec_id)
        .filter(
            SpecAdmin.admin_id == actor.id,
            Spec.is_active.is_(True),
            db.or_(
                Spec.is_builtin.is_(True),
                Spec.created_by_admin_id != actor.id,
            ),
        )
        .order_by(Spec.is_builtin.desc(), Spec.id.asc())
        .all()
    )
    return {
        "created_specs": created,
        "applicable_specs": applicable,
        "quota_left": quota_left(actor),
        "quota_total": QUOTA_ADMIN,
    }


def create_spec(actor, name, price_yuan) -> Spec:
    """创建自定义规格（校验名称/价格/创建配额），默认仅创建者自己适用。"""
    name = validate_spec_name(name)
    price_fen = parse_price_yuan_to_fen(price_yuan)

    used = Spec.query.filter_by(
        created_by_admin_id=actor.id, is_builtin=False
    ).count()
    quota = _quota_of(actor)
    if used >= quota:
        raise ValueError(
            f"创建配额已用完（最多 {quota} 个自定义规格，不含内置），请先删除或联系超级管理员"
        )

    spec = Spec(
        name=name,
        price_fen=price_fen,
        is_builtin=False,
        is_active=True,
        created_by_admin_id=actor.id,
    )
    db.session.add(spec)
    db.session.flush()
    # 创建者默认适用自己（不可移除）
    db.session.add(SpecAdmin(spec_id=spec.id, admin_id=actor.id))
    db.session.commit()
    return spec


def change_price(actor, spec, price_yuan) -> Spec:
    """改价：内置一律拒绝（含超管）；超管可改任意自定义；普通仅自己的。"""
    if spec.is_builtin:
        raise ValueError("内置规格价格已完全锁定，不可修改")
    if not actor.is_super and spec.created_by_admin_id != actor.id:
        raise ValueError("无权修改该规格价格")
    price_fen = parse_price_yuan_to_fen(price_yuan)
    if spec.price_fen == price_fen:
        return spec
    spec.price_fen = price_fen
    db.session.commit()
    return spec


def toggle_active(actor, spec) -> bool:
    """下架/上架自定义规格：内置不可下架（恒启用）；超管任意自定义；普通仅自己的。
    下架保留适用关系。返回新的启用状态。"""
    if spec.is_builtin:
        raise ValueError("内置规格不可下架")
    if not actor.is_super and spec.created_by_admin_id != actor.id:
        raise ValueError("无权操作该规格")
    spec.is_active = not spec.is_active
    db.session.commit()
    return spec.is_active


def delete_spec(actor, spec) -> None:
    """删除规格：内置不可删；超管任意自定义；普通仅自己的。
    先删 spec_admins 适用关系，再删规格（历史订单快照不受影响）。"""
    if spec.is_builtin:
        raise ValueError("内置规格不可删除")
    if not actor.is_super and spec.created_by_admin_id != actor.id:
        raise ValueError("无权删除该规格")
    SpecAdmin.query.filter_by(spec_id=spec.id).delete(synchronize_session=False)
    db.session.delete(spec)
    db.session.commit()


def set_applicable_admins(actor, spec, admin_ids) -> None:
    """超管设置规格的适用管理员集合（diff 增删）。

    规则：
      - 仅超管可操作；
      - 自定义规格：创建者强制包含（UI 置灰锁定，服务端也强制补回）；
      - 内置规格：可增删任意管理员（决策③：不设 2 人下限，可删到 <2）；
      - 任一涉及管理员「适用」总数（含本规格）≤ 20。
    """
    if not actor.is_super:
        raise ValueError("仅超级管理员可设置适用管理员")

    try:
        requested = {int(x) for x in (admin_ids or [])}
    except (TypeError, ValueError):
        raise ValueError("适用管理员参数不正确") from None

    # 过滤真实存在的管理员
    if requested:
        valid_ids = {
            a.id
            for a in Admin.query.filter(Admin.id.in_(list(requested))).all()
        }
    else:
        valid_ids = set()
    selected = set(valid_ids)

    # 自定义规格创建者强制包含
    if not spec.is_builtin and spec.created_by_admin_id is not None:
        selected.add(spec.created_by_admin_id)

    current = {
        sa.admin_id
        for sa in SpecAdmin.query.filter_by(spec_id=spec.id).all()
    }

    # 涉及管理员（新增或移除）逐个校验适用总数 ≤ MAX_APPLICABLE
    affected = selected | current
    if affected:
        counts = dict(
            db.session.query(SpecAdmin.admin_id, db.func.count(SpecAdmin.spec_id))
            .filter(SpecAdmin.admin_id.in_(list(affected)))
            .group_by(SpecAdmin.admin_id)
            .all()
        )
        admin_by_id = {
            a.id: a for a in Admin.query.filter(Admin.id.in_(list(affected))).all()
        }
        for admin_id in affected:
            new_count = counts.get(admin_id, 0)
            if admin_id in current and admin_id not in selected:
                new_count -= 1
            elif admin_id not in current and admin_id in selected:
                new_count += 1
            if new_count > MAX_APPLICABLE:
                phone = admin_by_id.get(admin_id).phone if admin_id in admin_by_id else admin_id
                raise ValueError(
                    f"管理员 {phone} 适用的规格已达 {MAX_APPLICABLE} 个上限，请先减少其他规格"
                )

    for admin_id in current - selected:
        row = SpecAdmin.query.filter_by(
            spec_id=spec.id, admin_id=admin_id
        ).first()
        if row is not None:
            db.session.delete(row)
    for admin_id in selected - current:
        db.session.add(SpecAdmin(spec_id=spec.id, admin_id=admin_id))
    db.session.commit()


def sync_builtin_for_admin(admin) -> None:
    """新管理员创建后同步内置默认适用（幂等；可反复调用）。"""
    builtins = Spec.query.filter_by(is_builtin=True).all()
    if not builtins:
        return
    existing = {
        sa.spec_id
        for sa in SpecAdmin.query.filter_by(admin_id=admin.id).all()
    }
    added = False
    for spec in builtins:
        if spec.id not in existing:
            db.session.add(SpecAdmin(spec_id=spec.id, admin_id=admin.id))
            added = True
    if added:
        db.session.commit()


def on_admin_deleted(admin, super_admin=None) -> None:
    """删除管理员联动（决策①）：其自定义规格移交超管，并清除其全部 spec_admins。

    说明：不在此函数 commit，由调用方（admin_service.delete_admin）在同一事务内
    一并提交，保证「订单转移 + 规格移交 + 删除管理员」原子性。
    """
    if super_admin is None:
        super_admin = Admin.query.filter_by(role=Admin.ROLE_SUPER).first()

    own_specs = (
        Spec.query.filter(
            Spec.created_by_admin_id == admin.id,
            Spec.is_builtin.is_(False),
        ).all()
    )
    target_id = super_admin.id if super_admin is not None else None

    if own_specs:
        if super_admin is not None and super_admin.id != admin.id:
            existing_super = {
                sa.spec_id
                for sa in SpecAdmin.query.filter_by(
                    admin_id=super_admin.id
                ).all()
            }
            for spec in own_specs:
                spec.created_by_admin_id = super_admin.id
                # 保证超管作为新创建者默认适用（创建者不可移除的不变量）
                if spec.id not in existing_super:
                    db.session.add(
                        SpecAdmin(spec_id=spec.id, admin_id=super_admin.id)
                    )
                    existing_super.add(spec.id)
        else:
            for spec in own_specs:
                spec.created_by_admin_id = target_id

    # 清除被删除管理员全部 spec_admins 适用关系（与订单转移一致）
    SpecAdmin.query.filter_by(admin_id=admin.id).delete(
        synchronize_session=False
    )


def ensure_spec_defaults() -> None:
    """启动 seed 与自愈（幂等，可反复运行）。

    内置 5斤装/10斤装：
      - 缺则创建（created_by = 超管、is_builtin=True、启用）；
      - 存在则回正 price_fen / created_by=超管 / is_active=True；
      - 为所有启用管理员补内置默认适用关系（含超管）。
    无超管时跳过（迁移/种子顺序安全：超管由 _seed 先创建）。
    """
    super_admin = Admin.query.filter_by(role=Admin.ROLE_SUPER).first()
    if super_admin is None:
        current_app.logger.warning("无超级管理员，跳过内置规格初始化")
        return

    changed = False
    for name, price_fen in BUILTIN_SPECS:
        spec = _find_builtin(name)
        if spec is None:
            spec = Spec(
                name=name,
                price_fen=price_fen,
                is_builtin=True,
                is_active=True,
                created_by_admin_id=super_admin.id,
            )
            db.session.add(spec)
            changed = True
        else:
            if (
                spec.price_fen != price_fen
                or spec.created_by_admin_id != super_admin.id
                or not spec.is_builtin
                or not spec.is_active
            ):
                spec.price_fen = price_fen
                spec.created_by_admin_id = super_admin.id
                spec.is_builtin = True
                spec.is_active = True
                changed = True
    db.session.flush()  # 保证新规格拿到 id

    builtin_ids = [
        s.id for s in Spec.query.filter_by(is_builtin=True).all()
    ]
    if builtin_ids:
        existing = set(
            db.session.query(SpecAdmin.spec_id, SpecAdmin.admin_id)
            .filter(SpecAdmin.spec_id.in_(builtin_ids))
            .all()
        )
        active_admins = Admin.query.filter_by(is_active=True).all()
        for admin in active_admins:
            for sid in builtin_ids:
                if (sid, admin.id) not in existing:
                    db.session.add(SpecAdmin(spec_id=sid, admin_id=admin.id))
                    existing.add((sid, admin.id))
                    changed = True

    db.session.commit()
    if changed:
        current_app.logger.info("内置规格 seed 已完成（5斤装/10斤装 + 管理员适用）")
