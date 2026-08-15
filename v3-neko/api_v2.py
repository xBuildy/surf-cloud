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
# Correct CDP flow (this is the fix for the 15s /navigate hang):
#   1. GET /json -> pick a REAL page target (http/https/about, excluding
#      chrome-extension / devtools / chrome-untrusted / background targets).
#   2. Connect to THAT page target's own webSocketDebuggerUrl. A page-level
#      socket is implicitly attached to the page, so no Target.attachToTarget
#      is needed (this Chrome build rejects attachToTarget with -32000
#      "Not allowed" over the browser socket anyway).
#   3. Send Page.enable + Runtime.enable FIRST (missing Page.enable is a
#      classic cause of Page.* commands never resolving), THEN the real command.
#
# Two earlier bugs combined here: the old code opened a page socket but never
# called Page.enable AND sometimes grabbed an extension's page target — so the
# command response never arrived and every call ate the full 15s timeout.

CDP_TIMEOUT = 6.0

# websockets connect kwargs: send an Origin header Chrome will accept under
# --remote-allow-origins. Missing Origin => Chrome refuses to service CDP
# commands (page socket hangs; browser socket returns -32000 "Not allowed").
import websockets as _ws_pkg
_WS_VER = tuple(int(x) for x in getattr(_ws_pkg, "__version__", "0").split(".")[:2] if x.isdigit())

def _ws_connect(url):
    kwargs = dict(open_timeout=10, close_timeout=5, max_size=None)
    hdrs = [("Origin", "http://127.0.0.1:9222")]
    if _WS_VER >= (12,):
        kwargs["additional_headers"] = hdrs
    else:
        kwargs["extra_headers"] = hdrs
    return websockets.connect(url, **kwargs)


def _is_real_page(t: dict) -> bool:
    """A real, attachable browsing tab — not an extension/devtools/internal target.
    Also excludes chrome:// pages (the New Tab Page renderer wedges on this
    build and its CDP socket never answers Page.enable)."""
    if not isinstance(t, dict):
        return False
    if t.get("type") != "page":
        return False
    url = t.get("url", "") or ""
    for bad in ("chrome-extension://", "devtools://", "chrome-untrusted://", "chrome://"):
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

    async def prepare(self):
        """Enable the domains we rely on BEFORE issuing Page/Runtime commands.
        On a page-level socket there is no sessionId — commands go straight to
        the attached page, so use_session stays False throughout."""
        await self.send("Page.enable", use_session=False)
        await self.send("Runtime.enable", use_session=False)


async def _pick_page_ws() -> str:
    """Return the webSocketDebuggerUrl of a real, attachable page target.
    Creates an about:blank tab if none exists. Connecting to a page target's
    OWN socket gives an implicitly-attached session — no Target.attachToTarget
    (which this Chrome build rejects with -32000 "Not allowed")."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        targets = (await client.get(f"{CDP_URL}/json")).json()
        page = next((t for t in targets if _is_real_page(t)), None)
        if not page:
            # Create a fresh about:blank tab. Newer Chrome requires PUT for
            # /json/new and rejects GET; try PUT first, fall back to GET.
            try:
                page = (await client.put(f"{CDP_URL}/json/new?about:blank")).json()
            except Exception:
                page = (await client.get(f"{CDP_URL}/json/new?about:blank")).json()
    ws = page.get("webSocketDebuggerUrl", "")
    return ws.replace("localhost", "127.0.0.1")


async def _with_session(fn):
    """Open the page-level socket, enable domains, run fn(session), clean up."""
    ws_url = await _pick_page_ws()
    if not ws_url:
        return {"error": "No page webSocketDebuggerUrl available"}
    async with _ws_connect(ws_url) as ws:
        session = CDPSession(ws)
        await session.prepare()
        return await fn(session)


async def cdp_send(method: str, params: dict = None, session_id: str = None):
    """Back-compat helper: attach to a page and run a single command over the session.

    Returns {"result": ...} on success or {"error": ...} on failure, matching
    the shape the endpoints below already expect.
    """
    async def _run(session: CDPSession):
        try:
            result = await session.send(method, params or {}, use_session=False)
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
            result = await session.send("Page.navigate", {"url": url}, use_session=False)
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
            }, use_session=False)
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
                "webrtc": "neko",
                "ai_available": (await ai_resolver.ai_health(client)).get("ai_available")
            }
    except Exception as e:
        err_msg = str(e) or type(e).__name__
        return {"status": "error", "message": err_msg, "cdp": "disconnected"}

@app.get("/debug/targets")
@app.get("/api/debug/neko")
async def debug_neko():
    import subprocess, glob, os
    out={}
    # neko binary version
    for b in ["/usr/bin/neko","/app/neko","neko"]:
        try:
            out["version"]=subprocess.run([b,"--version"],capture_output=True,text=True,timeout=5).stdout.strip() or subprocess.run([b,"serve","--help"],capture_output=True,text=True,timeout=5).stdout[:200]
            out["bin"]=b; break
        except Exception as e:
            out.setdefault("verr",[]).append(f"{b}: {e}")
    # resolved config file
    for p in ["/etc/neko/neko.yaml","/etc/neko/neko.yml"]:
        if os.path.exists(p):
            out["config_file"]=p; out["config"]=open(p).read()[:1500]
    # NEKO_* env actually in the neko process
    try:
        ps=subprocess.run(["ps","-eo","pid,args"],capture_output=True,text=True,timeout=5).stdout
        out["neko_proc"]=[l for l in ps.splitlines() if "neko" in l.lower() and "serve" in l.lower() or ("/neko" in l and "--" in l)][:4]
    except Exception as e:
        out["neko_proc"]=f"err {e}"
    out["neko_env"]={k:v for k,v in os.environ.items() if k.startswith("NEKO_")}
    # supervisor conf for neko
    for p in glob.glob("/etc/neko/supervisord/*.conf"):
        if "neko" in p.lower():
            out[os.path.basename(p)]=open(p).read()[:800]
    return out


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
