
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from dotenv import load_dotenv

from app.routers.status import router as status_router
from app.routers.alerts import router as alerts_router

from app.routers import admin_mail
from app.routers import cron_jobs

BASE_DIR = Path(__file__).resolve().parents[1]   # app/ -> backend/
load_dotenv(BASE_DIR / ".env")

FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://127.0.0.1:5500")

app = FastAPI(title="BestDeals API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN, "http://localhost:5500", "http://127.0.0.1:5500"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(status_router)
app.include_router(alerts_router)
app.include_router(admin_mail.router)
app.include_router(cron_jobs.router)


@app.get("/")
def root():
    return {"ok": True, "msg": "BestDeals backend is running"}