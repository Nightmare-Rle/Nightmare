import os
import sys
import json
import time
import shutil
import tempfile


DEFAULT_MEMORY = {
    "user_name": "",
    "facts": {},
    "learned": {},
    "notes": [],
    "aliases": {},
    "stats": {"learned": 0, "recalled": 0}
}

DEFAULT_SETTINGS = {
    "wake_word": "nightmare",
    "always_on_top": False,
    "accent": "red",
    "rate": 180,
    "volume": 1.0,
    "edge_voice": "en-GB-RyanNeural",
    "voice_input": True,
    "theme": "red",
    "voice_speed": 0,
    "tts_voice": "",
    "input_device": None,
    "output_device": "",
    "language": "en",
    "proactive": True
}


def data_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _data_candidates():
    """Every place a .nightmare folder has been used, in priority order.

    Running from source used the project folder while the packaged app used the
    home folder, so the two kept separate settings. Both layouts are still
    checked so existing data is found no matter how the app was started.
    """
    base = data_dir()
    roots = [base]
    if getattr(sys, 'frozen', False):
        # dist\Nightmare\Nightmare.exe -> also check the parent dist\ folder
        roots.append(os.path.dirname(base))
    roots.append(os.path.expanduser("~"))
    out = []
    for r in roots:
        c = os.path.normpath(os.path.join(r, ".nightmare"))
        if c not in out:
            out.append(c)
    return out


# payload folders that identify the "real" data dir (models/media), not config
_PAYLOAD = ("models", "media", "vosk-model-small-en-us-0.15")


def find_nightmare_dir(*prefer):
    """Home for models/media. Returns the candidate that actually holds data."""
    cands = _data_candidates()
    wanted = tuple(prefer) or _PAYLOAD
    for c in cands:
        if any(os.path.isdir(os.path.join(c, w)) for w in wanted):
            return c
    for c in cands:
        if os.path.isdir(c):
            return c
    fallback = cands[0]
    os.makedirs(fallback, exist_ok=True)
    return fallback


def config_dir():
    """Single home for settings.json / memory.json / chatlog.json.

    Always the user's home folder, whether running from source or as the frozen
    exe, so a change made in one is visible in the other. The dist folder is
    wiped on every build and the project folder is easy to lose, so neither can
    be the canonical location. Anything found in a legacy folder is copied in
    the first time, newest wins, and existing files are never overwritten.
    """
    home = os.path.normpath(os.path.join(os.path.expanduser("~"), ".nightmare"))
    os.makedirs(home, exist_ok=True)
    legacy = [c for c in _data_candidates() if os.path.normpath(c) != home]
    for name in ("settings.json", "memory.json", "chatlog.json",
                 "autonomy.json", "protocols.json"):
        dst = os.path.join(home, name)
        if os.path.exists(dst):
            continue
        best, best_mtime = None, -1.0
        for src_dir in legacy:
            src = os.path.join(src_dir, name)
            if not os.path.exists(src):
                continue
            try:
                m = os.path.getmtime(src)
            except OSError:
                m = 0.0
            if m > best_mtime:
                best, best_mtime = src, m
        if best:
            try:
                shutil.copy2(best, dst)
            except Exception:
                pass
    return home


def _atomic_write(path, obj):
    try:
        d = os.path.dirname(path)
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(obj, f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass
    except Exception:
        try:
            with open(os.path.join(os.path.dirname(path), "save_error.log"), "a", encoding="utf-8") as f:
                import traceback
                f.write(traceback.format_exc())
        except Exception:
            pass


class Memory:
    def __init__(self):
        self.dir = config_dir()
        self.memory_path = os.path.join(self.dir, "memory.json")
        self.settings_path = os.path.join(self.dir, "settings.json")
        self.chatlog_path = os.path.join(self.dir, "chatlog.json")
        self.data = self._load(self.memory_path, DEFAULT_MEMORY)
        self.settings = self._load(self.settings_path, DEFAULT_SETTINGS)

    def _load(self, path, default):
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            merged = dict(default)
            if isinstance(loaded, dict):
                merged.update(loaded)
            return merged
        except Exception:
            return dict(default)

    def save(self):
        _atomic_write(self.memory_path, self.data)

    def save_settings(self):
        _atomic_write(self.settings_path, self.settings)

    def log_turn(self, role, text):
        if not text or not str(text).strip():
            return
        try:
            items = []
            if os.path.exists(self.chatlog_path):
                with open(self.chatlog_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, list):
                        items = loaded
            items.append({"role": role, "t": time.time(), "text": str(text)[:2000]})
            _atomic_write(self.chatlog_path, items[-40:])
        except Exception:
            pass

    def session_replay(self, limit=6):
        """Last interactions, so NIGHTMARE 'remembers' across restarts."""
        try:
            if not os.path.exists(self.chatlog_path):
                return ""
            with open(self.chatlog_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, list):
                return ""
            recent = [i for i in loaded[-limit:] if i.get("text", "").strip()]
            if not recent:
                return ""
            parts = []
            for it in recent:
                role = "User" if it.get("role") == "user" else "NIGHTMARE"
                txt = str(it.get("text", ""))[:240]
                parts.append(f"{role}: {txt}")
            return "Recent conversation (from before this session):\n" + "\n".join(parts)
        except Exception:
            return ""

    @property
    def user_name(self):
        return self.data.get("user_name", "")

    @property
    def learned(self):
        return self.data.get("learned", {})

    @property
    def aliases(self):
        return self.data.get("aliases", {})

    # -------------------------------------------------------- C:\BRAIN bridge
    # memory.json stays the fast local store, but durable knowledge the owner
    # explicitly teaches (facts, their name, command aliases) is also filed into
    # C:\BRAIN so it is classified, indexed and recalled alongside everything
    # else. Best-effort: if brain_store is unavailable the JSON memory is
    # untouched and still works.

    def _brain(self):
        try:
            from modules import brain_store
            return brain_store
        except Exception:
            try:
                import brain_store
                return brain_store
            except Exception:
                return None

    def _mirror_fact(self, subject, fact):
        bs = self._brain()
        if bs is None:
            return
        try:
            text = "%s: %s" % ((subject or "").strip(), (fact or "").strip())
            if bs._exists_similar(text, bs.MEM):
                return
            bs.save_memory(text, title=(subject or "").strip() or "fact",
                           tags=["taught"], kind="memories")
        except Exception:
            pass

    def _mirror_owner(self, name):
        if not name:
            return
        bs = self._brain()
        if bs is None:
            return
        try:
            fact = "Owner name/identity: %s" % name
            if bs._exists_similar(fact, bs.OWNER):
                return
            bs.save_owner_fact(fact, tags=["identity", "taught"])
        except Exception:
            pass

    def _mirror_protocol(self, alias, command):
        bs = self._brain()
        if bs is None:
            return
        try:
            rule = "Alias '%s' runs: %s" % (alias, command)
            if bs._exists_similar(rule, bs.PROTO):
                return
            bs.save_protocol(rule, tags=["alias", "taught"])
        except Exception:
            pass

    def learn(self, subject, fact):
        learned = self.data.setdefault("learned", {})
        learned[subject.strip()] = fact.strip()
        stats = self.data.setdefault("stats", {})
        stats["learned"] = len(learned)
        self.save()
        self._mirror_fact(subject, fact)

    def recall(self, subject):
        return self.learned.get(subject.strip())

    def set_user_name(self, name):
        self.data["user_name"] = name.strip()
        self.save()
        self._mirror_owner(name.strip())

    def set_alias(self, alias, command):
        aliases = self.data.setdefault("aliases", {})
        aliases[alias.strip().lower()] = command.strip().lower()
        self.save()
        self._mirror_protocol(alias.strip(), command.strip())

    def context_block(self, limit=None):
        lines = []
        if self.user_name:
            lines.append(f"The user's name is {self.user_name}.")
        learned = self.learned
        if learned:
            count = 2 if limit else 5
            top = list(learned.items())[-count:]
            width = 80 if limit else 160
            facts = "; ".join(f"{k[:40]} = {v[:width]}" for k, v in top)
            lines.append(f"You remember these things: {facts}")
        aliases = self.aliases
        if aliases:
            aliases_str = "; ".join(f"\"{k}\" -> {v}" for k, v in aliases.items())
            lines.append(
                f"When the user says an alias listed below, run the command on the right side "
                f"(via execute_action if needed) and confirm briefly. ALIASES: {aliases_str}"
            )
        return "\n".join(lines)