import subprocess
import pyautogui
import json
import time
import os
import psutil

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.5

def screenshot(path=None):
    if not path:
        path = os.path.expanduser("~\\Desktop\\screenshot.png")
    pyautogui.screenshot(path)
    return f"Screenshot saved to {path}"

def click(x=None, y=None, button="left"):
    if x is not None and y is not None:
        pyautogui.click(x, y, button=button)
        return f"Clicked at ({x}, {y})"
    pyautogui.click(button=button)
    return f"Clicked ({button} button) at current position"

def double_click(x=None, y=None):
    if x is not None and y is not None:
        pyautogui.doubleClick(x, y)
        return f"Double-clicked at ({x}, {y})"
    pyautogui.doubleClick()
    return "Double-clicked"

def right_click(x=None, y=None):
    if x is not None and y is not None:
        pyautogui.rightClick(x, y)
        return f"Right-clicked at ({x}, {y})"
    pyautogui.rightClick()
    return "Right-clicked"

def type_text(text):
    pyautogui.typewrite(text, interval=0.05)
    return f"Typed: {text}"

def press_key(key):
    key_map = {
        "enter": "enter", "return": "enter", "tab": "tab",
        "space": "space", "backspace": "backspace", "delete": "delete",
        "escape": "esc", "esc": "esc",
        "up": "up", "down": "down", "left": "left", "right": "right",
        "home": "home", "end": "end", "pageup": "pageup", "pagedown": "pagedown",
        "f1": "f1", "f2": "f2", "f3": "f3", "f4": "f4", "f5": "f5",
        "f6": "f6", "f7": "f7", "f8": "f8", "f9": "f9", "f10": "f10",
        "f11": "f11", "f12": "f12",
        "alt": "alt", "ctrl": "ctrl", "control": "ctrl", "shift": "shift",
        "win": "win", "windows": "win",
        "copy": ["ctrl", "c"], "paste": ["ctrl", "v"],
        "cut": ["ctrl", "x"], "save": ["ctrl", "s"],
        "undo": ["ctrl", "z"], "redo": ["ctrl", "y"],
        "select all": ["ctrl", "a"], "new tab": ["ctrl", "t"],
        "close tab": ["ctrl", "w"], "refresh": ["ctrl", "r"],
    }
    key = key.lower().strip()
    if key in key_map:
        combo = key_map[key]
        if isinstance(combo, list):
            pyautogui.hotkey(*combo)
            return f"Pressed {key}"
        else:
            pyautogui.press(combo)
            return f"Pressed {key}"
    return f"Unknown key: {key}"

def key_combo(keys):
    pyautogui.hotkey(*keys)
    return f"Pressed {'+'.join(keys)}"

def scroll(amount, x=None, y=None):
    if x is not None and y is not None:
        pyautogui.scroll(amount, x, y)
        return f"Scrolled {amount} at ({x}, {y})"
    pyautogui.scroll(amount)
    return f"Scrolled {amount}"

def move_mouse(x, y):
    pyautogui.moveTo(x, y)
    return f"Moved mouse to ({x}, {y})"

def get_screen_size():
    w, h = pyautogui.size()
    return json.dumps({"width": w, "height": h}, indent=2)

def get_mouse_position():
    x, y = pyautogui.position()
    return json.dumps({"x": x, "y": y}, indent=2)

def find_image_on_screen(image_path, confidence=0.8):
    try:
        location = pyautogui.locateOnScreen(image_path, confidence=confidence)
        if location:
            center = pyautogui.center(location)
            return json.dumps({"found": True, "x": center.x, "y": center.y, "region": str(location)}, indent=2)
        return json.dumps({"found": False}, indent=2)
    except Exception as e:
        return f"Image search error: {e}"

def switch_to_app(name):
    try:
        result = subprocess.run(
            f'powershell -Command "(Get-Process | Where-Object {{$_.ProcessName -like \'*{name}*\'}} | Select-Object -First 1).Id"',
            shell=True, capture_output=True, text=True
        )
        pid = result.stdout.strip()
        if pid and pid.isdigit():
            shell = subprocess.Popen(f'powershell -Command "(New-Object -ComObject WScript.Shell).AppActivate({pid})"', shell=True)
            time.sleep(0.5)
            pyautogui.hotkey("alt", "tab")
            return f"Switched to {name}"
        return f"App not found: {name}"
    except Exception as e:
        return f"Error switching to {name}: {e}"

def minimize_all():
    pyautogui.hotkey("win", "d")
    return "Minimized all windows, showing desktop"

def maximize_window():
    pyautogui.hotkey("win", "up")
    return "Maximized current window"

def minimize_window():
    pyautogui.hotkey("win", "down")
    return "Minimized current window"

def close_window():
    pyautogui.hotkey("alt", "f4")
    return "Sent Alt+F4 to close current window"

def open_task_manager():
    pyautogui.hotkey("ctrl", "shift", "esc")
    return "Opened Task Manager"

def open_start_menu():
    pyautogui.press("win")
    return "Opened Start Menu"

def open_run_dialog():
    pyautogui.hotkey("win", "r")
    return "Opened Run dialog"

def open_file_explorer():
    pyautogui.hotkey("win", "e")
    return "Opened File Explorer"

def open_action_center():
    pyautogui.hotkey("win", "a")
    return "Opened Action Center"

def open_notification_center():
    pyautogui.hotkey("win", "n")
    return "Opened Notification Center"

def lock_pc():
    subprocess.run("rundll32.exe user32.dll,LockWorkStation", shell=True)
    return "PC locked"

def open_settings():
    pyautogui.hotkey("win", "i")
    return "Opened Settings"

def open_search():
    pyautogui.hotkey("win", "s")
    return "Opened Windows Search"

def volume_up():
    for _ in range(5):
        pyautogui.press("volumeup")
    return "Volume increased"

def volume_down():
    for _ in range(5):
        pyautogui.press("volumedown")
    return "Volume decreased"

def mute_volume():
    pyautogui.press("volumemute")
    return "Volume toggled"

def get_running_apps():
    try:
        apps = []
        for p in psutil.process_iter(['pid', 'name', 'status']):
            if p.info['status'] == 'running' and p.info['name']:
                apps.append({"pid": p.info['pid'], "name": p.info['name']})
        apps = apps[:50]
        return json.dumps(apps, indent=2)
    except Exception as e:
        return f"Error: {e}"
