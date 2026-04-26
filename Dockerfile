# 校园二手交易平台 — 便于 Render / Railway / Fly.io 等容器部署
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY templates ./templates

# 平台通常注入 PORT；本地默认 8000
EXPOSE 8000
CMD sh -c 'exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"'
