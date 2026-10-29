import os
import json
import threading
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from memory import find_nightmare_dir

PROTOCOLS_FILE = "protocols.json"
_lock = threading.Lock()

SEED_PROTOCOLS = {
    "house_party": {
        "name": "House Party",
        "steps": [
            {"action": "get_running_apps", "params": {}},
            {"action": "get_system_info", "params": {}}
        ],
        "note": "Cinematic homage. Define your own steps to make it meaningful."
    }
}


def _path():
    d = find_nightmare_dir()
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return os.path.join(d, PROTOCOLS_FILE)


def _load():
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            if "house_party" not in data:
                data["house_party"] = SEED_PROTOCOLS["house_party"]
            return data
    except Exception:
        pass
    return dict(SEED_PROTOCOLS)


def _save(data):
    try:
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def list_protocols():
    try:
        data = _load()
        names = list(data.keys())
        return f"Defined protocols ({len(names)}): " + ", ".join(names) if names else "No protocols defined."
    except Exception as e:
        return f"Error listing protocols: {e}"


def define_protocol(name, steps):
    name = (name or "").strip().lower().replace(" ", "_")
    if not name:
        return "Protocol requires a name."
    if isinstance(steps, str):
        try:
            steps = json.loads(steps)
        except Exception:
            return "Steps must be valid JSON, e.g. [{\"action\": \"open_app\", \"params\": {\"app_name\": \"chrome\"}}]"
    if not isinstance(steps, list) or not steps:
        return "Steps must be a non-empty list of {action, params}."
    if len(steps) > 20:
        steps = steps[:20]
    try:
        data = _load()
        data[name] = {"name": name.replace("_", " ").title(), "steps": steps}
        ok = _save(data)
        return f"Protocol '{name}' defined with {len(steps)} step(s)." if ok else "Failed to save protocol."
    except Exception as e:
        return f"Error defining protocol: {e}"


def run_protocol(name):
    name = (name or "").strip().lower().replace(" ", "_")
    data = _load()
    proto = data.get(name)
    if not proto:
        return f"Protocol '{name}' not found. Defined protocols: {', '.join(data.keys()) or 'none'}"
    steps = proto.get("steps") or []
    report = [f"House Party - executing protocol '{name}' ({len(steps)} steps):"]
    for i, step in enumerate(steps, 1):
        action = step.get("action", "")
        params = step.get("params", {}) or {}
        try:
            from modules.action_executor import execute_action
            result = execute_action(action, params)
            short = str(result).replace("\n", " ")[:160]
            report.append(f"  {i}. {action}: {short}")
        except Exception as e:
            report.append(f"  {i}. {action}: ERROR {e}")
    report.append("PROTOCOL COMPLETE.")
    return "\n".join(report)