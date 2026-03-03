from __future__ import annotations

import os
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from app.services.supabase_client import supabase
from app.services.email_service import send_email

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""


# -------------------------
# Admin Auth helpers (Supabase JWT)
# -------------------------
def _get_user_from_token(access_token: str) -> dict:
    # Validate Supabase access token by calling Supabase Auth endpoint.
    # Returns user dict if valid.
    if not access_token:
        raise HTTPException(status_code=401, detail="Missing access token")

    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(status_code=500, detail="Missing Supabase env (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY)")

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
    # Requires: Authorization: Bearer <access_token>
    # Checks Supabase user + admins table.
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization Bearer token")

    token = authorization.split(" ", 1)[1].strip()
    user = _get_user_from_token(token)
    uid = user.get("id")
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid token user")

    # check admin
    res = supabase.table("admins").select("user_id").eq("user_id", uid).limit(1).execute()
    if not getattr(res, "data", None):
        raise HTTPException(status_code=403, detail="Admin access required")

    return {"user": user, "uid": uid}



def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def norm_email(email: str) -> str:
    return (email or "").strip().lower()


def norm_keyword(keyword: str) -> str:
    return re.sub(r"\s+", " ", (keyword or "").strip().lower())


def make_token(nbytes: int = 24) -> str:
    return secrets.token_urlsafe(nbytes).replace("=", "")


def site_base_url() -> str:
    return (os.getenv("SITE_BASE_URL") or os.getenv("PUBLIC_BASE_URL") or "https://bestdeals.ddns.net").rstrip("/")


def build_welcome_email_html(email: str, keyword: str, unsubscribe_token: str) -> str:
    base = site_base_url()
    unsub = f"{base}/api/alerts/unsubscribe?token={unsubscribe_token}"
    return f"""
    <div style="font-family:Arial,Helvetica,sans-serif;line-height:1.5">
      <h2 style="margin:0 0 8px 0">✅ BestDeals Alert Subscription</h2>
      <p style="margin:0 0 12px 0">
        You're subscribed to deal alerts for keyword: <b>{keyword}</b>.
        We'll email you as soon as we find a matching deal.
      </p>
      <p style="margin:0 0 12px 0;color:#666">
        Subscribed email: <b>{email}</b>
      </p>
      <p style="margin:0 0 12px 0">
        Unsubscribe anytime:
        <a href="{unsub}">Unsubscribe</a>
      </p>
      <hr/>
      <p style="margin:0;color:#999;font-size:12px">
        © {datetime.now().year} BestDeals
      </p>
    </div>
    """


def build_admin_broadcast_html(body_html: str, image_url: Optional[str]) -> str:
    img = f'<p><img src="{image_url}" alt="image" style="max-width:100%;border-radius:12px"/></p>' if image_url else ""
    return f"""
    <div style="font-family:Arial,Helvetica,sans-serif;line-height:1.5">
      {img}
      {body_html}
      <hr/>
      <p style="margin:0;color:#999;font-size:12px">
        You are receiving this message because you subscribed to BestDeals alerts.
      </p>
    </div>
    """


class SubscribePayload(BaseModel):
    email: str
    keyword: str
    category_id: Optional[str] = None


class BroadcastPayload(BaseModel):
    emails: List[str]
    subject: str
    html: str
    image_url: Optional[str] = None



class DeleteSubscriberPayload(BaseModel):
    email: str

@router.get("/status")
def alerts_status() -> Dict[str, Any]:
    return {"ok": True, "service": "alerts"}


@router.get("/list")
def list_alerts() -> Dict[str, Any]:
    res = (
        supabase.table("deal_alert_subscriptions")
        .select("*")
        .order("created_at", desc=True)
        .limit(200)
        .execute()
    )
    return {"ok": True, "items": res.data or []}


@router.post("/subscribe")
def subscribe(payload: SubscribePayload) -> Dict[str, Any]:
    email = (payload.email or "").strip()
    keyword = (payload.keyword or "").strip()

    if not email or not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Invalid email")
    if not keyword:
        raise HTTPException(status_code=400, detail="Keyword is required")

    email_n = norm_email(email)
    keyword_n = norm_keyword(keyword)

    # If already exists -> no insert
    existing = (
        supabase.table("deal_alert_subscriptions")
        .select("id,email,keyword,verified,is_active,unsubscribe_token")
        .eq("email_norm", email_n)
        .eq("keyword_norm", keyword_n)
        .limit(1)
        .execute()
        .data
    )
    if existing:
        row = existing[0]
        return {
            "ok": True,
            "message": "You already subscribed to this keyword.",
            "subscription_id": row["id"],
            "already": True,
            "verified": bool(row.get("verified")),
        }

    unsubscribe_token = make_token(24)
    verify_token = make_token(24)

    auto_verify = os.getenv("ALERT_AUTO_VERIFY", "true").lower() in ("1", "true", "yes")
    verified = True if auto_verify else False

    insert_row = {
        "email": email,
        "keyword": keyword,
        "category_id": payload.category_id,
        "is_active": True,
        "verified": verified,
        "verify_token": None if verified else verify_token,
        "unsubscribe_token": unsubscribe_token,
        "created_at": now_utc().isoformat(),
}

    try:
        created = supabase.table("deal_alert_subscriptions").insert(insert_row).execute().data
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Subscribe error: {e}")

    sub_id = (created[0]["id"] if created else None)

    mail_result = None
    try:
        if verified:
            subject = "✅ BestDeals - Subscription confirmed"
            html = build_welcome_email_html(email=email, keyword=keyword, unsubscribe_token=unsubscribe_token)
            mail_result = send_email(email, subject, html)
        else:
            base = site_base_url()
            verify_link = f"{base}/api/alerts/verify?token={verify_token}"
            subject = "✅ BestDeals - Please verify your alert"
            html = f"""
            <div style="font-family:Arial,Helvetica,sans-serif;line-height:1.5">
              <h2 style="margin:0 0 8px 0">Verify your BestDeals alert</h2>
              <p>Keyword: <b>{keyword}</b></p>
              <p>Click to verify: <a href="{verify_link}">Verify subscription</a></p>
              <hr/>
              <p style="margin:0;color:#999;font-size:12px">© {datetime.now().year} BestDeals</p>
            </div>
            """
            mail_result = send_email(email, subject, html)
    except Exception as e:
        mail_result = {"ok": False, "error": str(e)}

    return {
        "ok": True,
        "message": "Subscription created. Check email.",
        "subscription_id": sub_id,
        "already": False,
        "verified": verified,
        "mail": mail_result,
    }


@router.get("/verify")
def verify(token: str) -> Dict[str, Any]:
    if not token:
        raise HTTPException(status_code=400, detail="Missing token")

    rows = (
        supabase.table("deal_alert_subscriptions")
        .select("id,verified")
        .eq("verify_token", token)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        raise HTTPException(status_code=400, detail="Invalid token")

    row = rows[0]
    if row.get("verified"):
        return {"ok": True, "message": "Already verified."}

    supabase.table("deal_alert_subscriptions").update({"verified": True, "verify_token": None}).eq("id", row["id"]).execute()
    return {"ok": True, "message": "Verified!"}


@router.get("/unsubscribe")
def unsubscribe(token: str) -> Dict[str, Any]:
    if not token:
        raise HTTPException(status_code=400, detail="Missing token")

    rows = (
        supabase.table("deal_alert_subscriptions")
        .select("id,is_active")
        .eq("unsubscribe_token", token)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        raise HTTPException(status_code=400, detail="Invalid token")

    row = rows[0]
    if not row.get("is_active", True):
        return {"ok": True, "message": "Already unsubscribed."}

    supabase.table("deal_alert_subscriptions").update({"is_active": False}).eq("id", row["id"]).execute()
    return {"ok": True, "message": "Unsubscribed."}


# -----------------------------
# Admin endpoints (same router)
# -----------------------------
@router.get("/admin/subscribers")
def admin_list_subscribers(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _require_admin(authorization)

    res = (
        supabase.table("deal_alert_subscriptions")
        .select("email,created_at,verified,is_active")
        .eq("verified", True)
        .eq("is_active", True)
        .order("created_at", desc=True)
        .limit(2000)
        .execute()
    )
    items = res.data or []

    seen: Dict[str, str] = {}
    for r in items:
        em = (r.get("email") or "").strip()
        if em and em not in seen:
            seen[em] = r.get("created_at") or ""

    out = [{"email": k, "last_subscribed_at": v} for k, v in seen.items()]
    return {"ok": True, "items": out}


@router.post("/admin/subscribers/delete")
def admin_delete_subscriber(payload: DeleteSubscriberPayload, authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _require_admin(authorization)

    raw_email = (payload.email or "").strip()
    email = norm_email(raw_email)
    if not email or not EMAIL_RE.match(email):
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

    # Back-compat: in case old rows didn't have email_norm
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


@router.post("/admin/email/broadcast")
def admin_email_broadcast(payload: BroadcastPayload, authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _require_admin(authorization)

    emails = [norm_email(x) for x in (payload.emails or []) if norm_email(x)]
    if not emails:
        raise HTTPException(status_code=400, detail="No recipients")

    allowed_rows = (
        supabase.table("deal_alert_subscriptions")
        .select("email")
        .eq("verified", True)
        .eq("is_active", True)
        .in_("email_norm", emails)
        .execute()
        .data
        or []
    )
    allowed = {norm_email(r.get("email") or "") for r in allowed_rows}
    targets = [e for e in emails if e in allowed]
    if not targets:
        raise HTTPException(status_code=400, detail="No allowed recipients (must be verified + active)")

    html = build_admin_broadcast_html(payload.html, payload.image_url)

    sent = 0
    failed: List[Dict[str, str]] = []
    for to in targets:
        try:
            rs = send_email(to, payload.subject, html)
            if isinstance(rs, dict) and rs.get("ok") is False:
                failed.append({"email": to, "error": str(rs.get("error") or "send failed")})
            else:
                sent += 1
        except Exception as e:
            failed.append({"email": to, "error": str(e)})

    return {"ok": True, "message": f"Sent {sent}/{len(targets)}", "sent": sent, "total": len(targets), "failed": failed}
