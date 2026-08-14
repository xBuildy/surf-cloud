"""
Wave Surf — CDP Automation API v2
Works alongside Neko WebRTC viewer + Thorium browser
All automation endpoints talk to CDP on localhost:9222
"""

import json
import asyncio
import httpx
from fastapi import FastAPI, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from pydantic import BaseModel

app = FastAPI(title="Wave Surf CDP API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CDP_URL = "http://localhost:9222"

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
    async with httpx.AsyncClient() as client:
        # Get the first browser target
        targets_res = await client.get(f"{CDP_URL}/json")
        targets = targets_res.json()
        page_target = next((t for t in targets if t["type"] == "page"), None)
        if not page_target:
            return {"error": "No page target found"}
        
        # Connect via WebSocket to the page target
        ws_url = page_target["webSocketDebuggerUrl"]
        
        # Use HTTP-based CDP commands instead (simpler for Railway)
        # Actually, we need WebSocket for CDP — use websockets lib
        import websockets
        async with websockets.connect(ws_url) as ws:
            msg = {
                "id": 1,
                "method": method,
                "params": params or {}
            }
            await ws.send(json.dumps(msg))
            resp = await asyncio.wait_for(ws.recv(), timeout=30)
            return json.loads(resp)

async def cdp_evaluate(expression: str):
    """Evaluate a JavaScript expression in the current page."""
    result = await cdp_send("Runtime.evaluate", {
        "expression": expression,
        "returnByValue": True
    })
    if "result" in result and "result" in result["result"]:
        return result["result"]["result"].get("value")
    return None

# ===== Endpoints =====

@app.get("/health")
async def health():
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(f"{CDP_URL}/json/version", timeout=5)
            version = res.json()
            return {
                "status": "ok",
                "browser": version.get("Browser", "unknown"),
                "cdp": "connected",
                "engine": "thorium" if "Thorium" in version.get("Browser", "") else "chromium",
                "webrtc": "neko"
            }
    except Exception as e:
        return {"status": "error", "message": str(e), "cdp": "disconnected"}

@app.post("/navigate")
async def navigate(req: NavigateRequest):
    try:
        result = await cdp_send("Page.navigate", {"url": req.url})
        return {"status": "ok", "url": req.url}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/click")
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
        return {"status": "error", "message": str(e)}

@app.post("/type")
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
        return {"status": "error", "message": str(e)}

@app.get("/content")
async def get_content(user_id: Optional[str] = "demo"):
    try:
        js = "document.body.innerText"
        content = await cdp_evaluate(js)
        return {"status": "ok", "content": content or ""}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/observe")
async def observe(req: ObserveRequest):
    """AI-powered element resolution — finds elements by natural language description."""
    try:
        # Get page content for context
        content = await cdp_evaluate("document.body.innerHTML.substring(0, 5000)")
        
        # Call Wave Assistant (Theta EdgeCloud GLM-5.2) for element resolution
        async with httpx.AsyncClient() as client:
            res = await client.post(
                "https://ai.thetaedgecloud.com/v1/chat/completions",
                json={
                    "model": "glm-5.2",
                    "messages": [
                        {"role": "system", "content": "You are a browser automation assistant. Given a page description and an instruction, return the CSS selector for the element the user wants to interact with. Return ONLY the CSS selector, nothing else."},
                        {"role": "user", "content": f"Instruction: {req.instruction}\n\nPage HTML (first 5000 chars):\n{content}"}
                    ],
                    "max_tokens": 100
                },
                headers={"Authorization": "Bearer surf-default-key"},
                timeout=20
            )
            data = res.json()
            selector = data["choices"][0]["message"]["content"].strip()
        
        return {"status": "ok", "elements": [{"description": req.instruction, "selector": selector, "method": "css"}]}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/act")
async def act(req: ActRequest):
    """AI-driven action — performs a browser action described in natural language."""
    try:
        # First observe to find the element
        observe_result = await observe(ObserveRequest(instruction=req.instruction, user_id=req.user_id))
        if observe_result["status"] != "ok":
            return observe_result
        
        elements = observe_result["elements"]
        if elements and len(elements) > 0:
            selector = elements[0]["selector"]
            # Try clicking
            click_result = await click(ClickRequest(selector=selector, user_id=req.user_id))
            return {"status": "ok", "action": "click", "selector": selector, "result": click_result}
        
        return {"status": "error", "message": "Could not resolve element for action"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/extract")
async def extract(req: ExtractRequest):
    """AI-powered structured data extraction from current page."""
    try:
        # Get page content
        content = await cdp_evaluate("document.body.innerText")
        
        # Call Wave Assistant for extraction
        async with httpx.AsyncClient() as client:
            res = await client.post(
                "https://ai.thetaedgecloud.com/v1/chat/completions",
                json={
                    "model": "glm-5.2",
                    "messages": [
                        {"role": "system", "content": f"Extract data from the page based on the instruction. Return a JSON array of objects. Max {req.max_results} results."},
                        {"role": "user", "content": f"Instruction: {req.instruction}\n\nPage content:\n{content[:10000]}"}
                    ],
                    "max_tokens": 2000
                },
                headers={"Authorization": "Bearer surf-default-key"},
                timeout=30
            )
            data = res.json()
            response_text = data["choices"][0]["message"]["content"]
        
        # Try to parse JSON from response
        try:
            # Find JSON array in response
            start = response_text.find("[")
            end = response_text.rfind("]") + 1
            if start >= 0 and end > start:
                extracted = json.loads(response_text[start:end])
            else:
                extracted = [{"raw": response_text}]
        except:
            extracted = [{"raw": response_text}]
        
        return {"status": "ok", "data": extracted[:req.max_results]}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/screenshot")
async def screenshot(user_id: Optional[str] = "demo"):
    try:
        result = await cdp_send("Page.captureScreenshot", {"format": "png"})
        if "result" in result and "data" in result["result"]:
            import base64
            img_data = base64.b64decode(result["result"]["data"])
            return Response(content=img_data, media_type="image/png")
        return {"status": "error", "message": "Screenshot failed"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/resize")
async def resize(req: ResizeRequest):
    try:
        await cdp_send("Emulation.setDeviceMetricsOverride", {
            "width": req.width,
            "height": req.height,
            "deviceScaleFactor": 1,
            "mobile": False
        })
        return {"status": "ok", "width": req.width, "height": req.height}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/automate")
async def automate(req: AutomateRequest):
    """Full automation task — routes to Wave Assistant for planning, then executes steps."""
    try:
        # Call Wave Assistant for task planning
        async with httpx.AsyncClient() as client:
            res = await client.post(
                "https://ai.thetaedgecloud.com/v1/chat/completions",
                json={
                    "model": "glm-5.2",
                    "messages": [
                        {"role": "system", "content": "You are a browser automation assistant. Break down the user's task into a sequence of browser actions. Return a JSON array of step objects with 'action' (navigate/click/type/extract/screenshot) and relevant params."},
                        {"role": "user", "content": req.task}
                    ],
                    "max_tokens": 1000
                },
                headers={"Authorization": "Bearer surf-default-key"},
                timeout=30
            )
            data = res.json()
            plan_text = data["choices"][0]["message"]["content"]
        
        # Parse the plan
        try:
            start = plan_text.find("[")
            end = plan_text.rfind("]") + 1
            steps = json.loads(plan_text[start:end]) if start >= 0 else []
        except:
            steps = []
        
        # Execute steps
        results = []
        for step in steps:
            action = step.get("action", "")
            if action == "navigate":
                r = await navigate(NavigateRequest(url=step.get("url", ""), user_id=req.user_id))
            elif action == "click":
                r = await click(ClickRequest(selector=step.get("selector", ""), user_id=req.user_id))
            elif action == "type":
                r = await type_text(TypeRequest(selector=step.get("selector", ""), text=step.get("text", ""), user_id=req.user_id))
            elif action == "extract":
                r = await extract(ExtractRequest(instruction=step.get("instruction", ""), user_id=req.user_id))
            elif action == "screenshot":
                r = {"status": "ok", "action": "screenshot"}
            else:
                r = {"status": "skipped", "action": action}
            results.append({"action": action, "result": r.get("status", "unknown")})
        
        return {
            "status": "ok",
            "response": f"Executed {len(results)} steps for: {req.task}",
            "steps": results
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/back")
async def back(user_id: Optional[str] = "demo"):
    try:
        await cdp_evaluate("history.back()")
        return {"status": "ok"}
    except:
        return {"status": "error"}

@app.post("/forward")
async def forward(user_id: Optional[str] = "demo"):
    try:
        await cdp_evaluate("history.forward()")
        return {"status": "ok"}
    except:
        return {"status": "error"}

@app.post("/reload")
async def reload(user_id: Optional[str] = "demo"):
    try:
        await cdp_evaluate("location.reload()")
        return {"status": "ok"}
    except:
        return {"status": "error"}

# ===== Session Management =====

@app.delete("/session/destroy")
async def destroy_session(user_id: Optional[str] = "demo"):
    """Close the browser session."""
    try:
        await cdp_send("Browser.close")
        return {"status": "ok"}
    except:
        return {"status": "error"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
