import os
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from app.services.supabase_client import supabase
from app.services.email_service import send_email

LOOKBACK_HOURS = int(os.getenv("ALERT_LOOKBACK_HOURS", "24"))
DIGEST_SUBJECT = os.getenv("ALERT_DIGEST_SUBJECT", "BestDeals: New deals matching your alerts")
SITE_BASE = os.getenv("PUBLIC_BASE_URL", "https://bestdeals.ddns.net").rstrip("/")


def now_utc():
    return datetime.now(timezone.utc)


def keyword_match(deal, keyword: str) -> bool:
    kw = (keyword or "").strip().lower()
    if not kw:
        return False
    hay = f"{deal.get('title','')} {deal.get('description','')}".lower()
    return kw in hay


def get_active_subscriptions():
    # Option A: verified=true luôn; nhưng vẫn lọc verified & active cho sạch
    res = (
        supabase.table("deal_alert_subscriptions")
        .select("id,email,keyword,category_id,is_active,verified,created_at")
        .eq("is_active", True)
        .eq("verified", True)
        .order("created_at", desc=True)
        .limit(2000)
        .execute()
    )
    return res.data or []


def get_recent_deals(hours=24):
    since = (now_utc() - timedelta(hours=hours)).isoformat()

    # IMPORTANT: deals table của bạn KHÔNG có store_name -> chỉ chọn cột đang tồn tại
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


def get_already_sent_map(subscription_ids):
    """
    Return set of (subscription_id, deal_id) đã gửi, để không gửi lại.
    """
    if not subscription_ids:
        return set()

    # lấy log gần đây (cũng đủ cho MVP)
    res = (
        supabase.table("alert_delivery_log")
        .select("subscription_id,deal_id")
        .in_("subscription_id", subscription_ids)
        .limit(5000)
        .execute()
    )
    rows = res.data or []
    return set((r["subscription_id"], r["deal_id"]) for r in rows)


def log_sent(subscription_id: str, deal_id: str):
    try:
        supabase.table("alert_delivery_log").insert({
            "subscription_id": subscription_id,
            "deal_id": deal_id
        }).execute()
    except Exception:
        # unique constraint uq_delivery_sub_deal có thể đã tồn tại => ignore
        pass


def deal_line_html(d):
    title = d.get("title") or "Deal"
    store = d.get("store") or ""
    url = f"{SITE_BASE}/deal.html?id={d.get('id')}"
    aff = d.get("affiliate_url") or url

    # Email: ưu tiên “View on site” để tránh deal not found nếu aff link khác
    return f"""
      <div style="padding:10px 0;border-bottom:1px solid #eee">
        <div style="font-size:15px;font-weight:700;margin-bottom:4px">{title}</div>
        <div style="color:#666;font-size:13px;margin-bottom:6px">{store}</div>
        <div>
          <a href="{url}" style="display:inline-block;margin-right:10px">View deal</a>
          <a href="{aff}" style="display:inline-block">Go to store</a>
        </div>
      </div>
    """


def build_digest_html(email: str, sections: dict):
    # sections: keyword -> list[deal]
    parts = []
    parts.append(f"<div style='font-family:Arial,sans-serif'>")
    parts.append(f"<h2 style='margin:0 0 8px'>BestDeals Alerts</h2>")
    parts.append(f"<div style='color:#666;margin-bottom:14px'>Hi {email}, here are new deals matching your alerts (last {LOOKBACK_HOURS}h).</div>")

    for kw, deals in sections.items():
        parts.append(f"<h3 style='margin:18px 0 8px'>Keyword: {kw} ({len(deals)})</h3>")
        for d in deals:
            parts.append(deal_line_html(d))

    parts.append(f"<div style='color:#888;font-size:12px;margin-top:18px'>You received this because you subscribed on {SITE_BASE}.</div>")
    parts.append("</div>")
    return "".join(parts)


def process_daily_digest():
    subs = get_active_subscriptions()
    if not subs:
        print(f"[{now_utc()}] No active subscriptions")
        return 0

    deals = get_recent_deals(hours=LOOKBACK_HOURS)
    if not deals:
        print(f"[{now_utc()}] No recent deals in last {LOOKBACK_HOURS}h")
        return 0

    sub_ids = [s["id"] for s in subs]
    sent_set = get_already_sent_map(sub_ids)

    # email -> keyword -> deals
    bucket = defaultdict(lambda: defaultdict(list))

    for s in subs:
        sid = s["id"]
        email = s["email"]
        kw = (s["keyword"] or "").strip().lower()

        if not kw:
            continue

        for d in deals:
            # tránh gửi lại deal đã gửi cho sub này
            if (sid, d["id"]) in sent_set:
                continue

            if keyword_match(d, kw):
                bucket[email][kw].append(d)

    total_sent = 0

    for email, sections in bucket.items():
        # bỏ keyword không có deal
        sections = {kw: ds for kw, ds in sections.items() if ds}
        if not sections:
            continue

        html = build_digest_html(email, sections)
        rs = send_email(email, DIGEST_SUBJECT, html)

        if rs.get("ok"):
            # log đã gửi theo từng subscription_id + deal_id
            # cần map lại subscription theo (email, keyword)
            for s in subs:
                if s["email"] != email:
                    continue
                kw = (s["keyword"] or "").strip().lower()
                ds = sections.get(kw, [])
                for d in ds:
                    log_sent(s["id"], d["id"])

            total_sent += 1
            print(f"[{now_utc()}] ✅ Sent digest to {email} sections={len(sections)}")
        else:
            print(f"[{now_utc()}] ❌ Email send failed to {email}: {rs}")

    if total_sent == 0:
        print(f"[{now_utc()}] No deals matched any subscription")
    return total_sent


if __name__ == "__main__":
    print("🚀 BestDeals Email Worker started (Option A auto-verify)...")
    process_daily_digest()