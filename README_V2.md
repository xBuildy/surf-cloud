# Surf Cloud v2 — Browser Automation Engine

Upgraded browser automation engine for Wave OS. Self-hosted on Railway with AI-driven element resolution, CDP recording, and session persistence.

## What's New in v2

### AI Element Resolution (Stagehand patterns)
- `observe` — Find elements by natural language ("find the login form fields")
- `act` — Perform actions by description ("click the Log in button")
- `extract` — Extract structured data from pages ("get the form field values")
- Powered by Theta EdgeCloud GLM-5.2 vision model
- Falls back to DOM-only analysis if Theta is down

### Playwright Integration (React-safe)
- `fill` — Proper React controlled input filling (fixes the issue CDP had)
- `pw-click` — Playwright click with proper event dispatching
- `pw-type` — Character-by-character typing with configurable delay
- `wait` — Wait for element, navigation, or network idle
- `pdf` — Generate PDF exports of pages

### Session Persistence
- Save/load browser auth state (cookies + localStorage + sessionStorage)
- Pre-seed Wave OS login session — automations skip login entirely
- Named session profiles stored in container volume

### CDP Recording / Replay
- Record browser actions during manual browsing in noVNC
- Generate Playwright Python scripts from recordings
- Replay at variable speed (0.5x, 1x, 2x)
- Store recordings in container volume

### noVNC Customization
- Wave OS dark theme branding
- Auto-connect on load
- Custom loading screen with Surf Cloud branding
- Clean toolbar

## API Endpoints

### Existing (backward compatible)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check + feature availability |
| POST | `/api/navigate` | Navigate to URL |
| GET | `/api/screenshot` | Screenshot (base64) |
| GET | `/api/screenshot-image` | Screenshot (raw PNG) |
| GET | `/api/content` | Get page text content |
| POST | `/api/click` | Click element (CDP) |
| POST | `/api/type` | Type text (CDP) |
| POST | `/api/execute` | Execute JavaScript |
| GET | `/api/tabs` | List browser tabs |
| POST | `/api/new-tab` | Create new tab |

### New: Playwright (React-safe)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/fill` | React-safe input filling |
| POST | `/api/pw-click` | Playwright click |
| POST | `/api/pw-type` | Playwright character-by-character type |
| POST | `/api/wait` | Wait for element/navigation/network |
| POST | `/api/pdf` | Generate PDF export |

### New: AI Element Resolution
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/observe` | Find elements by natural language |
| POST | `/api/act` | Perform action by description |
| POST | `/api/extract` | Extract structured data with AI |

### New: Session Persistence
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/session/save` | Save browser session |
| POST | `/api/session/load` | Load saved session |
| GET | `/api/session/list` | List saved sessions |
| DELETE | `/api/session/delete` | Delete saved session |

### New: Recording
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/record/start` | Start recording |
| POST | `/api/record/stop` | Stop recording, get events + script |
| POST | `/api/record/replay` | Replay recorded script |

### New: Combo Automation
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/automate` | Multi-step workflow with session support |

## Architecture

```
Surf Cloud Container (Railway)
├── Chromium + CDP (port 9222, localhost only)
├── noVNC viewer (port 5800) — branded, auto-connect
├── nginx reverse proxy (port 8080) — public entry point
├── FastAPI (port 8000)
│   ├── CDP operations (existing)
│   ├── Playwright bridge (new — React-safe)
│   ├── AI resolver (new — Stagehand patterns + Theta EdgeCloud)
│   ├── Session store (new — cookie/localStorage persistence)
│   └── CDP recorder (new — record/replay)
└── Persistent volume
    ├── /config/browser-profiles/ — saved sessions
    └── /config/recordings/ — CDP recordings
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SURF_API_KEY` | `surf-default-key` | API authentication key |
| `CDP_HOST` | `127.0.0.1` | CDP host (localhost only) |
| `CDP_PORT` | `9222` | CDP port |
| `API_PORT` | `8000` | FastAPI port |
| `THETA_API_KEY` | (empty) | Theta EdgeCloud API key |
| `THETA_API_URL` | `https://ai.thetaedgecloud.com/v1` | Theta EdgeCloud API URL |
| `VISION_MODEL` | `glm-4.9v-flash` | Vision model for AI resolution |
| `PROFILE_DIR` | `/config/browser-profiles` | Session storage directory |

## Deployment

1. Push to GitHub: `xBuildy/surf-cloud`
2. Railway auto-deploys from main branch
3. Set environment variables in Railway dashboard:
   - `THETA_API_KEY` — get from ThetaKey entity (wave-prod-2)
   - `SURF_API_KEY` — set a strong key
4. Verify health: `curl https://surf-cloud-production.up.railway.app/api/health`

## Integration with Wave OS

The `surfAutomateV2` backend function in Wave OS calls these endpoints.
The Wave Assistant (Theta EdgeCloud GLM-5.2) plans automation tasks and calls
this function, which forwards requests to Surf Cloud v2.

```
User: "Go check my competitor's pricing page"
  → Wave Assistant plans: navigate → wait → extract → save
  → Calls surfAutomateV2 backend function
  → surfAutomateV2 calls Surf Cloud /api/automate
  → Surf Cloud drives the browser (Playwright + AI)
  → Returns extracted data to Wave Assistant
  → Wave Assistant creates Notification + sends Telegram
```
