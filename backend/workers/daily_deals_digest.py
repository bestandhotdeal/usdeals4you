import os
import sys
import html
import re
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
DAILY_SUBJECT = os.getenv("DAILY_DEALS_SUBJECT", "BestDeals — New deals tonight | Deal mới tối nay")
SITE_BASE = os.getenv("PUBLIC_BASE_URL", "https://bestdeals.ddns.net").rstrip("/")
MAX_DEALS_PER_EMAIL = int(os.getenv("DAILY_DEALS_MAX", "30"))

def esc_html(s: str) -> str:
    return html.escape((s or "").strip(), quote=True)


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
    title = esc_html(d.get("title") or "Deal")
    store = esc_html(d.get("store") or "")
    desc = (d.get("description") or "").strip()
    desc = re.sub(r"\s+", " ", desc)
    desc_short = esc_html(desc[:160] + ("…" if len(desc) > 160 else "")) if desc else ""
    url = deal_view_url(d)

    store_badge = (
        f"""<span style="display:inline-block;background:#eef2ff;color:#3730a3;
        padding:2px 8px;border-radius:999px;font-size:12px;margin-left:8px;vertical-align:middle">{store}</span>"""
        if store else ""
    )

    desc_block = (
        f"""<div style="color:#6b7280;font-size:13px;margin-top:6px">{desc_short}</div>"""
        if desc_short else ""
    )

    return f"""
      <tr>
        <td style="padding:14px 12px;border-bottom:1px solid #eef2f7">
          <div style="font-weight:700;font-size:15px;color:#111827;line-height:1.25">{title}{store_badge}</div>
          {desc_block}
        </td>
        <td style="padding:14px 12px;border-bottom:1px solid #eef2f7;text-align:right;white-space:nowrap">
          <a href="{url}" style="display:inline-block;padding:10px 14px;border-radius:12px;background:#111827;color:#ffffff;text-decoration:none;font-weight:700;font-size:13px">
            View deal
          </a>
        </td>
      </tr>
    """


def build_daily_email_html(email: str, keywords: list[str], deals: list[dict]) -> str:
    greeting_email = esc_html(email)

    count = len(deals)
    hours = LOOKBACK_HOURS

    rows = "".join(deal_item_html(d) for d in deals[:MAX_DEALS_PER_EMAIL])

    more = ""
    if len(deals) > MAX_DEALS_PER_EMAIL:
        more = f"""
          <div style="margin-top:14px;color:#6b7280;font-size:13px">
            + {len(deals) - MAX_DEALS_PER_EMAIL} more deals are available.
            <a href="{SITE_BASE}/index.html" style="color:#2563eb;text-decoration:none;font-weight:700">Browse all deals</a>
          </div>
        """


    manage_links = f"""
      <div style="margin-top:14px">
        <a href="{SITE_BASE}/index.html" style="display:inline-block;background:#2563eb;color:#fff;text-decoration:none;
          padding:12px 16px;border-radius:14px;font-weight:800">Browse all deals</a>
        <span style="display:inline-block;width:10px"></span>
        <a href="{SITE_BASE}/index.html#alert" style="display:inline-block;background:#111827;color:#fff;text-decoration:none;
          padding:12px 16px;border-radius:14px;font-weight:800">Manage alerts</a>
      </div>
    """


    en_intro = f"""
      <h2 style="margin:0 0 6px 0;font-size:20px;line-height:1.25;color:#111827">BestDeals — Tonight’s New Deals</h2>
      <div style="color:#6b7280;font-size:14px;margin:0 0 14px 0">Hi <b>{greeting_email}</b>,</div>
      <div style="color:#374151;font-size:14px;margin:0 0 14px 0">
        Here are <b>{count}</b> new deals we found in the last <b>{hours} hours</b>.
        Tap <b>View deal</b> to see details.
      </div>
    """


    vi_intro = f"""
      <hr style="border:none;border-top:1px solid #e5e7eb;margin:18px 0"/>
      <h2 style="margin:0 0 6px 0;font-size:18px;line-height:1.25;color:#111827">BestDeals — Deal mới tối nay</h2>
      <div style="color:#6b7280;font-size:14px;margin:0 0 14px 0">Chào <b>{greeting_email}</b>,</div>
      <div style="color:#374151;font-size:14px;margin:0 0 14px 0">
        Đây là <b>{count}</b> deal mới trong <b>{hours} giờ</b> gần nhất.
        Nhấn <b>View deal</b> để xem chi tiết.
      </div>
    """


    year = datetime.now().year
    footer = f"""
      <hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0"/>
      <div style="color:#9ca3af;font-size:12px;line-height:1.5">
        <div><b>EN:</b> You’re receiving this email because you opted in to BestDeals email updates. If you’d like to stop receiving emails, please unsubscribe from any alert email you received, or contact our support.</div>
        <div style="margin-top:8px"><b>VI:</b> Bạn nhận email này vì đã đăng ký nhận cập nhật từ BestDeals. Nếu muốn dừng nhận email, bạn có thể bấm Unsubscribe trong các email alert trước đó, hoặc liên hệ hỗ trợ.</div>
        <div style="margin-top:10px">© {year} BestDeals • <a href="{SITE_BASE}" style="color:#9ca3af;text-decoration:none">{SITE_BASE}</a></div>
      </div>
    """


    return f"""
      <div style="background:#f6f7fb;padding:22px 10px">
        <div style="max-width:680px;margin:0 auto;background:#ffffff;border:1px solid #eef2f7;border-radius:18px;overflow:hidden">
          <div style="padding:18px 18px 6px 18px">
            {en_intro}
            {manage_links}
          </div>
          <div style="padding:0 18px 10px 18px">
            <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">
              <tbody>
                {rows}
              </tbody>
            </table>
            {more}
          </div>
          <div style="padding:0 18px 6px 18px">
            {vi_intro}
            {manage_links}
          </div>
          <div style="padding:0 18px 18px 18px">
            {footer}
          </div>
        </div>
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
