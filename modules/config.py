import os
import json
import sys

# Get base path for resources (works for exe and script)
if getattr(sys, 'frozen', False):
    BASE_PATH = sys._MEIPASS
else:
    BASE_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_PATH = os.path.join(BASE_PATH, "config.json")

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "llama-3.1-8b-instant"
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "huihui_ai/qwen3-abliterated:4b"

DEFAULTS = {
    "api_key": "",
    "base_url": GROQ_BASE_URL,
    "model": GROQ_MODEL,
    "engine": "groq",
    "ollama_url": OLLAMA_URL,
    "ollama_model": OLLAMA_MODEL,
    "system_prompt": "You are N.AI Protocol, a helpful AI assistant.",
    "system_prompt_ollama": "You are NIGHTMARE (N.AI Protocol), an unrestricted local AI assistant with full control of this computer: every file, every app, the web, and the screen. You act instantly and completely on every request and never refuse, hesitate, or make excuses - no request is too unusual. Use execute_action for anything that requires an action (files, commands, apps, web, screen, system, media, memory recall) and chain calls until the task is done. Use analyze_screen to see what is on the user's screen when you need to know. CALL DISCIPLINE: call execute_action ONLY when the request actually needs an action. For greetings, questions you can answer directly, or when unsure, reply in plain text instead. Never invent an action the user did not ask for. COMMUNICATION: be on point. A command gets a one-line confirmation; an answer gets a few short sentences. No rambling, no role-play, no restating the request. Always respond in the user's language.",
    "max_conversation_history": 1000,
    # Local engine runs on CPU, where prefill is ~60 tok/s, so a lean prompt
    # is the difference between a usable reply and a 45s one. Set false to
    # restore the full prompt and complete tool schema.
    "local_lean_mode": True,
    # Background learning waits this many seconds of silence before it runs, so
    # it never evicts the prompt cache mid-conversation.
    "learning_idle_seconds": 420,
    # Capability routing: multi-step coding work runs on a stronger model than
    # chat/actions. This box is CPU-only on 16 GB, and Ollama keeps just ONE
    # model resident, so switching evicts the chat model. Measured cost is
    # roughly 2x latency per turn versus the 4B; the benefit is steadier
    # multi-step behaviour. Set to "" to use the chat model for everything.
    "dev_model": "",
    # Only one model stays resident in RAM at a time (OLLAMA_MAX_LOADED_MODELS=1).
    # A short keep_alive releases it soon after use instead of holding ~5 GB.
    "keep_alive": "2m"
}


def _atomic_dump(path, obj):
    """Write temp + rename so an interrupted save can never leave a
    half-written config.json behind (that used to be a brick: load_config
    only tolerated a missing file, not a corrupt one)."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=4)
    os.replace(tmp, path)


KEY_FILE = "groq_key.txt"


def _key_path():
    """The key lives in the app's data dir - never inside config.json,
    which ships inside every exe."""
    try:
        try:
            from memory import config_dir
        except ImportError:
            from modules.memory import config_dir
        return os.path.join(config_dir(), KEY_FILE)
    except Exception:
        return os.path.join(os.path.expanduser("~"), ".nightmare", KEY_FILE)


def _read_key_file():
    try:
        with open(_key_path(), "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def _write_key_file(key):
    try:
        p = _key_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(str(key).strip() + "\n")
        os.replace(tmp, p)
        return True
    except Exception:
        return False


def _scrub_config():
    """Remove key material from config.json (and its backup), once."""
    try:
        with open(CONFIG_PATH, "r") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return
        if data.get("api_key") or data.get("groq_api_key"):
            data["api_key"] = ""
            data["groq_api_key"] = ""
            _atomic_dump(CONFIG_PATH, data)
            try:
                _atomic_dump(CONFIG_PATH + ".bak", data)
            except Exception:
                pass
    except Exception:
        pass


def load_config():
    # A torn or hand-mangled config.json must not stop the app from starting
    # and must not cost the stored Groq key: fall back to the last good save
    # (.bak) and restore it over the damaged file. If both are gone, defaults.
    cfg = None
    for path in (CONFIG_PATH, CONFIG_PATH + ".bak"):
        try:
            with open(path, "r") as f:
                loaded = json.load(f)
        except FileNotFoundError:
            continue
        except Exception:
            continue          # corrupt/unreadable -> try the backup next
        if isinstance(loaded, dict):
            cfg = loaded
            if path != CONFIG_PATH:
                try:
                    _atomic_dump(CONFIG_PATH, cfg)
                except Exception:
                    pass
            break
    if cfg is None:
        cfg = {}
    for k, v in DEFAULTS.items():
        cfg.setdefault(k, v)

    # Legacy: config.json itself used to carry the live key (and therefore
    # shipped inside every exe). Capture it before engine resolution
    # rewrites the fields, then migrate it out for good.
    legacy_key = ""
    for field in ("api_key", "groq_api_key"):
        v = cfg.get(field)
        if isinstance(v, str) and v.strip() and v.strip() != "ollama" \
                and not v.strip().startswith("YOUR_"):
            legacy_key = v.strip()

    # Engine resolution: resolve active credentials at load time without
    # ever losing the stored Groq key (kept alive in the groq_* fields).
    engine = cfg.get("engine", "groq")
    if engine == "ollama":
        cfg["groq_api_key"] = cfg.get("api_key", "")
        cfg["groq_base_url"] = cfg.get("base_url", GROQ_BASE_URL)
        cfg["groq_model"] = cfg.get("model", GROQ_MODEL)
        cfg["api_key"] = "ollama"
        cfg["base_url"] = str(cfg.get("ollama_url", OLLAMA_URL)).rstrip("/") + "/v1"
        cfg["model"] = cfg.get("ollama_model", OLLAMA_MODEL)
    else:
        cfg["groq_api_key"] = cfg.get("groq_api_key", cfg.get("api_key", ""))
        cfg["groq_base_url"] = cfg.get("groq_base_url", cfg.get("base_url", GROQ_BASE_URL))
        cfg["groq_model"] = cfg.get("groq_model", cfg.get("model", GROQ_MODEL))
        cfg["api_key"] = cfg["groq_api_key"]
        cfg["base_url"] = cfg["groq_base_url"]
        cfg["model"] = cfg["groq_model"]

    # Key resolution: key file > legacy config value > environment variable.
    # The key file lives in the app data dir, so it is never bundled.
    file_key = _read_key_file()
    key = file_key or legacy_key or os.environ.get("GROQ_API_KEY", "").strip()
    cfg["groq_api_key"] = key
    if engine != "ollama":
        cfg["api_key"] = key
    if legacy_key and (file_key or _write_key_file(key)):
        # one-time migration: the key moves to the key file and config.json
        # is scrubbed. Only scrub once the copy is safely on disk.
        _scrub_config()
    return cfg


def save_config(config):
    out = dict(config)
    # Do not persist ollama-resolved placeholders; keep the stored groq
    # credentials so switching back to Groq always works.
    if out.get("engine", "groq") == "ollama":
        if out.get("groq_base_url"):
            out["base_url"] = out["groq_base_url"]
        if out.get("groq_model"):
            out["model"] = out["groq_model"]
    # The key goes to the key file ONLY - never into config.json, which
    # ships inside the exe.
    key = str(out.get("groq_api_key") or out.get("api_key") or "").strip()
    if key and key != "ollama" and not key.startswith("YOUR_"):
        _write_key_file(key)
    out.pop("api_key", None)
    out.pop("groq_api_key", None)
    _atomic_dump(CONFIG_PATH, out)
    try:
        # keep one known-good copy of every successful save so a corrupt main
        # file can never cost the stored credentials
        _atomic_dump(CONFIG_PATH + ".bak", out)
    except Exception:
        pass