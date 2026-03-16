from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from jose import JWTError, jwt
from datetime import datetime, timezone, timedelta
from database import get_db
from config import settings
import hashlib, secrets

bearer = HTTPBearer(auto_error=False)
api_key_hdr = APIKeyHeader(name="X-API-Key", auto_error=False)


def hash_token(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def make_jwt(user_id: int) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=settings.JWT_EXPIRE_DAYS)
    return jwt.encode({"sub": str(user_id), "exp": exp}, settings.JWT_SECRET, settings.JWT_ALGORITHM)


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    cred: HTTPAuthorizationCredentials = Security(bearer),
    api_key: str = Security(api_key_hdr),
):
    if cred:
        return await _from_jwt(cred.credentials, db)
    if api_key:
        return await _from_api_key(api_key, db)
    raise HTTPException(401, "Authentication required.")


async def optional_user(
    db: AsyncSession = Depends(get_db),
    cred: HTTPAuthorizationCredentials = Security(bearer),
    api_key: str = Security(api_key_hdr),
):
    try:
        return await get_current_user(db, cred, api_key)
    except HTTPException:
        return None


async def admin_only(user=Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Admin access required.")
    return user


async def _from_jwt(token: str, db: AsyncSession) -> dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        uid = payload.get("sub")
    except JWTError:
        raise HTTPException(401, "Invalid or expired session. Please sign in again.")

    r = await db.execute(
        text("""
            SELECT u.id,u.email,u.first_name,u.last_name,u.role,u.plan,
                   u.plan_expires_at,u.is_banned,u.storage_used,u.download_count
            FROM sessions s JOIN users u ON u.id=s.user_id
            WHERE s.token_hash=:h AND s.expires_at>NOW() AND u.is_banned=0 AND u.id=:uid
        """),
        {"h": hash_token(token), "uid": int(uid)}
    )
    row = r.fetchone()
    if not row:
        raise HTTPException(401, "Session expired. Please sign in again.")

    user = dict(row._mapping)
    # Auto-downgrade expired plans
    if user["plan_expires_at"] and user["plan_expires_at"] < datetime.now():
        await db.execute(text("UPDATE users SET plan='free',plan_expires_at=NULL WHERE id=:id"), {"id": user["id"]})
        user["plan"] = "free"
    return user


async def _from_api_key(raw: str, db: AsyncSession) -> dict:
    r = await db.execute(
        text("""
            SELECT u.id,u.email,u.first_name,u.last_name,u.role,u.plan,u.is_banned,ak.id AS kid
            FROM api_keys ak JOIN users u ON u.id=ak.user_id
            WHERE ak.key_hash=:h AND ak.is_active=1 AND u.is_banned=0
        """),
        {"h": hash_token(raw)}
    )
    row = r.fetchone()
    if not row:
        raise HTTPException(401, "Invalid API key.")
    await db.execute(text("UPDATE api_keys SET calls_total=calls_total+1,last_used_at=NOW() WHERE id=:id"), {"id": row.kid})
    return dict(row._mapping)
