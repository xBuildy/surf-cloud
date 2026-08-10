FROM debian:bookworm-slim

RUN apt-get update &&     DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends         chromium         xvfb         x11vnc         novnc         websockify         python3         python3-pip         python3-venv         nginx         supervisor         fonts-liberation         fonts-noto-cjk         dbus x11-xserver-utils xdotool wmctrl

RUN pip3 install --no-cache-dir --break-system-packages         fastapi uvicorn[standard] websocket-client httpx

COPY nginx.conf /etc/nginx/sites-available/surf
RUN ln -sf /etc/nginx/sites-available/surf /etc/nginx/sites-enabled/surf

COPY api.py /app/api.py
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

ENV DISPLAY=:99
ENV PORT=8080
ENV API_PORT=8000
ENV SURF_API_KEY=surf-default-key

EXPOSE 8080

CMD ["/app/start.sh"]
