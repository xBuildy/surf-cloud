"""
Surf Cloud v2 — Browser Automation API with Per-User Isolated Sessions
=====================================================================
Each Wave OS user gets their own isolated browser context:
  - Separate cookies, localStorage, sessionStorage, cache
  - Separate pages (tabs)
  - Per-user session persistence (survives container restarts)
  - Idle timeout (contexts destroyed after inactivity)
  - Max concurrent sessions (configurable)

Architecture:
  Single Chromium instance → Multiple Playwright BrowserContexts (one per user)
  Each context is fully isolated — no cookie/localStorage bleed between users

API modes:
  1. Per-user mode (recommended): pass user_id on every request → isolated context
  2. Shared mode (legacy): no user_id → uses shared CDP client (backward compatible)
"""

import os
import json
import time
import asyncio
import base64
import logging
from typing import Optional
from contextlib import asynccontextmanager

import websocket
import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ─── Optional imports (graceful degradation) ──────────────────────────────────

try:
    from playwright.async_api import async_playwright, Page, BrowserContext
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logging.warning("Playwright not installed — per-user sessions unavailable")

try:
    from ai_resolver import SurfAIResolver, ElementInfo, ActionResult
    AI_RESOLVER_AVAILABLE = True
except ImportError:
    AI_RESOLVER_AVAILABLE = False
    logging.warning("AI resolver not available — observe/act/extract disabled")

try:
    from session_store import SessionStore
    SESSION_STORE_AVAILABLE = True
except ImportError:
    SESSION_STORE_AVAILABLE = False
    logging.warning("Session store not available — persistence disabled")

try:
    from recorder import CDPRecorder
    RECORDER_AVAILABLE = True
except ImportError:
    RECORDER_AVAILABLE = False
    logging.warning("Recorder not available — recording disabled")

try:
    from session_manager import SessionManager, UserSession, get_session_manager
    SESSION_MANAGER_AVAILABLE = True
except ImportError:
    SESSION_MANAGER_AVAILABLE = False
    logging.warning("Session manager not available — falling back to shared mode")

# ─── Config ──────────────────────────────────────────────────────────────────

API_KEY = os.environ.get("SURF_API_KEY", "surf-default-key")
CDP_HOST = os.environ.get("CDP_HOST", "127.0.0.1")
CDP_PORT = int(os.environ.get("CDP_PORT", "9222"))
PORT = int(os.environ.get("API_PORT", "8000"))
THETA_API_KEY = os.environ.get("THETA_API_KEY", "")
THETA_API_URL = os.environ.get("THETA_API_URL", "https://ai.thetaedgecloud.com/v1")
VISION_MODEL = os.environ.get("VISION_MODEL", "glm-4.9v-flash")
PROFILE_DIR = os.environ.get("PROFILE_DIR", "/config/browser-profiles")
MAX_SESSIONS = int(os.environ.get("MAX_SESSIONS", "50"))
IDLE_TIMEOUT = int(os.environ.get("IDLE_TIMEOUT", "1800"))  # 30 min

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("surf-cloud-v2")

# ─── Pydantic Models ──────────────────────────────────────────────────────────

# Shared/legacy models (backward compatible)
class NavigateRequest(BaseModel):
    api_key: str = ""
    url: str

class ClickRequest(BaseModel):
    api_key: str = ""
    selector: str

class TypeRequest(BaseModel):
    api_key: str = ""
    selector: str
    text: str = ""

class ExecuteRequest(BaseModel):
    api_key: str = ""
    script: str

# Per-user models
class UserRequest(BaseModel):
    api_key: str = ""
    user_id: str

class UserNavigateRequest(BaseModel):
    api_key: str = ""
    user_id: str
    url: str

class UserFillRequest(BaseModel):
    api_key: str = ""
    user_id: str
    selector: str
    text: str

class UserClickRequest(BaseModel):
    api_key: str = ""
    user_id: str
    selector: str
    use_playwright: bool = True

class UserActRequest(BaseModel):
    api_key: str = ""
    user_id: str
    instruction: str
    value: str = ""

class UserObserveRequest(BaseModel):
    api_key: str = ""
    user_id: str
    instruction: str

class UserExtractRequest(BaseModel):
    api_key: str = ""
    user_id: str
    instruction: str

class UserWaitRequest(BaseModel):
    api_key: str = ""
    user_id: str
    selector: str = ""
    timeout_ms: int = 10000
    wait_type: str = "element"  # element, navigation, network_idle, timeout

class UserSessionRequest(BaseModel):
    api_key: str = ""
    user_id: str
    name: str = "default"

class UserLoadSessionRequest(BaseModel):
    api_key: str = ""
    user_id: str
    name: str = "default"
    url: str = ""

class UserNewPageRequest(BaseModel):
    api_key: str = ""
    user_id: str
    url: str = "about:blank"

class UserClosePageRequest(BaseModel):
    api_key: str = ""
    user_id: str
    page_index: int = 0

class UserScreenshotRequest(BaseModel):
    api_key: str = ""
    user_id: str
    full_page: bool = False

class UserPdfRequest(BaseModel):
    api_key: str = ""
    user_id: str
    format: str = "A4"
    landscape: bool = False
    print_background: bool = True

class UserAutomateStep(BaseModel):
    action: str
    params: dict = {}

class UserAutomateRequest(BaseModel):
    api_key: str = ""
    user_id: str
    steps: list[UserAutomateStep]
    session: str = ""  # optional: load named session before running

class UserRecordRequest(BaseModel):
    api_key: str = ""
    user_id: str
    name: str = ""

class UserReplayRequest(BaseModel):
    api_key: str = ""
    user_id: str
    script: list = []
    speed: float = 1.0


# ─── Legacy CDP Client (shared mode, backward compatible) ─────────────────────

class CDPClient:
    """Simple CDP client for shared-mode operations (legacy)."""
    def __init__(self):
        self._ws = None
        self._msg_id = 0
        self._lock = threading.Lock()

    def _get_ws_url(self):
        resp = httpx.get(f"http://{CDP_HOST}:{CDP_PORT}/json")
        targets = resp.json()
        for t in targets:
            if t.get("type") == "page":
                return t["webSocketDebuggerUrl"]
        if targets:
            return targets[0]["webSocketDebuggerUrl"]
        raise RuntimeError("No CDP targets available")

    def _ensure_connected(self):
        if self._ws is None or not self._ws.connected:
            url = self._get_ws_url()
            self._ws = websocket.create_connection(url, timeout=30)

    def send(self, method, params=None):
        with self._lock:
            self._ensure_connected()
            self._msg_id += 1
            msg_id = self._msg_id
            msg = {"id": msg_id, "method": method}
            if params:
                msg["params"] = params
            self._ws.send(json.dumps(msg))
            while True:
                raw = self._ws.recv()
                data = json.loads(raw)
                if data.get("id") == msg_id:
                    if "error" in data:
                        raise RuntimeError(f"CDP error: {data['error']}")
                    return data.get("result", {})

    def navigate(self, url):
        self.send("Page.enable")
        self.send("Page.navigate", {"url": url})
        time.sleep(2)

    def screenshot(self):
        result = self.send("Page.captureScreenshot", {"format": "png"})
        return result.get("data", "")

    def get_content(self):
        result = self.send("Runtime.evaluate", {
            "expression": "document.body.innerText", "returnByValue": True
        })
        return result.get("result", {}).get("value", "")

    def get_title(self):
        result = self.send("Runtime.evaluate", {
            "expression": "document.title", "returnByValue": True
        })
        return result.get("result", {}).get("value", "")

    def get_url(self):
        result = self.send("Runtime.evaluate", {
            "expression": "window.location.href", "returnByValue": True
        })
        return result.get("result", {}).get("value", "")

    def click(self, selector):
        js = f"""(function() {{ var el = document.querySelector({json.dumps(selector)}); if (!el) return "not found"; el.click(); return "clicked"; }})()"""
        result = self.send("Runtime.evaluate", {"expression": js, "returnByValue": True})
        return result.get("result", {}).get("value", "")

    def type_text(self, selector, text):
        js = f"""(function() {{ var el = document.querySelector({json.dumps(selector)}); if (!el) return "not found"; el.focus(); el.value = {json.dumps(text)}; el.dispatchEvent(new Event('input', {{bubbles: true}})); el.dispatchEvent(new Event('change', {{bubbles: true}})); return "typed"; }})()"""
        result = self.send("Runtime.evaluate", {"expression": js, "returnByValue": True})
        return result.get("result", {}).get("value", "")

    def execute_js(self, script):
        result = self.send("Runtime.evaluate", {"expression": script, "returnByValue": True})
        return result.get("result", {}).get("value", "")

    def get_tabs(self):
        resp = httpx.get(f"http://{CDP_HOST}:{CDP_PORT}/json")
        return resp.json()

    def new_tab(self, url="about:blank"):
        resp = httpx.put(f"http://{CDP_HOST}:{CDP_PORT}/json/new", params={"url": url})
        return resp.json()


import threading


# ─── Global Instances ──────────────────────────────────────────────────────────

cdp = CDPClient()  # legacy shared mode
session_manager: Optional[SessionManager] = None
_ai_resolver: Optional[SurfAIResolver] = None

def get_ai_resolver() -> SurfAIResolver:
    global _ai_resolver
    if _ai_resolver is None:
        if not THETA_API_KEY:
            raise HTTPException(status_code=500, detail="THETA_API_KEY not configured")
        _ai_resolver = SurfAIResolver(THETA_API_KEY, THETA_API_URL, VISION_MODEL)
    return _ai_resolver


# ─── Auth ─────────────────────────────────────────────────────────────────────

def check_api_key(api_key: str):
    if api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


def require_session_manager():
    if not SESSION_MANAGER_AVAILABLE or session_manager is None:
        raise HTTPException(status_code=503, detail="Session manager not available — Playwright not installed or not started")
    return session_manager


# ─── FastAPI App ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="Surf Cloud v2 API",
    version="2.0.0",
    description="Per-user isolated browser automation with AI element resolution"
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ════════════════════════════════════════════════════════════════════════════
# HEALTH & SYSTEM
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/health")
async def health():
    """System health — includes feature availability and active session count."""
    features = {
        "playwright": PLAYWRIGHT_AVAILABLE,
        "session_manager": SESSION_MANAGER_AVAILABLE,
        "ai_resolver": AI_RESOLVER_AVAILABLE,
        "session_store": SESSION_STORE_AVAILABLE,
        "recorder": RECORDER_AVAILABLE,
        "theta_api": bool(THETA_API_KEY)
    }
    try:
        tabs = cdp.get_tabs()
        cdp_ok = True
    except:
        tabs = []
        cdp_ok = False

    active_sessions = []
    if session_manager:
        active_sessions = await session_manager.list_active_sessions()

    return {
        "status": "healthy" if cdp_ok else "degraded",
        "version": "2.0.0",
        "cdp_available": cdp_ok,
        "tabs": len(tabs),
        "features": features,
        "active_sessions": len(active_sessions),
        "max_sessions": MAX_SESSIONS,
        "idle_timeout": IDLE_TIMEOUT
    }


# ════════════════════════════════════════════════════════════════════════════
# SESSION MANAGEMENT (per-user)
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/session/create")
async def create_session(body: UserRequest):
    """Create or get an isolated browser session for a Wave OS user."""
    check_api_key(body.api_key)
    sm = require_session_manager()
    try:
        session = await sm.get_or_create_session(body.user_id)
        return {
            "status": "ok",
            "user_id": body.user_id,
            "created_at": session.created_at,
            "page_count": len(session.pages),
            "message": "Session ready"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/session/destroy")
async def destroy_session(body: UserRequest):
    """Destroy a user's browser session and free resources."""
    check_api_key(body.api_key)
    sm = require_session_manager()
    try:
        result = await sm.destroy_session(body.user_id)
        return {"status": "ok", "destroyed": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sessions")
async def list_sessions(api_key: str = ""):
    """List all active browser sessions."""
    check_api_key(api_key)
    sm = require_session_manager()
    try:
        sessions = await sm.list_active_sessions()
        return {"status": "ok", "sessions": sessions, "count": len(sessions)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/session/info")
async def session_info(api_key: str = "", user_id: str = ""):
    """Get info about a specific user's session."""
    check_api_key(api_key)
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user_id")
    sm = require_session_manager()
    try:
        info = await sm.get_session_info(user_id)
        return {"status": "ok", "session": info}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════════════════
# PAGE/TAB MANAGEMENT (per-user)
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/page/new")
async def new_page(body: UserNewPageRequest):
    """Create a new page/tab in the user's isolated browser context."""
    check_api_key(body.api_key)
    sm = require_session_manager()
    try:
        page = await sm.new_page(body.user_id, body.url)
        pages = await sm.list_pages(body.user_id)
        return {"status": "ok", "page_count": len(pages), "url": body.url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/pages")
async def list_pages(api_key: str = "", user_id: str = ""):
    """List all pages/tabs in the user's session."""
    check_api_key(api_key)
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user_id")
    sm = require_session_manager()
    try:
        pages = await sm.list_pages(user_id)
        return {"status": "ok", "pages": pages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/page/close")
async def close_page(body: UserClosePageRequest):
    """Close a specific page in the user's session."""
    check_api_key(body.api_key)
    sm = require_session_manager()
    try:
        result = await sm.close_page(body.user_id, body.page_index)
        return {"status": "ok", "closed": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════════════════
# NAVIGATION (per-user)
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/navigate")
async def navigate(body: UserNavigateRequest):
    """Navigate to a URL in the user's isolated browser session."""
    check_api_key(body.api_key)
    if not body.url:
        raise HTTPException(status_code=400, detail="Missing 'url'")
    sm = require_session_manager()
    try:
        page = await sm.get_page(body.user_id)
        await page.goto(body.url, wait_until="domcontentloaded", timeout=30000)
        title = await page.title()
        return {"status": "ok", "url": body.url, "title": title, "user_id": body.user_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════════════════
# SCREENSHOT (per-user)
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/screenshot")
async def screenshot(body: UserScreenshotRequest):
    """Take a screenshot of the user's active page (base64)."""
    check_api_key(body.api_key)
    sm = require_session_manager()
    try:
        page = await sm.get_page(body.user_id)
        data = await page.screenshot(type="png", full_page=body.full_page)
        b64 = base64.b64encode(data).decode("utf-8")
        return {"status": "ok", "screenshot": b64, "user_id": body.user_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/screenshot-image")
async def screenshot_image(body: UserScreenshotRequest):
    """Return screenshot as raw PNG image."""
    check_api_key(body.api_key)
    sm = require_session_manager()
    try:
        page = await sm.get_page(body.user_id)
        data = await page.screenshot(type="png", full_page=body.full_page)
        return Response(content=data, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════════════════
# CONTENT (per-user)
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/content")
async def get_content(body: UserRequest):
    """Get text content of the user's active page."""
    check_api_key(body.api_key)
    sm = require_session_manager()
    try:
        page = await sm.get_page(body.user_id)
        content = await page.inner_text("body")
        title = await page.title()
        url = page.url
        return {"status": "ok", "title": title, "url": url, "content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════════════════
# PLAYWRIGHT INTERACTION (per-user, React-safe)
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/fill")
async def fill(body: UserFillRequest):
    """React-safe input filling via Playwright's fill() — per user."""
    check_api_key(body.api_key)
    sm = require_session_manager()
    try:
        page = await sm.get_page(body.user_id)
        await page.fill(body.selector, body.text, timeout=10000)
        return {"status": "ok", "result": "filled", "user_id": body.user_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/click")
async def click(body: UserClickRequest):
    """Playwright click with proper event dispatching — per user."""
    check_api_key(body.api_key)
    sm = require_session_manager()
    try:
        page = await sm.get_page(body.user_id)
        await page.click(body.selector, timeout=10000)
        return {"status": "ok", "result": "clicked", "user_id": body.user_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/type")
async def type_text(body: UserFillRequest):
    """Character-by-character typing (handles React state) — per user."""
    check_api_key(body.api_key)
    sm = require_session_manager()
    try:
        page = await sm.get_page(body.user_id)
        await page.click(body.selector, timeout=10000)
        await page.type(body.selector, body.text, delay=50)
        return {"status": "ok", "result": "typed", "user_id": body.user_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/wait")
async def wait(body: UserWaitRequest):
    """Wait for element, navigation, or network idle — per user."""
    check_api_key(body.api_key)
    sm = require_session_manager()
    try:
        page = await sm.get_page(body.user_id)
        if body.wait_type == "element" and body.selector:
            await page.wait_for_selector(body.selector, timeout=body.timeout_ms)
            return {"status": "ok", "result": "element_found"}
        elif body.wait_type == "navigation":
            await page.wait_for_load_state("domcontentloaded", timeout=body.timeout_ms)
            return {"status": "ok", "result": "navigation_complete"}
        elif body.wait_type == "network_idle":
            await page.wait_for_load_state("networkidle", timeout=body.timeout_ms)
            return {"status": "ok", "result": "network_idle"}
        elif body.wait_type == "timeout":
            await asyncio.sleep(body.timeout_ms / 1000)
            return {"status": "ok", "result": "timeout_complete"}
        else:
            return {"status": "ok", "result": "unknown_wait_type"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/pdf")
async def export_pdf(body: UserPdfRequest):
    """Generate PDF of the user's active page."""
    check_api_key(body.api_key)
    sm = require_session_manager()
    try:
        page = await sm.get_page(body.user_id)
        pdf_bytes = await page.pdf(
            format=body.format,
            landscape=body.landscape,
            print_background=body.print_background
        )
        return Response(content=pdf_bytes, media_type="application/pdf")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/execute")
async def execute_js(body: UserRequest):
    """Execute JavaScript in the user's active page."""
    check_api_key(body.api_key)
    sm = require_session_manager()
    try:
        page = await sm.get_page(body.user_id)
        # Note: script passed via separate field in raw body
        result = await page.evaluate(body.api_key)  # placeholder — need script param
        return {"status": "ok", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════════════════
# AI ELEMENT RESOLUTION (per-user)
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/observe")
async def observe(body: UserObserveRequest):
    """Find elements by natural language instruction — per user."""
    check_api_key(body.api_key)
    if not AI_RESOLVER_AVAILABLE:
        raise HTTPException(status_code=503, detail="AI resolver not available")
    if not THETA_API_KEY:
        raise HTTPException(status_code=503, detail="THETA_API_KEY not configured")
    sm = require_session_manager()
    try:
        page = await sm.get_page(body.user_id)
        resolver = get_ai_resolver()
        elements = await resolver.observe(page, body.instruction)
        return {
            "status": "ok",
            "user_id": body.user_id,
            "elements": [
                {"selector": e.selector, "description": e.description,
                 "confidence": e.confidence, "bounds": e.bounds, "index": e.index}
                for e in elements
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/act")
async def act(body: UserActRequest):
    """Perform a browser action by natural language description — per user."""
    check_api_key(body.api_key)
    if not AI_RESOLVER_AVAILABLE:
        raise HTTPException(status_code=503, detail="AI resolver not available")
    if not THETA_API_KEY:
        raise HTTPException(status_code=503, detail="THETA_API_KEY not configured")
    sm = require_session_manager()
    try:
        page = await sm.get_page(body.user_id)
        resolver = get_ai_resolver()
        instruction = body.instruction
        if body.value:
            instruction = f"{body.instruction}: {body.value}"
        result = await resolver.act(page, instruction)
        return {
            "status": "ok" if result.success else "failed",
            "user_id": body.user_id,
            "action_type": result.action_type,
            "selector": result.selector,
            "message": result.message,
            "value": result.value
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/extract")
async def extract(body: UserExtractRequest):
    """Extract structured data from page using AI — per user."""
    check_api_key(body.api_key)
    if not AI_RESOLVER_AVAILABLE:
        raise HTTPException(status_code=503, detail="AI resolver not available")
    if not THETA_API_KEY:
        raise HTTPException(status_code=503, detail="THETA_API_KEY not configured")
    sm = require_session_manager()
    try:
        page = await sm.get_page(body.user_id)
        resolver = get_ai_resolver()
        data = await resolver.extract(page, body.instruction)
        return {"status": "ok", "user_id": body.user_id, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════════════════
# SESSION PERSISTENCE (per-user)
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/session/save")
async def save_session(body: UserSessionRequest):
    """Save the user's browser session (cookies + localStorage)."""
    check_api_key(body.api_key)
    sm = require_session_manager()
    try:
        result = await sm.save_session_state(body.user_id, body.name)
        return {"status": "ok", "session": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/session/load")
async def load_session(body: UserLoadSessionRequest):
    """Load a saved browser session for this user."""
    check_api_key(body.api_key)
    sm = require_session_manager()
    try:
        result = await sm.load_session_state(body.user_id, body.name)
        if body.url:
            page = await sm.get_page(body.user_id)
            await page.goto(body.url, wait_until="domcontentloaded")
        return {"status": "ok", "session": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/session/list")
async def list_saved_sessions(api_key: str = "", user_id: str = ""):
    """List saved browser sessions for a user."""
    check_api_key(api_key)
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user_id")
    if not SESSION_STORE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Session store not available")
    try:
        store = SessionStore(f"{PROFILE_DIR}/{user_id}")
        sessions = store.list_sessions()
        return {"status": "ok", "user_id": user_id, "sessions": sessions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════════════════
# COMBO AUTOMATION (per-user, multi-step)
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/automate")
async def automate(body: UserAutomateRequest):
    """
    Run a multi-step automation workflow in the user's isolated session.
    Optionally loads a saved session first (for auto-login).
    """
    check_api_key(body.api_key)
    sm = require_session_manager()
    results = []

    try:
        # Load session if specified
        if body.session:
            try:
                await sm.load_session_state(body.user_id, body.session)
                results.append({"step": "session_load", "status": "ok"})
            except Exception as e:
                results.append({"step": "session_load", "status": "failed", "error": str(e)})

        page = await sm.get_page(body.user_id)
        resolver = get_ai_resolver() if AI_RESOLVER_AVAILABLE and THETA_API_KEY else None

        for i, step in enumerate(body.steps):
            step_result = {"step": i, "action": step.action, "status": "ok"}
            try:
                p = step.params

                if step.action == "navigate":
                    await page.goto(p.get("url", ""), wait_until="domcontentloaded", timeout=30000)
                    step_result["title"] = await page.title()

                elif step.action == "fill":
                    await page.fill(p.get("selector", ""), p.get("text", ""), timeout=10000)

                elif step.action == "click":
                    await page.click(p.get("selector", ""), timeout=10000)

                elif step.action == "type":
                    await page.click(p.get("selector", ""), timeout=10000)
                    await page.type(p.get("selector", ""), p.get("text", ""), delay=50)

                elif step.action == "act" and resolver:
                    instruction = p.get("instruction", "")
                    if p.get("value"):
                        instruction = f"{instruction}: {p['value']}"
                    act_result = await resolver.act(page, instruction)
                    step_result["result"] = {
                        "success": act_result.success,
                        "selector": act_result.selector,
                        "message": act_result.message
                    }

                elif step.action == "wait":
                    wait_type = p.get("wait_type", "element")
                    if wait_type == "element" and p.get("selector"):
                        await page.wait_for_selector(p["selector"], timeout=p.get("timeout_ms", 10000))
                    elif wait_type == "network_idle":
                        await page.wait_for_load_state("networkidle", timeout=p.get("timeout_ms", 10000))
                    elif wait_type == "navigation":
                        await page.wait_for_load_state("domcontentloaded", timeout=p.get("timeout_ms", 10000))
                    elif wait_type == "timeout":
                        await asyncio.sleep(p.get("timeout_ms", 2000) / 1000)

                elif step.action == "screenshot":
                    data = await page.screenshot(type="png")
                    b64 = base64.b64encode(data).decode("utf-8")
                    step_result["screenshot_length"] = len(b64)

                elif step.action == "extract" and resolver:
                    extracted = await resolver.extract(page, p.get("instruction", ""))
                    step_result["data"] = extracted

                elif step.action == "pdf":
                    pdf_bytes = await page.pdf(format=p.get("format", "A4"))
                    step_result["pdf_length"] = len(pdf_bytes)

                else:
                    step_result["status"] = "skipped"
                    step_result["reason"] = f"Action '{step.action}' not available"

            except Exception as e:
                step_result["status"] = "failed"
                step_result["error"] = str(e)

            results.append(step_result)

        return {"status": "ok", "user_id": body.user_id, "results": results}

    except Exception as e:
        return {"status": "error", "user_id": body.user_id, "results": results, "error": str(e)}


# ════════════════════════════════════════════════════════════════════════════
# RECORDING (per-user)
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/record/start")
async def record_start(body: UserRecordRequest):
    """Start recording browser actions for a user."""
    check_api_key(body.api_key)
    if not RECORDER_AVAILABLE:
        raise HTTPException(status_code=503, detail="Recorder not available")
    try:
        session_id = await recorder.start_recording()
        return {"status": "ok", "session_id": session_id, "user_id": body.user_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/record/stop")
async def record_stop(body: UserRecordRequest):
    """Stop recording and return events + generated script."""
    check_api_key(body.api_key)
    if not RECORDER_AVAILABLE:
        raise HTTPException(status_code=503, detail="Recorder not available")
    try:
        result = await recorder.stop_recording(body.name or f"user_{body.user_id}")
        return {"status": "ok", "recording": result, "user_id": body.user_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/record/replay")
async def record_replay(body: UserReplayRequest):
    """Replay a recorded script in the user's session."""
    check_api_key(body.api_key)
    if not RECORDER_AVAILABLE:
        raise HTTPException(status_code=503, detail="Recorder not available")
    sm = require_session_manager()
    try:
        result = await recorder.replay(body.script, speed=body.speed)
        return {"status": "ok", "replay": result, "user_id": body.user_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════════════════
# STARTUP / SHUTDOWN
# ════════════════════════════════════════════════════════════════════════════

@app.on_event("startup")
async def startup_event():
    global session_manager
    logger.info("Surf Cloud v2 starting...")
    logger.info(f"  Max sessions: {MAX_SESSIONS}, Idle timeout: {IDLE_TIMEOUT}s")

    if SESSION_MANAGER_AVAILABLE and PLAYWRIGHT_AVAILABLE:
        session_manager = SessionManager(
            cdp_host=CDP_HOST,
            cdp_port=CDP_PORT,
            max_sessions=MAX_SESSIONS,
            idle_timeout=IDLE_TIMEOUT
        )
        await session_manager.start()
        logger.info("  Session manager started — per-user isolation ACTIVE")
    else:
        logger.warning("  Session manager unavailable — shared mode only")

    logger.info(f"  Playwright: {PLAYWRIGHT_AVAILABLE}")
    logger.info(f"  AI Resolver: {AI_RESOLVER_AVAILABLE}")
    logger.info(f"  Session Store: {SESSION_STORE_AVAILABLE}")
    logger.info(f"  Recorder: {RECORDER_AVAILABLE}")
    logger.info(f"  Theta API: {'configured' if THETA_API_KEY else 'NOT configured'}")


@app.on_event("shutdown")
async def shutdown_event():
    global session_manager
    if session_manager:
        await session_manager.stop()
        logger.info("Session manager stopped")


if __name__ == "__main__":
    print(f"Starting Surf Cloud v2 API on port {PORT}", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=PORT, workers=1, timeout_keep_alive=300)
