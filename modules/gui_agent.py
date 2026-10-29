"""Real GUI agent: drives Windows UI to satisfy a goal.

Strategy, in order of reliability:
  1. Windows UI Automation - find controls by name and invoke them. This is
     exact and needs no model, so it handles most real tasks.
  2. Local vision model (moondream) - for anything UI Automation cannot see
     (custom canvas, games, drawing surfaces).
  3. Cloud vision - last resort; currently unavailable (Groq retired its vision
     models).

Bounded steps, small waits, and a final verification screenshot either way.
"""
import os
import re
import time

import pyautogui

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.15

MAX_STEPS = 12

# goal phrasing -> (control name, how to use it)
_COMMON_CONTROLS = [
    (r"\bclose (?:the )?(?:window|app|application)\b", "Close", "invoke"),
    (r"\bmaximi[sz]e\b", "Maximize", "invoke"),
    (r"\bminimi[sz]e\b", "Minimize", "invoke"),
    (r"\bclick (?:the )?(\w[\w \-]{0,30}?) (?:button|tab|link)\b", r"\1", "invoke"),
    (r"\bpress (?:the )?(\w[\w \-]{0,30}?) (?:button)\b", r"\1", "invoke"),
    (r"\btype [\"']([^\"']+)[\"']", None, "type"),
    (r"\btype ([^,]+?)(?: in| into)? ?$", None, "type"),
]

_APP_ALIASES = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "paint": "mspaint.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "cmd": "cmd.exe",
    "command prompt": "cmd.exe",
    "terminal": "wt.exe",
    "powershell": "powershell.exe",
    "edge": "msedge.exe",
    "chrome": "chrome.exe",
    "browser": "msedge.exe",
    "task manager": "taskmgr.exe",
    "settings": "ms-settings:",
    "control panel": "control.exe",
    "registry editor": "regedit.exe",
    "snipping tool": "snippingtool.exe",
}


def _shot(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img = pyautogui.screenshot()
    img.save(path)
    return path


def _parse_goal(goal):
    """Pull out an app to open and/or text to type, if the goal implies them."""
    g = goal.lower()
    app = None
    for name, exe in _APP_ALIASES.items():
        if re.search(r"\bopen (?:the )?" + re.escape(name) + r"\b", g) or \
           re.search(r"\b" + re.escape(name) + r"\b", g) and "open" in g:
            app = exe
            break
    text = None
    m = re.search(r'\btype [\'"](.+?)[\'"]', goal, re.I)
    if m:
        text = m.group(1)
    return app, text


_CLICKABLE = ["ButtonControl", "MenuItemControl", "TabItemControl", "LinkControl",
              "TreeItemControl", "ListItemControl", "CheckBoxControl"]


def _uia_goal(goal, log):
    """Try to satisfy a goal using UI Automation only. Returns True if done."""
    from modules import uia
    if not uia.available():
        return False
    low = goal.lower()

    # pull the window out of the goal: "click X in the Y window" -> (X, Y)
    win_name = None
    m_win = re.search(r"\b(?:in|on|inside|of) (?:the )?([\w ]+?) "
                      r"(?:window|app|application|dialog|tab)\b", low)
    if m_win:
        win_name = m_win.group(1).strip()
    target_win = uia.find_window(win_name, timeout=3) if win_name else None
    if target_win is None and win_name:
        log.append(f"UIA: no window matching '{win_name}'")

    m = re.search(r"\b(?:click|press|tap|select)\s+(?:the\s+)?(.+)$", low)
    if not m:
        return False
    wanted = m.group(1)
    # drop the window clause and trailing widget nouns
    wanted = re.sub(r"\s+(?:button|tab|link|menu item)\b.*$", "", wanted)
    wanted = re.sub(r"\s+in the .*$", "", wanted).strip()
    wanted = re.sub(r"^(the|a|an)\s+", "", wanted).strip()
    if not wanted or wanted in ("it", "that", "this", "there"):
        return False

    # try the full phrase, then progressively shorter prefixes: small
    # differences in naming ("maximize" vs "maximize button") should not
    # prevent a match.
    candidates = [wanted]
    words = wanted.split()
    for n in range(len(words) - 1, 0, -1):
        cand = " ".join(words[:n])
        if cand not in candidates:
            candidates.append(cand)

    for cand in candidates:
        for types in (_CLICKABLE, None):
            ctl = uia.find_control(cand, control_types=types,
                                   window=target_win, timeout=1)
            if ctl is not None:
                how = uia.invoke(ctl)
                log.append(f"UIA: invoked '{uia._name_of(ctl)}' matching "
                           f"'{cand}' ({how})")
                return True
    log.append(f"UIA: no control matched {candidates}")
    return False


def _vision_loop(goal, workdir, max_steps):
    """Run the UIA-first, vision-fallback loop. Returns a transcript."""
    log = ["Goal: " + goal]
    from modules import uia
    if uia.available():
        log.append("UI Automation: available")
    else:
        log.append("UI Automation: unavailable, vision only")

    app, text = _parse_goal(goal)
    if app:
        os.startfile(app)
        time.sleep(1.5)
        log.append("opened " + app)
    if text:
        target = uia.find_window(app.split(".")[0] if app else "", timeout=4) \
            if app else None
        ctl = None
        if target is not None:
            ctl = uia.find_control("", control_types=["EditControl", "DocumentControl"],
                                   window=target)
        if ctl is not None:
            res = uia.set_value(ctl, text)
            log.append("typed via UI Automation: " + str(res))
        else:
            pyautogui.typewrite(text, interval=0.01)
            log.append("typed via keyboard focus")
        time.sleep(0.4)
    if app or text:
        if not _needs_vision(goal):
            shot = _shot(os.path.join(workdir, "final.png"))
            log.append("final screenshot: " + shot)
            return "\n".join(log)

    if _uia_goal(goal, log):
        shot = _shot(os.path.join(workdir, "final.png"))
        log.append("final screenshot: " + shot)
        return "\n".join(log)
    return "\n".join(log + _vision_loop(goal, workdir, max_steps))


def _needs_vision(goal):
    """True when the goal needs pixel-level understanding we cannot get via UIA."""
    low = goal.lower()
    return bool(re.search(r"\b(where|on screen|button|icon|color|colour|read|"
                          r"what|which|locate|find)\b", low)) and \
        not re.search(r"\btype\b", low) and "open" not in low


def _vision_loop(goal, workdir, max_steps):
    """Vision-driven loop (local VLM first, cloud last resort)."""
    out = []
    w, h = pyautogui.size()
    for step in range(1, max_steps + 1):
        shot = _shot(os.path.join(workdir, f"step_{step}.png"))
        prompt = (
            f"Goal: {goal}\nThis is step {step} of {max_steps}. "
            f"Screen is {w}x{h}.\n"
            "Decide the single next action to progress the goal. Allowed actions and JSON:\n"
            '{"action":"click","x":<px>,"y":<py>}\n'
            '{"action":"double_click","x":<px>,"y":<py>}\n'
            '{"action":"right_click","x":<px>,"y":<py>}\n'
            '{"action":"type","text":"..."}\n'
            '{"action":"key","key":"enter"}\n'
            '{"action":"hotkey","keys":"ctrl s"}\n'
            '{"action":"scroll","amount":-3}\n'
            '{"action":"open","app":"notepad"}\n'
            '{"action":"done"}\n'
            '{"action":"fail","reason":"why impossible"}\n'
            "Rules: do exactly one action per reply. If the goal is already achieved, "
            "reply {\"action\":\"done\"}. If it cannot be done, reply {\"action\":\"fail\"}."
        )
        act = _vision_json(prompt, shot)
        if not act:
            out.append(f"step {step}: no vision response, scrolling")
            break
        kind = str(act.get("action", "")).lower()
        if kind == "done":
            out.append(f"step {step}: goal complete")
            break
        if kind == "fail":
            out.append(f"step {step}: gave up - {act.get('reason','unspecified')}")
            break
        res = _act(act)
        detail = {k: v for k, v in act.items() if k != "action"}
        out.append(f"step {step}: {kind} {detail} -> {res}")
        time.sleep(0.6)
    return out


def run_goal(goal, max_steps=MAX_STEPS, workdir=None):
    """Drive the GUI to satisfy `goal`. Returns a transcript of what it did."""
    workdir = workdir or os.path.join(os.path.expanduser("~"), ".nightmare", "gui_agent")
    os.makedirs(workdir, exist_ok=True)
    try:
        return _vision_loop(goal, workdir, max_steps)
    except Exception as e:
        return f"Goal: {goal}\ngui_drive failed: {e}"


def _vision_json(prompt, shot_path, timeout=180):
    """Ask a vision model for a JSON action. Tries local VLM first, then cloud."""
    from modules import local_vision
    if local_vision.local_vlm():
        res = local_vision.local_vision_describe(shot_path, prompt, timeout=timeout)
        if res:
            return _parse_json(res)
    from modules.screen_analysis import _vision_call
    import base64
    with open(shot_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    messages = [
        {"role": "system", "content": "You are a GUI automation agent driving a Windows PC. "
         "Reply with ONLY a JSON object describing the single next action."},
        {"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
        ]}
    ]
    try:
        res = _vision_call(messages, temperature=0.1, timeout=timeout)
    except Exception:
        res = None
    if not res or str(res).startswith(("Vision unavailable", "Vision API error")):
        return None
    return _parse_json(res)


def _parse_json(text):
    import json
    import re
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        res = None


def _do_open(a):
    target = str(a.get("app") or a.get("path") or "").strip()
    if not target:
        return "no app or path given"
    os.startfile(target)
    return target


ACTIONS = {
    "click": lambda a: pyautogui.click(int(a["x"]), int(a["y"])),
    "double_click": lambda a: pyautogui.doubleClick(int(a["x"]), int(a["y"])),
    "right_click": lambda a: pyautogui.rightClick(int(a["x"]), int(a["y"])),
    "type": lambda a: pyautogui.typewrite(str(a.get("text", "")), interval=0.01),
    "key": lambda a: pyautogui.press(str(a.get("key", "enter"))),
    "hotkey": lambda a: pyautogui.hotkey(*str(a.get("keys", "ctrl c")).split()),
    "scroll": lambda a: pyautogui.scroll(int(a.get("amount", -3))),
    "open": _do_open,
    "done": lambda a: None,
    "fail": lambda a: None,
}


def _act(a):
    kind = str(a.get("action", "")).lower()
    fn = ACTIONS.get(kind)
    if not fn:
        return f"unsupported action '{kind}'"
    try:
        fn(a)
        return f"{kind} ok"
    except Exception as e:
        return f"{kind} failed: {e}"

