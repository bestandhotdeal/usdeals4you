import os
from datetime import datetime
from importlib import import_module
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, HTTPException

router = APIRouter(prefix="/api/cron", tags=["cron"])
LA = ZoneInfo("America/Los_Angeles")

def require_secret(x_cron_secret: str | None):
    expected = os.getenv("CRON_SECRET")
    if not expected:
        raise HTTPException(status_code=500, detail="CRON_SECRET is not set on server")
    if not x_cron_secret or x_cron_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid cron secret")

def within_la_window(target_hour: int, target_minute: int, window_min: int = 10) -> bool:
    now = datetime.now(LA)
    if now.hour != target_hour:
        return False
    return abs(now.minute - target_minute) <= window_min

@router.post("/keyword-alerts-digest")
def keyword_alerts_digest(
    force: bool = False,
    x_cron_secret: str | None = Header(default=None, alias="X-Cron-Secret"),
):
    """
    Task 1: Keyword alerts
    - chạy lúc 7:00pm LA (19:00)
    """
    require_secret(x_cron_secret)

    if not force and not within_la_window(19, 0, 10):
        return {
            "ok": True,
            "skipped": True,
            "reason": "outside 7:00pm LA window",
            "now_la": datetime.now(LA).isoformat(),
        }

    mod = import_module("workers.email_alerts")
    sent = mod.process_daily_digest()
    return {"ok": True, "sent": sent, "now_la": datetime.now(LA).isoformat()}

@router.post("/daily-deals-digest")
def daily_deals_digest(
    force: bool = False,
    x_cron_secret: str | None = Header(default=None, alias="X-Cron-Secret"),
):
    """
    Task 2: Daily deals digest
    - chạy lúc 7:30pm LA (19:30)
    """
    require_secret(x_cron_secret)

    if not force and not within_la_window(19, 30, 10):
        return {
            "ok": True,
            "skipped": True,
            "reason": "outside 7:30pm LA window",
            "now_la": datetime.now(LA).isoformat(),
        }

    mod = import_module("workers.daily_deals_digest")
    sent = mod.process_daily_new_deals_digest()
    return {"ok": True, "sent": sent, "now_la": datetime.now(LA).isoformat()}
