"""
Surf Cloud v2 — CDP Event Recorder & Replay Module
Captures browser actions (Page.navigate, DOM.dispatchEvent, Input.dispatchKeyEvent, Page.frameNavigated)
over Chrome DevTools Protocol (CDP) and replays them via Playwright or CDP.
Generates executable Playwright Python scripts for recorded sessions.
"""

import os
import json
import time
import asyncio
import uuid
import logging
from typing import Dict, List, Any, Optional, Union
import httpx
import websockets
from fastapi import FastAPI, APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("surf_cloud.recorder")
logging.basicConfig(level=logging.INFO)

DEFAULT_RECORDINGS_DIR = "/config/recordings"


class RecordStartRequest(BaseModel):
    cdp_host: Optional[str] = "127.0.0.1"
    cdp_port: Optional[int] = 9222


class RecordStopRequest(BaseModel):
    session_id: str


class ReplayRequest(BaseModel):
    script: Union[List[Dict[str, Any]], Dict[str, Any], str]
    speed: Optional[float] = 1.0
    cdp_host: Optional[str] = "127.0.0.1"
    cdp_port: Optional[int] = 9222


class CDPRecorder:
    """
    CDP Event Recorder & Replay Engine for Surf Cloud v2.
    Listens to CDP browser events, logs actions, generates Playwright scripts,
    and replays sessions at variable speeds.
    """

    def __init__(self, cdp_host: str = "127.0.0.1", cdp_port: int = 9222, storage_dir: str = DEFAULT_RECORDINGS_DIR):
        self.cdp_host = cdp_host
        self.cdp_port = cdp_port
        self.storage_dir = storage_dir
        self.active_sessions: Dict[str, Dict[str, Any]] = {}

        try:
            os.makedirs(self.storage_dir, exist_ok=True)
        except Exception as e:
            logger.warning(f"Failed to create storage dir {self.storage_dir}: {e}. Falling back to local ./recordings.")
            self.storage_dir = "./recordings"
            os.makedirs(self.storage_dir, exist_ok=True)

    async def _get_ws_url(self) -> str:
        """Fetch WebSocket debugger URL for the active CDP page target."""
        url = f"http://{self.cdp_host}:{self.cdp_port}/json"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=10.0)
            targets = resp.json()

        for t in targets:
            if t.get("type") == "page" and "webSocketDebuggerUrl" in t:
                return t["webSocketDebuggerUrl"]
        if targets and "webSocketDebuggerUrl" in targets[0]:
            return targets[0]["webSocketDebuggerUrl"]

        raise RuntimeError(f"No CDP page targets available at {self.cdp_host}:{self.cdp_port}")

    async def start_recording(self) -> str:
        """
        Start recording browser events on the active tab.
        Returns a session_id string.
        """
        session_id = f"session_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        ws_url = await self._get_ws_url()

        ws = await websockets.connect(ws_url, max_size=None)

        msg_id = 1

        async def send_cmd(method: str, params: Optional[dict] = None):
            nonlocal msg_id
            m = {"id": msg_id, "method": method}
            if params:
                m["params"] = params
            msg_id += 1
            await ws.send(json.dumps(m))

        await send_cmd("Page.enable")
        await send_cmd("DOM.enable")
        await send_cmd("Runtime.enable")
        await send_cmd("Input.enable")
        await send_cmd("Runtime.addBinding", {"name": "__cdp_record_event__"})

        injected_js = """
        (function() {
            if (window.__cdp_recorder_active) return;
            window.__cdp_recorder_active = true;

            function getCssSelector(el) {
                if (!el || el.nodeType !== 1) return '';
                if (el.id) return '#' + el.id;
                if (el.getAttribute && el.getAttribute('data-testid')) return '[data-testid="' + el.getAttribute('data-testid') + '"]';
                if (el.name) return el.tagName.toLowerCase() + '[name="' + el.name + '"]';
                var path = [];
                while (el && el.nodeType === 1) {
                    var selector = el.tagName.toLowerCase();
                    if (el.id) {
                        selector += '#' + el.id;
                        path.unshift(selector);
                        break;
                    } else {
                        var sib = el, nth = 1;
                        while (sib = sib.previousElementSibling) {
                            if (sib.tagName === el.tagName) nth++;
                        }
                        if (nth !== 1) selector += ":nth-of-type(" + nth + ")";
                    }
                    path.unshift(selector);
                    el = el.parentElement;
                }
                return path.join(" > ");
            }

            function sendEvent(type, params) {
                var payload = JSON.stringify({
                    event_type: type,
                    params: params,
                    timestamp: Date.now() / 1000.0
                });
                if (window.__cdp_record_event__) {
                    window.__cdp_record_event__(payload);
                }
            }

            document.addEventListener('click', function(e) {
                var target = e.target;
                var selector = getCssSelector(target);
                var text = (target.innerText || target.textContent || target.value || '').substring(0, 50).trim();
                sendEvent('DOM.dispatchEvent', {
                    action: 'click',
                    selector: selector,
                    x: e.clientX,
                    y: e.clientY,
                    button: e.button,
                    text: text,
                    tag: target.tagName
                });
            }, true);

            document.addEventListener('keydown', function(e) {
                if (['Control', 'Shift', 'Alt', 'Meta'].includes(e.key)) return;
                var target = e.target;
                var selector = getCssSelector(target);
                sendEvent('Input.dispatchKeyEvent', {
                    type: 'keyDown',
                    key: e.key,
                    code: e.code,
                    selector: selector,
                    value: target.value || ''
                });
            }, true);

            document.addEventListener('change', function(e) {
                var target = e.target;
                var selector = getCssSelector(target);
                sendEvent('Input.dispatchKeyEvent', {
                    type: 'change',
                    selector: selector,
                    value: target.value || ''
                });
            }, true);
        })();
        """

        await send_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": injected_js})
        await send_cmd("Runtime.evaluate", {"expression": injected_js, "returnByValue": True})

        session_data = {
            "session_id": session_id,
            "ws": ws,
            "start_time": time.time(),
            "events": [],
            "running": True,
            "task": None
        }

        async def listen_loop():
            try:
                while session_data["running"]:
                    msg_raw = await ws.recv()
                    data = json.loads(msg_raw)
                    method = data.get("method")
                    params = data.get("params", {})

                    if method in ("Page.navigate", "Page.frameNavigated"):
                        url = params.get("frame", {}).get("url") or params.get("url")
                        if url and not url.startswith("chrome://") and not url.startswith("about:"):
                            event_type = "Page.navigate" if method == "Page.navigate" else "Page.frameNavigated"
                            session_data["events"].append({
                                "timestamp": time.time(),
                                "event_type": event_type,
                                "params": {
                                    "url": url,
                                    "frame_id": params.get("frame", {}).get("id")
                                }
                            })
                    elif method == "Runtime.bindingCalled" and params.get("name") == "__cdp_record_event__":
                        try:
                            payload = json.loads(params.get("payload", "{}"))
                            session_data["events"].append({
                                "timestamp": payload.get("timestamp", time.time()),
                                "event_type": payload.get("event_type", "DOM.dispatchEvent"),
                                "params": payload.get("params", {})
                            })
                        except Exception as parse_err:
                            logger.error(f"Error parsing binding payload: {parse_err}")

            except asyncio.CancelledError:
                pass
            except Exception as loop_err:
                logger.debug(f"Recorder listener loop finished for {session_id}: {loop_err}")

        session_data["task"] = asyncio.create_task(listen_loop())
        self.active_sessions[session_id] = session_data

        logger.info(f"Started CDP recording session: {session_id}")
        return session_id

    async def stop_recording(self, session_id: str) -> dict:
        """
        Stop recording, save event log & Playwright script, and return recording summary.
        """
        if session_id not in self.active_sessions:
            raise ValueError(f"Recording session '{session_id}' not found or already stopped.")

        session_data = self.active_sessions.pop(session_id)
        session_data["running"] = False

        if session_data["task"]:
            session_data["task"].cancel()

        ws = session_data["ws"]
        try:
            await ws.close()
        except Exception:
            pass

        events = session_data["events"]
        playwright_script = self.generate_playwright_script(events)

        file_timestamp = int(time.time())
        filename = f"recording_{session_id}_{file_timestamp}.json"
        recording_file = os.path.join(self.storage_dir, filename)

        result_data = {
            "session_id": session_id,
            "recording_file": recording_file,
            "events_count": len(events),
            "events": events,
            "playwright_script": playwright_script,
            "created_at": file_timestamp
        }

        try:
            with open(recording_file, "w", encoding="utf-8") as f:
                json.dump(result_data, f, indent=2)
        except Exception as file_err:
            logger.error(f"Failed to write recording file {recording_file}: {file_err}")

        logger.info(f"Stopped recording session {session_id}. Saved {len(events)} events to {recording_file}.")
        return result_data

    def generate_playwright_script(self, events: list) -> str:
        """
        Generates executable Playwright Python code string from recorded events.
        """
        code_lines = [
            "import asyncio",
            "from playwright.async_api import async_playwright",
            "",
            "async def run():",
            "    async with async_playwright() as p:",
            "        browser = await p.chromium.launch(headless=False)",
            "        context = await browser.new_context()",
            "        page = await context.new_page()",
            ""
        ]

        if not events:
            code_lines.append("        # No events recorded")
            code_lines.append("        pass")
        else:
            prev_ts = None
            for idx, event in enumerate(events):
                ts = event.get("timestamp", 0)
                event_type = event.get("event_type", "")
                params = event.get("params", {})

                if prev_ts is not None and ts > prev_ts:
                    delay = round(min(ts - prev_ts, 3.0), 2)
                    if delay >= 0.2:
                        code_lines.append(f"        await asyncio.sleep({delay})")
                prev_ts = ts

                if event_type == "Page.navigate":
                    url = params.get("url")
                    code_lines.append(f'        await page.goto("{url}")')

                elif event_type == "Page.frameNavigated":
                    url = params.get("url")
                    if url:
                        code_lines.append(f'        # Frame loaded: {url}')
                    code_lines.append('        await page.wait_for_load_state("load")')

                elif event_type == "DOM.dispatchEvent":
                    action = params.get("action", "click")
                    selector = params.get("selector", "")
                    text = params.get("text", "")
                    if selector:
                        code_lines.append(f'        await page.click("{selector}")')
                    elif text:
                        code_lines.append(f'        await page.click("text={text}")')
                    else:
                        x = params.get("x", 0)
                        y = params.get("y", 0)
                        code_lines.append(f'        await page.mouse.click({x}, {y})')

                elif event_type == "Input.dispatchKeyEvent":
                    key_type = params.get("type", "")
                    selector = params.get("selector", "")
                    value = params.get("value", "")
                    key = params.get("key", "")

                    if key_type == "change" or value:
                        if selector:
                            code_lines.append(f'        await page.fill("{selector}", "{value}")')
                    elif key and key not in ("Unidentified", ""):
                        if len(key) == 1:
                            code_lines.append(f'        await page.keyboard.type("{key}")')
                        else:
                            code_lines.append(f'        await page.keyboard.press("{key}")')

        code_lines.extend([
            "",
            "        await browser.close()",
            "",
            'if __name__ == "__main__":',
            "    asyncio.run(run())"
        ])

        return "\n".join(code_lines)

    async def replay(self, script: Union[list, dict, str], speed: float = 1.0) -> dict:
        """
        Replays recorded script using Playwright's async API with variable speed.
        Returns detailed per-step execution results.
        """
        from playwright.async_api import async_playwright

        events = []
        if isinstance(script, str):
            try:
                parsed = json.loads(script)
                if isinstance(parsed, dict) and "events" in parsed:
                    events = parsed["events"]
                elif isinstance(parsed, list):
                    events = parsed
            except json.JSONDecodeError:
                raise ValueError("String script provided is not valid JSON events")
        elif isinstance(script, dict):
            events = script.get("events", [])
        elif isinstance(script, list):
            events = script

        speed = max(0.1, float(speed))
        results = []
        success_count = 0
        fail_count = 0

        async with async_playwright() as p:
            browser = None
            try:
                cdp_url = f"http://{self.cdp_host}:{self.cdp_port}"
                browser = await p.chromium.connect_over_cdp(cdp_url)
                context = browser.contexts[0] if browser.contexts else await browser.new_context()
                page = context.pages[0] if context.pages else await context.new_page()
            except Exception as conn_err:
                logger.info(f"CDP connection failed for replay ({conn_err}), launching headless Chromium")
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context()
                page = await context.new_page()

            prev_ts = None
            for idx, event in enumerate(events):
                ts = event.get("timestamp", 0)
                event_type = event.get("event_type", "")
                params = event.get("params", {})

                if prev_ts is not None and ts > prev_ts:
                    raw_delay = ts - prev_ts
                    adjusted_delay = (raw_delay / speed)
                    if adjusted_delay > 0.05:
                        await asyncio.sleep(min(adjusted_delay, 5.0 / speed))
                prev_ts = ts

                step_start = time.time()
                step_res = {
                    "step": idx + 1,
                    "event_type": event_type,
                    "params": params,
                    "status": "pending",
                    "duration_ms": 0,
                    "error": None
                }

                try:
                    if event_type == "Page.navigate":
                        url = params.get("url")
                        if url:
                            await page.goto(url, timeout=15000)

                    elif event_type == "Page.frameNavigated":
                        await page.wait_for_load_state("load", timeout=10000)

                    elif event_type == "DOM.dispatchEvent":
                        selector = params.get("selector")
                        text = params.get("text")
                        if selector:
                            await page.click(selector, timeout=5000)
                        elif text:
                            await page.click(f"text={text}", timeout=5000)
                        else:
                            x = params.get("x", 0)
                            y = params.get("y", 0)
                            await page.mouse.click(x, y)

                    elif event_type == "Input.dispatchKeyEvent":
                        key_type = params.get("type")
                        selector = params.get("selector")
                        value = params.get("value", "")
                        key = params.get("key", "")

                        if key_type == "change" or value:
                            if selector:
                                await page.fill(selector, value, timeout=5000)
                        elif key:
                            if selector:
                                await page.focus(selector, timeout=3000)
                            await page.keyboard.press(key)

                    step_res["status"] = "success"
                    success_count += 1
                except Exception as step_err:
                    step_res["status"] = "failed"
                    step_res["error"] = str(step_err)
                    fail_count += 1

                step_res["duration_ms"] = int((time.time() - step_start) * 1000)
                results.append(step_res)

        return {
            "status": "completed" if fail_count == 0 else "partial_failure",
            "total_steps": len(events),
            "successful_steps": success_count,
            "failed_steps": fail_count,
            "speed": speed,
            "results": results
        }


# FastAPI router & instance setup
recorder_instance = CDPRecorder()
router = APIRouter(prefix="/api/record", tags=["recorder"])


@router.post("/start")
async def api_record_start(req: RecordStartRequest = RecordStartRequest()):
    try:
        recorder = CDPRecorder(cdp_host=req.cdp_host, cdp_port=req.cdp_port) if (req.cdp_host or req.cdp_port) else recorder_instance
        session_id = await recorder.start_recording()
        if recorder != recorder_instance:
            recorder_instance.active_sessions[session_id] = recorder.active_sessions[session_id]
        return {"status": "ok", "session_id": session_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop")
async def api_record_stop(req: RecordStopRequest):
    try:
        res = await recorder_instance.stop_recording(req.session_id)
        return {"status": "ok", **res}
    except ValueError as val_err:
        raise HTTPException(status_code=404, detail=str(val_err))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/replay")
async def api_record_replay(req: ReplayRequest):
    try:
        res = await recorder_instance.replay(script=req.script, speed=req.speed or 1.0)
        return {"status": "ok", **res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


app = FastAPI(title="Surf Cloud CDP Recorder API")
app.include_router(router)
