# ============================================================
# Wave Surf — Neko WebRTC + Chromium Browser + CDP API
# Replaces noVNC with ultra-low-latency WebRTC streaming
# ============================================================

FROM m1k1o/neko:chromium AS base

# Switch to root for installations
USER root

# Base tooling for the CDP API + reverse proxy.
# NOTE: software-properties-common removed — not used (no add-apt-repository
# calls in this Dockerfile) and unavailable in the current base image's
# Debian trixie repos, which was breaking the build (exit code 100).
RUN apt-get update && apt-get install -y \
    wget \
    gnupg2 \
    python3 \
    python3-pip \
    nginx \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# NOTE: Thorium install disabled for now. The GitHub release wget attempts
# were silently creating an invalid/empty /tmp/thorium.deb on 404 (wget
# still writes -O output even on failure), which then failed `apt-get install`
# with "could not locate member control.tar" and broke every build.
# Shipping on the base image's bundled vanilla Chromium (same CDP protocol,
# all automation endpoints work identically) to get Surf Cloud live now.
# Revisit Thorium later with a verified, pinned release URL + checksum check.

# Install Python dependencies for CDP API
RUN pip3 install --no-cache-dir --break-system-packages \
    fastapi==0.104.1 \
    uvicorn==0.24.0 \
    playwright==1.40.0 \
    httpx==0.25.2 \
    pydantic==2.5.2 \
    websockets==12.0

# Create directories
RUN mkdir -p /app/api /app/frontend /app/config /var/log/supervisor

# Copy CDP API
COPY api_v2.py /app/api/api_v2.py
COPY ai_resolver.py /app/api/ai_resolver.py
COPY session_store.py /app/api/session_store.py

# Copy custom Wave OS frontend shell
COPY frontend/ /app/frontend/

# Copy configs
COPY nginx.conf /etc/nginx/sites-available/default
COPY supervisord.conf /etc/supervisor/conf.d/surf-neko.conf
COPY start.sh /app/start.sh

RUN chmod +x /app/start.sh

# Environment variables
ENV NEKO_SCREEN=1920x1080@30
ENV NEKO_AUDIO_BITRATE=128
ENV NEKO_VIDEO_BITRATE=4000
ENV NEKO_MAX_FPS=60
ENV NEKO_PASSWORD=wave-surf
ENV NEKO_ADMIN_PASSWORD=wave-admin
ENV NEKO_CONTROL_PROTECTION=false
ENV NEKO_IMPLICIT_CONTROL=true
ENV NEKO_LOCK_RGBA=false
ENV CHROMIUM_ARGS="--remote-debugging-port=9222 --remote-debugging-address=0.0.0.0 --remote-allow-origins=* --no-sandbox --disable-gpu-sandbox --disable-dev-shm-usage --force-device-scale-factor=1"

EXPOSE 8080 9222

USER root

CMD ["/app/start.sh"]
