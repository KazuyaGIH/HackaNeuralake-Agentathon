FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv

COPY apps/api/requirements.lock.txt /srv/apps/api/requirements.lock.txt
RUN pip install --no-cache-dir -r /srv/apps/api/requirements.lock.txt

COPY apps/api /srv/apps/api
COPY fixtures /srv/fixtures

ENV AGENTATHON_DATA_DIR=/data AGENTATHON_HOST=0.0.0.0 AGENTATHON_PORT=8000
VOLUME ["/data"]
EXPOSE 8000
WORKDIR /srv/apps/api
# PORT e definido por plataformas como o Render; localmente (Docker Compose) cai no 8000.
CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
