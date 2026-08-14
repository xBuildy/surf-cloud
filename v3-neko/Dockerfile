# ============================================================
# Wave Surf — Neko WebRTC + Chromium + CDP API
# Uses Neko base + ensurepip for Python deps
# ============================================================

FROM m1k1o/neko:chromium

USER root

# Install Python pip via ensurepip (built into Python, no apt needed)
# Then install our Python dependencies
RUN python3 -m ensurepip --upgrade && \
    python3 -m pip install --no-cache-dir --break-system-packages \
    fastapi==0.104.1 \
    uvicorn==0.24.0 \
    httpx==0.25.2 \
    pydantic==2.5.2 \
    aiofiles==23.2.1 \
    websockets==12.0

# Create app directories
RUN mkdir -p /app/api /app/frontend /var/log/supervisor

# Copy CDP API files
COPY api_v2.py /app/api/api_v2.py
COPY ai_resolver.py /app/api/ai_resolver.py
COPY session_store.py /app/api/session_store.py

# Copy custom Wave OS frontend shell
COPY frontend/ /app/frontend/

# Copy supervisor config
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

EXPOSE 8080 9222

CMD ["/app/start.sh"]
