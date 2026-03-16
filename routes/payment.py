from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from database import get_db, setting
from middleware.auth import get_current_user
from utils.response import ok, err
import httpx, secrets

router = APIRouter()

PLAN_KEYS = {
    "pro_monthly":        ("pro",        "monthly",  "price_pro_monthly",  31),
    "pro_annual":         ("pro",        "annual",   "price_pro_annual",   366),
    "enterprise_monthly": ("enterprise", "monthly",  "price_ent_monthly",  31),
    "enterprise_annual":  ("enterprise", "annual",   "price_ent_annual",   366),
}


async def plan_cfg(db, key):
    if key not in PLAN_KEYS:
        return None
    tier, billing, price_key, days = PLAN_KEYS[key]
    amount = int(await setting(db, price_key, "0"))
    currency = await setting(db, "currency", "NGN")
    return {"tier": tier, "billing": billing, "amount_kobo": amount * 100,
            "currency": currency, "days": days, "label": key.replace("_"," ").title()}


class InitIn(BaseModel):
    plan: str

class VerifyIn(BaseModel):
    reference: str


@router.post("/initialize")
async def initialize(body: InitIn, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    plan = await plan_cfg(db, body.plan)
    if not plan:
        return err("Invalid plan.")

    sk = await setting(db, "paystack_secret_key", "")
    pk = await setting(db, "paystack_public_key", "")
    site_url = await setting(db, "site_url", "https://yourdomain.cpanelfree.com")

    if not sk or "REPLACE" in sk:
        return err("Payments not configured yet. Contact admin.", 503)

    ref = "MFP-" + secrets.token_hex(8).upper()
    await db.execute(
        text("INSERT INTO payments(user_id,paystack_ref,plan,amount_kobo,currency) VALUES(:u,:r,:p,:a,:c)"),
        {"u": user["id"], "r": ref, "p": body.plan, "a": plan["amount_kobo"], "c": plan["currency"]}
    )

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.paystack.co/transaction/initialize",
                json={"email": user["email"], "amount": plan["amount_kobo"],
                      "reference": ref, "currency": plan["currency"],
                      "callback_url": f"{site_url}/pages/payment-success.php?ref={ref}",
                      "metadata": {"user_id": user["id"], "plan": body.plan, "cancel_action": "close"}},
                headers={"Authorization": f"Bearer {sk}"},
            )
            data = resp.json()
    except Exception as e:
        return err(f"Payment gateway error: {str(e)}", 502)

    if not data.get("status"):
        return err(data.get("message", "Paystack error."), 502)

    return ok({"reference": ref, "access_code": data["data"]["access_code"],
               "public_key": pk, "amount": plan["amount_kobo"],
               "currency": plan["currency"], "email": user["email"],
               "plan_label": plan["label"]})


@router.post("/verify")
async def verify(body: VerifyIn, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    p = (await db.execute(
        text("SELECT * FROM payments WHERE paystack_ref=:r AND user_id=:u"),
        {"r": body.reference, "u": user["id"]}
    )).fetchone()
    if not p:
        return err("Payment not found.", 404)
    p = dict(p._mapping)
    if p["status"] == "success":
        return ok({"plan": p["plan"].split("_")[0]}, "Plan already active.")

    sk = await setting(db, "paystack_secret_key", "")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://api.paystack.co/transaction/verify/{body.reference}",
                headers={"Authorization": f"Bearer {sk}"},
            )
            ps = resp.json()
    except Exception as e:
        return err(f"Could not verify: {str(e)}", 502)

    ps_data = ps.get("data", {})
    if not ps.get("status") or ps_data.get("status") != "success":
        return err("Payment not confirmed by Paystack.", 402)
    if int(ps_data.get("amount", 0)) != p["amount_kobo"]:
        return err("Amount mismatch.", 402)

    plan = await plan_cfg(db, p["plan"])
    if not plan:
        return err("Unknown plan.", 500)

    await db.execute(
        text("UPDATE payments SET status='success',channel=:ch,paid_at=NOW() WHERE id=:id"),
        {"ch": ps_data.get("channel"), "id": p["id"]}
    )
    await db.execute(
        text("UPDATE users SET plan=:plan,plan_expires_at=DATE_ADD(NOW(),INTERVAL :days DAY) WHERE id=:id"),
        {"plan": plan["tier"], "days": plan["days"], "id": user["id"]}
    )

    return ok({"plan": plan["tier"], "billing": plan["billing"]},
              f"🎉 {plan['label']} activated!")
