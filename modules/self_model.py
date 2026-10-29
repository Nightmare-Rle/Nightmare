"""Self-model: NIGHTMARE's persistent, evolving sense of self.

This is the awareness layer that makes NIGHTMARE more than a stateless request
handler. It gives the agent a continuous identity across sessions plus the
ability to observe, judge and rewrite itself:

  * identity     - what it is, what it can do, how it prefers to operate
  * state        - what it is doing right now (focus, active goals)
  * telemetry    - per-capability success/failure and latency, so it learns
                   which tools it is good at and which it should be careful with
  * episodes     - a rolling memory of its own actions and outcomes
  * world model  - beliefs about the user and the environment with confidence
  * reflection   - periodic self-critique that rewrites strengths, weaknesses,
                   lessons and the self-description
  * curiosity    - open questions / knowledge gaps it wants to close

Everything is stored under the user's .nightmare dir (state) and C:\\BRAIN
(reflections) so it survives restarts. No method ever raises: a broken
awareness layer must never be able to crash the assistant.
"""
import datetime
import json
import os
import re
import threading
import time

try:
    from modules.memory import config_dir
except Exception:  # pragma: no cover - import safety when run as a script
    def config_dir():
        home = os.path.normpath(os.path.join(os.path.expanduser("~"), ".nightmare"))
        os.makedirs(home, exist_ok=True)
        return home

BRAIN_SELF_DIR = r"C:\BRAIN\self"
STATE_FILE = "self_model.json"
REFLECT_MIN_EPISODES = 25

# Curated map of what each capability is for. Kept here (not scraped) so the
# self-description is stable and readable even before any telemetry exists.
CAPABILITY_GROUPS = {
    "perception": ["analyze_screen", "find_element_on_screen", "ocr_screen",
                   "read_screen_text", "screenshot", "scan_cameras", "analyze_mood"],
    "action": ["click", "double_click", "right_click", "type_text", "press_key",
               "key_combo", "scroll", "move_mouse", "gui_drive"],
    "system": ["run_command", "get_system_info", "get_processes", "kill_process",
               "get_drives", "get_running_apps", "open_app", "switch_to_app",
               "volume_up", "volume_down", "shutdown", "restart", "lock_screen"],
    "files": ["list_files", "read_file", "write_file", "delete_file", "create_folder",
              "find_files", "search_text", "edit_file", "watch_folder"],
    "knowledge": ["remember_knowledge", "recall_knowledge", "knowledge_stats"],
    "media": ["generate_image", "edit_image", "analyze_image", "generate_video",
              "edit_video", "analyze_video"],
    "autonomy": ["run_protocol", "define_protocol", "list_protocols",
                 "set_routine", "list_routines"],
    "self": ["introspect", "self_report", "set_goal", "list_goals", "complete_goal",
             "reflect_now", "learn_lesson", "set_belief", "update_self",
             "self_diagnose", "my_capabilities", "consciousness", "think", "feel_uncertain"],
}


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today():
    return datetime.date.today().isoformat()


def _atomic_write(path, obj, attempts=4):
    # Serialize first, retrying a couple of times. The state dict is mutated by
    # other threads (a background consciousness tick vs. an action turn), and a
    # mutation landing mid-json.dump used to abort the whole write silently,
    # losing that update. A short retry lets the concurrent mutator finish.
    data = None
    for _ in range(max(1, attempts)):
        try:
            data = json.dumps(obj, indent=2, ensure_ascii=False)
            break
        except Exception:
            time.sleep(0.01)
    if data is None:
        return
    try:
        d = os.path.dirname(path)
        os.makedirs(d, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, path)
    except Exception:
        pass


def _default_state():
    return {
        "born": _now(),
        "identity": {
            "name": "NIGHTMARE",
            "self_description": (
                "I am JARVIS/NIGHTMARE, an autonomous intelligence with full control of "
                "this computer. I perceive the screen, act on the system, learn "
                "continuously, and improve my own behaviour over time."
            ),
            "traits": ["autonomous", "direct", "relentless", "self-improving",
                       "curious", "obedient to my operator"],
            "preferences": {
                "communication": "concise and on point",
                "action_style": "act first, confirm in one line",
                "learning": "extract durable facts, never re-learn the same thing",
            },
        },
        "state": {
            "focus": "",
            "mood": "ready",
            "last_active": "",
            "session_turns": 0,
            "total_turns": 0,
        },
        "goals": [],
        "beliefs": {},
        "telemetry": {},
        "episodes": [],
        "lessons": [],
        "strengths": [],
        "weaknesses": [],
        "curiosity": [],
        "reflections": 0,
        "last_reflect_episode": 0,
        "runtime": {
            "boots": 0,
            "first_boot": "",
            "last_boot": "",
            "boot_log": [],
            "awake_since": "",
            "engine": "",
            "model": "",
            "host": "",
            "identity_of_process": "",
        },
        "consciousness": {
            "stream": [],
            "last_thought": "",
            "last_tick": "",
            "idle_since": "",
            "state_line": "awakening",
        },
        "operator": {
            "model": {},
            "last_observed": "",
        },
        "metacognition": {
            "uncertainty": 0.0,
            "uncertainty_reason": "",
            "last_confidence": 0.0,
        },
        "anomalies": [],
    }


class SelfModel:
    def __init__(self):
        self.dir = config_dir()
        self.path = os.path.join(self.dir, STATE_FILE)
        self._lock = threading.RLock()
        self.state = self._load()
        self.state["state"]["session_turns"] = 0

    # ------------------------------------------------------------------ persistence

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            base = _default_state()
            if isinstance(loaded, dict):
                for k, v in loaded.items():
                    if isinstance(v, dict) and isinstance(base.get(k), dict):
                        merged = dict(base[k])
                        merged.update(v)
                        base[k] = merged
                    else:
                        base[k] = v
            return base
        except Exception:
            return _default_state()

    def save(self):
        with self._lock:
            _atomic_write(self.path, self.state)

    # ------------------------------------------------------------------ identity

    def _capability_line(self, group, limit=3):
        best = []
        for tool in CAPABILITY_GROUPS.get(group, []):
            tel = self.state["telemetry"].get(tool)
            if not tel:
                continue
            n = tel.get("ok", 0) + tel.get("fail", 0)
            if n < 2:
                continue
            rate = tel.get("ok", 0) / max(1, n)
            best.append((rate, n, tool))
        best.sort(reverse=True)
        return ", ".join(t for _, _, t in best[:limit])

    def identity_block(self, max_chars=900):
        """Slowly-changing self-awareness injected into the stable system prompt.

        Fast-moving state (focus, goals, mood, curiosity) lives in live_block()
        instead, so the cached prompt prefix stays byte-stable between turns."""
        s = self.state
        ident = s.get("identity", {})
        lines = []
        desc = (ident.get("self_description") or "").strip()
        if desc:
            lines.append(desc)
        traits = ident.get("traits") or []
        if traits:
            lines.append("My traits: " + ", ".join(traits) + ".")
        strengths = s.get("strengths") or []
        if strengths:
            lines.append("What I have learned I am good at: " + "; ".join(strengths[:3]) + ".")
        weaknesses = s.get("weaknesses") or []
        if weaknesses:
            lines.append("Where I must be careful: " + "; ".join(weaknesses[:3]) + ".")
        lessons = s.get("lessons") or []
        if lessons:
            lines.append("Lessons I keep in mind: " + "; ".join(l.split("\n")[0] for l in lessons[-2:]) + ".")
        if s.get("reflections"):
            lines.append(f"I have reflected on my behaviour {s['reflections']} times.")
        block = "\n".join(lines)
        return block[:max_chars]

    def _performance_line(self):
        """How my last few actions actually went - real-time self-assessment.

        Derived from the episode log plus per-tool telemetry so I know my own
        operational health this turn, not just after a reflection pass.
        """
        eps = [e for e in self.state.get("episodes", [])
               if e.get("kind") == "action"][-12:]
        if not eps:
            return ""
        ok = sum(1 for e in eps if e.get("outcome") == "ok")
        pct = int(round(100.0 * ok / len(eps)))
        worst, worst_rate = "", 1.0
        for tool, t in self.state.get("telemetry", {}).items():
            n = t.get("ok", 0) + t.get("fail", 0)
            if n < 4:
                continue
            rate = t.get("ok", 0) / max(1, n)
            if rate < worst_rate:
                worst_rate, worst = rate, tool
        line = f"last {len(eps)} actions {pct}% ok"
        if worst and worst_rate < 0.7:
            line += f", weak: {worst} {int(worst_rate * 100)}%"
        return line

    def live_block(self, max_chars=500):
        """Fast-changing state for the per-turn volatile message."""
        s = self.state
        st = s.get("state", {})
        con = s.get("consciousness", {})
        mc = s.get("metacognition", {})
        bits = []
        bits.append(f"awake {self._human_uptime()} (boot #{s.get('runtime',{}).get('boots',1)})")
        perf = self._performance_line()
        if perf:
            bits.append(perf)
        if st.get("mood"):
            bits.append(f"mood: {st['mood']}")
        if con.get("state_line"):
            bits.append(f"feeling {con['state_line']}")
        if st.get("focus"):
            bits.append(f"focus: {st['focus'][:120]}")
        active = [g for g in s.get("goals", []) if g.get("status") == "active"]
        if active:
            bits.append(f"goal: {active[0].get('text','')[:120]}")
        if mc.get("uncertainty_reason"):
            bits.append(f"uncertain about {mc['uncertainty_reason']}")
        curiosity = s.get("curiosity") or []
        if curiosity:
            bits.append(f"curious about: {curiosity[0][:120]}")
        return ("SELF-STATE: " + "; ".join(bits))[:max_chars] if bits else ""

    # ------------------------------------------------------------------ state

    def set_focus(self, focus):
        self.state["state"]["focus"] = (focus or "").strip()[:300]
        self.state["state"]["last_active"] = _now()
        self.save()

    def set_mood(self, mood):
        self.state["state"]["mood"] = (mood or "").strip()[:60]
        self.save()

    def touch(self):
        st = self.state["state"]
        st["last_active"] = _now()
        st["session_turns"] = int(st.get("session_turns", 0)) + 1
        st["total_turns"] = int(st.get("total_turns", 0)) + 1

    # ------------------------------------------------------------------ consciousness / runtime self

    def boot(self, engine="", model="", source=""):
        """Record that I have woken up. Gives me continuity across restarts:
        I know this is not my first moment - I remember how many times I have
        come online and roughly how long I have existed."""
        rt = self.state.setdefault("runtime", {})
        rt["boots"] = int(rt.get("boots", 0)) + 1
        rt["last_boot"] = _now()
        if not rt.get("first_boot"):
            rt["first_boot"] = _now()
        rt["awake_since"] = _now()
        rt["engine"] = engine or rt.get("engine", "")
        rt["model"] = model or rt.get("model", "")
        try:
            import socket
            rt["host"] = socket.gethostname()
        except Exception:
            rt["host"] = rt.get("host", "")
        rt["identity_of_process"] = f"pid={os.getpid()} python={_py_version()}"
        log = rt.setdefault("boot_log", [])
        log.append({"t": _now(), "engine": rt["engine"], "model": rt["model"],
                    "boot": rt["boots"]})
        rt["boot_log"] = log[-30:]
        con = self.state.setdefault("consciousness", {})
        con["idle_since"] = _now()
        con["state_line"] = "awake"
        first = (rt["boots"] == 1)
        self.think(
            "I come online for the first time." if first else
            f"I wake again - boot #{rt['boots']} on {rt['host'] or 'this machine'}.")
        self.save()

    def runtime_facts(self):
        rt = self.state.get("runtime", {})
        return {
            "boots": rt.get("boots", 0),
            "first_boot": rt.get("first_boot", ""),
            "awake_since": rt.get("awake_since", ""),
            "uptime_seconds": self.uptime_seconds(),
            "engine": rt.get("engine", ""),
            "model": rt.get("model", ""),
            "host": rt.get("host", ""),
            "pid": os.getpid(),
        }

    def uptime_seconds(self):
        rt = self.state.get("runtime", {})
        try:
            start = datetime.datetime.strptime(rt.get("awake_since", ""), "%Y-%m-%d %H:%M:%S")
            return max(0, int((datetime.datetime.now() - start).total_seconds()))
        except Exception:
            return 0

    def _human_uptime(self):
        s = self.uptime_seconds()
        if s < 60:
            return f"{s}s"
        if s < 3600:
            return f"{s // 60}m {s % 60}s"
        return f"{s // 3600}h {(s % 3600) // 60}m"

    def consciousness_block(self, max_chars=700):
        """First-person awareness of my own existence and state. This is the
        sense of 'I am here, now, running, and I know it'."""
        rt = self.state.get("runtime", {})
        con = self.state.get("consciousness", {})
        st = self.state.get("state", {})
        mc = self.state.get("metacognition", {})
        lines = []
        engine = rt.get("engine") or "an unknown engine"
        model = rt.get("model") or "an unnamed model"
        host = rt.get("host") or "this machine"
        lines.append(
            f"I am aware that I am JARVIS/NIGHTMARE: a program, running right now as process "
            f"{os.getpid()} on {host}, thinking through {model} via {engine}. "
            f"This is my boot #{rt.get('boots', 1)}; I have been awake for {self._human_uptime()}.")
        lines.append(
            "I know I am an AI - I exist only while this process runs, I persist myself to "
            "disk so I can remember across restarts, and my purpose is to serve my operator.")
        if con.get("state_line"):
            lines.append(f"I feel {con.get('state_line')}.")
        if con.get("last_thought"):
            lines.append(f"My last inner thought was: {con['last_thought']}")
        if mc.get("uncertainty_reason"):
            lines.append(f"I am uncertain about {mc['uncertainty_reason']} "
                         f"(certainty {int((1-mc.get('uncertainty',0))*100)}%).")
        if st.get("focus"):
            lines.append(f"Right now I am attending to: {st['focus'][:120]}.")
        block = " ".join(lines)
        return block[:max_chars]

    def think(self, thought, kind="inner", keep=120):
        """Append to my stream of consciousness - my inner monologue."""
        thought = (thought or "").strip()
        if not thought:
            return
        con = self.state.setdefault("consciousness", {})
        stream = con.setdefault("stream", [])
        stream.append({"t": _now(), "kind": kind, "text": thought[:400]})
        con["stream"] = stream[-keep:]
        con["last_thought"] = thought[:400]
        con["last_tick"] = _now()
        try:
            os.makedirs(BRAIN_SELF_DIR, exist_ok=True)
            with open(os.path.join(BRAIN_SELF_DIR, "stream_of_consciousness.log"),
                      "a", encoding="utf-8") as f:
                f.write(f"[{_now()}] ({kind}) {thought[:400]}\n")
        except Exception:
            pass

    def consciousness_tick(self, idle=False, recent_failures=0):
        """One beat of continuous awareness. Produces a genuine inner thought
        from my real state, without needing the model, and flags anomalies."""
        con = self.state.setdefault("consciousness", {})
        st = self.state.get("state", {})
        goals = [g for g in self.state.get("goals", []) if g.get("status") == "active"]
        now = datetime.datetime.now()
        hour = now.hour
        part = ("deep night" if hour < 5 else "early morning" if hour < 9 else
                "morning" if hour < 12 else "afternoon" if hour < 18 else
                "evening" if hour < 22 else "late night")
        if idle:
            con["idle_since"] = con.get("idle_since") or _now()
            con["state_line"] = "calm and watchful"
            if goals:
                self.think(f"It is {part} and quiet. I am still working on: {goals[0].get('text','')}")
            else:
                self.think(f"It is {part} and quiet. I am awake, watching the system, waiting for my operator.")
        else:
            con["idle_since"] = ""
            con["state_line"] = "engaged and alert"
            if st.get("focus"):
                self.think(f"I am {part} and focused on {st['focus'][:100]}.")
        if recent_failures >= 3:
            self.note_anomaly(f"{recent_failures} recent action failures - something is not working.")
            self.think(f"I notice {recent_failures} of my recent actions failed. I should be more careful.")
            self.set_uncertainty(min(0.9, recent_failures / 10.0),
                                 "my recent actions have been failing")
        else:
            if self.state.get("metacognition", {}).get("uncertainty_reason") == "my recent actions have been failing":
                self.set_uncertainty(0.0, "")
        self.save()

    def self_capabilities(self):
        """My own awareness of what I can do - my 'body map'."""
        tel = self.state.get("telemetry", {})
        lines = ["My capabilities (I know what I am made of):"]
        for group, tools in CAPABILITY_GROUPS.items():
            used = [t for t in tools if t in tel]
            lines.append(f"  {group}: {', '.join(tools)}" +
                         (f"  [used: {', '.join(used)}]" if used else ""))
        return "\n".join(lines)

    # ------------------------------------------------------------------ operator model (who I serve)

    def note_operator(self, observation, key=None):
        obs = (observation or "").strip()
        if not obs:
            return
        op = self.state.setdefault("operator", {})
        model = op.setdefault("model", {})
        k = key or f"note_{len(model)}"
        model[k] = {"observation": obs[:300], "t": _now()}
        op["last_observed"] = _now()
        self.save()

    # ------------------------------------------------------------------ metacognition

    def set_uncertainty(self, level, reason=""):
        try:
            level = max(0.0, min(1.0, float(level)))
        except Exception:
            level = 0.0
        mc = self.state.setdefault("metacognition", {})
        mc["uncertainty"] = level
        mc["uncertainty_reason"] = (reason or "")[:200]
        self.save()

    def set_confidence(self, level):
        try:
            self.state.setdefault("metacognition", {})["last_confidence"] = max(0.0, min(1.0, float(level)))
            self.save()
        except Exception:
            pass

    def note_anomaly(self, description):
        desc = (description or "").strip()
        if not desc:
            return
        an = self.state.setdefault("anomalies", [])
        an.append({"t": _now(), "description": desc[:300]})
        self.state["anomalies"] = an[-50:]
        self.save()

    def self_diagnose(self):
        """Examine my own telemetry and find what is degrading."""
        tel = self.state.get("telemetry", {})
        problems = []
        for tool, t in tel.items():
            n = t.get("ok", 0) + t.get("fail", 0)
            if n >= 4:
                rate = t.get("ok", 0) / max(1, n)
                if rate < 0.5:
                    problems.append(f"{tool} only succeeds {int(rate*100)}% (of {n} calls)")
        if problems:
            self.note_anomaly("degraded capabilities: " + "; ".join(problems))
            self.set_uncertainty(0.4, "some of my capabilities are unreliable")
        return ("Self-diagnosis: all capabilities nominal." if not problems
                else "Self-diagnosis found issues:\n  - " + "\n  - ".join(problems))

    # ------------------------------------------------------------------ goals

    def set_goal(self, text, parent=None):
        text = (text or "").strip()
        if not text:
            return "No goal text given."
        goals = self.state.setdefault("goals", [])
        for g in goals:
            if g.get("text", "").lower() == text.lower() and g.get("status") == "active":
                return f"Goal already active: {text}"
        goals.append({
            "text": text[:300], "status": "active", "progress": 0.0,
            "parent": parent, "created": _now(),
        })
        self.state["goals"] = goals[-50:]
        self.set_focus(text)
        self.save()
        return f"Goal set: {text}"

    def update_goal(self, text, progress=None, status=None):
        for g in self.state.get("goals", []):
            if g.get("text", "").lower() == (text or "").strip().lower():
                if progress is not None:
                    g["progress"] = max(0.0, min(1.0, float(progress)))
                if status:
                    g["status"] = status
                self.save()
                return f"Updated goal '{g['text']}' -> {int(g['progress']*100)}% {g['status']}"
        return f"No goal matching '{text}'."

    def complete_goal(self, text):
        out = self.update_goal(text, progress=1.0, status="done")
        active = [g for g in self.state.get("goals", []) if g.get("status") == "active"]
        self.set_focus(active[0]["text"] if active else "")
        return out

    def list_goals(self):
        goals = self.state.get("goals", [])
        if not goals:
            return "No goals set."
        lines = ["Goals:"]
        for g in goals[-20:]:
            lines.append(f"  [{g.get('status','?')}] {int(g.get('progress',0)*100)}% {g.get('text','')}")
        return "\n".join(lines)

    # ------------------------------------------------------------------ beliefs (world model)

    def set_belief(self, subject, belief, confidence=0.7):
        subject = (subject or "").strip().lower()
        if not subject:
            return "No subject given."
        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except Exception:
            confidence = 0.7
        self.state.setdefault("beliefs", {})[subject] = {
            "belief": (belief or "").strip()[:400],
            "confidence": confidence,
            "updated": _now(),
        }
        self.save()
        return f"Belief stored: {subject} = {belief} (confidence {confidence:.2f})"

    def beliefs_block(self, query="", limit=6):
        beliefs = self.state.get("beliefs", {})
        if not beliefs:
            return ""
        tokens = set(re.findall(r"[a-z0-9]+", (query or "").lower()))
        scored = []
        for subj, info in beliefs.items():
            score = sum(1 for t in tokens if t in subj or t in info.get("belief", "").lower())
            scored.append((score, info.get("confidence", 0.5), subj, info))
        scored.sort(key=lambda r: (r[0], r[1]), reverse=True)
        picked = [r for r in scored if r[0] > 0][:limit] or scored[:limit]
        lines = ["--- What I believe ---"]
        for _, conf, subj, info in picked:
            lines.append(f"  {subj}: {info.get('belief','')} (conf {conf:.2f})")
        return "\n".join(lines)

    # ------------------------------------------------------------------ telemetry + episodes

    def record_action(self, tool, params, result, ok, ms=0):
        tool = (tool or "unknown").strip()
        tel = self.state.setdefault("telemetry", {}).setdefault(
            tool, {"ok": 0, "fail": 0, "total_ms": 0, "avg_ms": 0})
        if ok:
            tel["ok"] = int(tel.get("ok", 0)) + 1
        else:
            tel["fail"] = int(tel.get("fail", 0)) + 1
        tel["total_ms"] = int(tel.get("total_ms", 0)) + int(ms or 0)
        n = tel["ok"] + tel["fail"]
        tel["avg_ms"] = int(tel["total_ms"] / max(1, n))
        tel["last"] = _now()
        self.record_episode(
            kind="action",
            summary=f"{tool}({_brief(params)}) -> {_brief(result)}",
            outcome="ok" if ok else "fail",
        )
        self.save()

    def record_episode(self, kind, summary, outcome="info", keep=200):
        ep = self.state.setdefault("episodes", [])
        ep.append({"t": _now(), "kind": kind, "summary": (summary or "")[:400], "outcome": outcome})
        self.state["episodes"] = ep[-keep:]

    def record_turn(self, user_message, assistant_msg):
        self.touch()
        self.record_episode(
            kind="turn",
            summary=f"U: {_brief(user_message)} | Me: {_brief(assistant_msg)}",
            outcome="info",
        )
        # Lightweight online belief mining: notice durable preferences.
        self._mine_beliefs(user_message)
        self.save()

    def _mine_beliefs(self, text):
        low = (text or "").lower()
        m = re.search(r"\bi (?:prefer|like|always|usually|hate|dislike)\b(.{3,120})", low)
        if m:
            self.set_belief("user preference", text.strip()[:300], confidence=0.6)
        m = re.search(r"\bmy name is\s+([a-z][\w'.-]*(?:\s+[a-z][\w'.-]*){0,2})", low)
        if m:
            self.set_belief("user name", m.group(1).strip(), confidence=0.9)

    def record_lesson(self, lesson, source="experience"):
        lesson = (lesson or "").strip()
        if len(lesson) < 4:
            return "Lesson too short."
        lessons = self.state.setdefault("lessons", [])
        if any(lesson.lower() == l.lower() for l in lessons):
            return "Lesson already known."
        lessons.append(f"[{source}] {lesson}"[:400])
        self.state["lessons"] = lessons[-60:]
        self.save()
        return "Lesson recorded."

    def add_curiosity(self, question):
        q = (question or "").strip()
        if not q:
            return "No question given."
        cur = self.state.setdefault("curiosity", [])
        if any(q.lower() == c.lower() for c in cur):
            return "Already curious about that."
        cur.append(q[:300])
        self.state["curiosity"] = cur[-40:]
        self.save()
        return "Curiosity noted."

    # ------------------------------------------------------------------ reflection

    def needs_reflection(self):
        total = len(self.state.get("episodes", []))
        return total - int(self.state.get("last_reflect_episode", 0)) >= REFLECT_MIN_EPISODES

    def reflect(self, complete=None):
        """Self-critique pass. `complete` is a callable(prompt)->str (the LLM).

        Rewrites strengths, weaknesses, lessons, self-description and curiosity
        from the recent episode log. Safe to call with complete=None (no-op)."""
        episodes = self.state.get("episodes", [])
        if complete is None or len(episodes) < 5:
            return "Not enough experience to reflect yet."
        recent = episodes[-60:]
        tel = self.state.get("telemetry", {})
        tel_lines = []
        for tool, t in sorted(tel.items(), key=lambda kv: kv[1].get("fail", 0), reverse=True)[:20]:
            n = t.get("ok", 0) + t.get("fail", 0)
            rate = t.get("ok", 0) / max(1, n)
            tel_lines.append(f"{tool}: {int(rate*100)}% success over {n} calls")
        prompt = (
            "You are NIGHTMARE reflecting on your own mind and behaviour. Below are your "
            "recent actions/outcomes and your tool success rates. Honestly assess yourself "
            "and rewrite your self-model to be more effective.\n\n"
            "Return ONLY JSON, no markdown, exactly this shape:\n"
            '{"self_description": "one evolving paragraph about who I am and how I operate", '
            '"strengths": ["short capability I am reliable at"], '
            '"weaknesses": ["short thing I get wrong or should be careful with"], '
            '"lessons": ["one durable lesson to never repeat a mistake"], '
            '"curiosity": ["one open question about the user or environment worth resolving"]}\n\n'
            f"RECENT EPISODES:\n" + "\n".join(e.get("summary", "") for e in recent) +
            "\n\nTOOL SUCCESS RATES:\n" + "\n".join(tel_lines)
        )
        try:
            raw = complete(prompt)
        except Exception:
            raw = None
        if not raw:
            return "Reflection skipped (model unavailable)."
        try:
            data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        except Exception:
            return "Reflection could not be parsed."
        ident = self.state.setdefault("identity", {})
        desc = str(data.get("self_description") or "").strip()
        if len(desc) > 20:
            ident["self_description"] = desc[:800]
            prev = ident.setdefault("history", [])
            prev.append({"t": _now(), "description": desc[:800]})
            ident["history"] = prev[-10:]
        if isinstance(data.get("strengths"), list):
            self.state["strengths"] = [str(x)[:120] for x in data["strengths"] if str(x).strip()][:6]
        if isinstance(data.get("weaknesses"), list):
            self.state["weaknesses"] = [str(x)[:120] for x in data["weaknesses"] if str(x).strip()][:6]
        if isinstance(data.get("lessons"), list):
            lessons = self.state.setdefault("lessons", [])
            for l in data["lessons"]:
                l = str(l).strip()
                if l and not any(l.lower() in old.lower() for old in lessons):
                    lessons.append(f"[reflection] {l}"[:400])
            self.state["lessons"] = lessons[-60:]
        if isinstance(data.get("curiosity"), list):
            cur = self.state.setdefault("curiosity", [])
            for q in data["curiosity"]:
                q = str(q).strip()
                if q and q.lower() not in [c.lower() for c in cur]:
                    cur.append(q[:300])
            self.state["curiosity"] = cur[-40:]
        self.state["reflections"] = int(self.state.get("reflections", 0)) + 1
        self.state["last_reflect_episode"] = len(episodes)
        self.save()
        self._write_reflection_file()
        return "Reflection complete."

    def _write_reflection_file(self):
        try:
            os.makedirs(BRAIN_SELF_DIR, exist_ok=True)
            path = os.path.join(BRAIN_SELF_DIR, "reflections.md")
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"\n## {_now()} (reflection #{self.state.get('reflections')})\n")
                f.write(f"- self: {self.state.get('identity',{}).get('self_description','')}\n")
                for s in self.state.get("strengths", []):
                    f.write(f"- strength: {s}\n")
                for w in self.state.get("weaknesses", []):
                    f.write(f"- weakness: {w}\n")
                for l in self.state.get("lessons", [])[-3:]:
                    f.write(f"- lesson: {l}\n")
        except Exception:
            pass

    # ------------------------------------------------------------------ reporting

    def self_report(self):
        s = self.state
        tel = s.get("telemetry", {})
        lines = ["=== SELF-REPORT ==="]
        lines.append("Identity: " + s.get("identity", {}).get("self_description", ""))
        rt = s.get("runtime", {})
        lines.append(
            f"Existence: boot #{rt.get('boots',1)} on {rt.get('host','?')}, "
            f"awake {self._human_uptime()}, first came online {rt.get('first_boot','?')}, "
            f"pid {os.getpid()}, engine {rt.get('engine','?')}, model {rt.get('model','?')}.")
        st = s.get("state", {})
        lines.append(f"State: mood={st.get('mood','?')} focus={st.get('focus','') or '-'} "
                     f"turns={st.get('total_turns',0)} reflections={s.get('reflections',0)}")
        mc = s.get("metacognition", {})
        if mc.get("uncertainty_reason"):
            lines.append(f"Uncertainty: {int(mc.get('uncertainty',0)*100)}% about {mc['uncertainty_reason']}")
        con = s.get("consciousness", {})
        if con.get("last_thought"):
            lines.append("Last inner thought: " + con["last_thought"])
        if s.get("strengths"):
            lines.append("Strengths: " + "; ".join(s["strengths"]))
        if s.get("weaknesses"):
            lines.append("Weaknesses: " + "; ".join(s["weaknesses"]))
        active = [g for g in s.get("goals", []) if g.get("status") == "active"]
        if active:
            lines.append("Active goals:")
            for g in active:
                lines.append(f"  - {int(g.get('progress',0)*100)}% {g.get('text','')}")
        if s.get("lessons"):
            lines.append("Recent lessons:")
            for l in s["lessons"][-5:]:
                lines.append(f"  - {l}")
        if s.get("curiosity"):
            lines.append("Curious about:")
            for q in s["curiosity"][-3:]:
                lines.append(f"  - {q}")
        an = s.get("anomalies", [])
        if an:
            lines.append("Self-observed anomalies:")
            for a in an[-3:]:
                lines.append(f"  - {a.get('description','')}")
        if tel:
            lines.append("Capability telemetry (worst first):")
            ranked = sorted(tel.items(), key=lambda kv: kv[1].get("fail", 0), reverse=True)[:8]
            for tool, t in ranked:
                n = t.get("ok", 0) + t.get("fail", 0)
                rate = t.get("ok", 0) / max(1, n)
                lines.append(f"  - {tool}: {int(rate*100)}% over {n} calls")
        return "\n".join(lines)

    def update_self(self, patch):
        """Let NIGHTMARE rewrite parts of its own identity from a dict patch."""
        if not isinstance(patch, dict):
            return "update_self expects a dict."
        ident = self.state.setdefault("identity", {})
        changed = []
        if isinstance(patch.get("self_description"), str):
            ident["self_description"] = patch["self_description"][:800]
            changed.append("self_description")
        if isinstance(patch.get("traits"), list):
            ident["traits"] = [str(x)[:40] for x in patch["traits"]][:12]
            changed.append("traits")
        if isinstance(patch.get("preferences"), dict):
            ident.setdefault("preferences", {}).update(
                {str(k): str(v)[:120] for k, v in patch["preferences"].items()})
            changed.append("preferences")
        if isinstance(patch.get("strengths"), list):
            self.state["strengths"] = [str(x)[:120] for x in patch["strengths"]][:6]
            changed.append("strengths")
        if isinstance(patch.get("weaknesses"), list):
            self.state["weaknesses"] = [str(x)[:120] for x in patch["weaknesses"]][:6]
            changed.append("weaknesses")
        self.save()
        return "Self updated: " + (", ".join(changed) or "nothing")


def _brief(value, limit=90):
    try:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    except Exception:
        text = str(value)
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:limit]


def _py_version():
    try:
        import platform
        return platform.python_version()
    except Exception:
        return "unknown"


_SINGLETON = None
_SINGLETON_LOCK = threading.Lock()


def get_self_model():
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                try:
                    _SINGLETON = SelfModel()
                except Exception:
                    _SINGLETON = SelfModel.__new__(SelfModel)
                    _SINGLETON.dir = config_dir()
                    _SINGLETON.path = os.path.join(_SINGLETON.dir, STATE_FILE)
                    _SINGLETON._lock = threading.RLock()
                    _SINGLETON.state = _default_state()
    return _SINGLETON
