# backend/app/routers/admin_mail.py

import os
import requests
from typing import Optional, List
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.services.supabase_client import supabase
from app.services.email_service import send_email

router = APIRouter(prefix="/api/admin/mail", tags=["admin-mail"])

SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    # supabase_client.py đã raise rồi, nhưng thêm cho rõ
    pass


# -------------------------
# Auth helpers (Supabase JWT)
# -------------------------
def _get_user_from_token(access_token: str) -> dict:
    """
    Validate Supabase access token by calling Supabase Auth endpoint.
    Returns user dict if valid.
    """
    if not access_token:
        raise HTTPException(status_code=401, detail="Missing access token")

    url = f"{SUPABASE_URL}/auth/v1/user"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
    }
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid token")
    return r.json()


def _require_admin(authorization: Optional[str]) -> dict:
    """
    Requires: Authorization: Bearer <access_token>
    Checks Supabase user + admins table.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization Bearer token")

    token = authorization.split(" ", 1)[1].strip()
    user = _get_user_from_token(token)
    uid = user.get("id")
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid token user")

    # check admin
    res = supabase.table("admins").select("user_id").eq("user_id", uid).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=403, detail="Admin access required")

    return {"user": user, "uid": uid}


# -------------------------
# Models
# -------------------------
class SendEmailPayload(BaseModel):
    # send single (optional)
    to_email: Optional[str] = None

    # send all verified/active (optional)
    send_all: bool = False

    subject: str
    message_html: str

    # optional image URL
    image_url: Optional[str] = None


class DeleteSubscriberPayload(BaseModel):
    email: str


# -------------------------
# Endpoints
# -------------------------

@router.get("/subscribers")
def list_subscribers(authorization: Optional[str] = Header(default=None)):
    _require_admin(authorization)

    # list distinct emails from subscriptions
    rows = (
        supabase.table("deal_alert_subscriptions")
        .select("email,email_norm,verified,is_active,created_at,keyword")
        .eq("is_active", True)
        .order("created_at", desc=True)
        .limit(2000)
        .execute()
        .data
        or []
    )

    # build map by email
    agg = {}
    for r in rows:
        em = (r.get("email_norm") or r.get("email") or "").strip().lower()
        if not em:
            continue
        if em not in agg:
            agg[em] = {
                "email": r.get("email") or em,
                "email_norm": em,
                "verified_any": bool(r.get("verified")),
                "keywords": set(),
                "created_at": r.get("created_at"),
            }
        kw = (r.get("keyword") or "").strip()
        if kw:
            agg[em]["keywords"].add(kw)
        # keep newest created_at
        if r.get("created_at") and (agg[em]["created_at"] is None or r["created_at"] > agg[em]["created_at"]):
            agg[em]["created_at"] = r["created_at"]
        # verified flag
        if r.get("verified"):
            agg[em]["verified_any"] = True

    items = []
    for em, v in agg.items():
        items.append({
            "email": v["email"],
            "email_norm": v["email_norm"],
            "verified": v["verified_any"],
            "keywords": sorted(list(v["keywords"]))[:50],
            "created_at": v["created_at"],
        })

    # sort newest
    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)

    return {"ok": True, "count": len(items), "items": items}


@router.post("/subscribers/delete")
def delete_subscriber(payload: DeleteSubscriberPayload, authorization: Optional[str] = Header(default=None)):
    _require_admin(authorization)

    raw_email = (payload.email or "").strip()
    email = (raw_email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email")

    # Delete ALL subscription rows for this email (all keywords, any status)
    rows1 = (
        supabase.table("deal_alert_subscriptions")
        .select("id")
        .eq("email_norm", email)
        .limit(5000)
        .execute()
        .data
        or []
    )
    rows2 = []
    if raw_email and raw_email != email:
        rows2 = (
            supabase.table("deal_alert_subscriptions")
            .select("id")
            .eq("email", raw_email)
            .limit(5000)
            .execute()
            .data
            or []
        )

    ids = {r.get("id") for r in (rows1 + rows2) if r.get("id")}
    if not ids:
        return {"ok": True, "deleted": 0, "email": email, "message": "No subscription rows found for this email."}

    supabase.table("deal_alert_subscriptions").delete().in_("id", list(ids)).execute()
    return {"ok": True, "deleted": len(ids), "email": email, "message": f"Deleted {len(ids)} subscription rows."}


@router.post("/send")
def send_manual_email(payload: SendEmailPayload, authorization: Optional[str] = Header(default=None)):
    _require_admin(authorization)

    subject = (payload.subject or "").strip()
    html = (payload.message_html or "").strip()

    if not subject or not html:
        return {"ok": False, "message": "Missing subject or message_html"}

    # optional image
    if payload.image_url:
        img = payload.image_url.strip()
        if img:
            html = f"""
            <div>
              <div style="margin:0 0 12px 0">{html}</div>
              <div style="margin-top:12px">
                <img src="{img}" alt="image" style="max-width:100%;border-radius:12px" />
              </div>
            </div>
            """

    recipients: List[str] = []

    if payload.send_all:
        # send to distinct verified+active emails
        rows = (
            supabase.table("deal_alert_subscriptions")
            .select("email_norm,email,verified,is_active")
            .eq("is_active", True)
            .eq("verified", True)
            .limit(5000)
            .execute()
            .data
            or []
        )
        seen = set()
        for r in rows:
            em = (r.get("email_norm") or r.get("email") or "").strip().lower()
            if em and em not in seen:
                seen.add(em)
                recipients.append(em)
    else:
        em = (payload.to_email or "").strip().lower()
        if not em:
            return {"ok": False, "message": "Missing to_email (or set send_all=true)"}
        recipients = [em]

    sent = 0
    failed = []

    for to in recipients:
        rs = send_email(to, subject, html)
        if rs.get("ok"):
            sent += 1
        else:
            failed.append({"to": to, "error": rs.get("error")})

    return {"ok": True, "sent": sent, "failed": failed, "total": len(recipients)}
