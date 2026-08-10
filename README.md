# Surf Cloud

Cloud browser container for Wave OS. Runs Chromium with noVNC (user browsing) + CDP API (AI automation) on a single container.

## Architecture

- **Chromium** with Xvfb virtual display (via jlesage/chromium base image)
- **noVNC** web interface (port 5800) — user browses in real-time via embedded iframe
- **CDP** on port 9222 (localhost) — Chrome DevTools Protocol for automation
- **FastAPI** automation API (port 8000) — wraps CDP with REST endpoints
- **nginx** reverse proxy (port 8080) — multiplexes noVNC + API on a single port

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | noVNC web interface (embedded in Wave OS Surf app) |
| `/api/health` | GET | Health check + CDP status |
| `/api/navigate` | POST | Navigate to URL |
| `/api/screenshot` | GET | Capture page screenshot (base64 PNG) |
| `/api/content` | GET | Get page text content |
| `/api/click` | POST | Click element by CSS selector |
| `/api/type` | POST | Type text into element |
| `/api/execute` | POST | Execute JavaScript |
| `/api/tabs` | GET | List open tabs |
| `/api/new-tab` | POST | Open new tab |

## Environment Variables

| Var | Default | Description |
|-----|---------|-------------|
| `PORT` | 8080 | nginx public port (Railway) |
| `API_PORT` | 8000 | FastAPI port |
| `SURF_API_KEY` | surf-default-key | API key for automation endpoints |
| `CHROME_CLI_ARGS` | (set in Dockerfile) | CDP flags for Chromium |

## Deploy

Railway auto-deploys from GitHub. Service URL: `https://surf-cloud-production.up.railway.app`
