"""
Surf Cloud v2 - AI Element Resolution Module
Ports Stagehand's AI-driven browser interaction patterns to Python,
using Playwright + Theta EdgeCloud GLM-5.2 / GLM-4.9v as the vision/AI model.
"""

import os
import re
import json
import base64
import logging
import asyncio
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
import httpx

logger = logging.getLogger("surf_cloud.ai_resolver")


@dataclass
class ElementInfo:
    selector: str
    description: str
    confidence: float
    bounds: dict  # {x, y, width, height}
    index: int


@dataclass
class ActionResult:
    success: bool
    action_type: str  # click, type, select, hover, scroll
    selector: str
    message: str
    value: str = ""  # for type actions


class SurfAIResolver:
    """
    AI-driven element resolution module for Playwright pages using Theta EdgeCloud Vision API.
    Provides observe(), act(), and extract() primitives inspired by Stagehand.
    """

    def __init__(
        self,
        theta_api_key: Optional[str] = None,
        theta_api_url: str = "https://ai.thetaedgecloud.com/v1/chat/completions",
        vision_model: str = "glm-4.9v-flash",
    ):
        self.theta_api_key = theta_api_key or os.getenv("THETA_API_KEY", "")
        self.theta_api_url = theta_api_url or "https://ai.thetaedgecloud.com/v1/chat/completions"
        self.vision_model = vision_model or "glm-4.9v-flash"

    async def _get_simplified_dom(self, page: Any) -> List[Dict[str, Any]]:
        """
        Extracts visible elements from the page with tag name, attributes, text,
        bounding box coordinates, and indices.
        Limits to ~500 visible elements.
        """
        js_script = """
        () => {
            const isVisible = (el) => {
                if (!el) return false;
                const rect = el.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) return false;
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                return true;
            };

            const truncate = (str, maxLen = 100) => {
                if (!str) return '';
                const trimmed = str.replace(/\\s+/g, ' ').trim();
                return trimmed.length > maxLen ? trimmed.slice(0, maxLen) + '...' : trimmed;
            };

            const getCssSelector = (el) => {
                if (el.id) return `#${CSS.escape(el.id)}`;
                let path = [];
                let current = el;
                while (current && current.nodeType === Node.ELEMENT_NODE && current.tagName !== 'BODY' && current.tagName !== 'HTML') {
                    let selector = current.tagName.toLowerCase();
                    if (current.id) {
                        selector += `#${CSS.escape(current.id)}`;
                        path.unshift(selector);
                        break;
                    }
                    if (current.name) {
                        selector += `[name="${CSS.escape(current.name)}"]`;
                        path.unshift(selector);
                        break;
                    }
                    let sibling = current;
                    let nth = 1;
                    while (sibling = sibling.previousElementSibling) {
                        if (sibling.tagName === current.tagName) nth++;
                    }
                    if (nth > 1) selector += `:nth-of-type(${nth})`;
                    path.unshift(selector);
                    current = current.parentElement;
                }
                return path.join(' > ') || el.tagName.toLowerCase();
            };

            const allElements = Array.from(document.querySelectorAll('*'));
            const elementsInfo = [];
            let index = 0;

            for (const el of allElements) {
                if (elementsInfo.length >= 500) break;
                if (!isVisible(el)) continue;

                const tag = el.tagName.toLowerCase();
                const isInteractive = ['a', 'button', 'input', 'select', 'textarea', 'option', 'details', 'summary', 'label'].includes(tag)
                    || el.hasAttribute('onclick')
                    || el.hasAttribute('role')
                    || el.hasAttribute('tabindex');

                const hasDirectText = Array.from(el.childNodes).some(n => n.nodeType === Node.TEXT_NODE && n.textContent.trim().length > 0);

                if (['div', 'section', 'article', 'main', 'aside', 'header', 'footer', 'nav', 'span', 'ul', 'ol', 'li', 'form', 'table', 'tbody', 'tr', 'td'].includes(tag)) {
                    if (!isInteractive && !hasDirectText) continue;
                }

                const rect = el.getBoundingClientRect();
                el.setAttribute('data-surf-idx', index.toString());

                const info = {
                    index: index,
                    tag: tag,
                    id: el.id || '',
                    classes: el.className && typeof el.className === 'string' ? el.className.trim() : '',
                    text: truncate(el.innerText || el.textContent || ''),
                    role: el.getAttribute('role') || '',
                    aria_label: el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || '',
                    placeholder: el.getAttribute('placeholder') || '',
                    href: el.getAttribute('href') || '',
                    type: el.getAttribute('type') || '',
                    name: el.getAttribute('name') || '',
                    value: el.value !== undefined && typeof el.value === 'string' ? truncate(el.value) : '',
                    bounds: {
                        x: Math.round(rect.x),
                        y: Math.round(rect.y),
                        width: Math.round(rect.width),
                        height: Math.round(rect.height)
                    },
                    selector: `[data-surf-idx="${index}"]`,
                    fallback_selector: getCssSelector(el)
                };

                elementsInfo.push(info);
                index++;
            }

            return elementsInfo;
        }
        """
        try:
            dom_elements = await page.evaluate(js_script)
            return dom_elements or []
        except Exception as e:
            logger.error(f"Error extracting simplified DOM: {e}")
            return []

    async def _capture_screenshot_b64(self, page: Any) -> Optional[str]:
        """Captures viewport screenshot and encodes as base64 string."""
        try:
            screenshot_bytes = await page.screenshot(full_page=False, type="png")
            return base64.b64encode(screenshot_bytes).decode("utf-8")
        except Exception as e:
            logger.error(f"Error capturing screenshot: {e}")
            return None

    def _format_dom_for_prompt(self, dom_elements: List[Dict[str, Any]]) -> str:
        """Formats extracted DOM elements into a readable string for the AI model."""
        lines = []
        for el in dom_elements:
            tag = el.get("tag", "")
            idx = el.get("index", 0)
            attrs = []
            if el.get("id"):
                attrs.append(f'id="{el["id"]}"')
            if el.get("classes"):
                attrs.append(f'class="{el["classes"]}"')
            if el.get("type"):
                attrs.append(f'type="{el["type"]}"')
            if el.get("name"):
                attrs.append(f'name="{el["name"]}"')
            if el.get("role"):
                attrs.append(f'role="{el["role"]}"')
            if el.get("aria_label"):
                attrs.append(f'aria-label="{el["aria_label"]}"')
            if el.get("placeholder"):
                attrs.append(f'placeholder="{el["placeholder"]}"')
            if el.get("href"):
                attrs.append(f'href="{el["href"]}"')

            attr_str = " " + " ".join(attrs) if attrs else ""
            text_str = el.get("text", "")
            bounds = el.get("bounds", {})
            bounds_str = f"bounds: [x={bounds.get('x')}, y={bounds.get('y')}, w={bounds.get('width')}, h={bounds.get('height')}]"

            line = f'[{idx}] <{tag}{attr_str}>{text_str}</{tag}> ({bounds_str}, selector: {el.get("selector")})'
            lines.append(line)

        return "\n".join(lines)

    async def _call_theta_api(
        self, prompt: str, image_b64: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Sends request to Theta EdgeCloud Vision API with 3 retries and exponential backoff.
        Falls back gracefully if API is down or unavailable.
        """
        if not self.theta_api_key:
            logger.warning("THETA_API_KEY is not set. Falling back to DOM-only analysis.")
            return None

        headers = {
            "Authorization": f"Bearer {self.theta_api_key}",
            "Content-Type": "application/json",
        }

        user_content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        if image_b64:
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                }
            )

        payload = {
            "model": self.vision_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an AI element resolution vision assistant for web automation. "
                        "You analyze screenshots and DOM trees to identify elements matching user instructions. "
                        "Always respond with strict, valid JSON matching the requested schema."
                    ),
                },
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.1,
            "max_tokens": 1000,
        }

        max_attempts = 3
        backoff = 1.0

        for attempt in range(1, max_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        self.theta_api_url, json=payload, headers=headers
                    )
                    if response.status_code == 200:
                        return response.json()

                    logger.warning(
                        f"Theta API returned HTTP {response.status_code} "
                        f"(attempt {attempt}/{max_attempts}): {response.text[:200]}"
                    )
            except Exception as e:
                logger.warning(
                    f"Theta API call exception (attempt {attempt}/{max_attempts}): {e}"
                )

            if attempt < max_attempts:
                await asyncio.sleep(backoff)
                backoff *= 2.0

        logger.error(
            "Theta API calls failed after maximum retry attempts. Falling back to DOM-only analysis."
        )
        return None

    def _extract_json_from_text(self, text: str) -> Optional[Any]:
        """Extracts JSON object or array from LLM response text."""
        if not text:
            return None

        text = text.strip()

        # Check for markdown code blocks
        code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if code_block_match:
            text = code_block_match.group(1).strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try finding JSON start/end
        json_match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        return None

    def _observe_fallback(
        self, dom_elements: List[Dict[str, Any]], instruction: str
    ) -> List[ElementInfo]:
        """DOM-only heuristic analysis fallback when AI API is unavailable."""
        logger.info(f"Running DOM-only fallback observation for instruction: '{instruction}'")
        terms = [t.lower() for t in re.findall(r"\w+", instruction) if len(t) > 2]
        if not terms:
            terms = [instruction.lower()]

        results = []
        for el in dom_elements:
            score = 0.0
            searchable_text = " ".join(
                [
                    el.get("text", ""),
                    el.get("aria_label", ""),
                    el.get("placeholder", ""),
                    el.get("id", ""),
                    el.get("name", ""),
                    el.get("value", ""),
                    el.get("classes", ""),
                    el.get("tag", ""),
                ]
            ).lower()

            for term in terms:
                if term in searchable_text:
                    score += 1.0

            if score > 0:
                confidence = min(0.85, 0.4 + (score * 0.15))
                desc = (
                    el.get("text")
                    or el.get("aria_label")
                    or el.get("placeholder")
                    or el.get("id")
                    or f"{el.get('tag')} element"
                )
                results.append(
                    (
                        score,
                        ElementInfo(
                            selector=el["selector"],
                            description=f"Matched element: {desc}",
                            confidence=confidence,
                            bounds=el["bounds"],
                            index=el["index"],
                        ),
                    )
                )

        results.sort(key=lambda x: x[0], reverse=True)
        return [r[1] for r in results[:10]]

    def _extract_fallback(
        self, dom_elements: List[Dict[str, Any]], instruction: str
    ) -> Dict[str, Any]:
        """DOM-only heuristic data extraction fallback when AI API is unavailable."""
        logger.info(f"Running DOM-only fallback extraction for instruction: '{instruction}'")
        data: Dict[str, Any] = {"extracted_elements": []}

        for el in dom_elements:
            field_name = el.get("name") or el.get("id") or el.get("placeholder") or el.get("aria_label")
            if field_name:
                data["extracted_elements"].append({
                    "field": field_name,
                    "tag": el.get("tag"),
                    "value": el.get("value") or el.get("text"),
                    "selector": el.get("selector")
                })
        return data

    def _parse_action_instruction(self, instruction: str) -> Tuple[str, str, str]:
        """
        Parses action instruction to determine action type, target description, and optional input value.
        Action types: click, type, select, hover, scroll
        """
        instr = instruction.strip()
        instr_lower = instr.lower()

        # 1. Scroll
        if re.search(r"\b(scroll|swipe|page down|page up)\b", instr_lower):
            direction = "up" if "up" in instr_lower else "down"
            return "scroll", "window", direction

        # 2. Type / Fill / Enter / Input / Write
        type_quote_match = re.search(
            r"\b(?:type|fill|enter|input|write|set)\b\s+['\"]([^'\"]+)['\"]\s+(?:into|in|to|for|on)?\s*(.*)",
            instr,
            re.IGNORECASE,
        )
        if type_quote_match:
            val = type_quote_match.group(1)
            target = type_quote_match.group(2).strip() or instr
            return "type", target, val

        fill_with_match = re.search(
            r"\b(?:fill|type|enter|input|set)\b\s+(?:the\s+)?(.*?)\s+with\s+['\"]?([^'\"]+?)['\"]?$",
            instr,
            re.IGNORECASE,
        )
        if fill_with_match:
            target = fill_with_match.group(1).strip()
            val = fill_with_match.group(2).strip()
            return "type", target, val

        enter_in_match = re.search(
            r"\b(?:type|fill|enter|input|write)\b\s+(\S+)\s+(?:into|in|to|on)\s+(.*)",
            instr,
            re.IGNORECASE,
        )
        if enter_in_match:
            val = enter_in_match.group(1).strip()
            target = enter_in_match.group(2).strip()
            return "type", target, val

        # 3. Select / Choose / Pick
        select_match = re.search(
            r"\b(?:select|choose|pick)\b\s+['\"]?([^'\"]+?)['\"]?\s+(?:from|in|on)\s+(.*)",
            instr,
            re.IGNORECASE,
        )
        if select_match:
            val = select_match.group(1).strip()
            target = select_match.group(2).strip()
            return "select", target, val

        # 4. Hover
        hover_match = re.search(
            r"\b(?:hover|move to|mouse over)\b\s*(?:over|on)?\s*(.*)",
            instr,
            re.IGNORECASE,
        )
        if hover_match and hover_match.group(1).strip():
            target = hover_match.group(1).strip()
            return "hover", target, ""

        # 5. Click
        click_match = re.search(
            r"\b(?:click|press|tap|check|uncheck|toggle|open)\b\s*(?:on|the)?\s*(.*)",
            instr,
            re.IGNORECASE,
        )
        if click_match and click_match.group(1).strip():
            target = click_match.group(1).strip()
            return "click", target, ""

        return "click", instr, ""

    async def observe(self, page: Any, instruction: str) -> List[ElementInfo]:
        """
        Observes the page to locate elements matching a natural language instruction.
        Returns a list of ElementInfo dataclass instances.
        """
        dom_elements = await self._get_simplified_dom(page)
        if not dom_elements:
            logger.warning("No visible DOM elements found on page.")
            return []

        screenshot_b64 = await self._capture_screenshot_b64(page)
        dom_context = self._format_dom_for_prompt(dom_elements)

        prompt = f"""Identify elements on the web page that match the following natural language instruction:
Instruction: "{instruction}"

Simplified DOM Tree of Visible Elements:
{dom_context}

Respond ONLY with a valid JSON object in the following format:
{{
  "matches": [
    {{
      "index": <element index integer>,
      "selector": "<CSS selector>",
      "description": "<short description of the element match>",
      "confidence": <confidence score float from 0.0 to 1.0>
    }}
  ]
}}
If no elements match, return {{"matches": []}}.
"""

        api_response = await self._call_theta_api(prompt, screenshot_b64)

        if not api_response:
            return self._observe_fallback(dom_elements, instruction)

        try:
            choices = api_response.get("choices", [])
            if not choices:
                return self._observe_fallback(dom_elements, instruction)

            content = choices[0].get("message", {}).get("content", "")
            parsed_json = self._extract_json_from_text(content)

            if not parsed_json or "matches" not in parsed_json:
                return self._observe_fallback(dom_elements, instruction)

            dom_by_index = {el["index"]: el for el in dom_elements}
            results = []

            for match in parsed_json.get("matches", []):
                idx = match.get("index")
                dom_el = dom_by_index.get(idx)

                selector = match.get("selector") or (dom_el.get("selector") if dom_el else "")
                description = match.get("description") or (dom_el.get("text") if dom_el else "Matching element")
                confidence = float(match.get("confidence", 0.9))
                bounds = dom_el.get("bounds", {"x": 0, "y": 0, "width": 0, "height": 0}) if dom_el else match.get("bounds", {"x": 0, "y": 0, "width": 0, "height": 0})

                results.append(
                    ElementInfo(
                        selector=selector,
                        description=description,
                        confidence=confidence,
                        bounds=bounds,
                        index=idx if idx is not None else -1,
                    )
                )

            return results
        except Exception as e:
            logger.error(f"Error parsing observe API response: {e}")
            return self._observe_fallback(dom_elements, instruction)

    async def act(self, page: Any, instruction: str) -> ActionResult:
        """
        Executes an action on the page matching the instruction.
        Handles click, type, select, hover, and scroll actions.
        """
        action_type, target_desc, value = self._parse_action_instruction(instruction)

        # Handle scroll action directly
        if action_type == "scroll":
            try:
                scroll_distance = -500 if value == "up" else 500
                await page.evaluate(f"window.scrollBy(0, {scroll_distance})")
                return ActionResult(
                    success=True,
                    action_type="scroll",
                    selector="window",
                    message=f"Successfully scrolled window {value}",
                    value=value,
                )
            except Exception as e:
                return ActionResult(
                    success=False,
                    action_type="scroll",
                    selector="window",
                    message=f"Failed to scroll window: {e}",
                    value=value,
                )

        # For element interaction actions, locate element via observe
        observed_elements = await self.observe(page, target_desc)

        if not observed_elements:
            return ActionResult(
                success=False,
                action_type=action_type,
                selector="",
                message=f"No element found matching instruction target '{target_desc}'",
                value=value,
            )

        target_element = observed_elements[0]
        primary_selector = target_element.selector
        bounds = target_element.bounds

        # Perform action
        try:
            if action_type == "click":
                try:
                    await page.click(primary_selector, timeout=5000)
                    return ActionResult(
                        success=True,
                        action_type="click",
                        selector=primary_selector,
                        message=f"Successfully clicked element with selector '{primary_selector}'",
                    )
                except Exception as e:
                    logger.warning(f"Click by selector '{primary_selector}' failed, trying bounding box click: {e}")
                    if bounds and bounds.get("width", 0) > 0 and bounds.get("height", 0) > 0:
                        cx = bounds["x"] + bounds["width"] / 2.0
                        cy = bounds["y"] + bounds["height"] / 2.0
                        await page.mouse.click(cx, cy)
                        return ActionResult(
                            success=True,
                            action_type="click",
                            selector=primary_selector,
                            message=f"Successfully clicked element via bounding box coordinates ({cx}, {cy})",
                        )
                    raise e

            elif action_type == "type":
                try:
                    await page.fill(primary_selector, value, timeout=5000)
                    return ActionResult(
                        success=True,
                        action_type="type",
                        selector=primary_selector,
                        message=f"Successfully typed value into '{primary_selector}'",
                        value=value,
                    )
                except Exception as e:
                    logger.warning(f"Fill by selector '{primary_selector}' failed, trying click and keyboard type: {e}")
                    if bounds and bounds.get("width", 0) > 0:
                        cx = bounds["x"] + bounds["width"] / 2.0
                        cy = bounds["y"] + bounds["height"] / 2.0
                        await page.mouse.click(cx, cy)
                        await page.keyboard.type(value)
                        return ActionResult(
                            success=True,
                            action_type="type",
                            selector=primary_selector,
                            message=f"Successfully typed value via mouse click at ({cx}, {cy}) and keyboard",
                            value=value,
                        )
                    raise e

            elif action_type == "select":
                try:
                    await page.select_option(primary_selector, value=value, timeout=5000)
                    return ActionResult(
                        success=True,
                        action_type="select",
                        selector=primary_selector,
                        message=f"Successfully selected option '{value}' in '{primary_selector}'",
                        value=value,
                    )
                except Exception as e:
                    try:
                        await page.select_option(primary_selector, label=value, timeout=5000)
                        return ActionResult(
                            success=True,
                            action_type="select",
                            selector=primary_selector,
                            message=f"Successfully selected option label '{value}' in '{primary_selector}'",
                            value=value,
                        )
                    except Exception:
                        raise e

            elif action_type == "hover":
                try:
                    await page.hover(primary_selector, timeout=5000)
                    return ActionResult(
                        success=True,
                        action_type="hover",
                        selector=primary_selector,
                        message=f"Successfully hovered over '{primary_selector}'",
                    )
                except Exception as e:
                    if bounds and bounds.get("width", 0) > 0:
                        cx = bounds["x"] + bounds["width"] / 2.0
                        cy = bounds["y"] + bounds["height"] / 2.0
                        await page.mouse.move(cx, cy)
                        return ActionResult(
                            success=True,
                            action_type="hover",
                            selector=primary_selector,
                            message=f"Successfully hovered over coordinates ({cx}, {cy})",
                        )
                    raise e

        except Exception as e:
            return ActionResult(
                success=False,
                action_type=action_type,
                selector=primary_selector,
                message=f"Failed to execute action '{action_type}' on selector '{primary_selector}': {e}",
                value=value,
            )

        return ActionResult(
            success=False,
            action_type=action_type,
            selector=primary_selector,
            message=f"Unsupported action type '{action_type}'",
            value=value,
        )

    async def extract(self, page: Any, instruction: str) -> Dict[str, Any]:
        """
        Extracts structured data from the page using screenshot and DOM context based on instruction.
        Returns a dictionary containing extracted JSON data.
        """
        dom_elements = await self._get_simplified_dom(page)
        screenshot_b64 = await self._capture_screenshot_b64(page)
        dom_context = self._format_dom_for_prompt(dom_elements)

        prompt = f"""Extract structured data from the web page based on the following instruction:
Instruction: "{instruction}"

Simplified DOM Tree of Visible Elements:
{dom_context}

Respond ONLY with a valid JSON object representing the extracted data. Do not include markdown or explanations outside JSON.
"""

        api_response = await self._call_theta_api(prompt, screenshot_b64)

        if not api_response:
            return self._extract_fallback(dom_elements, instruction)

        try:
            choices = api_response.get("choices", [])
            if not choices:
                return self._extract_fallback(dom_elements, instruction)

            content = choices[0].get("message", {}).get("content", "")
            extracted_dict = self._extract_json_from_text(content)

            if isinstance(extracted_dict, dict):
                return extracted_dict
            elif isinstance(extracted_dict, list):
                return {"data": extracted_dict}
            else:
                return self._extract_fallback(dom_elements, instruction)

        except Exception as e:
            logger.error(f"Error parsing extract API response: {e}")
            return self._extract_fallback(dom_elements, instruction)


# Standalone function exports for convenient import
async def observe(
    page: Any, instruction: str, resolver: Optional[SurfAIResolver] = None
) -> List[ElementInfo]:
    """Standalone observe function delegating to SurfAIResolver."""
    if resolver is None:
        resolver = SurfAIResolver()
    return await resolver.observe(page, instruction)


async def act(
    page: Any, instruction: str, resolver: Optional[SurfAIResolver] = None
) -> ActionResult:
    """Standalone act function delegating to SurfAIResolver."""
    if resolver is None:
        resolver = SurfAIResolver()
    return await resolver.act(page, instruction)


async def extract(
    page: Any, instruction: str, resolver: Optional[SurfAIResolver] = None
) -> Dict[str, Any]:
    """Standalone extract function delegating to SurfAIResolver."""
    if resolver is None:
        resolver = SurfAIResolver()
    return await resolver.extract(page, instruction)
