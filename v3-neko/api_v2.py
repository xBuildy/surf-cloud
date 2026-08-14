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

async def cdp_send(method: str, params: dict = None, session_id: str = None):
    """Send a CDP command to the browser."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            targets_res = await client.get(f"{CDP_URL}/json")
            targets = targets_res.json()
        except Exception as e:
            return {"error": f"Failed to connect to CDP: {e}"}
        
        page_target = next((t for t in targets if isinstance(t, dict) and t.get("type") == "page"), None)
        
        if not page_target:
            try:
                new_res = await client.get(f"{CDP_URL}/json/new")
                page_target = new_res.json()
            except Exception as e:
                return {"error": f"No page target found and failed to create new target: {e}"}
        
        ws_url = page_target.get("webSocketDebuggerUrl")
        if not ws_url:
            return {"error": "Page target has no webSocketDebuggerUrl"}
        
        ws_url = ws_url.replace("localhost", "127.0.0.1")
        
        try:
            async with websockets.connect(ws_url, open_timeout=10, close_timeout=5) as ws:
                msg_id = 1
                msg = {
                    "id": msg_id,
                    "method": method,
                    "params": params or {}
                }
                await ws.send(json.dumps(msg))
                
                start_time = asyncio.get_event_loop().time()
                while True:
                    remaining = 15.0 - (asyncio.get_event_loop().time() - start_time)
                    if remaining <= 0:
                        raise asyncio.TimeoutError("CDP response timeout")
                    resp_str = await asyncio.wait_for(ws.recv(), timeout=remaining)
                    resp = json.loads(resp_str)
                    if resp.get("id") == msg_id:
                        return resp
        except Exception as e:
            err_msg = str(e) or type(e).__name__
            return {"error": f"CDP connection failed: {err_msg}"}

async def cdp_evaluate(expression: str):
    """Evaluate a JavaScript expression in the current page."""
    result = await cdp_send("Runtime.evaluate", {
        "expression": expression,
        "returnByValue": True
    })
    if isinstance(result, dict) and "result" in result and "result" in result["result"]:
        return result["result"]["result"].get("value")
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
        result = await cdp_send("Page.navigate", {"url": req.url})
        if isinstance(result, dict) and "error" in result:
            return {"status": "error", "message": result["error"]}
        return {"status": "ok", "url": req.url}
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
