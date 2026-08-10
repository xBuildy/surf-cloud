"""
Surf Cloud — Browser Automation API
Wraps Chrome DevTools Protocol (CDP) for programmatic browser control.
Used by Wave OS Surf app's "Ask AI" panel via the Wave Assistant.
"""

import os
import subprocess
import json
import time
import threading
import websocket
import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

API_KEY = os.environ.get("SURF_API_KEY", "surf-default-key")
CDP_HOST = os.environ.get("CDP_HOST", "127.0.0.1")
CDP_PORT = int(os.environ.get("CDP_PORT", "9222"))
PORT = int(os.environ.get("API_PORT", "8000"))

app = FastAPI(title="Surf Cloud API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class CDPClient:
    """Simple CDP client over WebSocket for browser automation."""

    def __init__(self):
        self._ws = None
        self._msg_id = 0
        self._lock = threading.Lock()
        self._target_url = None

    def _get_ws_url(self):
        """Get the WebSocket debug URL for the active tab."""
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
        """Send a CDP command and wait for the response."""
        with self._lock:
            self._ensure_connected()
            self._msg_id += 1
            msg_id = self._msg_id
            msg = {"id": msg_id, "method": method}
            if params:
                msg["params"] = params
            self._ws.send(json.dumps(msg))
            # Wait for response with matching id
            while True:
                raw = self._ws.recv()
                data = json.loads(raw)
                if data.get("id") == msg_id:
                    if "error" in data:
                        raise RuntimeError(f"CDP error: {data['error']}")
                    return data.get("result", {})

    def send_no_wait(self, method, params=None):
        """Send a CDP command without waiting for response."""
        with self._lock:
            self._ensure_connected()
            self._msg_id += 1
            msg = {"id": self._msg_id, "method": method}
            if params:
                msg["params"] = params
            self._ws.send(json.dumps(msg))

    def navigate(self, url):
        self.send("Page.enable")
        result = self.send("Page.navigate", {"url": url})
        # Wait for page to load
        time.sleep(2)
        return result

    def screenshot(self):
        result = self.send("Page.captureScreenshot", {"format": "png"})
        return result.get("data", "")

    def get_content(self):
        result = self.send("Runtime.evaluate", {
            "expression": "document.body.innerText",
            "returnByValue": True
        })
        return result.get("result", {}).get("value", "")

    def get_title(self):
        result = self.send("Runtime.evaluate", {
            "expression": "document.title",
            "returnByValue": True
        })
        return result.get("result", {}).get("value", "")

    def get_url(self):
        result = self.send("Runtime.evaluate", {
            "expression": "window.location.href",
            "returnByValue": True
        })
        return result.get("result", {}).get("value", "")

    def click(self, selector):
        js = f"""
        (function() {{
            var el = document.querySelector({json.dumps(selector)});
            if (!el) return "Element not found: {selector}";
            el.click();
            return "clicked";
        }})()
        """
        result = self.send("Runtime.evaluate", {
            "expression": js,
            "returnByValue": True
        })
        return result.get("result", {}).get("value", "")

    def type_text(self, selector, text):
        js = f"""
        (function() {{
            var el = document.querySelector({json.dumps(selector)});
            if (!el) return "Element not found: {selector}";
            el.focus();
            el.value = {json.dumps(text)};
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
            return "typed";
        }})()
        """
        result = self.send("Runtime.evaluate", {
            "expression": js,
            "returnByValue": True
        })
        return result.get("result", {}).get("value", "")

    def execute_js(self, script):
        result = self.send("Runtime.evaluate", {
            "expression": script,
            "returnByValue": True
        })
        return result.get("result", {}).get("value", "")

    def get_tabs(self):
        resp = httpx.get(f"http://{CDP_HOST}:{CDP_PORT}/json")
        return resp.json()

    def new_tab(self, url="about:blank"):
        resp = httpx.put(f"http://{CDP_HOST}:{CDP_PORT}/json/new", params={"url": url})
        return resp.json()

    def close(self):
        if self._ws:
            self._ws.close()
            self._ws = None


def check_api_key(api_key: str):
    if api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


cdp = CDPClient()


@app.get("/api/health")
async def health():
    try:
        tabs = cdp.get_tabs()
        return {
            "status": "healthy",
            "cdp_available": True,
            "tabs": len(tabs),
            "tabs_info": [{"title": t.get("title", ""), "url": t.get("url", "")} for t in tabs]
        }
    except Exception as e:
        return {
            "status": "degraded",
            "cdp_available": False,
            "error": str(e)
        }


@app.post("/api/navigate")
async def navigate(body: dict):
    check_api_key(body.get("api_key", ""))
    url = body.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="Missing 'url'")
    try:
        result = cdp.navigate(url)
        title = cdp.get_title()
        return {"status": "ok", "url": url, "title": title}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/screenshot")
async def screenshot(api_key: str = ""):
    check_api_key(api_key)
    try:
        data = cdp.screenshot()
        return {"status": "ok", "screenshot": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/content")
async def get_content(api_key: str = ""):
    check_api_key(api_key)
    try:
        content = cdp.get_content()
        title = cdp.get_title()
        url = cdp.get_url()
        return {"status": "ok", "title": title, "url": url, "content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/click")
async def click(body: dict):
    check_api_key(body.get("api_key", ""))
    selector = body.get("selector")
    if not selector:
        raise HTTPException(status_code=400, detail="Missing 'selector'")
    try:
        result = cdp.click(selector)
        return {"status": "ok", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/type")
async def type_text(body: dict):
    check_api_key(body.get("api_key", ""))
    selector = body.get("selector")
    text = body.get("text", "")
    if not selector:
        raise HTTPException(status_code=400, detail="Missing 'selector'")
    try:
        result = cdp.type_text(selector, text)
        return {"status": "ok", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/execute")
async def execute_js(body: dict):
    check_api_key(body.get("api_key", ""))
    script = body.get("script")
    if not script:
        raise HTTPException(status_code=400, detail="Missing 'script'")
    try:
        result = cdp.execute_js(script)
        return {"status": "ok", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/tabs")
async def get_tabs(api_key: str = ""):
    check_api_key(api_key)
    try:
        tabs = cdp.get_tabs()
        return {
            "status": "ok",
            "tabs": [{"id": t.get("id", ""), "title": t.get("title", ""), "url": t.get("url", "")} for t in tabs]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/new-tab")
async def new_tab(body: dict):
    check_api_key(body.get("api_key", ""))
    url = body.get("url", "about:blank")
    try:
        result = cdp.new_tab(url)
        return {"status": "ok", "tab": {"id": result.get("id", ""), "url": result.get("url", "")}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@app.post("/api/resize")
async def resize_display(body: dict):
    check_api_key(body.get("api_key", ""))
    width = body.get("width")
    height = body.get("height")
    if not width or not height:
        raise HTTPException(status_code=400, detail="Missing 'width' or 'height'")

    log = {"steps": []}
    env = {**os.environ, "DISPLAY": ":99"}

    try:
        # 1) Add the target resolution as a RANDR mode, then switch the output to it.
        #    xrandr --fb alone can't shrink below the current CRTC size, so we must
        #    add a mode and switch the output to it for the framebuffer to actually resize.
        mode_name = f"{width}x{height}_60"
        # Add the mode (ignore error if it already exists)
        subprocess.run(
            ["xrandr", "--newmode", mode_name, "30.00"],
            capture_output=True, timeout=5, text=True, env=env
        )
        # Find the output name (Xvfb usually reports "screen" or "default")
        query = subprocess.run(
            ["xrandr", "-q"],
            capture_output=True, timeout=5, text=True, env=env
        )
        output_name = "screen"
        for line in query.stdout.split("\n"):
            if " connected" in line and not "disconnected" in line:
                output_name = line.split()[0]
                break
        # Add mode to the output (ignore error if already added)
        subprocess.run(
            ["xrandr", "--addmode", output_name, mode_name],
            capture_output=True, timeout=5, text=True, env=env
        )
        # Switch the output to the new mode — this resizes the actual framebuffer
        r1 = subprocess.run(
            ["xrandr", "--output", output_name, "--mode", mode_name],
            capture_output=True, timeout=5, text=True, env=env
        )
        log["steps"].append({
            "cmd": f"xrandr --output {output_name} --mode {mode_name}",
            "returncode": r1.returncode,
            "stderr": r1.stderr.strip()[:300]
        })
        time.sleep(0.5)

        # 2) Find the Chromium window via xdotool and force it to match the new size exactly
        try:
            search = subprocess.run(
                ["xdotool", "search", "--class", "chromium"],
                capture_output=True, timeout=5, text=True, env=env
            )
            window_ids = [w for w in search.stdout.strip().split("\n") if w]
            log["steps"].append({"cmd": "xdotool search", "window_ids": window_ids})

            for wid in window_ids:
                subprocess.run(["xdotool", "windowmove", wid, "0", "0"], capture_output=True, timeout=5, env=env)
                r2 = subprocess.run(
                    ["xdotool", "windowsize", wid, str(width), str(height)],
                    capture_output=True, timeout=5, text=True, env=env
                )
                log["steps"].append({"cmd": f"xdotool windowsize {wid}", "returncode": r2.returncode, "stderr": r2.stderr.strip()[:200]})
        except Exception as e:
            log["steps"].append({"cmd": "xdotool", "error": str(e)})

        # 3) CDP resize as a second guarantee (works even if xdotool window match failed)
        try:
            window_info = cdp.send("Browser.getWindowForTarget")
            window_id = window_info.get("windowId")
            if window_id:
                cdp.send("Browser.setWindowBounds", {
                    "windowId": window_id,
                    "bounds": {"left": 0, "top": 0, "width": width, "height": height, "windowState": "normal"}
                })
                log["steps"].append({"cmd": "CDP setWindowBounds", "window_id": window_id, "ok": True})
        except Exception as e:
            log["steps"].append({"cmd": "CDP setWindowBounds", "error": str(e)})

        return {"status": "ok", "width": width, "height": height, "debug": log}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    print(f"Starting Surf Cloud API on port {PORT}", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=PORT, workers=1)
