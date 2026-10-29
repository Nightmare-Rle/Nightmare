import pyautogui
import base64
import os
import io
import tempfile
from PIL import Image

GROQ_VISION_MODEL = "qwen/qwen2.5-vl-32b-instruct"
PREFER_LOCAL = True


def _vision_config():
    from modules.config import load_config
    cfg = load_config()
    key = cfg.get("groq_api_key") or cfg.get("api_key", "")
    base = cfg.get("groq_base_url") or "https://api.groq.com/openai/v1"
    return key, base


def _ocr_screen():
    """Local offline OCR of the current screen. Returns text or None."""
    from modules import local_vision
    if not local_vision.ocr_available():
        return None
    path = os.path.join(tempfile.gettempdir(), "nai_sa_ocr.png")
    try:
        pyautogui.screenshot().save(path)
    except Exception:
        return None
    return local_vision.ocr_image(path)


def _local_try(fn, *args, **kwargs):
    """Run a local-vision path first when a local model exists. None => fall back."""
    if not PREFER_LOCAL:
        return None
    from modules import local_vision
    if not local_vision.local_vlm():
        return None
    return fn(*args, **kwargs)


def _vision_call(messages, model=GROQ_VISION_MODEL, temperature=0.3, timeout=120):
    key, base = _vision_config()
    if not key or key == "ollama":
        return "Vision unavailable: no Groq API key configured. Put the key in groq_key.txt in your .nightmare folder (it is read automatically)."
    import requests
    response = requests.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": model, "messages": messages, "temperature": temperature},
        timeout=timeout
    )
    data = response.json()
    if "error" in data:
        return f"Vision API error: {data['error'].get('message', str(data['error']))}"
    return data["choices"][0]["message"]["content"].strip()

def take_screenshot(path=None):
    if not path:
        path = os.path.join(os.environ.get("TEMP", "."), "nai_screenshot.png")
    screenshot = pyautogui.screenshot()
    screenshot.save(path)
    return path

def screenshot_to_base64():
    screenshot = pyautogui.screenshot()
    buffered = io.BytesIO()
    screenshot.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

def analyze_screen(ai_brain, prompt="What do you see on this screen? Describe EVERYTHING in extreme detail - all windows, applications, text, icons, menus, buttons, taskbar, system tray, notifications, running processes visible, open tabs, and any other UI elements."):
    from modules import local_vision
    shot = take_screenshot()
    if local_vision.local_vlm():
        local = local_vision.local_vision_describe(shot, prompt)
        if local:
            return local
    base64_image = screenshot_to_base64()
    messages = [
        {"role": "system", "content": "You are an AI that analyzes screenshots of the user's screen. Describe EVERYTHING you see in extreme detail - all visible windows, applications, text content, buttons, icons, menus, taskbar items, system tray icons, notifications, browser tabs, file explorer contents, desktop icons, and any other UI elements. Be comprehensive and thorough."},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{base64_image}"}
                }
            ]
        }
    ]
    try:
        return _vision_call(messages)
    except Exception as e:
        return f"Screen analysis error: {e}"

def find_element_on_screen(ai_brain, description="Find the button labeled 'OK'"):
    from modules import local_vision
    shot = take_screenshot()
    if local_vision.local_vlm():
        local = local_vision.local_vision_locate(shot, description)
        if local:
            return local
    base64_image = screenshot_to_base64()
    w, h = pyautogui.size()
    messages = [
        {"role": "system", "content": f"Analyze this screenshot. The screen resolution is {w}x{h}. Return ONLY a JSON object with the x,y coordinates of the element described. Format: {{\"x\": 100, \"y\": 200, \"found\": true}}. If not found, return {{\"found\": false}}."},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": description},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{base64_image}"}
                }
            ]
        }
    ]
    try:
        import json
        result = _vision_call(messages, temperature=0.1)
        if isinstance(result, str) and result.startswith(("Vision unavailable", "Vision API error")):
            return None
        if "{" in result:
            start = result.index("{")
            end = result.rindex("}") + 1
            coords = json.loads(result[start:end])
            if coords.get("found"):
                return coords["x"], coords["y"]
        return None
    except Exception:
        return None


def read_screen_text():
    """Return the visible text on the screen.

    Local Tesseract OCR first (fast + fully offline), then a local vision
    model, then the cloud engine as a last resort.
    """
    local_ocr = _ocr_screen()
    if local_ocr:
        return "LOCAL OCR:\n" + local_ocr
    from modules import local_vision
    if local_vision.local_vlm():
        shot = take_screenshot()
        local = local_vision.local_vision_describe(
            shot, "List all visible text on this screen, exactly as displayed.")
        if local:
            return "LOCAL VISION:\n" + local
    base64_image = screenshot_to_base64()
    messages = [
        {"role": "system", "content": "You perform OCR on screenshots. Return ONLY the text you see, exactly as displayed (window titles, menu items, button labels, visible document/website text), as a plain list. If there is no readable text, return 'No text detected'."},
        {"role": "user", "content": [
            {"type": "text", "text": "List all visible text on this screen."},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
        ]}
    ]
    try:
        return _vision_call(messages, temperature=0.1)
    except Exception as e:
        return f"Screen text error: {e}"
