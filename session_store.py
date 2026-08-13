"""
Surf Cloud v2 — Cookie & Session Persistence Module
Saves and loads browser state (cookies, localStorage, sessionStorage) as named profiles.
Supports pre-seeding default sessions (e.g. wave_os_default) on container startup.
Supports per-user storage isolation via optional user_id parameter.
"""

import os
import json
import time
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional, Union

logger = logging.getLogger("surf_cloud.session_store")
logging.basicConfig(level=logging.INFO)

DEFAULT_STORAGE_DIR = "/config/browser-profiles"


class SessionStore:
    """
    Manages saving and loading browser auth state (cookies, localStorage, sessionStorage)
    stored as named profiles in JSON format. Supports per-user subdirectories.
    """

    def __init__(self, storage_dir: str = DEFAULT_STORAGE_DIR, user_id: Optional[str] = None):
        if user_id:
            if storage_dir.endswith(user_id):
                self.storage_dir = storage_dir
            else:
                self.storage_dir = os.path.join(storage_dir, user_id)
        else:
            self.storage_dir = storage_dir

        try:
            os.makedirs(self.storage_dir, exist_ok=True)
        except Exception as e:
            logger.warning(f"Failed to create storage dir {self.storage_dir}: {e}. Falling back to local ./browser-profiles.")
            fallback = os.path.join("./browser-profiles", user_id) if user_id else "./browser-profiles"
            self.storage_dir = fallback
            os.makedirs(self.storage_dir, exist_ok=True)

    async def save_cookies(self, cdp_client_or_page: Any, cookie_file: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Extract all cookies via CDP Network.getAllCookies or Playwright context and save to JSON.
        """
        cookies = []

        # Playwright Page / Context
        if hasattr(cdp_client_or_page, "context") and hasattr(cdp_client_or_page.context, "cookies"):
            cookies = await cdp_client_or_page.context.cookies()
        elif hasattr(cdp_client_or_page, "cookies") and callable(cdp_client_or_page.cookies):
            cookies = await cdp_client_or_page.cookies()
        # Custom CDP client
        elif hasattr(cdp_client_or_page, "send"):
            if asyncio_is_coroutine_function(cdp_client_or_page.send):
                res = await cdp_client_or_page.send("Network.getAllCookies")
            else:
                res = cdp_client_or_page.send("Network.getAllCookies")
            cookies = res.get("cookies", []) if isinstance(res, dict) else []

        if cookie_file:
            with open(cookie_file, "w", encoding="utf-8") as f:
                json.dump(cookies, f, indent=2)

        return cookies

    async def load_cookies(self, cdp_client_or_page: Any, cookie_file_or_data: Union[str, List[Dict[str, Any]]]) -> bool:
        """
        Load cookies from JSON file or list, and set via CDP Network.setCookie or Playwright add_cookies.
        """
        if isinstance(cookie_file_or_data, str):
            with open(cookie_file_or_data, "r", encoding="utf-8") as f:
                cookies = json.load(f)
        else:
            cookies = cookie_file_or_data

        if isinstance(cookies, dict) and "cookies" in cookies:
            cookies = cookies["cookies"]

        # Playwright Page / Context
        if hasattr(cdp_client_or_page, "context") and hasattr(cdp_client_or_page.context, "add_cookies"):
            await cdp_client_or_page.context.add_cookies(cookies)
        elif hasattr(cdp_client_or_page, "add_cookies") and callable(cdp_client_or_page.add_cookies):
            await cdp_client_or_page.add_cookies(cookies)
        # Custom CDP client
        elif hasattr(cdp_client_or_page, "send"):
            send_fn = cdp_client_or_page.send
            is_async = asyncio_is_coroutine_function(send_fn)

            # Try bulk Network.setCookies first
            try:
                if is_async:
                    await send_fn("Network.setCookies", {"cookies": cookies})
                else:
                    send_fn("Network.setCookies", {"cookies": cookies})
            except Exception:
                # Fallback to individual Network.setCookie
                for cookie in cookies:
                    try:
                        if is_async:
                            await send_fn("Network.setCookie", cookie)
                        else:
                            send_fn("Network.setCookie", cookie)
                    except Exception as cookie_err:
                        logger.debug(f"Failed setting cookie {cookie.get('name')}: {cookie_err}")

        return True

    async def save_local_storage(self, page: Any, storage_file: Optional[str] = None) -> Dict[str, str]:
        """
        Extract localStorage entries via Runtime.evaluate or page.evaluate and save to JSON.
        """
        js_code = """
        (function() {
            var store = {};
            for (var i = 0; i < localStorage.length; i++) {
                var k = localStorage.key(i);
                store[k] = localStorage.getItem(k);
            }
            return store;
        })()
        """
        data = await self._evaluate_js(page, js_code)
        if not isinstance(data, dict):
            data = {}

        if storage_file:
            with open(storage_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

        return data

    async def load_local_storage(self, page: Any, storage_file_or_data: Union[str, Dict[str, str]]) -> bool:
        """
        Load localStorage entries via Runtime.evaluate or page.evaluate.
        """
        if isinstance(storage_file_or_data, str):
            with open(storage_file_or_data, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = storage_file_or_data

        if not isinstance(data, dict):
            data = {}

        # Playwright page
        if hasattr(page, "evaluate") and callable(page.evaluate):
            await page.evaluate("""(items) => {
                for (let k in items) {
                    localStorage.setItem(k, items[k]);
                }
            }""", data)
        else:
            js_code = f"""
            (function() {{
                var items = {json.dumps(data)};
                for (var k in items) {{
                    localStorage.setItem(k, items[k]);
                }}
            }})()
            """
            await self._evaluate_js(page, js_code)

        return True

    async def save_session_storage(self, page: Any, storage_file: Optional[str] = None) -> Dict[str, str]:
        """
        Extract sessionStorage entries via Runtime.evaluate or page.evaluate and save to JSON.
        """
        js_code = """
        (function() {
            var store = {};
            for (var i = 0; i < sessionStorage.length; i++) {
                var k = sessionStorage.key(i);
                store[k] = sessionStorage.getItem(k);
            }
            return store;
        })()
        """
        data = await self._evaluate_js(page, js_code)
        if not isinstance(data, dict):
            data = {}

        if storage_file:
            with open(storage_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

        return data

    async def load_session_storage(self, page: Any, storage_file_or_data: Union[str, Dict[str, str]]) -> bool:
        """
        Load sessionStorage entries via Runtime.evaluate or page.evaluate.
        """
        if isinstance(storage_file_or_data, str):
            with open(storage_file_or_data, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = storage_file_or_data

        if not isinstance(data, dict):
            data = {}

        if hasattr(page, "evaluate") and callable(page.evaluate):
            await page.evaluate("""(items) => {
                for (let k in items) {
                    sessionStorage.setItem(k, items[k]);
                }
            }""", data)
        else:
            js_code = f"""
            (function() {{
                var items = {json.dumps(data)};
                for (var k in items) {{
                    sessionStorage.setItem(k, items[k]);
                }}
            }})()
            """
            await self._evaluate_js(page, js_code)

        return True

    async def save_session(self, page: Any, name: str) -> dict:
        """
        Save full session state (cookies + localStorage + sessionStorage) as a named profile JSON file.
        Returns summary of saved data.
        """
        cookies = await self.save_cookies(page)
        local_storage = await self.save_local_storage(page)
        session_storage = await self.save_session_storage(page)

        page_url = ""
        try:
            if hasattr(page, "url"):
                page_url = page.url if not callable(page.url) else page.url()
            else:
                page_url = await self._evaluate_js(page, "window.location.href")
        except Exception:
            pass

        profile_filename = f"{name}_session.json"
        profile_path = os.path.join(self.storage_dir, profile_filename)

        session_payload = {
            "name": name,
            "saved_at": datetime.now().isoformat(),
            "timestamp": time.time(),
            "url": page_url,
            "cookies": cookies,
            "localStorage": local_storage,
            "sessionStorage": session_storage
        }

        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(session_payload, f, indent=2)

        summary = {
            "name": name,
            "file_path": profile_path,
            "cookie_count": len(cookies),
            "local_storage_keys": len(local_storage),
            "session_storage_keys": len(session_storage),
            "saved_at": session_payload["saved_at"]
        }

        logger.info(f"Saved session profile '{name}' to {profile_path}")
        return summary

    async def load_session(self, page: Any, name: str) -> dict:
        """
        Load a named session profile (cookies + localStorage + sessionStorage) onto page.
        Returns summary of loaded data.
        """
        profile_path = os.path.join(self.storage_dir, f"{name}_session.json")
        if not os.path.exists(profile_path):
            alt_path = os.path.join(self.storage_dir, f"{name}.json")
            if os.path.exists(alt_path):
                profile_path = alt_path
            else:
                raise FileNotFoundError(f"Session profile '{name}' not found at {profile_path}")

        with open(profile_path, "r", encoding="utf-8") as f:
            session_data = json.load(f)

        cookies = session_data.get("cookies", [])
        local_storage = session_data.get("localStorage", {})
        session_storage = session_data.get("sessionStorage", {})

        await self.load_cookies(page, cookies)
        await self.load_local_storage(page, local_storage)
        await self.load_session_storage(page, session_storage)

        summary = {
            "name": name,
            "status": "loaded",
            "file_path": profile_path,
            "cookie_count": len(cookies),
            "local_storage_keys": len(local_storage),
            "session_storage_keys": len(session_storage),
            "saved_at": session_data.get("saved_at", "")
        }

        logger.info(f"Loaded session profile '{name}' from {profile_path}")
        return summary

    def list_sessions(self) -> List[str]:
        """
        List all saved session profiles in the storage directory.
        """
        if not os.path.exists(self.storage_dir):
            return []

        sessions = []
        for fname in os.listdir(self.storage_dir):
            if fname.endswith("_session.json"):
                name = fname[:-13]
                if name not in sessions:
                    sessions.append(name)
            elif fname.endswith(".json"):
                name = fname[:-5]
                if name not in sessions:
                    sessions.append(name)

        return sorted(sessions)

    def delete_session(self, name: str) -> bool:
        """
        Delete a session profile file. Returns True if deleted, False if not found.
        """
        profile_path = os.path.join(self.storage_dir, f"{name}_session.json")
        deleted = False

        if os.path.exists(profile_path):
            os.remove(profile_path)
            deleted = True

        alt_path = os.path.join(self.storage_dir, f"{name}.json")
        if os.path.exists(alt_path):
            os.remove(alt_path)
            deleted = True

        if deleted:
            logger.info(f"Deleted session profile '{name}'")
        return deleted

    async def auto_load_default_session(self, page: Any) -> Optional[dict]:
        """
        Pre-seed check: if 'wave_os_default' session exists, auto-load it on container startup.
        """
        sessions = self.list_sessions()
        if "wave_os_default" in sessions:
            logger.info("Pre-seeded 'wave_os_default' session found. Auto-loading on startup...")
            return await self.load_session(page, "wave_os_default")
        return None

    async def _evaluate_js(self, page: Any, js_code: str) -> Any:
        """Helper to evaluate JS code across different page/CDP client objects."""
        if hasattr(page, "evaluate") and callable(page.evaluate):
            return await page.evaluate(js_code)
        elif hasattr(page, "execute_js") and callable(page.execute_js):
            return page.execute_js(js_code)
        elif hasattr(page, "send"):
            send_fn = page.send
            payload = {"expression": js_code, "returnByValue": True}
            if asyncio_is_coroutine_function(send_fn):
                res = await send_fn("Runtime.evaluate", payload)
            else:
                res = send_fn("Runtime.evaluate", payload)
            return res.get("result", {}).get("value")
        return None


def asyncio_is_coroutine_function(fn: Any) -> bool:
    import inspect
    return inspect.iscoroutinefunction(fn)


# Module-level convenience functions using default SessionStore instance
default_store = SessionStore()


async def save_cookies(cdp_client_or_page: Any, cookie_file: Optional[str] = None) -> List[Dict[str, Any]]:
    return await default_store.save_cookies(cdp_client_or_page, cookie_file)


async def load_cookies(cdp_client_or_page: Any, cookie_file_or_data: Union[str, List[Dict[str, Any]]]) -> bool:
    return await default_store.load_cookies(cdp_client_or_page, cookie_file_or_data)


async def save_local_storage(page: Any, storage_file: Optional[str] = None) -> Dict[str, str]:
    return await default_store.save_local_storage(page, storage_file)


async def load_local_storage(page: Any, storage_file_or_data: Union[str, Dict[str, str]]) -> bool:
    return await default_store.load_local_storage(page, storage_file_or_data)


async def save_session(page: Any, name: str) -> dict:
    return await default_store.save_session(page, name)


async def load_session(page: Any, name: str) -> dict:
    return await default_store.load_session(page, name)


def list_sessions() -> List[str]:
    return default_store.list_sessions()


def delete_session(name: str) -> bool:
    return default_store.delete_session(name)


async def auto_load_default_session(page: Any) -> Optional[dict]:
    return await default_store.auto_load_default_session(page)
