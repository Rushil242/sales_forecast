# syntax=docker/dockerfile:1

# ── builder ───────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY pyproject.toml README.md ./
COPY app ./app

# CPU-only torch. The CUDA wheels are ~2.5 GB and this image is meant to run
# anywhere; GPU deployments should build with the default index instead.
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install --extra-index-url https://download.pytorch.org/whl/cpu . \
 && find /opt/venv -name '__pycache__' -type d -prune -exec rm -rf {} +

# ── runtime ───────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Model weights land here; mount a volume to avoid re-downloading on restart.
    HF_HOME=/models \
    RETAILIQ_ENVIRONMENT=production \
    RETAILIQ_LOG_JSON=true \
    RETAILIQ_CHRONOS_DEVICE=cpu

RUN groupadd --system retailiq && useradd --system --gid retailiq --create-home retailiq

COPY --from=builder /opt/venv /opt/venv

WORKDIR /srv/backend
COPY --chown=retailiq:retailiq app ./app
COPY --chown=retailiq:retailiq scripts ./scripts
COPY --chown=retailiq:retailiq pyproject.toml README.md ./

RUN mkdir -p /models /data && chown -R retailiq:retailiq /models /data
USER retailiq

EXPOSE 8000

# Liveness only. Readiness (/ready) reports the database and model state, but the
# service is legitimately servable via statistical fallback before Chronos loads.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
