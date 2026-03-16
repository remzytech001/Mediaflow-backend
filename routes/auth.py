from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel, field_validator
from passlib.context import CryptContext
from database import get_db, setting
from middleware.auth import make_jwt, hash_token, get_current_user
from utils.response import ok, created, err
import re, secrets

router = APIRouter()
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
GMAIL = re.compile(r'^[a-zA-Z0-9._%+\-]+@gmail\.com$', re.I)


class RegIn(BaseModel):
    first_name: str
    last_name:  str = ""
    email:      str
    password:   str

    @field_validator("email")
    @classmethod
    def gmail_only(cls, v):
        v = v.strip().lower()
        if not GMAIL.match(v):
            raise ValueError("Only @gmail.com addresses are accepted.")
        return v

    @field_validator("password")
    @classmethod
    def strong(cls, v):
        if len(v) < 8:
            raise ValueError("Minimum 8 characters.")
        if not re.search(r'[A-Z]', v):
            raise ValueError("Must include an uppercase letter.")
        if not re.search(r'[0-9]', v):
            raise ValueError("Must include a number.")
        return v

    @field_validator("first_name")
    @classmethod
    def nonempty(cls, v):
        if not v.strip():
            raise ValueError("First name required.")
        return v.strip()


class LoginIn(BaseModel):
    email:    str
    password: str
    remember: bool = False


# ── Register ──────────────────────────────────────────
@router.post("/register")
async def register(body: RegIn, request: Request, db: AsyncSession = Depends(get_db)):
    if await setting(db, "registration_open", "1") == "0":
        return err("Registrations are currently closed.", 403)

    exists = (await db.execute(text("SELECT id FROM users WHERE email=:e"), {"e": body.email})).fetchone()
    if exists:
        return err("An account with this email already exists.", 409)

    pw_hash = pwd.hash(body.password)
    r = await db.execute(
        text("INSERT INTO users (email,password_hash,first_name,last_name) VALUES(:e,:p,:f,:l)"),
        {"e": body.email, "p": pw_hash, "f": body.first_name, "l": body.last_name}
    )
    uid = r.lastrowid
    token = make_jwt(uid)
    await db.execute(
        text("INSERT INTO sessions(user_id,token_hash,ip_address,user_agent,expires_at) VALUES(:u,:h,:i,:a,DATE_ADD(NOW(),INTERVAL 30 DAY))"),
        {"u": uid, "h": hash_token(token), "i": request.client.host, "a": request.headers.get("user-agent","")}
    )
    return created({"token": token, "user": {"id": uid, "email": body.email,
        "first_name": body.first_name, "last_name": body.last_name, "role": "user", "plan": "free"}},
        "Account created! Welcome to MediaFlow Pro.")


# ── Login ─────────────────────────────────────────────
@router.post("/login")
async def login(body: LoginIn, request: Request, db: AsyncSession = Depends(get_db)):
    ip = request.client.host

    # Brute-force check
    rl = (await db.execute(
        text("SELECT requests FROM rate_limits WHERE identifier=:ip AND bucket='auth' AND window_start>DATE_SUB(NOW(),INTERVAL 15 MINUTE)"),
        {"ip": ip}
    )).fetchone()
    if rl and rl[0] >= 10:
        return err("Too many attempts. Try again in 15 minutes.", 429)

    u = (await db.execute(
        text("SELECT id,email,password_hash,first_name,last_name,role,plan,is_banned,ban_reason FROM users WHERE email=:e"),
        {"e": body.email.strip().lower()}
    )).fetchone()

    if not u or not pwd.verify(body.password, u.password_hash):
        await db.execute(
            text("INSERT INTO rate_limits(identifier,bucket,requests,window_start) VALUES(:ip,'auth',1,NOW()) ON DUPLICATE KEY UPDATE requests=requests+1"),
            {"ip": ip}
        )
        return err("Incorrect email or password.", 401)

    if u.is_banned:
        return err(f"Account suspended. {u.ban_reason or 'Contact support.'}", 403)

    await db.execute(text("DELETE FROM rate_limits WHERE identifier=:ip AND bucket='auth'"), {"ip": ip})

    token = make_jwt(u.id)
    days = 30 if body.remember else 1
    await db.execute(
        text("INSERT INTO sessions(user_id,token_hash,ip_address,user_agent,expires_at) VALUES(:u,:h,:i,:a,DATE_ADD(NOW(),INTERVAL :d DAY))"),
        {"u": u.id, "h": hash_token(token), "i": ip, "a": request.headers.get("user-agent",""), "d": days}
    )
    await db.execute(text("UPDATE users SET last_login_at=NOW() WHERE id=:id"), {"id": u.id})

    return ok({"token": token, "user": {"id": u.id, "email": u.email,
        "first_name": u.first_name, "last_name": u.last_name, "role": u.role, "plan": u.plan}})


# ── Logout ────────────────────────────────────────────
@router.post("/logout")
async def logout(current_user=Depends(get_current_user)):
    return ok(msg="Signed out.")


# ── Me ────────────────────────────────────────────────
@router.get("/me")
async def me(db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    r = await db.execute(
        text("SELECT id,uuid,email,first_name,last_name,role,plan,plan_expires_at,storage_used,download_count,created_at FROM users WHERE id=:id"),
        {"id": current_user["id"]}
    )
    user = dict(r.fetchone()._mapping)
    user["downloads_today"] = (await db.execute(
        text("SELECT COUNT(*) FROM downloads WHERE user_id=:id AND DATE(created_at)=CURDATE()"),
        {"id": user["id"]}
    )).scalar()
    user["api_key_count"] = (await db.execute(
        text("SELECT COUNT(*) FROM api_keys WHERE user_id=:id AND is_active=1"),
        {"id": user["id"]}
    )).scalar()
    return ok(user)
