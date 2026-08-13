"""
Surf Cloud v2 — Per-User Browser Session Manager
Replaces single shared Chromium instance with isolated Playwright browser contexts per Wave OS user.
Provides per-user isolation of cookies, localStorage, sessionStorage, tabs, and recording.
Handles idle session timeout cleanup and maximum concurrent session eviction.
"""

import os
import sys
import time
import json
import logging
import asyncio
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Union

from pydantic import BaseModel, Field

logger = logging.getLogger("surf_cloud.session_manager")
logging.basicConfig(level=logging.INFO)

# Config defaults
PROFILE_DIR = os.environ.get("PROFILE_DIR", "/config/browser-profiles")
DEFAULT_MAX_SESSIONS = int(os.environ.get("MAX_SESSIONS", "50"))
DEFAULT_IDLE_TIMEOUT = int(os.environ.get("IDLE_TIMEOUT", "1800"))  # 30 min (1800 sec)

# Import Playwright if available
try:
    from playwright.async_api import async_playwright, Browser, BrowserContext, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    BrowserContext = Any
    Page = Any
    Browser = Any
    logger.warning("Playwright not installed in environment. Per-user isolation disabled.")


# ════════════════════════════════════════════════════════════════════════════
# DATA CLASSES & MODELS
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class UserSession:
    """Represents a single user's isolated browser session."""
    user_id: str
    context: Any  # Playwright BrowserContext
    active_page: Any  # current active Page for this user
    created_at: float
    last_active: float
    pages: List[Any] = field(default_factory=list)  # all open pages/tabs for this user


# Pydantic Models for API v2 requests
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
    wait_type: str = "element"

class UserSessionRequest(BaseModel):
    api_key: str = ""
    user_id: str
    name: str = "default"

class UserNewPageRequest(BaseModel):
    api_key: str = ""
    user_id: str
    url: str = "about:blank"

class UserClosePageRequest(BaseModel):
    api_key: str = ""
    user_id: str
    page_index: int = 0

class UserAutomateStep(BaseModel):
    action: str
    params: dict = {}

class UserAutomateRequest(BaseModel):
    api_key: str = ""
    user_id: str
    steps: list[UserAutomateStep]
    session: str = ""

class UserPdfRequest(BaseModel):
    api_key: str = ""
    user_id: str
    format: str = "A4"
    landscape: bool = False
    print_background: bool = True

class UserScreenshotRequest(BaseModel):
    api_key: str = ""
    user_id: str
    full_page: bool = False


# ════════════════════════════════════════════════════════════════════════════
# SESSION MANAGER CLASS
# ════════════════════════════════════════════════════════════════════════════

class SessionManager:
    """Manages per-user isolated browser sessions."""

    def __init__(
        self,
        cdp_host: str = "127.0.0.1",
        cdp_port: int = 9222,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        idle_timeout: int = DEFAULT_IDLE_TIMEOUT,
        profile_dir: str = PROFILE_DIR
    ):
        self._cdp_host = cdp_host
        self._cdp_port = cdp_port
        self._max_sessions = max_sessions
        self._idle_timeout = idle_timeout
        self._profile_dir = profile_dir

        self._playwright = None
        self._browser = None  # single Chromium instance via CDP
        self._sessions: Dict[str, UserSession] = {}  # user_id -> UserSession
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start(self):
        """Initialize Playwright and connect to Chromium via CDP."""
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("Playwright is not available — SessionManager cannot start Playwright CDP connection.")
            return

        async with self._lock:
            if self._browser is not None:
                try:
                    if self._browser.is_connected():
                        logger.info("SessionManager already connected to Chromium over CDP.")
                        return
                except Exception:
                    pass

            try:
                from playwright.async_api import async_playwright
                self._playwright = await async_playwright().start()
                cdp_url = f"http://{self._cdp_host}:{self._cdp_port}"
                logger.info(f"Connecting SessionManager to Chromium CDP at {cdp_url}...")
                self._browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
                logger.info("Successfully connected to Chromium via CDP!")
            except Exception as e:
                logger.error(f"Failed to connect to Chromium over CDP at http://{self._cdp_host}:{self._cdp_port}: {e}")
                logger.warning("SessionManager will attempt reconnection when a session is requested.")

            if self._cleanup_task is None or self._cleanup_task.done():
                self._cleanup_task = asyncio.create_task(self._cleanup_idle_sessions())
                logger.info(f"Idle cleanup background task started (timeout: {self._idle_timeout}s, max_sessions: {self._max_sessions})")

    async def _reconnect_cdp(self):
        """Internal helper to attempt connecting/reconnecting over CDP if connection dropped."""
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("Playwright is not available.")

        try:
            if self._playwright is None:
                from playwright.async_api import async_playwright
                self._playwright = await async_playwright().start()

            cdp_url = f"http://{self._cdp_host}:{self._cdp_port}"
            logger.info(f"Reconnecting SessionManager to CDP at {cdp_url}...")
            self._browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
            logger.info("CDP reconnection successful.")
        except Exception as e:
            logger.error(f"CDP reconnection failed: {e}")
            raise RuntimeError(f"Could not connect to browser over CDP: {e}") from e

    async def stop(self):
        """Clean up all sessions and disconnect."""
        async with self._lock:
            if self._cleanup_task and not self._cleanup_task.done():
                self._cleanup_task.cancel()
                try:
                    await self._cleanup_task
                except asyncio.CancelledError:
                    pass
                self._cleanup_task = None

            # Destroy all active user sessions
            user_ids = list(self._sessions.keys())
            for uid in user_ids:
                try:
                    await self._destroy_session_internal(uid)
                except Exception as e:
                    logger.error(f"Error destroying session for '{uid}' during stop: {e}")

            self._sessions.clear()

            if self._browser:
                try:
                    await self._browser.close()
                except Exception as e:
                    logger.debug(f"Error closing browser during stop: {e}")
                self._browser = None

            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception as e:
                    logger.debug(f"Error stopping playwright during stop: {e}")
                self._playwright = None

            logger.info("SessionManager stopped successfully.")

    async def get_or_create_session(self, user_id: str) -> UserSession:
        """Get existing session or create a new isolated browser context for this user."""
        if not user_id:
            raise ValueError("user_id is required for per-user session isolation.")

        async with self._lock:
            if user_id in self._sessions:
                session = self._sessions[user_id]
                session.last_active = time.time()

                # Clean closed pages
                valid_pages = []
                for p in session.pages:
                    try:
                        if not p.is_closed():
                            valid_pages.append(p)
                    except Exception:
                        pass
                session.pages = valid_pages

                if not session.pages:
                    new_page = await session.context.new_page()
                    session.pages = [new_page]
                    session.active_page = new_page
                elif session.active_page is None or session.active_page not in session.pages or session.active_page.is_closed():
                    session.active_page = session.pages[-1]

                return session

            # Evict oldest if at capacity
            if len(self._sessions) >= self._max_sessions:
                logger.warning(f"Max session limit ({self._max_sessions}) reached. Evicting oldest idle session...")
                await self._evict_oldest_session_internal()

            # Ensure CDP browser is connected
            if self._browser is None or not self._browser.is_connected():
                await self._reconnect_cdp()

            logger.info(f"Creating isolated BrowserContext for user '{user_id}'...")
            context = await self._browser.new_context()
            page = await context.new_page()
            now = time.time()

            session = UserSession(
                user_id=user_id,
                context=context,
                active_page=page,
                created_at=now,
                last_active=now,
                pages=[page]
            )
            self._sessions[user_id] = session

            # Auto-load saved session state if default profile exists
            try:
                await self._load_session_state_internal(user_id, "default", page=page)
                logger.info(f"Auto-loaded default session state for user '{user_id}'")
            except FileNotFoundError:
                pass  # No default session saved yet
            except Exception as e:
                logger.warning(f"Could not auto-load default session state for user '{user_id}': {e}")

            return session

    async def get_page(self, user_id: str) -> Page:
        """Get the active page for a user."""
        session = await self.get_or_create_session(user_id)
        session.last_active = time.time()

        valid_pages = []
        for p in session.pages:
            try:
                if not p.is_closed():
                    valid_pages.append(p)
            except Exception:
                pass
        session.pages = valid_pages

        if not session.pages:
            new_page = await session.context.new_page()
            session.pages = [new_page]
            session.active_page = new_page
        elif session.active_page is None or session.active_page not in session.pages or session.active_page.is_closed():
            session.active_page = session.pages[-1]

        return session.active_page

    async def new_page(self, user_id: str, url: str = "about:blank") -> Page:
        """Create a new page/tab in the user's context."""
        session = await self.get_or_create_session(user_id)
        session.last_active = time.time()

        page = await session.context.new_page()
        if url and url != "about:blank":
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                logger.warning(f"Error navigating new page to {url} for user '{user_id}': {e}")

        session.pages.append(page)
        session.active_page = page
        return page

    async def list_pages(self, user_id: str) -> list[dict]:
        """List all pages/tabs for a user."""
        session = await self.get_or_create_session(user_id)
        session.last_active = time.time()

        valid_pages = []
        for p in session.pages:
            try:
                if not p.is_closed():
                    valid_pages.append(p)
            except Exception:
                pass
        session.pages = valid_pages

        result = []
        for idx, page in enumerate(session.pages):
            page_url = ""
            page_title = ""
            try:
                page_url = page.url
            except Exception:
                pass
            try:
                page_title = await page.title()
            except Exception:
                pass

            is_active = (page == session.active_page)
            result.append({
                "index": idx,
                "url": page_url,
                "title": page_title,
                "is_active": is_active
            })

        return result

    async def close_page(self, user_id: str, page_index: int) -> bool:
        """Close a specific page in the user's session."""
        session = await self.get_or_create_session(user_id)
        session.last_active = time.time()

        valid_pages = []
        for p in session.pages:
            try:
                if not p.is_closed():
                    valid_pages.append(p)
            except Exception:
                pass
        session.pages = valid_pages

        if 0 <= page_index < len(session.pages):
            target_page = session.pages.pop(page_index)
            try:
                await target_page.close()
            except Exception as e:
                logger.warning(f"Error closing page {page_index} for user '{user_id}': {e}")

            if session.active_page == target_page:
                if session.pages:
                    session.active_page = session.pages[-1]
                else:
                    new_page = await session.context.new_page()
                    session.pages = [new_page]
                    session.active_page = new_page

            return True

        return False

    async def destroy_session(self, user_id: str) -> bool:
        """Destroy a user's session and clean up."""
        async with self._lock:
            return await self._destroy_session_internal(user_id)

    async def _destroy_session_internal(self, user_id: str) -> bool:
        if user_id not in self._sessions:
            return False

        session = self._sessions.pop(user_id)
        try:
            await session.context.close()
        except Exception as e:
            logger.error(f"Error closing BrowserContext for user '{user_id}': {e}")

        logger.info(f"Destroyed session for user '{user_id}'")
        return True

    async def list_active_sessions(self) -> list[dict]:
        """List all active sessions with metadata (user_id, created_at, last_active, page_count)."""
        now = time.time()
        result = []

        async with self._lock:
            for uid, session in list(self._sessions.items()):
                valid_pages = []
                for p in session.pages:
                    try:
                        if not p.is_closed():
                            valid_pages.append(p)
                    except Exception:
                        pass

                active_url = ""
                try:
                    if session.active_page and not session.active_page.is_closed():
                        active_url = session.active_page.url
                except Exception:
                    pass

                result.append({
                    "user_id": uid,
                    "created_at": session.created_at,
                    "created_at_iso": datetime.fromtimestamp(session.created_at).isoformat(),
                    "last_active": session.last_active,
                    "idle_seconds": round(now - session.last_active, 1),
                    "page_count": len(valid_pages),
                    "active_page_url": active_url
                })

        return result

    async def get_session_info(self, user_id: str) -> dict:
        """Get info about a specific user's session."""
        now = time.time()
        if user_id not in self._sessions:
            return {
                "active": False,
                "user_id": user_id
            }

        session = self._sessions[user_id]
        pages_list = await self.list_pages(user_id)

        return {
            "active": True,
            "user_id": user_id,
            "created_at": session.created_at,
            "created_at_iso": datetime.fromtimestamp(session.created_at).isoformat(),
            "last_active": session.last_active,
            "idle_seconds": round(now - session.last_active, 1),
            "page_count": len(pages_list),
            "pages": pages_list
        }

    async def _cleanup_idle_sessions(self):
        """Background task that destroys sessions idle for longer than idle_timeout."""
        logger.info(f"Idle cleanup background worker started (checking every 60s, timeout={self._idle_timeout}s)")
        while True:
            try:
                await asyncio.sleep(60)
                now = time.time()
                to_destroy = []

                async with self._lock:
                    for uid, session in list(self._sessions.items()):
                        idle_time = now - session.last_active
                        if idle_time > self._idle_timeout:
                            to_destroy.append((uid, round(idle_time, 1)))

                    for uid, idle_secs in to_destroy:
                        logger.info(f"Session for user '{uid}' idle for {idle_secs}s (> timeout {self._idle_timeout}s). Destroying...")
                        try:
                            await self._save_session_state_internal(uid, "auto_save")
                        except Exception as e:
                            logger.warning(f"Could not auto-save state for user '{uid}' before idle cleanup: {e}")

                        await self._destroy_session_internal(uid)

            except asyncio.CancelledError:
                logger.info("Idle cleanup background task cancelled.")
                break
            except Exception as e:
                logger.error(f"Error in idle session cleanup loop: {e}")

    async def _evict_oldest_session(self):
        """Evict the oldest idle session when at max capacity."""
        async with self._lock:
            await self._evict_oldest_session_internal()

    async def _evict_oldest_session_internal(self):
        if not self._sessions:
            return

        oldest_uid = min(self._sessions.keys(), key=lambda u: self._sessions[u].last_active)
        oldest_session = self._sessions[oldest_uid]
        idle_secs = round(time.time() - oldest_session.last_active, 1)

        logger.info(f"Evicting oldest session '{oldest_uid}' (idle for {idle_secs}s, capacity limit={self._max_sessions})")

        try:
            await self._save_session_state_internal(oldest_uid, "auto_evict")
        except Exception as e:
            logger.warning(f"Could not auto-save state before evicting user '{oldest_uid}': {e}")

        await self._destroy_session_internal(oldest_uid)

    async def save_session_state(self, user_id: str, name: str = "default") -> dict:
        """Save the user's browser state (cookies + localStorage) to persistent storage."""
        page = await self.get_page(user_id)
        return await self._save_session_state_internal(user_id, name, page=page)

    async def _save_session_state_internal(self, user_id: str, name: str = "default", page: Optional[Page] = None) -> dict:
        if page is None:
            if user_id in self._sessions:
                page = self._sessions[user_id].active_page
            else:
                raise ValueError(f"No active session found for user '{user_id}' to save state.")

        from session_store import SessionStore
        user_dir = os.path.join(self._profile_dir, user_id)
        os.makedirs(user_dir, exist_ok=True)

        store = SessionStore(storage_dir=user_dir)
        result = await store.save_session(page, name)
        logger.info(f"Saved session profile '{name}' for user '{user_id}' to {user_dir}")
        return result

    async def load_session_state(self, user_id: str, name: str = "default") -> dict:
        """Load a saved browser state for this user."""
        page = await self.get_page(user_id)
        return await self._load_session_state_internal(user_id, name, page=page)

    async def _load_session_state_internal(self, user_id: str, name: str = "default", page: Optional[Page] = None) -> dict:
        if page is None:
            if user_id in self._sessions:
                page = self._sessions[user_id].active_page
            else:
                raise ValueError(f"No active session found for user '{user_id}' to load state onto.")

        from session_store import SessionStore
        user_dir = os.path.join(self._profile_dir, user_id)

        store = SessionStore(storage_dir=user_dir)
        result = await store.load_session(page, name)
        logger.info(f"Loaded session profile '{name}' for user '{user_id}' from {user_dir}")
        return result


# Singleton instance helper
_global_session_manager: Optional[SessionManager] = None


def get_session_manager(
    cdp_host: str = "127.0.0.1",
    cdp_port: int = 9222,
    max_sessions: int = DEFAULT_MAX_SESSIONS,
    idle_timeout: int = DEFAULT_IDLE_TIMEOUT
) -> SessionManager:
    """Get or create the global singleton SessionManager instance."""
    global _global_session_manager
    if _global_session_manager is None:
        _global_session_manager = SessionManager(
            cdp_host=cdp_host,
            cdp_port=cdp_port,
            max_sessions=max_sessions,
            idle_timeout=idle_timeout
        )
    return _global_session_manager
