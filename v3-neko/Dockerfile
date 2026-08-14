# ============================================================
# Wave Surf — Neko WebRTC + Thorium Browser + CDP API
# Replaces noVNC with ultra-low-latency WebRTC streaming
# ============================================================

FROM m1k1o/neko:chromium AS base

# Switch to root for installations
USER root

# Install Thorium Browser (Chromium fork with 8-38% performance gains)
# Thorium uses same CDP protocol — all automation endpoints keep working
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

# Install Thorium from GitHub releases (latest stable)
RUN wget -q https://github.com/Alex313031/thorium/releases/latest/download/thorium-linux-amd64.deb -O /tmp/thorium.deb || \
    wget -q https://github.com/Alex313031/thorium/releases/download/M130/thorium-linux-amd64.deb -O /tmp/thorium.deb || \
    echo "FALLBACK: Using vanilla Chromium"

RUN if [ -f /tmp/thorium.deb ]; then \
        apt-get install -y /tmp/thorium.deb && \
        rm /tmp/thorium.deb && \
        ln -sf /usr/bin/thorium-browser /usr/bin/chromium-browser && \
        ln -sf /usr/bin/thorium-browser /usr/bin/chromium; \
    else \
        echo "Thorium download failed, keeping vanilla Chromium"; \
    fi

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
