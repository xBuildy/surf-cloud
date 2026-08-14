"""
Wave Surf — AI Element Resolver
Handles AI-powered element resolution and content extraction
using Theta EdgeCloud GLM-5.2
"""

import json
import httpx
from typing import Optional

THETA_API = "https://ai.thetaedgecloud.com/v1/chat/completions"
THETA_KEY = "surf-default-key"
MODEL = "glm-5.2"

async def resolve_element(instruction: str, page_html: str, client: httpx.AsyncClient = None):
    """Find a CSS selector for an element described in natural language."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()
    
    try:
        res = await client.post(
            THETA_API,
            json={
                "model": MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a browser automation assistant. Given a page's HTML and a natural language instruction, return ONLY the CSS selector for the element the user wants to interact with. No explanation, just the selector."
                    },
                    {
                        "role": "user",
                        "content": f"Instruction: {instruction}\n\nPage HTML (first 5000 chars):\n{page_html[:5000]}"
                    }
                ],
                "max_tokens": 100,
                "temperature": 0.1
            },
            headers={"Authorization": f"Bearer {THETA_KEY}"},
            timeout=20
        )
        data = res.json()
        selector = data["choices"][0]["message"]["content"].strip()
        # Clean up the selector (remove markdown, quotes)
        selector = selector.replace("`", "").replace('"', "").replace("'", "").strip()
        return selector
    except Exception as e:
        return None
    finally:
        if own_client:
            await client.aclose()

async def extract_data(instruction: str, page_text: str, max_results: int = 5, client: httpx.AsyncClient = None):
    """Extract structured data from page text using AI."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()
    
    try:
        res = await client.post(
            THETA_API,
            json={
                "model": MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": f"You are a data extraction assistant. Extract data from the page based on the instruction. Return a JSON array of objects. Maximum {max_results} results. Only return the JSON array, no explanation."
                    },
                    {
                        "role": "user",
                        "content": f"Instruction: {instruction}\n\nPage content:\n{page_text[:10000]}"
                    }
                ],
                "max_tokens": 2000,
                "temperature": 0.1
            },
            headers={"Authorization": f"Bearer {THETA_KEY}"},
            timeout=30
        )
        data = res.json()
        response_text = data["choices"][0]["message"]["content"]
        
        # Parse JSON from response
        try:
            start = response_text.find("[")
            end = response_text.rfind("]") + 1
            if start >= 0 and end > start:
                return json.loads(response_text[start:end])
            else:
                return [{"raw": response_text}]
        except:
            return [{"raw": response_text}]
    except Exception as e:
        return [{"error": str(e)}]
    finally:
        if own_client:
            await client.aclose()

async def plan_task(task: str, client: httpx.AsyncClient = None):
    """Break down a task into browser automation steps."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()
    
    try:
        res = await client.post(
            THETA_API,
            json={
                "model": MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a browser automation planner. Break down the user's task into a sequence of browser actions. Return a JSON array of step objects. Each step has: 'action' (navigate/click/type/extract/screenshot/wait), 'url' (for navigate), 'selector' (for click/type), 'text' (for type), 'instruction' (for extract), 'duration' (for wait, in seconds). Only return the JSON array."
                    },
                    {
                        "role": "user",
                        "content": task
                    }
                ],
                "max_tokens": 1000,
                "temperature": 0.1
            },
            headers={"Authorization": f"Bearer {THETA_KEY}"},
            timeout=30
        )
        data = res.json()
        plan_text = data["choices"][0]["message"]["content"]
        
        # Parse JSON from response
        try:
            start = plan_text.find("[")
            end = plan_text.rfind("]") + 1
            if start >= 0 and end > start:
                return json.loads(plan_text[start:end])
            return []
        except:
            return []
    except Exception as e:
        return []
    finally:
        if own_client:
            await client.aclose()
