# Wave Surf v3 — Neko WebRTC + Thorium Browser

Replaces noVNC with Neko (WebRTC streaming) and Chromium with Thorium (8-38% faster).

## Key Improvements
- Ultra-low latency streaming via WebRTC (sub-500ms vs VNC's 200-500ms+)
- Hardware-accelerated video encoding (H.264/VP8/VP9)
- Crystal clear text — no VNC pixelation
- Thorium browser — 8-38% faster page loads, same CDP protocol
- Custom Wave OS browser shell — address bar, bookmarks, history, Ask AI panel
- Wave Search integration — SearXNG as default search engine

## Deployment
1. Set Railway service root directory to `v3-neko/`
2. Set env vars: NEKO_PASSWORD, NEKO_ADMIN_PASSWORD, NEKO_SCREEN=1920x1080@30
3. Allocate 2GB RAM + 2GB shared memory
4. Deploy — Railway builds Docker image automatically

## API Endpoints (unchanged from v2)
POST /api/navigate, /api/click, /api/type, /api/extract, /api/observe, /api/act
GET /api/screenshot, /health
POST /api/automate — full AI automation via GLM-5.2
