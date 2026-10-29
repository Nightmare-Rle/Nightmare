"""A persistent model of the human on the other side of the microphone.

Everything else in NIGHTMARE can be looked up when it is needed: a file, a
window title, a stored fact. What it could not do was answer the questions
that only make sense if you already know the person you are talking to:

    "you've been in this project for three days running, did you finish it?"
    "you always work late on Fridays, is that why you're still up?"
    "you asked me last week to avoid touching the config, why is it different now?"

Those need a model that accumulates: which projects they work in, which apps
they live in, when they are active, how long their sessions run, what they
asked for before, and how they prefer to be answered. None of that is a
single lookup, so it is built here by watching, not by asking.

The model is a JSON file in the config directory. It is deliberately boring:
a dict of counters and lists that grow, decay, and get summarised. Nothing
here is a judgement about the user, and nothing is inferred about their
identity - it is a record of activity that they can delete at any time with
forget().

Privacy shape: everything stays on this machine in one file, it is a
summary of app names and durations rather than content, and nothing is
written about what was said in a conversation unless the user asked for it to
be remembered.
"""

import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from memory import config_dir

STATE_FILE = "user_model.json"

# Windows whose titles are noise rather than signal: a title that changes
# every second (a video playing) or that carries no information about what
# the user is doing.
_NOISE_TITLES = re.compile(
    r"^(Program Manager|Taskbar|Windows Input Experience|Search|"
    r"Notification|Action Center|Calendar|Settings|Control Panel|"
    r"Microsoft Text Input Application|App Switcher)", re.I)

# Apps that are always running and say nothing about the current task.
_BACKGROUND = {
    "system", "system idle process", "system settings", "windows explorer",
    "explorer.exe", "taskhostw.exe", "svchost.exe", "searchhost.exe",
    "searchapp.exe", "textinputhost.exe", "shellexperiencehost.exe",
    "startmenuexperiencehost.exe", "windowspushnotificationplatform",
    "ctfmon.exe", "conhost.exe", "dwm.exe", "audiodg.exe", "wudfhost.exe",
    "wmiprvse.exe", "runtimebroker.exe", "backgroundtaskhost.exe",
    "lockapp.exe", "peopleexperiencehost.exe", "mousocoreworker.exe",
    "widgets.exe", "widgetservice.exe", "crossdeviceactivitybroker.exe",
    "audiocdpsrv.exe", "lsass.exe", "csrss.exe", "winlogon.exe", "services.exe",
    "smss.exe", "wininit.exe", "registry", "memcompression",
    "systemsettings.exe", "usercpl.exe", "logonui.exe", "fontdrvhost.exe",
    "dasteamhost.exe", "spoolsv.exe", "rundll32.exe", "sihost.exe",
}

# Titles that reveal which project the user is in, even when the editor
# title is a document name.
_PROJECT_HINT = re.compile(
    r"(?:^|\\)([A-Za-z0-9_.\- ]{2,40})\.(?:py|js|ts|tsx|jsx|json|md|cpp|"
    r"c|h|hpp|rs|go|java|cs|rb|php|html|css|vue|svelte|swift|kt|sql|"
    r"sh|bat|ps1|yml|yaml|toml|ini|cfg|env)", re.I)


def _state_path():
    return os.path.join(config_dir(), STATE_FILE)


def _now():
    return time.time()


def _hour_bucket(ts=None):
    """Coarse time-of-day bucket. Precise timestamps would be noise."""
    ts = ts or _now()
    h = time.localtime(ts).tm_hour
    if 0 <= h < 6:
        return "late night"
    if 6 <= h < 11:
        return "morning"
    if 11 <= h < 14:
        return "midday"
    if 14 <= h < 18:
        return "afternoon"
    if 18 <= h < 22:
        return "evening"
    return "night"


def _day_key(ts=None):
    return time.strftime("%Y-%m-%d", time.localtime(ts or _now()))


def _norm_app(name):
    if not name:
        return ""
    n = str(name).strip().lower()
    if n.endswith(".exe"):
        n = n[:-4]
    return n


def _is_noise(title):
    if not title:
        return True
    t = str(title).strip()
    if len(t) > 120:
        # a very long title is usually a document or a browser page that
        # changed; keep the head, it still names the thing
        t = t[:120]
    if _NOISE_TITLES.match(t):
        return True
    if t in ("-", "Program Manager", "Desktop"):
        return True
    return False


class UserModel:
    """Watches what the user actually does and remembers the shape of it."""

    def __init__(self):
        self.path = _state_path()
        self.data = self._load()
        self._last_app = ""
        self._last_title = ""
        self._last_switch = 0.0
        self._session_start = _now()

    # ------------------------------------------------------------------ state

    def _load(self):
        default = {
            "created": _now(),
            "updated": _now(),
            "profile": {},        # subject -> value  (stated facts)
            "preferences": {},    # subject -> value  (how they like things)
            "apps": {},           # app -> {"count": n, "seconds": s, "last": ts}
            "titles": {},         # app -> [recent titles]
            "projects": {},       # project -> {"visits": n, "last": ts, "apps": []}
            "hours": {},          # bucket -> count
            "days": {},           # YYYY-MM-DD -> count
            "sessions": [],       # [{"start": ts, "end": ts, "apps": [...]}]
            "requests": [],       # recent asked-for things
            "corrections": [],    # "don't do X" - highest value signal there is
            "moods": {},          # YYYY-MM-DD -> {"happy": n, "neutral": n}
            "streak_days": 0,
            "last_seen": 0,
        }
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                merged = dict(default)
                merged.update(loaded)
                return merged
        except Exception:
            pass
        return default

    def save(self):
        try:
            self.data["updated"] = _now()
            d = os.path.dirname(self.path)
            if d:
                os.makedirs(d, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------- observation

    def observe(self, app="", title=""):
        """Record what the user is looking at right now. Cheap; call often."""
        app = _norm_app(app)
        title = str(title or "").strip()
        if not app or app in _BACKGROUND:
            return False
        if _is_noise(title):
            title = ""

        now = _now()
        changed = (app != self._last_app or title != self._last_title)
        if not changed:
            return False

        # time spent in the previous app is charged to it
        if self._last_app and self._last_switch:
            gap = min(now - self._last_switch, 3600.0)
            rec = self.data["apps"].setdefault(
                self._last_app, {"count": 0, "seconds": 0.0, "last": 0})
            rec["seconds"] = float(rec.get("seconds", 0.0)) + gap

        self._last_app = app
        self._last_title = title
        self._last_switch = now

        rec = self.data["apps"].setdefault(
            app, {"count": 0, "seconds": 0.0, "last": 0})
        rec["count"] = int(rec.get("count", 0)) + 1
        rec["last"] = now

        if title:
            titles = self.data["titles"].setdefault(app, [])
            if title not in titles:
                titles.insert(0, title)
                del titles[8:]

        proj = self._project_of(app, title)
        if proj:
            p = self.data["projects"].setdefault(
                proj, {"visits": 0, "last": 0, "apps": []})
            p["visits"] = int(p.get("visits", 0)) + 1
            p["last"] = now
            if app not in (p.get("apps") or []):
                p.setdefault("apps", []).append(app)
                del p["apps"][:6]

        bucket = _hour_bucket(now)
        self.data["hours"][bucket] = self.data["hours"].get(bucket, 0) + 1
        day = _day_key(now)
        self.data["days"][day] = self.data["days"].get(day, 0) + 1
        self.data["last_seen"] = now
        return True

    def _project_of(self, app, title):
        """Guess the project from the window title."""
        if not title:
            return ""
        m = _PROJECT_HINT.search(title)
        if m:
            name = m.group(1).strip()
            if name and not name.lower().startswith(("untitled", "new ", "document")):
                return name[:60]
        # a full path in the title is a reliable project hint
        if "\\" in title:
            parts = [p for p in title.replace("/", "\\").split("\\") if p]
            if len(parts) >= 2:
                return parts[-2][:60]
        return ""

    # ------------------------------------------------------------- learning

    def set_fact(self, subject, value):
        if not subject:
            return False
        self.data.setdefault("profile", {})[str(subject).strip()] = str(value).strip()
        return self.save()

    def set_preference(self, subject, value):
        if not subject:
            return False
        self.data.setdefault("preferences", {})[str(subject).strip()] = str(value).strip()
        return self.save()

    def note_request(self, text):
        """Remember what was asked for. Later 'do that again' needs this."""
        text = str(text or "").strip()
        if not text:
            return False
        reqs = self.data.setdefault("requests", [])
        reqs.append({"t": _now(), "text": text[:300]})
        del reqs[:-40]
        return self.save()

    def note_correction(self, text):
        """A correction is the most valuable signal a user gives.

        "don't open netflix" / "stop doing that" / "I said tea, not coffee"
        are worth keeping verbatim and surfacing to the model on every turn.
        """
        text = str(text or "").strip()
        if not text:
            return False
        corr = self.data.setdefault("corrections", [])
        corr.append({"t": _now(), "text": text[:300]})
        del corr[:-20]
        return self.save()

    def note_mood(self, mood):
        mood = str(mood or "").strip().lower()
        if not mood:
            return False
        day = _day_key()
        m = self.data.setdefault("moods", {}).setdefault(day, {})
        m[mood] = m.get(mood, 0) + 1
        del self.data["moods"][:-30]
        return self.save()

    def recent_requests(self, limit=5):
        reqs = self.data.get("requests") or []
        return [r.get("text", "") for r in reqs[-limit:]][::-1]

    # ------------------------------------------------------------- summarising

    def top_apps(self, n=5):
        apps = self.data.get("apps") or {}
        if not apps:
            return []
        ranked = sorted(apps.items(),
                        key=lambda kv: (float(kv[1].get("seconds", 0.0)),
                                        int(kv[1].get("count", 0))),
                        reverse=True)
        return [(a, float(d.get("seconds", 0.0)), int(d.get("count", 0)))
                for a, d in ranked[:n]]

    def active_projects(self, n=5):
        projs = self.data.get("projects") or {}
        if not projs:
            return []
        ranked = sorted(projs.items(), key=lambda kv: kv[1].get("last", 0),
                        reverse=True)
        return [(p, d) for p, d in ranked[:n]]

    def active_hours(self, n=3):
        hours = self.data.get("hours") or {}
        if not hours:
            return []
        return [h for h, _ in sorted(hours.items(),
                                     key=lambda kv: kv[1], reverse=True)[:n]]

    def session_length(self):
        return _now() - self._session_start

    def observe_context(self):
        """Sample the foreground window and record it. Never raises."""
        try:
            import ctypes
            u = ctypes.windll.user32
            hwnd = u.GetForegroundWindow()
            if not hwnd:
                return False
            n = u.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(hwnd, buf, n + 1)
            title = buf.value
            pid = ctypes.c_ulong()
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            app = ""
            try:
                import psutil
                app = psutil.Process(pid.value).name()
            except Exception:
                app = ""
            if not app:
                app = _app_class_for(hwnd)
            return self.observe(app, title)
        except Exception:
            return False

    # ---------------------------------------------------------------- output

    def profile_block(self, max_chars=1200):
        """The block that gets injected into the system prompt.

        This is the thing that makes NIGHTMARE sound like it knows the user.
        It is deliberately short: a prompt is paid for on every token, and a
        long list of trivia is worse than a short list of useful facts.
        """
        d = self.data
        lines = []

        prof = d.get("profile") or {}
        if prof:
            items = "; ".join(f"{k} = {v}" for k, v in list(prof.items())[:8])
            lines.append("About the user: " + items)

        prefs = d.get("preferences") or {}
        if prefs:
            items = "; ".join(f"{k} = {v}" for k, v in list(prefs.items())[:8])
            lines.append("How they want things done: " + items)

        corr = d.get("corrections") or []
        if corr:
            recent = "; ".join(c.get("text", "") for c in corr[-3:])
            lines.append("They have corrected you before - respect these: " + recent)

        apps = self.top_apps(3)
        if apps:
            items = ", ".join("%s (%.0fm, %dx)" % (a, s / 60.0, c)
                              for a, s, c in apps)
            lines.append("Their most-used apps: " + items)

        projs = self.active_projects(3)
        if projs:
            items = ", ".join(p for p, _ in projs)
            lines.append("Projects they have been in: " + items)

        hours = self.active_hours(2)
        if hours:
            lines.append("They are usually active around: " + ", ".join(hours))

        reqs = self.recent_requests(3)
        if reqs:
            lines.append("They recently asked for: " + " | ".join(reqs))

        days = d.get("days") or {}
        if days:
            last = _day_key()
            if last in days:
                lines.append("They are at their machine right now.")

        block = "\n".join(lines)
        return block[:max_chars]

    def summary(self):
        """A readable report of the model, for the user to inspect."""
        d = self.data
        out = ["=== USER MODEL ==="]
        out.append("Tracked since: " + time.strftime(
            "%Y-%m-%d %H:%M", time.localtime(d.get("created", _now()))))
        out.append("Observations: %d" % sum(
            int((a or {}).get("count", 0)) for a in (d.get("apps") or {}).values()))

        prof = d.get("profile") or {}
        if prof:
            out.append("\nKnown facts:")
            for k, v in list(prof.items())[:20]:
                out.append("  - %s = %s" % (k, v))

        prefs = d.get("preferences") or {}
        if prefs:
            out.append("\nPreferences:")
            for k, v in list(prefs.items())[:20]:
                out.append("  - %s = %s" % (k, v))

        corr = d.get("corrections") or []
        if corr:
            out.append("\nCorrections (never repeat these mistakes):")
            for c in corr[-10:]:
                out.append("  - %s" % c.get("text", ""))

        apps = self.top_apps(8)
        if apps:
            out.append("\nApp usage:")
            for a, s, c in apps:
                out.append("  - %s: %.0f min, %d uses" % (a, s / 60.0, c))

        projs = self.active_projects(8)
        if projs:
            out.append("\nProjects:")
            for p, info in projs:
                out.append("  - %s (%d visits, last %s)" % (
                    p, int(info.get("visits", 0)),
                    time.strftime("%Y-%m-%d %H:%M",
                                  time.localtime(info.get("last", 0)))))

        hours = self.active_hours(5)
        if hours:
            out.append("\nMost active hours: " + ", ".join(hours))

        reqs = self.recent_requests(8)
        if reqs:
            out.append("\nRecent requests:")
            for r in reqs:
                out.append("  - %s" % r)

        return "\n".join(out)

    def forget(self):
        """Wipe the model. The user keeps the right to that."""
        try:
            if os.path.exists(self.path):
                os.remove(self.path)
        except Exception:
            pass
        self.data = self._load()
        self._last_app = ""
        self._last_title = ""
        return True


def _app_class_for(hwnd):
    """Fallback app name when the process cannot be read."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
        return buf.value
    except Exception:
        return ""


_MODEL = None


def get_user_model():
    """The shared model instance."""
    global _MODEL
    if _MODEL is None:
        _MODEL = UserModel()
    return _MODEL
