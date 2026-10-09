FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Pick up distribution security fixes released since the base image was built (openssl, libpcre2, ...).
RUN apt-get update     && apt-get upgrade -y --no-install-recommends     && rm -rf /var/lib/apt/lists/*

# Runtime dependencies only (no pytest / fakeredis / scanners), pinned to the versions the tests ran against.
COPY requirements.txt constraints.txt ./
RUN pip install -r requirements.txt -c constraints.txt

COPY . .

# Least privilege: an unprivileged user with no login shell and no writable application code.
RUN useradd --system --no-create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/media-data \
    && chown appuser:appuser /app/media-data
USER appuser

EXPOSE 8000

# Liveness only: a database or Redis blip must not get the container killed. Readiness is /health/ready.
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2)"

# The application, not uvicorn, decides which X-Forwarded-For to believe (TRUSTED_PROXY_CIDRS in app/core/rate_limit.py);
# uvicorn's own proxy-header handling is therefore off, so a direct client cannot forge its address.
# Migrations run once per deploy by the release step (docs/deployment/migrations.md); `RUN_MIGRATIONS=1` keeps the
# single-container development behaviour of upgrading on start.
CMD ["sh", "-c", "if [ \"${RUN_MIGRATIONS:-1}\" = \"1\" ]; then alembic upgrade head; fi && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-1} --no-proxy-headers --no-server-header --timeout-graceful-shutdown 5"]
