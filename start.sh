#!/bin/bash
set -e

echo "[Surf Cloud v2] Starting services..."

# Start Xvfb (virtual display)
Xvfb :99 -screen 0 1920x1920x24 -ac &
sleep 2
echo "[Surf Cloud v2] Xvfb started on :99"

# Start x11vnc (VNC server)
x11vnc -display :99 -forever -shared -rfbport 5900 -nopw -quiet -xrandr &
sleep 2
echo "[Surf Cloud v2] x11vnc started on port 5900"

# Start websockify (WebSocket proxy for noVNC)
websockify --web=/usr/share/novnc 5800 localhost:5900 &
sleep 2
echo "[Surf Cloud v2] websockify started on port 5800"

# Start Chromium with CDP enabled
chromium --no-sandbox --disable-gpu --disable-dev-shm-usage \
    --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 \
    --remote-allow-origins=* --window-size=1920,1080 --window-position=0,0 \
    "https://www.google.com" &
sleep 3
echo "[Surf Cloud v2] Chromium started with CDP on port 9222"

# Start the FastAPI automation API (prefer v2)
cd /app
if [ -f /app/api_v2.py ]; then
    python3 /app/api_v2.py &
    echo "[Surf Cloud v2] API v2 started on port 8000"
elif [ -f /app/api.py ]; then
    python3 /app/api.py &
    echo "[Surf Cloud v2] API v1 started on port 8000"
fi

# Start nginx (foreground — keeps container alive)
echo "[Surf Cloud v2] Starting nginx on port 8080..."
exec nginx -g 'daemon off;'
