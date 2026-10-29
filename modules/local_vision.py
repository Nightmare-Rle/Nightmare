"""Local OCR + vision capability layer.

OCR: Tesseract (local, offline, free). VQA: a local Ollama vision model
(moondream / llava / minicpm-v / qwen2-vl) when one is installed, with
graceful fallback to the configured cloud engine.
"""
import os
import re
import shutil
import subprocess
import tempfile
import threading

_TESSERACT_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
]

# Local vision models, smallest/most capable first. moondream is ~1.7GB and
# fast on CPU; the others are fallbacks if the user has them installed.
_LOCAL_VLM_CANDIDATES = [
    "moondream",
    "moondream:latest",
    "llava:7b",
    "minicpm-v",
    "qwen2-vl:2b",
    "llava-llama3",
]

# The VLM is only needed while a vision tool is running. On a 16GB machine the
# text model is already resident, so the vision model is kept warm briefly and
# then released instead of sitting in RAM and tripping the low-memory watcher.
VLM_KEEP_ALIVE = 120
_cache = {"checked_at": 0.0, "path": None, "vlm": None}


def _tesseract_path():
    """Locate the tesseract binary (cached)."""
    if _cache["path"] is not None:
        return _cache["path"] or None
    found = None
    for cand in _TESSERACT_CANDIDATES:
        if os.path.isfile(cand):
            found = cand
            break
    if not found:
        found = shutil.which("tesseract")
    _cache["path"] = found or ""
    return _cache["path"] or None


def ocr_available():
    return _tesseract_path() is not None


def ocr_image(image_path, lang="eng", timeout=45):
    """Run Tesseract OCR on an image file. Returns the extracted text."""
    exe = _tesseract_path()
    if not exe:
        return None
    if not os.path.isfile(image_path):
        return None
    out_base = os.path.join(tempfile.gettempdir(),
                            "nai_ocr_%d" % (abs(hash(image_path)) % 10**8))
    try:
        proc = subprocess.run(
            [exe, image_path, out_base, "-l", lang, "--psm", "3"],
            capture_output=True, timeout=timeout)
        txt_path = out_base + ".txt"
        text = ""
        if os.path.isfile(txt_path):
            with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            try:
                os.remove(txt_path)
            except Exception:
                pass
        if not text.strip():
            return None
        return text.strip()
    except Exception:
        return None
    finally:
        for f in (out_base + ".txt",):
            try:
                if os.path.isfile(f):
                    os.remove(f)
            except Exception:
                pass


def _ollama_url():
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434").replace(
        "0.0.0.0", "localhost").rstrip("/")


def _ollama_installed_models():
    try:
        import requests
        r = requests.get(_ollama_url() + "/api/tags", timeout=3)
        if r.status_code != 200:
            return []
        return [m.get("name", "") for m in (r.json().get("models") or [])]
    except Exception:
        return []


def local_vlm():
    """Name of an installed local vision model, or None."""
    if _cache["vlm"]:
        return _cache["vlm"]
    installed = _ollama_installed_models()
    if not installed:
        return None
    for cand in _LOCAL_VLM_CANDIDATES:
        for name in installed:
            if name == cand or name.split(":")[0] == cand.split(":")[0]:
                _cache["vlm"] = name
                return name
    # any installed model with a known vision family
    for name in installed:
        if any(k in name.lower() for k in ("moondream", "llava", "minicpm", "qwen2-vl",
                                           "bakllava", "vision", "-vl")):
            _cache["vlm"] = name
            return name
    return None


def local_vision_describe(image_path, prompt="Describe what is on this screen.",
                          timeout=180, retries=1):
    """Describe an image using a LOCAL vision model. Returns None if unavailable.

    The first call after a cold start can return an empty body while the vision
    model is still being paged into RAM, so an empty result is retried once.
    """
    model = local_vlm()
    if not model or not os.path.isfile(image_path):
        return None
    import base64
    import requests
    for attempt in range(retries + 1):
        try:
            with open(image_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            r = requests.post(
                _ollama_url() + "/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "images": [b64],
                    "stream": False,
                    "think": False,
                    "options": {"num_ctx": 4096, "temperature": 0.3},
                    "keep_alive": VLM_KEEP_ALIVE,
                },
                timeout=timeout)
            if r.status_code != 200:
                return None
            out = (r.json().get("response") or "").strip()
            if out:
                return out
        except Exception:
            return None
    return None


def local_vision_locate(image_path, description, timeout=180):
    """Locate an element in an image with a local VLM. Returns (x, y) or None."""
    model = local_vlm()
    if not model or not os.path.isfile(image_path):
        return None
    try:
        import base64
        import json
        import requests
        try:
            from PIL import Image
            w, h = Image.open(image_path).size
        except Exception:
            w = h = 0
        prompt = (
            f"Find this element on the screen: {description}\n"
            f"Image size is {w}x{h} pixels. Return ONLY JSON: "
            '{"x": <pixel_x>, "y": <pixel_y>, "found": true} '
            'or {"found": false} if it is not visible.'
        )
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        r = requests.post(
            _ollama_url() + "/api/generate",
            json={"model": model, "prompt": prompt, "images": [b64],
                  "stream": False, "think": False,
                  "options": {"num_ctx": 4096, "temperature": 0.1},
                  "keep_alive": VLM_KEEP_ALIVE},
            timeout=timeout)
        if r.status_code != 200:
            return None
        raw = r.json().get("response") or ""
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return None
        data = json.loads(m.group(0))
        if data.get("found") and "x" in data and "y" in data:
            return int(data["x"]), int(data["y"])
        return None
    except Exception:
        return None


def vision_status():
    return {
        "ocr": "tesseract: " + (_tesseract_path() or "not installed"),
        "local_vlm": local_vlm() or "none installed",
        "cloud_fallback": True,
    }
