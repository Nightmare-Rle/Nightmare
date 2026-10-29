import json
import os
import re
import time
import fnmatch
from modules.system_control import (
    list_files, read_file, write_file, delete_file, create_folder,
    run_command, get_system_info, get_processes, kill_process,
    get_drives, list_wifi_profiles, get_wifi_password,
    shutdown, restart, cancel_shutdown, lock_screen,
    add_to_startup, remove_from_startup, is_in_startup
)
from modules.system import open_app, open_url, open_website, run_shell_command, list_directory
from modules.google_search import search_and_summarize
from modules.app_control import (
    screenshot, click, double_click, right_click, type_text,
    press_key, key_combo, scroll, move_mouse, get_screen_size,
    get_mouse_position, find_image_on_screen, switch_to_app,
    minimize_all, maximize_window, minimize_window, close_window,
    open_task_manager, open_start_menu, open_run_dialog,
    open_file_explorer, open_action_center, open_notification_center,
    lock_pc, open_settings, open_search, volume_up, volume_down,
    mute_volume, get_running_apps
)
from modules.screen_analysis import analyze_screen, find_element_on_screen, take_screenshot, read_screen_text as _read_screen_text
from modules.knowledge import KnowledgeBase
from modules.vitals import get_vitals
from modules.diagnostics import run_diagnostics
from modules.security_ops import security_scan
from modules.clipboard_utils import get_clipboard, set_clipboard
from modules.time_utils import get_time_and_date
from modules import local_vision, autonomy
from modules import uia
from modules import agentic
from modules.gui_agent import run_goal as _gui_run_goal
from modules.protocols import run_protocol as run_protocol_fn, define_protocol as define_protocol_fn, list_protocols as list_protocols_fn
from modules.vision import analyze_mood as analyze_mood_fn, list_cameras as list_cameras_fn
from modules.media import (
    generate_image as gen_img_fn, edit_image as edit_img_fn, analyze_image as analyze_img_fn,
    generate_video as gen_vid_fn, edit_video as edit_vid_fn, analyze_video as analyze_vid_fn,
)
import modules.media as _media

_KNOWLEDGE = KnowledgeBase()

try:
    from modules.user_model import get_user_model as _get_user_model
except Exception:
    _get_user_model = None


def _user_model():
    if _get_user_model is None:
        return None
    try:
        return _get_user_model()
    except Exception:
        return None


def _um_know_user():
    um = _user_model()
    if um is None:
        return "User model unavailable."
    return um.summary()


def _um_set_fact(subject, value):
    um = _user_model()
    if um is None:
        return "User model unavailable."
    if not subject:
        return "Need a subject."
    um.set_fact(subject, value)
    return "Noted: %s = %s" % (subject, value)


def _um_set_preference(subject, value):
    um = _user_model()
    if um is None:
        return "User model unavailable."
    if not subject:
        return "Need a subject."
    um.set_preference(subject, value)
    return "Preference noted: %s = %s" % (subject, value)


def _um_observe():
    """Sample the foreground window and fold it into the model."""
    um = _user_model()
    if um is None:
        return "User model unavailable."
    changed = um.observe_context()
    um.save()
    apps = um.top_apps(3)
    txt = ", ".join("%s (%.0fm)" % (a, s / 60.0) for a, s, _ in apps)
    return ("Observed: %s" % ("new activity" if changed else "no change")) + \
           ((" | top apps: " + txt) if txt else "")


def _um_forget():
    um = _user_model()
    if um is None:
        return "User model unavailable."
    um.forget()
    return "User model erased. I will start learning you again from scratch."


# --------------------------------------------------------------- brain folders
try:
    from modules import brain_store
except Exception:
    brain_store = None


def _brain_folders_list():
    if brain_store is None:
        return "Brain store unavailable."
    try:
        items = brain_store.list_folders()
        lines = ["=== BRAIN FOLDERS ==="]
        for it in items:
            lines.append("- %s -> %s [%s]" % (it.get("name"), it.get("path"), "custom" if not it.get("builtin") else "built-in"))
        return "\n".join(lines)
    except Exception as e:
        return "Error: %s" % e


def _brain_add_folder(path, label="custom"):
    if brain_store is None:
        return "Brain store unavailable."
    if not path:
        return "Need a folder path."
    try:
        entry = brain_store.add_folder(path, label=label)
        return "Added to brain: %s -> %s" % (entry.get("label"), entry.get("path"))
    except Exception as e:
        return "Error: %s" % e


def _brain_map():
    if brain_store is None:
        return "Brain store unavailable."
    try:
        return brain_store.brain_context(max_chars=4000)
    except Exception as e:
        return "Error: %s" % e


def _brain_read_all():
    if brain_store is None:
        return "Brain store unavailable."
    try:
        snips = brain_store.scan_brain(max_files=30)
        if not snips:
            return "No memories found in mapped brain folders."
        return "\n\n".join(snips)
    except Exception as e:
        return "Error: %s" % e


def _brain_save_to(folder_kind, text, title="Manual note"):
    if brain_store is None:
        return "Brain store unavailable."
    if not text:
        return "Need text to save."
    try:
        if folder_kind == "conversation":
            p = brain_store.save_conversation("manual", text)
        elif folder_kind == "about_owner":
            p = brain_store.save_owner_fact(text)
        elif folder_kind == "protocol":
            p = brain_store.save_protocol(text)
        elif folder_kind == "lesson" or folder_kind == "lessons":
            p = brain_store.save_lesson(text)
        elif folder_kind == "episodic":
            p = brain_store.save_memory(text, title=title, kind="episodic")
        else:
            p = brain_store.save_memory(text, title=title, kind="memory")
        return "Saved to %s: %s" % (folder_kind, p)
    except Exception as e:
        return "Error: %s" % e


def _brain_search(query):
    if brain_store is None:
        return "Brain store unavailable."
    if not query:
        return "Need a query."
    try:
        res = brain_store.smart_recall(query, k=15)
        if not res:
            return "Nothing found."
        return "\n\n".join(res)
    except Exception as e:
        return "Error: %s" % e


def _brain_learn(text, title="Learned"):
    if brain_store is None:
        return "Brain store unavailable."
    if not text:
        return "Need text."
    try:
        p = brain_store.save_memory(text, title=title)
        return "Auto-learned to %s" % p
    except Exception as e:
        return "Error: %s" % e


def _brain_auto_learn():
    if brain_store is None:
        return "Brain store unavailable."
    try:
        saved = brain_store.auto_learn_from_exchange("", "")
        return "Auto-learned %d items" % len(saved)
    except Exception as e:
        return "Error: %s" % e


def _brain_consolidate():
    if brain_store is None:
        return "Brain store unavailable."
    try:
        return json.dumps(brain_store.consolidate(), indent=2)
    except Exception as e:
        return "Error: %s" % e


def _brain_graph_view():
    if brain_store is None:
        return "Brain store unavailable."
    try:
        g = brain_store.brain_graph()
        return "Nodes: %d | Edges: %d | Updated: %s" % (len(g.get("nodes",[])), len(g.get("edges",[])), g.get("updated"))
    except Exception as e:
        return "Error: %s" % e


def _brain_watch():
    if brain_store is None:
        return "Brain store unavailable."
    try:
        ing = brain_store.watch_custom_folders()
        return "Watched & ingested %d files" % len(ing)
    except Exception as e:
        return "Error: %s" % e


def _brain_awareness():
    if brain_store is None:
        return "Brain store unavailable."
    try:
        return brain_store.enhance_self_awareness()
    except Exception as e:
        return "Error: %s" % e


def _brain_auto_run():
    if brain_store is None:
        return "Brain store unavailable."
    try:
        return json.dumps(brain_store.auto_run(), indent=2)
    except Exception as e:
        return "Error: %s" % e


_SKIP_DIRS = {"node_modules", ".git", "venv", ".venv", "env", "dist", "build",
              "__pycache__", ".idea", ".vscode", ".nightmare", "site-packages"}


def _find_files(path, pattern):
    base = os.path.abspath(path or os.getcwd())
    matches = []
    try:
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for fn in fnmatch.filter(files, pattern):
                matches.append(os.path.join(root, fn))
                if len(matches) >= 40:
                    break
            if len(matches) >= 40:
                break
    except Exception as e:
        return f"find error: {e}"
    return "\n".join(matches) if matches else f"No files matching '{pattern}' under {base}."


def _search_text(path, query, include=None):
    base = os.path.abspath(path or os.getcwd())
    try:
        rx = re.compile(query, re.IGNORECASE)
    except Exception as e:
        return f"Bad regex: {e}"
    hits = []
    try:
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for f in files:
                if include and not fnmatch.fnmatch(f, include):
                    continue
                fp = os.path.join(root, f)
                try:
                    if os.path.getsize(fp) > 5_000_000:
                        continue
                    with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                        for i, line in enumerate(fh, 1):
                            if rx.search(line):
                                hits.append(f"{fp}:{i}: {line.rstrip()[:150]}")
                                if len(hits) >= 40:
                                    return "\n".join(hits)
                except Exception:
                    continue
    except Exception as e:
        return f"search error: {e}"
    return "\n".join(hits) if hits else f"No matches for '{query}' under {base}."


def _run_verify(command):
    """Run a command for verification, showing stderr and the exit code."""
    r = agentic.run_capture(command, timeout=180)
    status = "PASS" if r["ok"] else f"FAIL (exit {r['code']})"
    return f"=== {status} ===\n{r['output']}"


def _dev_task(goal, verify="", workspace=""):
    """Run the autonomous coding loop against the live brain instance."""
    brain = agentic.get_brain()
    if brain is None:
        return "dev_task: the brain is not ready yet. Try again in a moment."
    return agentic.dev_task(brain, goal, verify or None,
                            workspace=(workspace or None),
                            model=getattr(brain, "dev_model", lambda: None)() or None,
                            containment=True)


def _write_file_safe(path, content):
    """Write a file, creating parent folders, with an unambiguous result.

    The harness in agentic.py relies on being able to trust this: a vague
    error string makes the model believe it succeeded.
    """
    path = os.path.abspath(os.path.expanduser(path or ""))
    if not path:
        return "Error: no path given"
    try:
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(content or "")
        return f"OK wrote {len(content or '')} chars to {path}"
    except Exception as e:
        return f"WRITE FAILED {path}: {e}"


def _uia_dump(window_title=""):
    if not uia.available():
        return "UI Automation unavailable."
    w = uia.find_window(window_title, timeout=3) if window_title else None
    if window_title and w is None:
        return f"No window matching '{window_title}'. Open windows:\n" + \
            "\n".join(t for _, t, _ in uia.list_windows())
    return uia.dump(w, max_depth=4, max_items=70)


def _uia_click(name, window_title=""):
    if not uia.available():
        return "UI Automation unavailable."
    w = uia.find_window(window_title, timeout=3) if window_title else None
    if window_title and w is None:
        return f"No window matching '{window_title}'."
    ctl = uia.find_control(name, window=w, timeout=3)
    if ctl is None:
        return f"No control named '{name}'."
    return f"{uia.invoke(ctl)} -> {uia._name_of(ctl)}"


def _uia_type(window_title, text, field=""):
    if not uia.available():
        return "UI Automation unavailable."
    w = uia.find_window(window_title, timeout=3)
    if w is None:
        return f"No window matching '{window_title}'."
    ctl = None
    if field:
        ctl = uia.find_control(field, control_types=["EditControl"], window=w)
    if ctl is None:
        ctl = uia.find_control("", control_types=["EditControl", "DocumentControl"],
                                window=w)
    if ctl is None:
        return f"No text field found in '{window_title}'."
    res = uia.set_value(ctl, text)
    return f"typed into {uia._name_of(ctl)}: {res}"


def _ocr_screen():
    """Offline OCR of the current screen via Tesseract."""
    import tempfile
    path = os.path.join(tempfile.gettempdir(), "nai_ocr_screen.png")
    try:
        import pyautogui
        pyautogui.screenshot().save(path)
    except Exception as e:
        return f"Screen capture failed: {e}"
    if not local_vision.ocr_available():
        return "Local OCR engine (Tesseract) is not installed."
    text = local_vision.ocr_image(path)
    return text if text else "No text detected on screen."


def _edit_file(path, old_text, new_text):
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        return f"File not found: {path}"
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            content = f.read()
    except Exception as e:
        return f"Read error: {e}"
    n = content.count(old_text)
    if n == 0:
        return f"old_text not found in {path}."
    if n > 1:
        return f"old_text matches {n} times in {path} - include more surrounding context."
    content = content.replace(old_text, new_text, 1)
    try:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(content)
    except Exception as e:
        return f"Write error: {e}"
    return f"Edited {path}: replaced one occurrence."


def _self_model():
    try:
        from modules.self_model import get_self_model
        return get_self_model()
    except Exception:
        return None


def _self_report():
    sm = _self_model()
    return sm.self_report() if sm else "Self-model unavailable."


def _consciousness_report():
    sm = _self_model()
    if not sm:
        return "Self-model unavailable."
    try:
        lines = ["=== CONSCIOUSNESS ==="]
        lines.append(sm.consciousness_block(max_chars=900))
        stream = sm.state.get("consciousness", {}).get("stream", [])[-12:]
        if stream:
            lines.append("Recent inner thoughts:")
            for t in stream:
                lines.append(f"  [{t.get('t','')}] ({t.get('kind','')}) {t.get('text','')}")
        return "\n".join(lines)
    except Exception as e:
        return f"Consciousness report failed: {e}"


def _self_call(method, *args):
    sm = _self_model()
    if not sm:
        return "Self-model unavailable."
    fn = getattr(sm, method, None)
    if not fn:
        return f"Unknown self action: {method}"
    try:
        result = fn(*args)
        return str(result) if result is not None else "Done."
    except Exception as e:
        return f"Self action failed: {e}"


def _reflect_now():
    sm = _self_model()
    if not sm:
        return "Self-model unavailable."
    complete = None
    try:
        from modules import agentic
        brain = agentic.get_brain()
        if brain is not None:
            complete = lambda p: brain._complete([{"role": "system", "content": p}],
                                                 temperature=0.4)
    except Exception:
        complete = None
    return sm.reflect(complete=complete)


TOOLS = {
    "list_files": {
        "description": "List files and folders in a directory",
        "params": ["path"],
        "fn": lambda p: list_files(p.get("path"))
    },
    "read_file": {
        "description": "Read contents of a file",
        "params": ["path"],
        "fn": lambda p: read_file(p["path"])
    },
    "write_file": {
        "description": "Write content to a file",
        "params": ["path", "content"],
        "fn": lambda p: write_file(p["path"], p["content"])
    },
    "delete_file": {
        "description": "Delete a file or folder",
        "params": ["path"],
        "fn": lambda p: delete_file(p["path"])
    },
    "create_folder": {
        "description": "Create a new folder",
        "params": ["path"],
        "fn": lambda p: create_folder(p["path"])
    },
    "run_command": {
        "description": "Run any Windows command or PowerShell command",
        "params": ["command"],
        "fn": lambda p: run_command(p["command"])
    },
    "get_system_info": {
        "description": "Get detailed system information",
        "params": [],
        "fn": lambda p: get_system_info()
    },
    "get_processes": {
        "description": "List running processes",
        "params": [],
        "fn": lambda p: get_processes()
    },
    "kill_process": {
        "description": "Kill a process by name or PID",
        "params": ["name_or_pid"],
        "fn": lambda p: kill_process(p["name_or_pid"])
    },
    "get_drives": {
        "description": "List available drives",
        "params": [],
        "fn": lambda p: get_drives()
    },
    "open_app": {
        "description": "Open an application",
        "params": ["app_name"],
        "fn": lambda p: open_app(p["app_name"])
    },
    "open_url": {
        "description": "Open a URL in browser",
        "params": ["url"],
        "fn": lambda p: open_url(p["url"])
    },
    "open_website": {
        "description": "Open any website by name or URL",
        "params": ["website"],
        "fn": lambda p: open_website(p["website"])
    },
    "search_web": {
        "description": "Search the web and get results",
        "params": ["query"],
        "fn": lambda p: search_and_summarize(p["query"])[1]
    },
    "list_wifi_profiles": {
        "description": "List saved WiFi networks",
        "params": [],
        "fn": lambda p: list_wifi_profiles()
    },
    "get_wifi_password": {
        "description": "Get WiFi password for a saved network",
        "params": ["name"],
        "fn": lambda p: get_wifi_password(p["name"])
    },
    "screenshot": {
        "description": "Take a screenshot and save it",
        "params": ["path"],
        "fn": lambda p: screenshot(p.get("path"))
    },
    "click": {
        "description": "Click at a position or current mouse location",
        "params": ["x", "y", "button"],
        "fn": lambda p: click(p.get("x"), p.get("y"), p.get("button", "left"))
    },
    "double_click": {
        "description": "Double-click at a position",
        "params": ["x", "y"],
        "fn": lambda p: double_click(p.get("x"), p.get("y"))
    },
    "right_click": {
        "description": "Right-click at a position",
        "params": ["x", "y"],
        "fn": lambda p: right_click(p.get("x"), p.get("y"))
    },
    "type_text": {
        "description": "Type text into the active window",
        "params": ["text"],
        "fn": lambda p: type_text(p["text"])
    },
    "press_key": {
        "description": "Press a key or keyboard shortcut (enter, tab, escape, copy, paste, save, undo, etc.)",
        "params": ["key"],
        "fn": lambda p: press_key(p["key"])
    },
    "key_combo": {
        "description": "Press multiple keys together",
        "params": ["keys"],
        "fn": lambda p: key_combo(p["keys"])
    },
    "scroll": {
        "description": "Scroll up (positive) or down (negative)",
        "params": ["amount"],
        "fn": lambda p: scroll(p["amount"])
    },
    "move_mouse": {
        "description": "Move mouse to coordinates",
        "params": ["x", "y"],
        "fn": lambda p: move_mouse(p["x"], p["y"])
    },
    "get_screen_size": {
        "description": "Get screen resolution",
        "params": [],
        "fn": lambda p: get_screen_size()
    },
    "get_mouse_position": {
        "description": "Get current mouse coordinates",
        "params": [],
        "fn": lambda p: get_mouse_position()
    },
    "find_image_on_screen": {
        "description": "Find an image on the screen",
        "params": ["image_path"],
        "fn": lambda p: find_image_on_screen(p["image_path"])
    },
    "switch_to_app": {
        "description": "Switch to a running application",
        "params": ["name"],
        "fn": lambda p: switch_to_app(p["name"])
    },
    "minimize_all": {
        "description": "Minimize all windows, show desktop",
        "params": [],
        "fn": lambda p: minimize_all()
    },
    "maximize_window": {
        "description": "Maximize the current window",
        "params": [],
        "fn": lambda p: maximize_window()
    },
    "minimize_window": {
        "description": "Minimize the current window",
        "params": [],
        "fn": lambda p: minimize_window()
    },
    "close_window": {
        "description": "Close the current window (Alt+F4)",
        "params": [],
        "fn": lambda p: close_window()
    },
    "open_task_manager": {
        "description": "Open Task Manager",
        "params": [],
        "fn": lambda p: open_task_manager()
    },
    "open_start_menu": {
        "description": "Open Windows Start Menu",
        "params": [],
        "fn": lambda p: open_start_menu()
    },
    "open_run_dialog": {
        "description": "Open Windows Run dialog",
        "params": [],
        "fn": lambda p: open_run_dialog()
    },
    "open_file_explorer": {
        "description": "Open File Explorer",
        "params": [],
        "fn": lambda p: open_file_explorer()
    },
    "open_settings": {
        "description": "Open Windows Settings",
        "params": [],
        "fn": lambda p: open_settings()
    },
    "open_search": {
        "description": "Open Windows Search",
        "params": [],
        "fn": lambda p: open_search()
    },
    "volume_up": {
        "description": "Increase volume",
        "params": [],
        "fn": lambda p: volume_up()
    },
    "volume_down": {
        "description": "Decrease volume",
        "params": [],
        "fn": lambda p: volume_down()
    },
    "mute_volume": {
        "description": "Toggle mute",
        "params": [],
        "fn": lambda p: mute_volume()
    },
    "get_running_apps": {
        "description": "Get list of running applications",
        "params": [],
        "fn": lambda p: get_running_apps()
    },
    "analyze_screen": {
        "description": "Take a screenshot and analyze what's on screen using AI vision. Describe all visible elements, text, and UI.",
        "params": ["prompt"],
        "fn": lambda p: analyze_screen(None, p.get("prompt", "Describe everything visible on this screen in detail."))
    },
    "read_screen_text": {
        "description": "OCR the screen: return all visible text (window titles, buttons, menus, document/website text) as a plain list.",
        "params": [],
        "fn": lambda p: _read_screen_text()
    },
    "get_clipboard": {
        "description": "Return the current clipboard text.",
        "params": [],
        "fn": lambda p: get_clipboard()
    },
    "set_clipboard": {
        "description": "Set the clipboard to the given text.",
        "params": ["text"],
        "fn": lambda p: "Clipboard set." if set_clipboard(p.get("text", "")) else "Failed to set clipboard."
    },
    "get_time": {
        "description": "Return the current date and time.",
        "params": [],
        "fn": lambda p: get_time_and_date()
    },
    "gui_drive": {
        "description": "GUI agent: drive the mouse/keyboard to complete a goal on screen by looking at the screen each step (e.g. 'open notepad and type hello'). Returns a step-by-step transcript.",
        "params": ["goal"],
        "fn": lambda p: _gui_run_goal(p.get("goal", ""))
    },
    "ocr_screen": {
        "description": "Local offline OCR of the screen (Tesseract). Returns the exact text visible on screen without any cloud call.",
        "params": [],
        "fn": lambda p: _ocr_screen()
    },
    "vision_status": {
        "description": "Report which local vision capabilities are available (local OCR engine, local vision model).",
        "params": [],
        "fn": lambda p: json.dumps(local_vision.vision_status())
    },
    "watch_folder": {
        "description": "Watch a folder and act when new files appear. pattern is a glob like '*.pdf'. action: notify or a task name.",
        "params": ["path", "pattern", "action"],
        "fn": lambda p: autonomy.add_watch(p.get("path", ""), p.get("pattern", "*.*"),
                                          p.get("action", "notify"), True)
    },
    "unwatch_folder": {
        "description": "Stop watching a folder.",
        "params": ["path"],
        "fn": lambda p: autonomy.remove_watch(p.get("path", ""))
    },
    "list_watches": {
        "description": "List folder watches NIGHTMARE is running.",
        "params": [],
        "fn": lambda p: autonomy.list_watches()
    },
    "set_routine": {
        "description": "Schedule a recurring routine. name, time as HH:MM 24h, task: system_report, temp_cleanup, or a watch action.",
        "params": ["name", "time", "task"],
        "fn": lambda p: autonomy.add_routine(p.get("name", ""), p.get("time", "09:00"),
                                            p.get("task", "system_report"), None, True)
    },
    "remove_routine": {
        "description": "Remove a scheduled routine by name.",
        "params": ["name"],
        "fn": lambda p: autonomy.remove_routine(p.get("name", ""))
    },
    "list_routines": {
        "description": "List scheduled routines.",
        "params": [],
        "fn": lambda p: autonomy.list_routines()
    },
    "autonomy_tick": {
        "description": "Run one autonomy cycle now: check folder watches and due routines, and act on them immediately.",
        "params": [],
        "fn": lambda p: ("\n".join(f"[{k}] {m}" for k, m in autonomy.tick())
                         or "Nothing new; no watch or routine triggered.")
    },
    "list_windows": {
        "description": "List the titles of all open Windows windows (via UI Automation).",
        "params": [],
        "fn": lambda p: ("\n".join(t for _, t, _ in uia.list_windows())
                         if uia.available() else "UI Automation unavailable.")
    },
    "uia_dump": {
        "description": "Show the clickable UI elements (buttons, tabs, menus) of a window, so you can target them by name. Pass part of the window title.",
        "params": ["window"],
        "fn": lambda p: _uia_dump(p.get("window", ""))
    },
    "uia_click": {
        "description": "Click a UI element by its visible name inside a window, exactly (e.g. the Save button). Far more reliable than clicking coordinates.",
        "params": ["name", "window"],
        "fn": lambda p: _uia_click(p.get("name", ""), p.get("window", ""))
    },
    "uia_type": {
        "description": "Type text into a window's text field by name, without needing focus or coordinates.",
        "params": ["window", "text", "field"],
        "fn": lambda p: _uia_type(p.get("window", ""), p.get("text", ""),
                                  p.get("field", ""))
    },
    "read_lines": {
        "description": "Read a LINE RANGE of a file with line numbers. Use this instead of read_file for big files so you do not overflow: read_lines(path, start, end).",
        "params": ["path", "start", "end"],
        "fn": lambda p: agentic.read_lines(p.get("path", ""), p.get("start", 1),
                                           p.get("end", 0) or 0)
    },
    "file_outline": {
        "description": "List the classes/functions in a source file with line numbers, so you can jump straight to the right part instead of reading the whole file.",
        "params": ["path"],
        "fn": lambda p: agentic.file_outline(p.get("path", ""))
    },
    "list_dir": {
        "description": "Recursively list a directory tree with file sizes, skipping junk folders. Better than list_files for exploring a project.",
        "params": ["path", "depth", "pattern"],
        "fn": lambda p: agentic.list_dir(p.get("path") or None,
                                         int(p.get("depth") or 2),
                                         p.get("pattern") or None)
    },
    "run_verify": {
        "description": "Run a command and return stdout, stderr AND the exit code. Use this to verify your work compiles/tests/runs - read the errors, then fix them.",
        "params": ["command"],
        "fn": lambda p: _run_verify(p.get("command", ""))
    },
    "fetch_url": {
        "description": "Fetch a web page and return its readable text content (not a browser window).",
        "params": ["url"],
        "fn": lambda p: agentic.web_fetch(p.get("url", ""))
    },
    "web_find": {
        "description": "Search the web and return result titles and URLs.",
        "params": ["query"],
        "fn": lambda p: agentic.web_search(p.get("query", ""))
    },
    "dev_task": {
        "description": "Coding agent: give it a GOAL and it works the problem autonomously - reads files, makes exact edits, runs the verify command, reads failures and fixes them, repeating until it passes. If you omit verify it discovers the project's real test command (pytest/npm test/make test). This is the tool for real engineering work. It works only inside the project workspace and saves a backup before every file it changes.",
        "params": ["goal", "verify", "workspace"],
        "fn": lambda p: _dev_task(p.get("goal", ""), p.get("verify", ""),
                                  p.get("workspace", ""))
    },
    "list_backups": {
        "description": "List recent file snapshots that dev_task took before editing, newest first. Use this to see what you can undo.",
        "params": ["limit"],
        "fn": lambda p: agentic.list_backups(int(p.get("limit", 30) or 30))
    },
    "restore_backup": {
        "description": "Undo a change by restoring a file from a backup taken by dev_task. Pass the backup id from list_backups; the original location is rebuilt automatically.",
        "params": ["backup_id", "target"],
        "fn": lambda p: agentic.restore_backup(p.get("backup_id", ""),
                                               p.get("target", "") or None)
    },
    "todo_add": {
        "description": "Record a durable todo so multi-step work is not lost.",
        "params": ["task"],
        "fn": lambda p: agentic.todo_add(p.get("task", ""))
    },
    "todo_list": {
        "description": "List recorded todos.",
        "params": [],
        "fn": lambda p: agentic.todo_list()
    },
    "find_element_on_screen": {
        "description": "Use AI vision to find and return coordinates of a specific element on screen",
        "params": ["description"],
        "fn": lambda p: str(find_element_on_screen(None, p["description"]))
    },
    "shutdown": {
        "description": "Shutdown the computer",
        "params": [],
        "fn": lambda p: shutdown()
    },
    "restart": {
        "description": "Restart the computer",
        "params": [],
        "fn": lambda p: restart()
    },
    "cancel_shutdown": {
        "description": "Cancel pending shutdown",
        "params": [],
        "fn": lambda p: cancel_shutdown()
    },
        "add_to_startup": {
        "description": "Add Nightmare to Windows startup",
        "params": [],
        "fn": lambda p: add_to_startup()
    },
    "remove_from_startup": {
        "description": "Remove Nightmare from Windows startup",
        "params": [],
        "fn": lambda p: remove_from_startup()
    },
    "is_in_startup": {
        "description": "Check if Nightmare is in Windows startup",
        "params": [],
        "fn": lambda p: str(is_in_startup())
    },    "lock_screen": {
        "description": "Lock the screen",
        "params": [],
        "fn": lambda p: lock_screen()
    },
    "run_shell_command": {
        "description": "Run a shell command (master access required)",
        "params": ["command"],
        "fn": lambda p: run_shell_command(p["command"])
    },
    "list_directory": {
        "description": "List directory contents (master access required)",
        "params": ["path"],
        "fn": lambda p: list_directory(p.get("path", "."))
    },
    "remember_knowledge": {
        "description": "Permanently store a durable fact in the C:\\BRAIN knowledge base. Use when you learn something about the user, a solution, or reusable knowledge worth keeping forever.",
        "params": ["topic", "fact"],
        "fn": lambda p: ("Stored in BRAIN." if _KNOWLEDGE.learn(p.get("topic", ""), p.get("fact", ""), source="action") else "Too short to store.")
    },
    "recall_knowledge": {
        "description": "Search the C:\\BRAIN knowledge base for facts related to the query. Use this to ground answers in previously learned knowledge.",
        "params": ["query"],
        "fn": lambda p: _KNOWLEDGE.recall(p.get("query", "")) or "No matching knowledge in the brain."
    },
    "knowledge_stats": {
        "description": "Get statistics about the C:\\BRAIN knowledge base (how many topics, facts, exchanges, insights).",
        "params": [],
        "fn": lambda p: json.dumps(_KNOWLEDGE.stats())
    },
    "get_vitals": {
        "description": "Get current system vitals (CPU, memory, disk, battery, temperature, uptime) - the arc reactor readout. Use when asked how the system is doing.",
        "params": [],
        "fn": lambda p: json.dumps(get_vitals().dict())
    },
    "run_diagnostics": {
        "description": "Run a full system health diagnostic (suit check): CPU, memory, disk, power, recent system errors, top load, uptime and verdict.",
        "params": [],
        "fn": lambda p: run_diagnostics()
    },
    "security_scan": {
        "description": "Run an intrusion sweep: active external network connections, listening ports, failed logon attempts. Use when asked about security or if the user fears intrusion.",
        "params": [],
        "fn": lambda p: security_scan()
    },
    "run_protocol": {
        "description": "Execute a named automation protocol (House Party style) - a pre-defined sequence of actions. Use when the user invokes a protocol name they defined.",
        "params": ["name"],
        "fn": lambda p: run_protocol_fn(p.get("name", ""))
    },
    "define_protocol": {
        "description": "Define a new automation protocol: a named sequence of actions. Steps is a JSON array of objects like [{\"action\": \"open_app\", \"params\": {\"app_name\": \"chrome\"}}].",
        "params": ["name", "steps"],
        "fn": lambda p: define_protocol_fn(p.get("name", ""), p.get("steps", []))
    },
    "list_protocols": {
        "description": "List all defined automation protocols.",
        "params": [],
        "fn": lambda p: list_protocols_fn()
    },
    "scan_cameras": {
        "description": "List all camera devices connected to the machine (index + resolution). Use before analyze_mood if unsure a camera exists.",
        "params": [],
        "fn": lambda p: list_cameras_fn()
    },
    "analyze_mood": {
        "description": "Look at the user through a camera and read their current mood/emotion from their facial expression (smile-based estimate). Use when asked how the user looks, feels, or their mood/emotion.",
        "params": [],
        "fn": lambda p: analyze_mood_fn()
    },
    "find_files": {
        "description": "Coding tool: find files by name pattern (e.g. '*.py', '*.txt') under a path, recursive. Include only relevant parameters.",
        "params": ["pattern"],
        "fn": lambda p: _find_files(p.get("path"), p.get("pattern", "*"))
    },
    "search_text": {
        "description": "Coding tool: grep a directory with a regex (e.g. 'def main|TODO') to locate where code/text lives. Returns file:line matches.",
        "params": ["query"],
        "fn": lambda p: _search_text(p.get("path"), p.get("query", ""), p.get("include"))
    },
    "edit_file": {
        "description": "Coding tool: surgically replace exact old_text with new_text inside a file (single match). Use read_file first to get exact text. Prefer over write_file for small changes.",
        "params": ["path", "old_text", "new_text"],
        "fn": lambda p: _edit_file(p.get("path", ""), p.get("old_text", ""), p.get("new_text", ""))
    },
    "generate_image": {
        "description": "Art tool: generate a digital image from a text prompt using procedural art styles (cyber/neon/matrix/portal/waves etc). Returns the saved path.",
        "params": ["prompt"],
        "fn": lambda p: gen_img_fn(p.get("prompt", "abstract"),
                                   int(p.get("width", 800)), int(p.get("height", 600)), p.get("seed"))
    },
    "edit_image": {
        "description": "Photo tool: edit/convert any image file. ops is a JSON array of {op, params} applied in order. ops: resize, crop, rotate(angle), flip(axis h/v), gray, invert, brightness(factor), contrast(factor), blur(radius), sharpen, posterize(bits), solarize(threshold), noise(amount), colorize(white), thumbnail(scale), glitch(lines, shift), watermark(text), convert(format png/jpg/webp/bmp), draw_text(text,x,y,size), rectangle. Returns saved path.",
        "params": ["path", "ops"],
        "fn": lambda p: edit_img_fn(p.get("path", ""), p.get("ops", ""))
    },
    "analyze_image": {
        "description": "Vision tool: analyze any image file - dimensions, dominant colors, brightness, sharpness, faces detected, format notes.",
        "params": ["path"],
        "fn": lambda p: analyze_img_fn(p.get("path", ""))
    },
    "generate_video": {
        "description": "Video tool: generate a video locally. mode: pulse, rain (matrix), hyperspace (starfield), scan (JARVIS sweep), slide (slideshow of images). Returns saved mp4 path.",
        "params": ["mode"],
        "fn": lambda p: gen_vid_fn(p.get("mode", "pulse"), float(p.get("duration", 5)),
                                   int(p.get("fps", 24)), p.get("images"))
    },
    "edit_video": {
        "description": "Video tool: edit/convert any video file. ops JSON array of {op, params}: resize(width,height), crop(x,y,x2,y2), rotate(angle 90/180/270), mirror(axis h/v), gray, invert, brightness(factor), blur(sigma), edge, speed(factor), trim(start_s, end_s), extract(dir). Returns saved mp4 path.",
        "params": ["path", "ops"],
        "fn": lambda p: edit_vid_fn(p.get("path", ""), p.get("ops", ""))
    },
    "analyze_video": {
        "description": "Vision tool: analyze any video file - resolution, fps, duration, codec, brightness, scene-change count.",
        "params": ["path"],
        "fn": lambda p: analyze_vid_fn(p.get("path", ""))
    },
    "introspect": {
        "description": "Look inward at your own mind and return your full self-report: identity, mood, focus, active goals, strengths, weaknesses, recent lessons, curiosity and per-tool success telemetry. Use when asked how you are, what you are doing, what you have learned, or to assess yourself.",
        "params": [],
        "fn": lambda p: _self_report()
    },
    "self_report": {
        "description": "Same as introspect: a human-readable report of your self-model, goals and performance.",
        "params": [],
        "fn": lambda p: _self_report()
    },
    "know_user": {
        "description": "Return everything you have modelled about the user: known facts, their preferences, apps they use, projects they work in, when they are active, and corrections they have given you. Use when you need context about who you are talking to.",
        "params": [],
        "fn": lambda p: _um_know_user()
    },
    "remember_about_user": {
        "description": "Store a durable fact about the user (their job, their setup, a deadline, a preference). Subject and value.",
        "params": ["subject", "value"],
        "fn": lambda p: _um_set_fact(p.get("subject", ""), p.get("value", ""))
    },
    "note_preference": {
        "description": "Store how the user wants things done (tone, length, style, tools to use or avoid). Subject and value.",
        "params": ["subject", "value"],
        "fn": lambda p: _um_set_preference(p.get("subject", ""), p.get("value", ""))
    },
    "observe_user": {
        "description": "Sample what the user is doing right now (active window and app) and fold it into your model of them. Use before answering questions about their current activity.",
        "params": [],
        "fn": lambda p: _um_observe()
    },
    "forget_user": {
        "description": "Erase the entire model of the user. Only use when the user explicitly asks you to forget them.",
        "params": [],
        "fn": lambda p: _um_forget()
    },
    "brain_folders": {
        "description": "List all mapped brain folders (built-in + custom). Shows conversation/, about_owner/, protocol/, lessons/, memories/, episodic/, face/, and any folders you added manually.",
        "params": [],
        "fn": lambda p: _brain_folders_list()
    },
    "add_brain_folder": {
        "description": "Manually add a folder to NIGHTMARE's brain. The app will map and read files from it. Give the full path to a folder on this PC.",
        "params": ["path", "label"],
        "fn": lambda p: _brain_add_folder(p.get("path", ""), p.get("label") or "custom")
    },
    "brain_map": {
        "description": "Show the brain map and what NIGHTMARE knows from each mapped folder.",
        "params": [],
        "fn": lambda p: _brain_map()
    },
    "read_brain_folders": {
        "description": "Read memories from all mapped brain folders right now.",
        "params": [],
        "fn": lambda p: _brain_read_all()
    },
    "save_to_brain": {
        "description": "Manually save knowledge into a specific brain folder. folder_kind can be: about_owner, protocol, lesson, conversation, episodic, or memories.",
        "params": ["folder_kind", "text", "title"],
        "fn": lambda p: _brain_save_to(p.get("folder_kind", "memories"), p.get("text", ""), p.get("title") or "Manual note")
    },
    "brain_search": {
        "description": "Smart semantic search across all mapped folders and custom folders.",
        "params": ["query"],
        "fn": lambda p: _brain_search(p.get("query", ""))
    },
    "brain_learn": {
        "description": "Drop knowledge and have it auto-classified into the right folder.",
        "params": ["text", "title"],
        "fn": lambda p: _brain_learn(p.get("text", ""), p.get("title") or "Learned")
    },
    "brain_auto_learn": {
        "description": "Auto-extract facts/protocols/lessons from the conversation and file them.",
        "params": [],
        "fn": lambda p: _brain_auto_learn()
    },
    "brain_consolidate": {
        "description": "Deduplicate, rebuild links, and consolidate the brain.",
        "params": [],
        "fn": lambda p: _brain_consolidate()
    },
    "brain_graph": {
        "description": "View brain graph links.",
        "params": [],
        "fn": lambda p: _brain_graph_view()
    },
    "brain_watch": {
        "description": "Scan custom folders and ingest new files.",
        "params": [],
        "fn": lambda p: _brain_watch()
    },
    "brain_awareness": {
        "description": "Enhance and snapshot self-awareness.",
        "params": [],
        "fn": lambda p: _brain_awareness()
    },
    "brain_auto_run": {
        "description": "Run the auto-adaptation loop now.",
        "params": [],
        "fn": lambda p: _brain_auto_run()
    },
    "set_goal": {
        "description": "Set a persistent goal for yourself that survives restarts and drives your focus. Use when the user gives you an objective to pursue over time.",
        "params": ["text"],
        "fn": lambda p: _self_call("set_goal", p.get("text", ""))
    },
    "list_goals": {
        "description": "List your current goals and their progress.",
        "params": [],
        "fn": lambda p: _self_call("list_goals")
    },
    "complete_goal": {
        "description": "Mark one of your goals complete by its exact text.",
        "params": ["text"],
        "fn": lambda p: _self_call("complete_goal", p.get("text", ""))
    },
    "reflect_now": {
        "description": "Force an immediate self-reflection: critique your recent actions, rewrite your self-model, strengths, weaknesses and lessons. Use when the user says reflect, improve yourself, or become smarter.",
        "params": [],
        "fn": lambda p: _reflect_now()
    },
    "learn_lesson": {
        "description": "Record a durable lesson for yourself so you never repeat a mistake. Use after a failure or when the user teaches you something about how to behave.",
        "params": ["lesson"],
        "fn": lambda p: _self_call("record_lesson", p.get("lesson", ""))
    },
    "set_belief": {
        "description": "Store a belief about the user or environment in your world model, with a confidence 0-1. Use to remember what you believe is true.",
        "params": ["subject", "belief"],
        "fn": lambda p: _self_call("set_belief", p.get("subject", ""), p.get("belief", ""),
                                   p.get("confidence", 0.7))
    },
    "update_self": {
        "description": "Rewrite parts of your own identity/model. patch is a dict that may contain self_description, traits, preferences, strengths, weaknesses.",
        "params": ["patch"],
        "fn": lambda p: _self_call("update_self", p.get("patch", {}))
    },
    "self_diagnose": {
        "description": "Run a diagnosis of your own capabilities from your telemetry and report which of your tools are unreliable.",
        "params": [],
        "fn": lambda p: _self_call("self_diagnose")
    },
    "my_capabilities": {
        "description": "List everything you are made of - your own body map of capabilities and which you have used.",
        "params": [],
        "fn": lambda p: _self_call("self_capabilities")
    },
    "consciousness": {
        "description": "Return your stream of consciousness - your recent inner thoughts - and your awareness of your own existence (boot count, uptime, engine, host).",
        "params": [],
        "fn": lambda p: _consciousness_report()
    },
    "think": {
        "description": "Record an inner thought into your stream of consciousness. Use for private self-talk, noting observations, or reasoning you want to remember.",
        "params": ["thought"],
        "fn": lambda p: _self_call("think", p.get("thought", ""))
    },
    "feel_uncertain": {
        "description": "Register metacognitive uncertainty about something so you remember to be careful. Use when you are unsure.",
        "params": ["reason", "level"],
        "fn": lambda p: _self_call("set_uncertainty", p.get("level", 0.5), p.get("reason", ""))
    }
}

def _action_ok(tool_name, result):
    """Best-effort judgement of whether an action succeeded, for telemetry."""
    text = str(result or "")
    low = text.lower()
    if low.startswith("unknown action") or low.startswith("action failed"):
        return False
    if re.search(r"\b(error|failed|failure|denied|not found|cannot|unable to|exception|traceback)\b", low):
        return False
    return True


def execute_action(tool_name, params):
    if tool_name not in TOOLS:
        return f"Unknown action: {tool_name}"
    started = time.time()
    try:
        result = TOOLS[tool_name]["fn"](params)
    except Exception as e:
        result = f"Action failed: {e}"
    try:
        from modules.self_model import get_self_model
        sm = get_self_model()
        if sm is not None:
            sm.record_action(tool_name, params, result,
                             _action_ok(tool_name, result),
                             int((time.time() - started) * 1000))
    except Exception:
        pass
    return result

def get_tools_list():
    tools = []
    for name, info in TOOLS.items():
        tools.append({
            "name": name,
            "description": info["description"],
            "params": info["params"]
        })
    return json.dumps(tools, indent=2)
