"""
Wave Surf — CDP Automation API v2
Works alongside Neko WebRTC viewer + Thorium browser
All automation endpoints talk to CDP on localhost:9222
"""

import json
import asyncio
import httpx
import websockets
from fastapi import FastAPI, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from pydantic import BaseModel

import session_store
import ai_resolver

app = FastAPI(title="Wave Surf CDP API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CDP_URL = "http://127.0.0.1:9222"

# ===== Models =====

class NavigateRequest(BaseModel):
    url: str
    user_id: Optional[str] = "demo"

class ClickRequest(BaseModel):
    selector: str
    user_id: Optional[str] = "demo"

class TypeRequest(BaseModel):
    selector: str
    text: str
    user_id: Optional[str] = "demo"

class ObserveRequest(BaseModel):
    instruction: str
    user_id: Optional[str] = "demo"

class ActRequest(BaseModel):
    instruction: str
    user_id: Optional[str] = "demo"

class ExtractRequest(BaseModel):
    instruction: str
    max_results: Optional[int] = 5
    user_id: Optional[str] = "demo"

class AutomateRequest(BaseModel):
    task: str
    user_id: Optional[str] = "demo"

class ResizeRequest(BaseModel):
    width: int
    height: int
    user_id: Optional[str] = "demo"

# ===== CDP Helpers =====
#
# Correct CDP attach topology (this is the fix for the 15s /navigate hang):
#   1. Connect to the BROWSER-level websocket (/json/version -> webSocketDebuggerUrl).
#   2. Target.getTargets -> pick a REAL page target (http/https/about,
#      excluding extensions, background_page, devtools, "other").
#   3. Target.attachToTarget {flatten: true} -> get a sessionId.
#   4. Send Page.enable FIRST over that sessionId (missing Page.enable is a
#      classic cause of Page.* commands never resolving), then the real command.
#
# Previously we opened the PAGE target's own devtools socket and fired
# Page.navigate with no Page.enable — over the wrong topology, the response
# event never came back and every call ate the full 15s timeout.

CDP_TIMEOUT = 20.0


async def _get_browser_ws() -> str:
    """Fetch the browser-level CDP websocket debugger URL."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        res = await client.get(f"{CDP_URL}/json/version")
        ws = res.json().get("webSocketDebuggerUrl", "")
    return ws.replace("localhost", "127.0.0.1")


def _is_real_page(t: dict) -> bool:
    """A real, attachable browsing tab — not an extension/devtools/internal target."""
    if not isinstance(t, dict):
        return False
    if t.get("type") != "page":
        return False
    url = t.get("url", "") or ""
    for bad in ("chrome-extension://", "devtools://", "chrome-untrusted://"):
        if url.startswith(bad):
            return False
    return True


class CDPSession:
    """A single browser-socket connection with request/response correlation.

    Attaches (flatten) to a real page target, tracks its sessionId, and routes
    every command over that session. Resolves each command on its matching id.
    """

    def __init__(self, ws):
        self.ws = ws
        self._id = 0
        self.session_id = None

    def _next_id(self):
        self._id += 1
        return self._id

    async def send(self, method: str, params: dict = None, use_session: bool = True, timeout: float = CDP_TIMEOUT):
        """Send a CDP command and wait for its response (by id)."""
        msg_id = self._next_id()
        msg = {"id": msg_id, "method": method, "params": params or {}}
        if use_session and self.session_id:
            msg["sessionId"] = self.session_id
        await self.ws.send(json.dumps(msg))

        start = asyncio.get_event_loop().time()
        while True:
            remaining = timeout - (asyncio.get_event_loop().time() - start)
            if remaining <= 0:
                raise asyncio.TimeoutError(f"CDP timeout waiting for {method}")
            resp_str = await asyncio.wait_for(self.ws.recv(), timeout=remaining)
            resp = json.loads(resp_str)
            # Skip events and responses for other ids/sessions.
            if resp.get("id") == msg_id:
                if "error" in resp:
                    raise RuntimeError(f"CDP {method} error: {resp['error']}")
                return resp.get("result", {})

    async def attach_to_page(self):
        """Find a real page target and attach (flatten) to it."""
        targets = (await self.send("Target.getTargets", use_session=False)).get("targetInfos", [])
        page = next((t for t in targets if _is_real_page(t)), None)

        if not page:
            # No usable page target — create one on about:blank.
            created = await self.send("Target.createTarget", {"url": "about:blank"}, use_session=False)
            target_id = created.get("targetId")
        else:
            target_id = page.get("targetId")

        attached = await self.send(
            "Target.attachToTarget",
            {"targetId": target_id, "flatten": True},
            use_session=False,
        )
        self.session_id = attached.get("sessionId")
        if not self.session_id:
            raise RuntimeError("Target.attachToTarget returned no sessionId")
        # Enable the domains we rely on BEFORE issuing Page/Runtime commands.
        await self.send("Page.enable")
        await self.send("Runtime.enable")
        return self.session_id


async def _with_session(fn):
    """Open browser socket, attach to a page, run fn(session), always clean up."""
    ws_url = await _get_browser_ws()
    if not ws_url:
        return {"error": "No browser webSocketDebuggerUrl available"}
    async with websockets.connect(ws_url, open_timeout=10, close_timeout=5, max_size=None) as ws:
        session = CDPSession(ws)
        await session.attach_to_page()
        return await fn(session)


async def cdp_send(method: str, params: dict = None, session_id: str = None):
    """Back-compat helper: attach to a page and run a single command over the session.

    Returns {"result": ...} on success or {"error": ...} on failure, matching
    the shape the endpoints below already expect.
    """
    async def _run(session: CDPSession):
        try:
            result = await session.send(method, params or {})
            return {"result": result}
        except Exception as e:
            return {"error": str(e) or type(e).__name__}
    try:
        return await _with_session(_run)
    except Exception as e:
        return {"error": f"CDP connection failed: {str(e) or type(e).__name__}"}


async def cdp_navigate(url: str):
    """Navigate the attached page. Resolves on Page.navigate's OWN return
    (commit: frameId/loaderId present) — NOT on load-complete, so a slow
    subresource can't eat the timeout after the nav already succeeded."""
    async def _run(session: CDPSession):
        try:
            result = await session.send("Page.navigate", {"url": url})
            if result.get("errorText"):
                return {"error": result["errorText"]}
            return {"result": result}  # has frameId / loaderId = committed
        except Exception as e:
            return {"error": str(e) or type(e).__name__}
    try:
        return await _with_session(_run)
    except Exception as e:
        return {"error": f"CDP connection failed: {str(e) or type(e).__name__}"}


async def cdp_evaluate(expression: str):
    """Evaluate a JavaScript expression in the attached page."""
    async def _run(session: CDPSession):
        try:
            result = await session.send("Runtime.evaluate", {
                "expression": expression,
                "returnByValue": True,
            })
            return result.get("result", {}).get("value")
        except Exception:
            return None
    try:
        return await _with_session(_run)
    except Exception:
        return None


# ===== Endpoints =====

@app.get("/health")
@app.get("/api/health")
async def health():
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(f"{CDP_URL}/json/version")
            version = res.json()
            return {
                "status": "ok",
                "browser": version.get("Browser", "unknown"),
                "cdp": "connected",
                "engine": "thorium" if "Thorium" in version.get("Browser", "") else "chromium",
                "webrtc": "neko"
            }
    except Exception as e:
        err_msg = str(e) or type(e).__name__
        return {"status": "error", "message": err_msg, "cdp": "disconnected"}

@app.get("/debug/targets")
@app.get("/api/debug/targets")
async def debug_targets():
    """Temporary diagnostic endpoint: raw CDP target list + version info."""
    out = {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            v = await client.get(f"{CDP_URL}/json/version")
            out["version"] = v.json()
        except Exception as e:
            out["version_error"] = str(e)
        try:
            t = await client.get(f"{CDP_URL}/json")
            out["targets"] = t.json()
        except Exception as e:
            out["targets_error"] = str(e)
    return out

@app.post("/navigate")
@app.post("/api/navigate")
async def navigate(req: NavigateRequest):
    try:
        session_store.store.add_to_history(req.user_id, req.url)
        result = await cdp_navigate(req.url)
        if isinstance(result, dict) and "error" in result:
            return {"status": "error", "message": result["error"]}
        return {"status": "ok", "url": req.url, "committed": result.get("result", {})}
    except Exception as e:
        err_msg = str(e) or type(e).__name__
        return {"status": "error", "message": err_msg}

@app.post("/click")
@app.post("/api/click")
async def click(req: ClickRequest):
    try:
        js = f"""
        (function() {{
            var el = document.querySelector({json.dumps(req.selector)});
            if (el) {{ el.click(); return true; }}
            return false;
        }})()
        """
        result = await cdp_evaluate(js)
        return {"status": "ok" if result else "error", "clicked": bool(result)}
    except Exception as e:
        err_msg = str(e) or type(e).__name__
        return {"status": "error", "message": err_msg}

@app.post("/type")
@app.post("/api/type")
async def type_text(req: TypeRequest):
    try:
        js = f"""
        (function() {{
            var el = document.querySelector({json.dumps(req.selector)});
            if (el) {{
                el.focus();
                el.value = {json.dumps(req.text)};
                el.dispatchEvent(new Event('input', {{bubbles: true}}));
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
                return true;
            }}
            return false;
        }})()
        """
        result = await cdp_evaluate(js)
        return {"status": "ok" if result else "error", "typed": bool(result)}
    except Exception as e:
        err_msg = str(e) or type(e).__name__
        return {"status": "error", "message": err_msg}

@app.get("/content")
@app.get("/api/content")
async def get_content(user_id: Optional[str] = "demo"):
    try:
        js = "document.body.innerText"
        content = await cdp_evaluate(js)
        return {"status": "ok", "content": content or ""}
    except Exception as e:
        err_msg = str(e) or type(e).__name__
        return {"status": "error", "message": err_msg}

@app.post("/observe")
@app.post("/api/observe")
async def observe(req: ObserveRequest):
    try:
        content = await cdp_evaluate("document.body.innerHTML.substring(0, 5000)") or ""
        selector = await ai_resolver.resolve_element(req.instruction, content)
        if selector:
            return {"status": "ok", "elements": [{"description": req.instruction, "selector": selector, "method": "css"}]}
        return {"status": "error", "message": "Could not resolve element"}
    except Exception as e:
        err_msg = str(e) or type(e).__name__
        return {"status": "error", "message": err_msg}

@app.post("/act")
@app.post("/api/act")
async def act(req: ActRequest):
    try:
        observe_result = await observe(ObserveRequest(instruction=req.instruction, user_id=req.user_id))
        if observe_result.get("status") != "ok":
            return observe_result
        
        elements = observe_result.get("elements", [])
        if elements and len(elements) > 0:
            selector = elements[0]["selector"]
            click_result = await click(ClickRequest(selector=selector, user_id=req.user_id))
            return {"status": "ok", "action": "click", "selector": selector, "result": click_result}
        
        return {"status": "error", "message": "Could not resolve element for action"}
    except Exception as e:
        err_msg = str(e) or type(e).__name__
        return {"status": "error", "message": err_msg}

@app.post("/extract")
@app.post("/api/extract")
async def extract(req: ExtractRequest):
    try:
        content = await cdp_evaluate("document.body.innerText") or ""
        extracted = await ai_resolver.extract_data(req.instruction, content, req.max_results or 5)
        return {"status": "ok", "data": extracted}
    except Exception as e:
        err_msg = str(e) or type(e).__name__
        return {"status": "error", "message": err_msg}

@app.get("/screenshot")
@app.get("/api/screenshot")
async def screenshot(user_id: Optional[str] = "demo"):
    try:
        result = await cdp_send("Page.captureScreenshot", {"format": "png"})
        if isinstance(result, dict) and "result" in result and "data" in result["result"]:
            import base64
            img_data = base64.b64decode(result["result"]["data"])
            return Response(content=img_data, media_type="image/png")
        return {"status": "error", "message": "Screenshot failed"}
    except Exception as e:
        err_msg = str(e) or type(e).__name__
        return {"status": "error", "message": err_msg}

@app.post("/resize")
@app.post("/api/resize")
async def resize(req: ResizeRequest):
    try:
        result = await cdp_send("Emulation.setDeviceMetricsOverride", {
            "width": req.width,
            "height": req.height,
            "deviceScaleFactor": 1,
            "mobile": False
        })
        return {"status": "ok", "width": req.width, "height": req.height}
    except Exception as e:
        err_msg = str(e) or type(e).__name__
        return {"status": "error", "message": err_msg}

@app.post("/automate")
@app.post("/api/automate")
async def automate(req: AutomateRequest):
    try:
        plan = await ai_resolver.plan_task(req.task)
        results = []
        for step in plan:
            action = step.get("action")
            if action == "navigate" and "url" in step:
                r = await navigate(NavigateRequest(url=step["url"], user_id=req.user_id))
            elif action == "click" and "selector" in step:
                r = await click(ClickRequest(selector=step["selector"], user_id=req.user_id))
            elif action == "type" and "selector" in step and "text" in step:
                r = await type_text(TypeRequest(selector=step["selector"], text=step["text"], user_id=req.user_id))
            elif action == "wait":
                await asyncio.sleep(step.get("duration", 1))
                r = {"status": "ok"}
            else:
                r = {"status": "skipped", "action": action}
            results.append({"action": action, "result": r.get("status", "unknown")})
        
        return {
            "status": "ok",
            "response": f"Executed {len(results)} steps for: {req.task}",
            "steps": results
        }
    except Exception as e:
        err_msg = str(e) or type(e).__name__
        return {"status": "error", "message": err_msg}

@app.post("/back")
@app.post("/api/back")
async def back(user_id: Optional[str] = "demo"):
    try:
        await cdp_evaluate("history.back()")
        return {"status": "ok"}
    except Exception as e:
        err_msg = str(e) or type(e).__name__
        return {"status": "error", "message": err_msg}

@app.post("/forward")
@app.post("/api/forward")
async def forward(user_id: Optional[str] = "demo"):
    try:
        await cdp_evaluate("history.forward()")
        return {"status": "ok"}
    except Exception as e:
        err_msg = str(e) or type(e).__name__
        return {"status": "error", "message": err_msg}

@app.post("/reload")
@app.post("/api/reload")
async def reload(user_id: Optional[str] = "demo"):
    try:
        await cdp_evaluate("location.reload()")
        return {"status": "ok"}
    except Exception as e:
        err_msg = str(e) or type(e).__name__
        return {"status": "error", "message": err_msg}

@app.delete("/session/destroy")
@app.delete("/api/session/destroy")
async def destroy_session(user_id: Optional[str] = "demo"):
    try:
        await cdp_send("Browser.close")
        session_store.store.destroy_session(user_id)
        return {"status": "ok"}
    except Exception as e:
        err_msg = str(e) or type(e).__name__
        return {"status": "error", "message": err_msg}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
