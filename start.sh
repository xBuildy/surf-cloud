#!/bin/bash
set -e

echo "[Surf Cloud] Starting services..."

# Start Xvfb (virtual display)
Xvfb :99 -screen 0 1920x1080x24 -ac &
sleep 2
echo "[Surf Cloud] Xvfb started on :99"

# Start x11vnc (VNC server)
x11vnc -display :99 -forever -shared -rfbport 5900 -nopw -quiet &
sleep 2
echo "[Surf Cloud] x11vnc started on port 5900"

# Start websockify (WebSocket proxy only, no web server)
websockify 5800 localhost:5900 &
sleep 2
echo "[Surf Cloud] websockify started on port 5800"

# Check noVNC files
if [ -d /usr/share/novnc ]; then
    echo "[Surf Cloud] noVNC files found at /usr/share/novnc"
    ls /usr/share/novnc/vnc.html 2>/dev/null && echo "[Surf Cloud] vnc.html exists" || echo "[Surf Cloud] vnc.html NOT found"
else
    echo "[Surf Cloud] WARNING: noVNC directory not found at /usr/share/novnc"
fi

# Start Chromium with CDP enabled
chromium --no-sandbox --disable-gpu --disable-dev-shm-usage --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 --remote-allow-origins=* --window-size=1920,1080 --window-position=0,0 --start-maximized "https://www.google.com" &
sleep 3
echo "[Surf Cloud] Chromium started with CDP on port 9222"

# Start the FastAPI automation API
python3 /app/api.py &
echo "[Surf Cloud] API started on port 8000"

# Start nginx (foreground)
echo "[Surf Cloud] Starting nginx on port 8080..."
exec nginx -g 'daemon off;'
