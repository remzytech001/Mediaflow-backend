"""
routes/admin.py
Admin can change: prices, site name, Paystack keys, limits, feature flags — all from UI.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional, Dict
from database import get_db, all_settings
from middleware.auth import admin_only
from utils.response import ok, err, paged

router = APIRouter()


# ── Stats ─────────────────────────────────────────────
@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db), _=Depends(admin_only)):
    async def cnt(q, p={}):
        return (await db.execute(text(q), p)).scalar() or 0

    return ok({
        "users": {
            "total":      await cnt("SELECT COUNT(*) FROM users"),
            "today":      await cnt("SELECT COUNT(*) FROM users WHERE DATE(created_at)=CURDATE()"),
            "pro":        await cnt("SELECT COUNT(*) FROM users WHERE plan='pro'"),
            "enterprise": await cnt("SELECT COUNT(*) FROM users WHERE plan='enterprise'"),
            "banned":     await cnt("SELECT COUNT(*) FROM users WHERE is_banned=1"),
        },
        "downloads": {
            "total": await cnt("SELECT COUNT(*) FROM downloads"),
            "today": await cnt("SELECT COUNT(*) FROM downloads WHERE DATE(created_at)=CURDATE()"),
        },
        "revenue": {
            "total_kobo":      await cnt("SELECT COALESCE(SUM(amount_kobo),0) FROM payments WHERE status='success'"),
            "this_month_kobo": await cnt("SELECT COALESCE(SUM(amount_kobo),0) FROM payments WHERE status='success' AND MONTH(paid_at)=MONTH(NOW()) AND YEAR(paid_at)=YEAR(NOW())"),
        },
        "files": {
            "total":       await cnt("SELECT COUNT(*) FROM files WHERE is_deleted=0"),
            "total_bytes": await cnt("SELECT COALESCE(SUM(size_bytes),0) FROM files WHERE is_deleted=0"),
        },
        "chart": await _chart(db),
        "top_platforms": await _top_plats(db),
        "recent_signups": await _recent_signups(db),
    })


async def _chart(db):
    r = await db.execute(text(
        "SELECT DATE(created_at) AS d, COUNT(*) AS c FROM downloads "
        "WHERE created_at>=DATE_SUB(NOW(),INTERVAL 30 DAY) GROUP BY d ORDER BY d"
    ))
    return [{"d": str(row.d), "c": row.c} for row in r]

async def _top_plats(db):
    r = await db.execute(text(
        "SELECT platform, COUNT(*) AS cnt FROM downloads GROUP BY platform ORDER BY cnt DESC LIMIT 8"
    ))
    return [dict(row._mapping) for row in r]

async def _recent_signups(db):
    r = await db.execute(text(
        "SELECT id,email,first_name,plan,created_at FROM users ORDER BY created_at DESC LIMIT 6"
    ))
    return [dict(row._mapping) for row in r]


# ── Users ─────────────────────────────────────────────
@router.get("/users")
async def list_users(page:int=1, per_page:int=20, search:str="", plan:str="",
    db: AsyncSession = Depends(get_db), _=Depends(admin_only)):
    where = "WHERE 1=1"
    params: dict = {}
    if search:
        where += " AND (email LIKE :s OR first_name LIKE :s OR last_name LIKE :s)"
        params["s"] = f"%{search}%"
    if plan in ("free","pro","enterprise"):
        where += " AND plan=:plan"; params["plan"] = plan
    total = (await db.execute(text(f"SELECT COUNT(*) FROM users {where}"), params)).scalar()
    offset = (page-1)*per_page
    rows = await db.execute(
        text(f"SELECT id,email,first_name,last_name,role,plan,is_banned,storage_used,download_count,created_at FROM users {where} ORDER BY created_at DESC LIMIT :l OFFSET :o"),
        {**params, "l": per_page, "o": offset}
    )
    return paged([dict(r._mapping) for r in rows], total, page, per_page)


class BanIn(BaseModel):
    user_id: int; ban: bool; reason: Optional[str] = ""

@router.post("/users/ban")
async def ban_user(body: BanIn, db: AsyncSession = Depends(get_db), _=Depends(admin_only)):
    await db.execute(
        text("UPDATE users SET is_banned=:b,ban_reason=:r WHERE id=:id"),
        {"b": int(body.ban), "r": body.reason or "", "id": body.user_id}
    )
    return ok(msg=f"User {'banned' if body.ban else 'unbanned'}.")


class PlanIn(BaseModel):
    user_id: int; plan: str; days: int = 30

@router.post("/users/set-plan")
async def set_plan(body: PlanIn, db: AsyncSession = Depends(get_db), _=Depends(admin_only)):
    if body.plan not in ("free","pro","enterprise"):
        return err("Invalid plan.")
    await db.execute(
        text("UPDATE users SET plan=:plan,plan_expires_at=DATE_ADD(NOW(),INTERVAL :days DAY) WHERE id=:id"),
        {"plan": body.plan, "days": body.days, "id": body.user_id}
    )
    return ok(msg="Plan updated.")


# ── Downloads ─────────────────────────────────────────
@router.get("/downloads")
async def list_downloads(page:int=1, per_page:int=20,
    db: AsyncSession = Depends(get_db), _=Depends(admin_only)):
    total = (await db.execute(text("SELECT COUNT(*) FROM downloads"))).scalar()
    offset = (page-1)*per_page
    rows = await db.execute(
        text("""
            SELECT d.id,d.platform,d.source_url,d.quality,d.format,d.status,d.created_at,
                   u.email,u.first_name
            FROM downloads d LEFT JOIN users u ON u.id=d.user_id
            ORDER BY d.created_at DESC LIMIT :l OFFSET :o
        """),
        {"l": per_page, "o": offset}
    )
    return paged([dict(r._mapping) for r in rows], total, page, per_page)


# ── Payments ──────────────────────────────────────────
@router.get("/payments")
async def list_payments(page:int=1, per_page:int=20,
    db: AsyncSession = Depends(get_db), _=Depends(admin_only)):
    total = (await db.execute(text("SELECT COUNT(*) FROM payments"))).scalar()
    offset = (page-1)*per_page
    rows = await db.execute(
        text("""
            SELECT p.id,p.paystack_ref,p.plan,p.amount_kobo,p.currency,p.status,p.channel,p.paid_at,
                   u.email,u.first_name
            FROM payments p LEFT JOIN users u ON u.id=p.user_id
            ORDER BY p.created_at DESC LIMIT :l OFFSET :o
        """),
        {"l": per_page, "o": offset}
    )
    return paged([dict(r._mapping) for r in rows], total, page, per_page)


# ══ SETTINGS CRUD — edit everything from admin panel ══

@router.get("/settings")
async def get_settings(db: AsyncSession = Depends(get_db), _=Depends(admin_only)):
    """Return all settings grouped."""
    rows = await db.execute(text(
        "SELECT `key`,`value`,`type`,`group`,`label`,`description` FROM settings ORDER BY `group`,`key`"
    ))
    groups: Dict[str, list] = {}
    for row in rows:
        g = row[3]
        if g not in groups:
            groups[g] = []
        groups[g].append({
            "key": row[0],
            "value": row[1] if row[2] != "password" else "••••••••",
            "type": row[2],
            "label": row[4],
            "description": row[5],
        })
    return ok(groups)


class SaveSettings(BaseModel):
    settings: Dict[str, str]  # {key: value}

@router.post("/settings")
async def save_settings(body: SaveSettings, db: AsyncSession = Depends(get_db), _=Depends(admin_only)):
    """Save one or multiple settings at once."""
    PROTECTED = {"paystack_secret_key", "paystack_public_key"}
    for key, value in body.settings.items():
        # Don't wipe password fields if sent as placeholder
        if key in PROTECTED and value in ("••••••••", ""):
            continue
        await db.execute(
            text("UPDATE settings SET `value`=:v WHERE `key`=:k"),
            {"v": value, "k": key}
        )
    return ok(msg="Settings saved.")


@router.get("/settings/public")
async def public_settings_endpoint(db: AsyncSession = Depends(get_db)):
    """Public settings (no auth needed — frontend fetches these on load)."""
    rows = await db.execute(text("SELECT `key`,`value` FROM settings WHERE is_public=1"))
    return ok({row[0]: row[1] for row in rows})
