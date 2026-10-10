FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FR_DATA_DIR=/app/data \
    TZ=Asia/Shanghai

WORKDIR /app/backend

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ libxml2-dev libxslt1-dev curl tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY backend/app ./app
COPY frontend /app/frontend

RUN mkdir -p /app/data
VOLUME ["/app/data"]
EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://127.0.0.1/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80"]
