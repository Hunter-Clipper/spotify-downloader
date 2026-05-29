# ---- Stage 1: static ffmpeg binaries ----
FROM mwader/static-ffmpeg:8.1 AS ffmpeg

# ---- Stage 2: install Python deps ----
FROM python:3.12-slim AS builder

COPY requirements.txt .
RUN pip install --no-cache-dir --no-compile --prefix=/install -r requirements.txt

# ---- Stage 3: minimal runtime ----
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Static ffmpeg — no apt install, no shared codec libs needed
COPY --from=ffmpeg /ffmpeg /ffprobe /usr/local/bin/

# Copy pre-built Python packages from builder
COPY --from=builder /install /usr/local

# Create non-root user with a proper home directory
RUN groupadd -r appuser && \
    useradd -r -g appuser -d /home/appuser -s /sbin/nologin appuser && \
    mkdir -p /home/appuser/.config/spotdl /home/appuser/.cache /data/downloads && \
    chown -R appuser:appuser /home/appuser /data/downloads

ENV HOME=/home/appuser

WORKDIR /app
COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:80/')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80"]
