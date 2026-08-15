"""
Wave Surf — AI Element Resolver (resilient)
AI-powered element resolution, extraction, and task planning.

Primary backend: Theta EdgeCloud GLM-5.2.
Resilience added:
  * Multiple Theta endpoints/models tried in order (auto-failover).
  * 502 / timeout / empty-body responses are treated as failures and
    fall through to the next backend instead of crashing the request.
  * When ALL AI backends are down, we DEGRADE GRACEFULLY instead of
    hard-erroring, so deterministic automations keep running:
      - resolve_element(): falls back to a heuristic CSS-selector guess
        built from the instruction (buttons/links/inputs by text/name).
      - extract_data(): returns [{"ai_unavailable": true, "error": ...}]
        so Flows can branch on it.
      - plan_task(): returns [] with the same signal via metadata.
"""

import os
import re
import json
import httpx
from typing import Optional, List

# ---- Backend config: ordered list of (endpoint, model, api_key) ----
# Primary is Theta EdgeCloud GLM-5.2. Secondaries are optional fallbacks
# configured via env (e.g. a backup Theta shard or an alt model).
def _backends():
    chain = []
    primary_ep = os.environ.get("THETA_API", "https://ai.thetaedgecloud.com/v1/chat/completions")
    primary_key = os.environ.get("THETA_KEY", "surf-default-key")
    primary_model = os.environ.get("THETA_MODEL", "glm-5.2")
    chain.append((primary_ep, primary_model, primary_key))

    # Optional secondary (e.g. a different Theta shard or alt model).
    fb_ep = os.environ.get("THETA_FALLBACK_API")
    fb_model = os.environ.get("THETA_FALLBACK_MODEL", primary_model)
    fb_key = os.environ.get("THETA_FALLBACK_KEY", primary_key)
    if fb_ep:
        chain.append((fb_ep, fb_model, fb_key))

    return chain


async def _theta_chat(messages: list, max_tokens: int, client: httpx.AsyncClient,
                      temperature: float = 0.1, per_try_timeout: float = 20.0) -> Optional[str]:
    """
    Try each configured backend in order. Returns the assistant message
    string on success, or None if every backend fails (502/timeout/empty).
    """
    last_err = None
    for (endpoint, model, key) in _backends():
        try:
            res = await client.post(
                endpoint,
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
                headers={"Authorization": f"Bearer {key}"},
                timeout=per_try_timeout,
            )
            # 502/503/504 => backend down, try next
            if res.status_code >= 500:
                last_err = f"http {res.status_code}"
                continue
            # Body must be JSON with a choices message; empty => treat as failure
            try:
                data = res.json()
            except Exception as e:
                last_err = f"non-json body ({e})"
                continue
            choices = (data or {}).get("choices") or []
            if not choices:
                last_err = "empty choices"
                continue
            content = (choices[0].get("message") or {}).get("content")
            if not content or not content.strip():
                last_err = "empty content"
                continue
            return content.strip()
        except Exception as e:
            last_err = str(e)
            continue
    # all backends failed
    return None


# ---- Heuristic fallback selector (no AI needed) --------------------
_STOP = {"the", "a", "an", "on", "in", "to", "click", "button", "link",
         "field", "input", "box", "search", "for", "of", "please", "type", "enter"}

def _heuristic_selector(instruction: str) -> Optional[str]:
    """
    Best-effort CSS selector from the instruction text, used only when
    every AI backend is unavailable. Not perfect, but keeps simple
    automations moving (e.g. 'click the login button').
    """
    text = (instruction or "").lower()
    # pull meaningful keywords
    words = [w for w in re.findall(r"[a-z0-9]+", text) if w not in _STOP]
    kw = words[0] if words else None

    if any(w in text for w in ["search", "query", "q "]):
        return "input[type=search], input[name=q], input[type=text]"
    if any(w in text for w in ["email"]):
        return "input[type=email], input[name*=email]"
    if any(w in text for w in ["password"]):
        return "input[type=password]"
    if "submit" in text or "login" in text or "sign in" in text:
        return "button[type=submit], input[type=submit], button"
    if "link" in text and kw:
        return f"a[href*='{kw}']"
    if kw:
        # generic clickable by likely attributes
        return (f"[aria-label*='{kw}' i], [title*='{kw}' i], "
                f"button, a")
    return None


# ---- Public API ----------------------------------------------------
async def resolve_element(instruction: str, page_html: str, client: httpx.AsyncClient = None):
    """Find a CSS selector for an element described in natural language.
    Falls back to a heuristic guess if AI backends are down (never None-only)."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()
    try:
        content = await _theta_chat(
            messages=[
                {"role": "system", "content": "You are a browser automation assistant. Given a page's HTML and a natural language instruction, return ONLY the CSS selector for the element the user wants to interact with. No explanation, just the selector."},
                {"role": "user", "content": f"Instruction: {instruction}\n\nPage HTML (first 5000 chars):\n{page_html[:5000]}"},
            ],
            max_tokens=100,
            client=client,
        )
        if content:
            selector = content.replace("`", "").replace('"', "").replace("'", "").strip()
            # take first line only
            selector = selector.splitlines()[0].strip() if selector else selector
            if selector:
                return selector
        # AI unavailable -> heuristic degrade
        return _heuristic_selector(instruction)
    finally:
        if own_client:
            await client.aclose()


async def extract_data(instruction: str, page_text: str, max_results: int = 5, client: httpx.AsyncClient = None):
    """Extract structured data from page text using AI.
    Returns [{'ai_unavailable': True, ...}] when all backends are down so
    callers/Flows can branch instead of failing silently."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()
    try:
        response_text = await _theta_chat(
            messages=[
                {"role": "system", "content": f"You are a data extraction assistant. Extract data from the page based on the instruction. Return a JSON array of objects. Maximum {max_results} results. Only return the JSON array, no explanation."},
                {"role": "user", "content": f"Instruction: {instruction}\n\nPage content:\n{page_text[:10000]}"},
            ],
            max_tokens=2000,
            client=client,
            per_try_timeout=30.0,
        )
        if response_text is None:
            return [{"ai_unavailable": True, "error": "All AI backends unavailable (Theta EdgeCloud down). Deterministic steps still work; retry extract when AI recovers."}]
        try:
            start = response_text.find("[")
            end = response_text.rfind("]") + 1
            if start >= 0 and end > start:
                return json.loads(response_text[start:end])
            return [{"raw": response_text}]
        except Exception:
            return [{"raw": response_text}]
    finally:
        if own_client:
            await client.aclose()


async def plan_task(task: str, client: httpx.AsyncClient = None):
    """Break down a task into browser automation steps.
    Returns [] when AI is unavailable (caller should surface ai_unavailable)."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()
    try:
        plan_text = await _theta_chat(
            messages=[
                {"role": "system", "content": "You are a browser automation planner. Break down the user's task into a sequence of browser actions. Return a JSON array of step objects. Each step has: 'action' (navigate/click/type/extract/screenshot/wait), 'url' (for navigate), 'selector' (for click/type), 'text' (for type), 'instruction' (for extract), 'duration' (for wait, in seconds). Only return the JSON array."},
                {"role": "user", "content": task},
            ],
            max_tokens=1000,
            client=client,
            per_try_timeout=30.0,
        )
        if plan_text is None:
            return []
        try:
            start = plan_text.find("[")
            end = plan_text.rfind("]") + 1
            if start >= 0 and end > start:
                return json.loads(plan_text[start:end])
            return []
        except Exception:
            return []
    finally:
        if own_client:
            await client.aclose()


async def ai_health(client: httpx.AsyncClient = None) -> dict:
    """Report whether any AI backend is reachable (used by /health)."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()
    try:
        ok = await _theta_chat(
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
            client=client,
            per_try_timeout=8.0,
        )
        return {"ai_available": ok is not None}
    finally:
        if own_client:
            await client.aclose()
