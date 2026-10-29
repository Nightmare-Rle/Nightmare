"""Windows UI Automation helpers.

Locating controls by name is far more reliable than asking a small vision model
for pixel coordinates, so the GUI agent uses this first and only falls back to
vision for anything UI Automation cannot see (canvas/game/custom drawing).
"""
import re
import time

try:
    import uiautomation as auto
    _HAVE_UIA = True
except Exception:  # pragma: no cover
    auto = None
    _HAVE_UIA = False


def available():
    return _HAVE_UIA


def _name_of(ctl):
    try:
        return ctl.Name or ""
    except Exception:
        return ""


def _type_of(ctl):
    try:
        return ctl.ControlTypeName or ""
    except Exception:
        return ""


def list_windows(visible_only=True):
    """Return [(handle, title, class)] for top-level windows."""
    out = []
    if not _HAVE_UIA:
        return out
    try:
        for w in auto.GetRootControl().GetChildren():
            try:
                name = _name_of(w)
                if not name.strip():
                    continue
                out.append((w.NativeWindowHandle, name, _type_of(w)))
            except Exception:
                continue
    except Exception:
        pass
    return out


def find_window(title_substr, timeout=5):
    """Return a top-level window control whose title contains title_substr."""
    if not _HAVE_UIA:
        return None
    deadline = time.time() + max(0, timeout)
    needle = (title_substr or "").lower()
    while True:
        for w in auto.GetRootControl().GetChildren():
            try:
                if needle in _name_of(w).lower():
                    return w
            except Exception:
                continue
        if time.time() >= deadline:
            return None
        time.sleep(0.4)


def _walk(ctl, depth, max_depth, out, needle, types, budget):
    """Depth-first search of descendants matching name/type."""
    if budget[0] <= 0 or depth > max_depth:
        return
    budget[0] -= 1
    for child in ctl.GetChildren():
        try:
            name = _name_of(child)
            ctype = _type_of(child)
            if (not needle or needle in name.lower()) and \
                    (not types or ctype in types):
                out.append(child)
            _walk(child, depth + 1, max_depth, out, needle, types, budget)
        except Exception:
            continue


def find_control(name_substr, control_types=None, window=None, max_depth=8,
                 timeout=3):
    """Find a control by (partial) name inside a window or the whole desktop.

    control_types may be a list like ['ButtonControl', 'MenuItemControl'].
    """
    if not _HAVE_UIA:
        return None
    types = set(control_types or [])
    needle = (name_substr or "").lower()
    root = window if window is not None else auto.GetRootControl()
    deadline = time.time() + max(0, timeout)
    while True:
        found = []
        _walk(root, 0, max_depth, found, needle, types, [4000])
        if found:
            return found[0]
        if time.time() >= deadline:
            return None
        time.sleep(0.4)


def control_text(ctl, limit=120):
    """Best-effort text content of a control (value, else legacy value, else name)."""
    for getter in ("GetValuePattern", "GetLegacyIAccessiblePattern"):
        try:
            obj = getattr(ctl, getter)()
            val = obj.Value if getter == "GetValuePattern" else obj.Value
            if val:
                return str(val)[:limit]
        except Exception:
            continue
    return _name_of(ctl)[:limit]


def invoke(ctl):
    """Click a control via its Invoke pattern (works for most buttons)."""
    ctl.SetFocus()
    time.sleep(0.1)
    try:
        ctl.GetInvokePattern().Invoke()
        return "invoked"
    except Exception:
        pass
    try:
        ctl.GetLegacyIAccessiblePattern().DoDefaultAction()
        return "default action"
    except Exception:
        pass
    # fall back to a physical click on the element's centre
    r = ctl.BoundingRectangle
    x = (r.left + r.right) // 2
    y = (r.top + r.bottom) // 2
    import pyautogui
    pyautogui.click(x, y)
    return f"clicked at {x},{y}"


def set_value(ctl, text):
    ctl.SetFocus()
    time.sleep(0.1)
    try:
        ctl.GetValuePattern().SetValue(str(text))
        return "set value"
    except Exception:
        pass
    try:
        ctl.GetLegacyIAccessiblePattern().SetValue(str(text))
        return "set legacy value"
    except Exception:
        return None


def dump(window=None, max_depth=4, max_items=60):
    """Human-readable outline of a window, for the model to reason about."""
    if not _HAVE_UIA:
        return "UI Automation unavailable."
    root = window if window is not None else auto.GetRootControl()
    lines = []

    def rec(ctl, depth):
        if len(lines) >= max_items or depth > max_depth:
            return
        try:
            name = _name_of(ctl).strip()
            ctype = _type_of(ctl)
            if name or depth == 0:
                lines.append("  " * depth + f"[{ctype}] {name[:70]}")
        except Exception:
            return
        try:
            for c in ctl.GetChildren():
                rec(c, depth + 1)
        except Exception:
            return

    rec(root, 0)
    return "\n".join(lines) if lines else "No UI elements found."
