#!/bin/zsh
cd /Users/spider/Desktop/bestdeals/backend
source venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8010 --env-file /Users/spider/Desktop/bestdeals/backend/.env