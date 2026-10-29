"""Autonomy: file watchers and scheduled routines.

NIGHTMARE can now act on its own:
  * watch folders for new/changed files and react (e.g. auto-organize downloads)
  * run routines on a schedule (e.g. daily system report at 9:00)

State is persisted in the user home .nightmare dir so it survives restarts.
"""
import datetime
import json
import os
import re
import threading
import time

from modules.memory import config_dir

STATE_FILE = "autonomy.json"

# Sensible default: watch the Downloads folder for new files.
DEFAULT_WATCHES = [
    {"path": os.path.join(os.path.expanduser("~"), "Downloads"),
     "pattern": "*.*", "action": "notify", "enabled": False}
]

DEFAULT_ROUTINES = [
    {"name": "morning_report", "time": "09:00", "days": [0, 1, 2, 3, 4, 5, 6],
     "task": "system_report", "enabled": False},
    {"name": "cleanup_temp", "time": "03:00", "days": [0, 1, 2, 3, 4, 5, 6],
     "task": "temp_cleanup", "enabled": False},
]

_lock = threading.Lock()
_state = None


def _path():
    return os.path.join(config_dir(), STATE_FILE)


def _load():
    global _state
    with _lock:
        if _state is None:
            try:
                with open(_path(), "r", encoding="utf-8") as f:
                    data = json.load(f)
                _state = {
                    "watches": data.get("watches") or list(DEFAULT_WATCHES),
                    "routines": data.get("routines") or list(DEFAULT_ROUTINES),
                    "seen": data.get("seen") or {},
                    "last_run": data.get("last_run") or {},
                }
            except Exception:
                _state = {
                    "watches": list(DEFAULT_WATCHES),
                    "routines": list(DEFAULT_ROUTINES),
                    "seen": {},
                    "last_run": {},
                }
        return _state


def _save():
    st = _load()
    try:
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump({"watches": st["watches"], "routines": st["routines"],
                       "seen": st["seen"], "last_run": st["last_run"]},
                      f, indent=2)
    except Exception:
        pass


# ------------------------------------------------------------------ public API

def add_watch(path, pattern="*.*", action="notify", enabled=True):
    st = _load()
    path = os.path.abspath(os.path.expanduser(path))
    for w in st["watches"]:
        if os.path.abspath(w["path"]) == path:
            w.update({"pattern": pattern, "action": action, "enabled": enabled})
            _save()
            return f"Watch updated: {path} (pattern {pattern}, action {action})"
    st["watches"].append({"path": path, "pattern": pattern,
                          "action": action, "enabled": enabled})
    _save()
    return f"Watching {path} for {pattern} -> {action}"


def remove_watch(path):
    st = _load()
    path = os.path.abspath(os.path.expanduser(path))
    before = len(st["watches"])
    st["watches"] = [w for w in st["watches"]
                     if os.path.abspath(w["path"]) != path]
    _save()
    return "Watch removed." if len(st["watches"]) < before else "No such watch."


def list_watches():
    st = _load()
    if not st["watches"]:
        return "No folder watches configured."
    lines = ["Configured folder watches:"]
    for w in st["watches"]:
        flag = "on" if w.get("enabled") else "off"
        lines.append(f"  [{flag}] {w['path']}  pattern={w.get('pattern','*.*')} "
                     f"action={w.get('action','notify')}")
    return "\n".join(lines)


def add_routine(name, at_time, task="system_report", days=None, enabled=True):
    st = _load()
    for r in st["routines"]:
        if r["name"] == name:
            r.update({"time": at_time, "task": task,
                      "days": days or list(range(7)), "enabled": enabled})
            _save()
            return f"Routine updated: {name} at {at_time} -> {task}"
    st["routines"].append({"name": name, "time": at_time, "task": task,
                           "days": days or list(range(7)), "enabled": enabled})
    _save()
    return f"Routine set: {name} daily at {at_time} -> {task}"


def remove_routine(name):
    st = _load()
    before = len(st["routines"])
    st["routines"] = [r for r in st["routines"] if r["name"] != name]
    _save()
    return "Routine removed." if len(st["routines"]) < before else "No such routine."


def list_routines():
    st = _load()
    if not st["routines"]:
        return "No routines configured."
    lines = ["Configured routines:"]
    for r in st["routines"]:
        flag = "on" if r.get("enabled") else "off"
        lines.append(f"  [{flag}] {r['name']} at {r['time']} -> {r['task']}")
    return "\n".join(lines)


# ------------------------------------------------------------------ engine

def _scan_watches():
    """Return a list of events for new files matching enabled watches."""
    st = _load()
    import fnmatch
    events = []
    for w in st["watches"]:
        if not w.get("enabled"):
            continue
        path = os.path.expanduser(w["path"])
        if not os.path.isdir(path):
            continue
        pattern = w.get("pattern", "*.*")
        try:
            names = os.listdir(path)
        except Exception:
            continue
        key = os.path.abspath(path)
        seen = st["seen"].get(key, [])
        seen_set = set(seen)
        current = set(names)
        for n in sorted(current):
            if n in seen_set or n.startswith(".~") or n.startswith("tmp"):
                continue
            if not fnmatch.fnmatch(n, pattern):
                continue
            try:
                full = os.path.join(path, n)
                if not os.path.isfile(full):
                    continue
                if os.path.getsize(full) == 0:
                    continue
            except Exception:
                continue
            events.append({"watch": path, "file": os.path.join(path, n),
                           "name": n, "action": w.get("action", "notify")})
        # cap memory
        st["seen"][key] = sorted(current)[-2000:]
    if events:
        _save()
    return events


def _due_routines(now=None):
    st = _load()
    now = now or datetime.datetime.now()
    today = now.weekday()
    stamp = now.strftime("%Y-%m-%d")
    due = []
    for r in st["routines"]:
        if not r.get("enabled"):
            continue
        if today not in (r.get("days") or list(range(7))):
            continue
        try:
            hh, mm = [int(x) for x in str(r["time"]).split(":")[:2]]
        except Exception:
            continue
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if now >= target and now - target < datetime.timedelta(minutes=5):
            if st["last_run"].get(r["name"]) != stamp:
                due.append(r)
                st["last_run"][r["name"]] = stamp
    if due:
        _save()
    return due


TASKS = {}


def register_task(name, fn):
    TASKS[name] = fn


def _builtin_system_report(_arg=None):
    try:
        from modules.vitals import get_vitals
        v = get_vitals()
        disks = ", ".join("%s %s%%" % (k, val)
                          for k, val in (v.disk_pct or {}).items())
        return ("System report: CPU %s%%, RAM %s%% (%s/%s MB), disk [%s], "
                "battery %s%s." % (
                    v.cpu, v.ram_pct, v.ram_used_mb, v.ram_total_mb,
                    disks or "n/a", v.battery if v.battery is not None else "n/a",
                    " (charging)" if getattr(v, "charging", False) else ""))
    except Exception as e:
        return f"Report failed: {e}"


def _builtin_temp_cleanup(_arg=None):
    import glob
    cutoff = time.time() - 7 * 86400
    removed = 0
    tmp = os.environ.get("TEMP", ".")
    for pat in (os.path.join(tmp, "*"), os.path.join(tmp, "*", "*")):
        for p in glob.glob(pat):
            try:
                if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                    os.remove(p)
                    removed += 1
            except Exception:
                continue
    return f"Temp cleanup: removed {removed} old file(s)."


def _builtin_archive(_arg=None):
    src = _arg
    if not src or not os.path.isfile(src):
        return "archive: no file given"
    import zipfile
    dest = os.path.splitext(src)[0] + ".zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(src, os.path.basename(src))
    return f"Archived to {dest}"


register_task("system_report", _builtin_system_report)
register_task("temp_cleanup", _builtin_temp_cleanup)
register_task("archive_file", _builtin_archive)


def _run_task(task_name, arg=None):
    fn = TASKS.get(task_name)
    if not fn:
        return f"Unknown autonomy task: {task_name}"
    try:
        return str(fn(arg) if arg is not None else fn())
    except Exception as e:
        return f"Task {task_name} failed: {e}"


def tick():
    """One autonomy cycle. Returns a list of (label, message) notices."""
    notices = []
    for ev in _scan_watches():
        notices.append(("WATCH", f"New file detected: {ev['file']}"))
        if ev.get("action") and ev["action"] != "notify":
            out = _run_task(ev["action"], ev["file"])
            notices.append(("AUTONOMY", out))
    for r in _due_routines():
        out = _run_task(r.get("task", ""), r.get("name"))
        notices.append(("ROUTINE", f"{r['name']}: {out}"))
    return notices
