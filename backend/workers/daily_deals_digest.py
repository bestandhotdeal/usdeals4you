import os
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# Ensure backend/ is on PYTHONPATH so "import app..." works even when running:
#   python workers/daily_deals_digest.py
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.supabase_client import supabase
from app.services.email_service import send_email

# =========================
# Daily New Deals Digest
# - Keeps keyword-alert system unchanged
# - Sends ONE daily email to each subscriber with ALL new deals in last N hours
# =========================

LOOKBACK_HOURS = int(os.getenv("DAILY_DEALS_LOOKBACK_HOURS", os.getenv("ALERT_LOOKBACK_HOURS", "24")))
DAILY_SUBJECT = os.getenv("DAILY_DEALS_SUBJECT", "BestDeals: Today's new deals")
SITE_BASE = os.getenv("PUBLIC_BASE_URL", "https://bestdeals.ddns.net").rstrip("/")
MAX_DEALS_PER_EMAIL = int(os.getenv("DAILY_DEALS_MAX", "30"))


def now_utc():
    return datetime.now(timezone.utc)


def norm_email(email: str) -> str:
    return (email or "").strip().lower()


def get_active_subscriptions():
    """
    Returns subscription rows (verified + active).
    Table used by existing keyword-alert system: deal_alert_subscriptions.
    """
    res = (
        supabase.table("deal_alert_subscriptions")
        .select("id,email,email_norm,keyword,is_active,verified,created_at")
        .eq("is_active", True)
        .eq("verified", True)
        .order("created_at", desc=True)
        .limit(5000)
        .execute()
    )
    return res.data or []


def get_recent_deals(hours: int):
    since = (now_utc() - timedelta(hours=hours)).isoformat()

    # Same columns as workers/email_alerts.py to avoid schema mismatch
    res = (
        supabase.table("deals")
        .select("id,slug,title,description,store,affiliate_url,image_url,created_at,published")
        .eq("published", True)
        .gte("created_at", since)
        .order("created_at", desc=True)
        .limit(500)
        .execute()
    )
    return res.data or []


def deal_view_url(d: dict) -> str:
    slug = (d.get("slug") or "").strip()
    if slug:
        # Your deal.html supports slug param
        return f"{SITE_BASE}/deal.html?slug={slug}"
    return f"{SITE_BASE}/deal.html?id={d.get('id')}"


def deal_item_html(d: dict) -> str:
    title = (d.get("title") or "Deal").strip()
    url = deal_view_url(d)

    # "Title + View Deal" on the same row (as requested)
    return f"""
      <tr>
        <td style="padding:10px 8px;border-bottom:1px solid #eee;font-weight:600">{title}</td>
        <td style="padding:10px 8px;border-bottom:1px solid #eee;text-align:right;white-space:nowrap">
          <a href="{url}" style="display:inline-block;padding:8px 12px;border-radius:10px;background:#111;color:#fff;text-decoration:none">
            View deal
          </a>
        </td>
      </tr>
    """


def build_daily_email_html(email: str, keywords: list[str], deals: list[dict]) -> str:
    kw_line = ", ".join([k for k in keywords if k]) if keywords else "(chưa có keyword)"

    intro = f"""
      <div style="color:#444;margin:0 0 12px 0">
        Bạn đã đăng ký <b>Alert theo keyword</b>: <b>{kw_line}</b>.<br/>
        Nếu có deal <b>match keyword</b>, hệ thống sẽ <b>gửi email ngay</b> ✅<br/>
        Nếu chưa match keyword thì bạn cứ chờ — khi có match sẽ gửi liền cho bạn.
      </div>
      <div style="margin:0 0 14px 0">
        Hôm nay chúng tôi đang có <b>{len(deals)}</b> deal mới (trong {LOOKBACK_HOURS} giờ gần nhất). Mời bạn ghé thăm:
      </div>
    """

    rows = "".join(deal_item_html(d) for d in deals[:MAX_DEALS_PER_EMAIL])

    more = ""
    if len(deals) > MAX_DEALS_PER_EMAIL:
        more = f"""
          <div style="margin-top:12px;color:#666">
            (Còn {len(deals) - MAX_DEALS_PER_EMAIL} deal nữa) — xem tất cả tại:
            <a href="{SITE_BASE}/index.html">{SITE_BASE}/index.html</a>
          </div>
        """

    footer = f"""
      <hr style="border:none;border-top:1px solid #eee;margin:18px 0"/>
      <div style="color:#888;font-size:12px">
        Bạn nhận email này vì đã subscribe deal alerts tại {SITE_BASE}.<br/>
        Nếu muốn dừng nhận email, bạn có thể unsubscribe trong email keyword-alert hoặc liên hệ admin.
      </div>
    """

    return f"""
      <div style="font-family:Arial,Helvetica,sans-serif;line-height:1.45">
        <h2 style="margin:0 0 10px 0">🛍️ BestDeals - Deal mới trong ngày</h2>
        <div style="color:#666;margin:0 0 14px 0">Chào <b>{email}</b> 👋</div>
        {intro}
        <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">
          <tbody>
            {rows}
          </tbody>
        </table>
        {more}
        {footer}
      </div>
    """


def process_daily_new_deals_digest() -> int:
    subs = get_active_subscriptions()
    if not subs:
        print(f"[{now_utc()}] No active subscriptions")
        return 0

    deals = get_recent_deals(hours=LOOKBACK_HOURS)
    if not deals:
        print(f"[{now_utc()}] No recent deals in last {LOOKBACK_HOURS}h")
        return 0

    agg = defaultdict(set)
    email_display = {}

    for s in subs:
        em = norm_email(s.get("email_norm") or s.get("email") or "")
        if not em:
            continue
        email_display[em] = s.get("email") or em
        kw = (s.get("keyword") or "").strip()
        if kw:
            agg[em].add(kw)

    total_sent = 0
    for em_norm, kwset in agg.items():
        to_email = email_display.get(em_norm, em_norm)
        html = build_daily_email_html(to_email, sorted(list(kwset))[:20], deals)
        rs = send_email(to_email, DAILY_SUBJECT, html)
        if isinstance(rs, dict) and rs.get("ok"):
            total_sent += 1
            print(f"[{now_utc()}] ✅ Daily digest sent to {to_email} deals={min(len(deals), MAX_DEALS_PER_EMAIL)}")
        else:
            print(f"[{now_utc()}] ❌ Daily digest failed to {to_email}: {rs}")

    return total_sent


if __name__ == "__main__":
    print("🚀 Daily New Deals Digest worker started ...")
    process_daily_new_deals_digest()
