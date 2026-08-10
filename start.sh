#!/bin/bash
set -e

echo "[Surf Cloud] Starting services..."

# Start Xvfb (virtual display)
Xvfb :99 -screen 0 1280x800x24 -ac &
sleep 1
echo "[Surf Cloud] Xvfb started on :99"

# Start x11vnc (VNC server on display :99, port 5900)
x11vnc -display :99 -forever -shared -rfbport 5900 -nopw -quiet &
sleep 1
echo "[Surf Cloud] x11vnc started on port 5900"

# Start websockify (noVNC web interface on port 5800)
websockify --web=/usr/share/novnc 5800 localhost:5900 --quiet &
sleep 1
echo "[Surf Cloud] noVNC started on port 5800"

# Start Chromium with CDP enabled
chromium     --no-sandbox     --disable-gpu     --disable-dev-shm-usage     --remote-debugging-port=9222     --remote-debugging-address=127.0.0.1     --window-size=1280,800     --window-position=0,0     --start-maximized     "https://www.google.com" &
sleep 2
echo "[Surf Cloud] Chromium started with CDP on port 9222"

# Start the FastAPI automation API
python3 /app/api.py &
echo "[Surf Cloud] API started on port 8000"

# Start nginx (foreground, this keeps the container alive)
echo "[Surf Cloud] Starting nginx on port 8080..."
exec nginx -g 'daemon off;'
