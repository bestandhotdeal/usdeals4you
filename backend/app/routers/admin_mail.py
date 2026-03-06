# backend/app/routers/admin_mail.py
#
# v2 (diagnostic + more robust admin check)
# - Adds GET /api/admin/mail/whoami (requires valid Supabase access token, NOT admin)
# - Admin check returns 500 on Supabase query errors (instead of masking as 403)
# - Admin check tries both supabase-py and direct PostgREST call (service_role)

import os
import requests
from typing import Optional, List, Tuple
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.services.supabase_client import supabase
from app.services.email_service import send_email

router = APIRouter(prefix="/api/admin/mail", tags=["admin-mail"])

SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()


def _require_env():
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(status_code=500, detail="Server misconfigured: missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY")


# -------------------------
# Auth helpers (Supabase JWT)
# -------------------------
def _get_user_from_token(access_token: str) -> dict:
    if not access_token:
        raise HTTPException(status_code=401, detail="Missing access token")
    _require_env()

    url = f"{SUPABASE_URL}/auth/v1/user"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
    }
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid token")
    return r.json()


def _admin_check_supabase_py(uid: str) -> Tuple[Optional[bool], Optional[str]]:
    try:
        res = supabase.table("admins").select("user_id").eq("user_id", uid).limit(1).execute()
        err = getattr(res, "error", None)
        if err:
            return None, f"supabase-py error: {err}"
        data = getattr(res, "data", None) or []
        return (len(data) > 0), None
    except Exception as e:
        return None, f"supabase-py exception: {e}"


def _admin_check_postgrest(uid: str) -> Tuple[Optional[bool], Optional[str]]:
    try:
        _require_env()
        url = f"{SUPABASE_URL}/rest/v1/admins"
        params = {"select": "user_id", "user_id": f"eq.{uid}", "limit": "1"}
        headers = {
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        }
        r = requests.get(url, params=params, headers=headers, timeout=15)
        if r.status_code != 200:
            return None, f"postgrest HTTP {r.status_code}: {r.text[:300]}"
        rows = r.json() if r.text else []
        return (len(rows) > 0), None
    except Exception as e:
        return None, f"postgrest exception: {e}"


def _is_admin(uid: str) -> Tuple[bool, Optional[str]]:
    # 1) supabase-py
    ok1, err1 = _admin_check_supabase_py(uid)
    if ok1 is True:
        return True, None
    # if supabase-py errored, keep note and try PostgREST
    ok2, err2 = _admin_check_postgrest(uid)
    if ok2 is True:
        return True, None

    # If either path produced a real error, surface it as 500 so you know what to fix.
    # Otherwise it's a real "not admin" case -> 403.
    errors = []
    if err1:
        errors.append(err1)
    if err2:
        errors.append(err2)
    if errors:
        return False, " | ".join(errors)
    return False, None


def _require_admin(authorization: Optional[str]) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization Bearer token")

    token = authorization.split(" ", 1)[1].strip()
    user = _get_user_from_token(token)
    uid = user.get("id")
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid token user")

    ok, err = _is_admin(uid)
    if err:
        raise HTTPException(
            status_code=500,
            detail=f"Admin check failed on server. Likely wrong SUPABASE_URL/key on Render. Details: {err}",
        )
    if not ok:
        raise HTTPException(status_code=403, detail="Admin access required")

    return {"user": user, "uid": uid}


# -------------------------
# Models
# -------------------------
class SendEmailPayload(BaseModel):
    to_email: Optional[str] = None
    send_all: bool = False
    subject: str
    message_html: str
    image_url: Optional[str] = None


class DeleteSubscriberPayload(BaseModel):
    email: str


# -------------------------
# Debug endpoint
# -------------------------
@router.get("/whoami")
def whoami(authorization: Optional[str] = Header(default=None)):
    """Helps confirm what the backend sees (useful on Render)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization Bearer token")

    token = authorization.split(" ", 1)[1].strip()
    user = _get_user_from_token(token)
    uid = user.get("id")

    ok, err = _is_admin(uid) if uid else (False, "missing uid")
    return {
        "ok": True,
        "email": user.get("email"),
        "uid": uid,
        "is_admin": bool(ok),
        "admin_check_error": err,
        "supabase_url": SUPABASE_URL,
    }


# -------------------------
# Endpoints
# -------------------------
@router.get("/subscribers")
def list_subscribers(authorization: Optional[str] = Header(default=None)):
    _require_admin(authorization)

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
        if r.get("created_at") and (agg[em]["created_at"] is None or r["created_at"] > agg[em]["created_at"]):
            agg[em]["created_at"] = r["created_at"]
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

    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return {"ok": True, "count": len(items), "items": items}


@router.post("/subscribers/delete")
def delete_subscriber(payload: DeleteSubscriberPayload, authorization: Optional[str] = Header(default=None)):
    _require_admin(authorization)

    raw_email = (payload.email or "").strip()
    email = (raw_email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email")

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
