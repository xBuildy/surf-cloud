#!/bin/bash
# ============================================================
# Wave Surf — Container Startup Script
# Launches Neko (WebRTC) + Chromium + Python CDP API
# ============================================================

set -e

echo "🌊 Wave Surf — Neko + Chromium starting up..."

# Kill any stale processes
pkill -f "neko" 2>/dev/null || true
pkill -f "chromium" 2>/dev/null || true
pkill -f "uvicorn" 2>/dev/null || true

sleep 1

# Start supervisor (manages all processes: neko, browser, API)
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/surf-neko.conf
