# ============================================================
# Wave Surf — Neko WebRTC + Chromium + CDP API
# Extends Neko base — adds CDP flags + Python API via supervisor include
# Uses Neko's built-in supervisor, X server, pulseaudio, chromium
# ============================================================

FROM m1k1o/neko:chromium

USER root

# Install pip via apt (Neko base has python3 but no pip/ensurepip)
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3-pip && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
# --ignore-installed: don't try to uninstall Debian-managed packages
# --break-system-packages: required on Trixie (PEP 668)
# --only-binary: prefer pre-built wheels (no Rust compiler in base)
RUN pip3 install --no-cache-dir --break-system-packages --ignore-installed --only-binary=:all: \
    fastapi==0.115.0 \
    uvicorn==0.30.0 \
    httpx==0.27.0 \
    "pydantic>=2.9.0" \
    aiofiles==23.2.1 \
    websockets==12.0

# Create app directories
RUN mkdir -p /app/api /app/frontend

# Copy CDP API files
COPY api_v2.py /app/api/api_v2.py
COPY ai_resolver.py /app/api/ai_resolver.py
COPY session_store.py /app/api/session_store.py

# Copy custom Wave OS frontend shell
COPY frontend/ /app/frontend/

# Override chromium supervisor config to add CDP debugging flags
# This replaces the chromium program in /etc/neko/supervisord/ to add remote debugging
RUN cat > /etc/neko/supervisord/chromium.conf << 'SUPCONF'
[program:chromium]
environment=HOME="/home/%(ENV_USER)s",USER="%(ENV_USER)s",DISPLAY="%(ENV_DISPLAY)s"
command=/usr/bin/chromium
  --no-sandbox
  --window-position=0,0
  --display=%(ENV_DISPLAY)s
  --user-data-dir=/home/neko/.config/chromium
  --no-first-run
  --start-maximized
  --force-dark-mode
  --disable-gpu
  --disable-software-rasterizer
  --disable-dev-shm-usage
  --remote-debugging-port=9222
  --remote-debugging-address=0.0.0.0
  --remote-allow-origins=*
stopsignal=INT
autorestart=true
priority=800
user=%(ENV_USER)s
stdout_logfile=/var/log/neko/chromium.log
stdout_logfile_maxbytes=100MB
stdout_logfile_backups=10
redirect_stderr=true
SUPCONF

# Add Python CDP API as a supervisor include (runs alongside Neko's services)
RUN cat > /etc/neko/supervisord/cdp-api.conf << 'SUPCONF'
[program:cdp-api]
command=python3 -m uvicorn api.api_v2:app --host 0.0.0.0 --port 8080
directory=/app
autorestart=true
priority=900
user=root
stdout_logfile=/var/log/neko/cdp-api.log
stdout_logfile_maxbytes=100MB
stdout_logfile_backups=10
redirect_stderr=true
SUPCONF

# Environment variables
ENV NEKO_SCREEN=1920x1080@30
ENV NEKO_AUDIO_BITRATE=128
ENV NEKO_VIDEO_BITRATE=4000
ENV NEKO_MAX_FPS=60
ENV NEKO_PASSWORD=wave-surf
ENV NEKO_ADMIN_PASSWORD=wave-admin
ENV NEKO_CONTROL_PROTECTION=false
ENV NEKO_IMPLICIT_CONTROL=true

# Expose Neko WebRTC (8081) + CDP API (8080) + CDP raw (9222)
EXPOSE 8080 9222

# Use Neko base image's default CMD (starts supervisord with /etc/neko/supervisord.conf)
