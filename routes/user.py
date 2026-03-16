from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from database import get_db
from middleware.auth import get_current_user, hash_token
from utils.response import ok, err
from passlib.context import CryptContext
import secrets

router = APIRouter()
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


class UpdateProfile(BaseModel):
    first_name: str
    last_name:  str = ""


class ChangePassword(BaseModel):
    current_password: str
    new_password:     str


@router.get("/profile")
async def profile(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    r = await db.execute(
        text("SELECT id,email,first_name,last_name,role,plan,plan_expires_at,storage_used,download_count,created_at FROM users WHERE id=:id"),
        {"id": user["id"]}
    )
    return ok(dict(r.fetchone()._mapping))


@router.patch("/profile")
async def update_profile(body: UpdateProfile, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    await db.execute(
        text("UPDATE users SET first_name=:f,last_name=:l WHERE id=:id"),
        {"f": body.first_name.strip(), "l": body.last_name.strip(), "id": user["id"]}
    )
    return ok(msg="Profile updated.")


@router.post("/change-password")
async def change_password(body: ChangePassword, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    r = await db.execute(text("SELECT password_hash FROM users WHERE id=:id"), {"id": user["id"]})
    row = r.fetchone()
    if not pwd.verify(body.current_password, row.password_hash):
        return err("Current password is incorrect.", 400)
    if len(body.new_password) < 8:
        return err("New password must be at least 8 characters.")
    await db.execute(
        text("UPDATE users SET password_hash=:h WHERE id=:id"),
        {"h": pwd.hash(body.new_password), "id": user["id"]}
    )
    return ok(msg="Password changed successfully.")


# ── API Keys ──────────────────────────────────────────
@router.get("/api-keys")
async def list_keys(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    rows = await db.execute(
        text("SELECT id,name,key_preview,is_active,calls_total,last_used_at,created_at FROM api_keys WHERE user_id=:id ORDER BY created_at DESC"),
        {"id": user["id"]}
    )
    return ok([dict(r._mapping) for r in rows])


@router.post("/api-keys")
async def create_key(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    raw = "mfp_" + secrets.token_hex(24)
    preview = raw[:8] + "..." + raw[-4:]
    await db.execute(
        text("INSERT INTO api_keys(user_id,key_hash,key_preview) VALUES(:u,:h,:p)"),
        {"u": user["id"], "h": hash_token(raw), "p": preview}
    )
    return ok({"key": raw, "preview": preview}, "API key created. Copy it now — it won't be shown again.")


@router.delete("/api-keys/{key_id}")
async def delete_key(key_id: int, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    await db.execute(
        text("UPDATE api_keys SET is_active=0 WHERE id=:id AND user_id=:uid"),
        {"id": key_id, "uid": user["id"]}
    )
    return ok(msg="API key revoked.")
