import os
import re
import json
import time
import threading
import datetime

BRAIN_ROOT = r"C:\BRAIN"
EXCHANGE_DIR = os.path.join(BRAIN_ROOT, "exchanges")
CONV_DIR = os.path.join(BRAIN_ROOT, "conversation")
LEARNED_DIR = os.path.join(BRAIN_ROOT, "learned")
INSIGHT_DIR = os.path.join(BRAIN_ROOT, "insights")
LESSONS_DIR = os.path.join(BRAIN_ROOT, "lessons")
OWNER_DIR = os.path.join(BRAIN_ROOT, "about_owner")
PROTO_DIR = os.path.join(BRAIN_ROOT, "protocol")
MEM_DIR = os.path.join(BRAIN_ROOT, "memories")
EPIS_DIR = os.path.join(BRAIN_ROOT, "episodic")
INDEX_PATH = os.path.join(BRAIN_ROOT, "index.json")
KNOW_INDEX_PATH = os.path.join(BRAIN_ROOT, "knowledge_index.json")
LOG_PATH = os.path.join(BRAIN_ROOT, "log.txt")

_lock = threading.Lock()


def _mkdirs():
    for d in (BRAIN_ROOT, EXCHANGE_DIR, CONV_DIR, LEARNED_DIR, INSIGHT_DIR,
              LESSONS_DIR, OWNER_DIR, PROTO_DIR, MEM_DIR, EPIS_DIR):
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
    try:
        from modules import brain_store
        brain_store.ensure()
    except Exception:
        pass


def _log(text):
    try:
        _mkdirs()
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
    except Exception:
        pass


def _slug(topic):
    s = re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")
    return s or "misc"


class KnowledgeBase:
    def __init__(self):
        _mkdirs()
        self.month = datetime.datetime.now().strftime("%Y-%m")
        self._index = self._load_index()

    def log(self, text):
        _log(text)

    # ---------------------------------------------------------------- persistence

    def _load_index(self):
        # Dedicated knowledge index. Older builds shared brain_store's
        # C:\BRAIN\index.json; if that file still carries our keys (and we have
        # no dedicated index yet) migrate them once so no learned knowledge is
        # lost. Splitting the two files also stops knowledge.py and brain_store
        # from overwriting each other's writes to the same path.
        for path in (KNOW_INDEX_PATH, INDEX_PATH):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            if not any(k in data for k in
                       ("topics", "exchanges", "last_consolidated", "ingested")):
                continue
            idx = {
                "exchanges": int(data.get("exchanges", 0) or 0),
                "last_consolidated": int(data.get("last_consolidated", 0) or 0),
                "topics": data.get("topics") if isinstance(data.get("topics"), dict) else {},
            }
            if isinstance(data.get("ingested"), dict):
                idx["ingested"] = data["ingested"]
            if path == INDEX_PATH:
                self._write_index(idx)  # one-time migration off the shared file
            return idx
        return {"exchanges": 0, "last_consolidated": 0, "topics": {}}

    def _save_index(self):
        self._write_index(self._index)

    def _write_index(self, idx):
        try:
            os.makedirs(BRAIN_ROOT, exist_ok=True)
            tmp = KNOW_INDEX_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(idx, f, indent=2, ensure_ascii=False)
            os.replace(tmp, KNOW_INDEX_PATH)
        except Exception as e:
            _log(f"index save error: {e}")

    # ---------------------------------------------------------------- exchange log

    def log_exchange(self, user_msg, assistant_msg):
        if not user_msg or not assistant_msg:
            return False
        try:
            _mkdirs()
            stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            entry = f"[{stamp}] Q: {user_msg.strip()}\n          A: {assistant_msg.strip()}\n\n"
            with _lock:
                with open(os.path.join(EXCHANGE_DIR, f"{self.month}.md"), "a", encoding="utf-8") as f:
                    f.write(entry)
                self._index["exchanges"] = int(self._index.get("exchanges", 0)) + 1
                self._save_index()
            # Also write to the new folder layout as a readable .txt file
            try:
                from modules import brain_store
                brain_store.save_conversation(user_msg, assistant_msg)
            except Exception as e:
                _log("brain mirror error: %s" % e)
            return True
        except Exception as e:
            _log(f"log_exchange error: {e}")
            return False

    # ---------------------------------------------------------------- facts

    def learn(self, topic, fact, source="auto"):
        topic = (topic or "").strip()
        fact = (fact or "").strip()
        if len(topic) < 2 or len(fact) < 5:
            return False
        slug = _slug(topic)
        try:
            _mkdirs()
            with _lock:
                path = os.path.join(LEARNED_DIR, f"{slug}.md")
                existing = []
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        existing = [l.strip() for l in f.read().splitlines() if l.strip().startswith("- ")]
                except Exception:
                    pass
                if any(l.strip().lower() == f"- {fact}".lower() for l in existing):
                    return False
                with open(path, "a", encoding="utf-8") as f:
                    f.write(f"- {fact}\n")

                info = self._index.setdefault("topics", {}).setdefault(slug, {
                    "file": os.path.relpath(path, BRAIN_ROOT),
                    "count": 0, "samples": []
                })
                info["count"] = int(info.get("count", 0)) + 1
                info["updated"] = datetime.date.today().isoformat()
                if len(info.get("samples", [])) < 6:
                    info.setdefault("samples", []).append(fact[:160])
                info["source"] = source
                self._save_index()
            _log(f"learned [{topic}]: {fact[:120]}")
            return True
        except Exception as e:
            _log(f"learn error: {e}")
            return False

    # ---------------------------------------------------------------- recall / context

    def recall(self, query, limit=10):
        topics = self._index.get("topics", {})
        if not topics:
            return ""
        tokens = set(re.findall(r"[a-zA-Z0-9]+", (query or "").lower()))
        scored = []
        for slug, info in topics.items():
            score = 0
            if tokens:
                blob = " ".join([slug] + info.get("samples", []) + [str(info.get("updated", ""))])
                score = sum(1 for t in tokens if t in blob)
            scored.append((score, info.get("updated", ""), slug, info))
        scored.sort(key=lambda r: (r[0], r[1]), reverse=True)
        picked = [r for r in scored if r[0] > 0][:limit]
        if not picked and topics:
            picked = [r for r in sorted(scored, key=lambda r: r[1], reverse=True)][:limit]
        lines = []
        for _, _, slug, info in picked:
            path = os.path.join(BRAIN_ROOT, info.get("file", ""))
            facts = []
            try:
                with open(path, "r", encoding="utf-8") as f:
                    facts = [l.strip()[2:] for l in f.read().splitlines() if l.strip().startswith("- ")]
            except Exception:
                pass
            if facts:
                lines.append(f"BRAIN topic '{slug}':")
                lines.extend(f"  - {f}" for f in facts[-10:])
        if not lines:
            return ""
        return "--- Knowledge (C:\\BRAIN) ---\n" + "\n".join(lines)

    def context(self, user_message):
        return self.recall(user_message, limit=10)

    def recent_exchanges(self, limit=40):
        try:
            _mkdirs()
            path = os.path.join(EXCHANGE_DIR, f"{self.month}.md")
            entries = []
            current = None
            with open(path, "r", encoding="utf-8") as f:
                for raw in f.read().splitlines():
                    line = raw.strip()
                    if line.startswith("[") and "] Q:" in line:
                        stamp = line[1:line.index("]")]
                        q = line.split("Q:", 1)[1].strip()
                        current = [stamp, q, ""]
                        entries.append(current)
                    elif line.startswith("A:") and current is not None:
                        current[2] = line.split("A:", 1)[1].strip()
                    elif current is not None and current[2]:
                        current[2] += " " + line
            return [tuple(e) for e in entries if e[2]][-limit:]
        except Exception:
            return []

    # ---------------------------------------------------------------- self-learning (mind)

    def ingest_notes(self, complete=None, max_bytes=100000):
        """Read NIGHTMARE's own memory notes (session logs, insight files) and
        extract NEW durable facts + insights into the BRAIN. Runs once per new/modified
        file (tracked by mtime in the index), so it learns from itself at every boot."""
        if complete is None:
            return 0
        files = []
        for base in (BRAIN_ROOT, INSIGHT_DIR):
            try:
                for name in os.listdir(base):
                    if not name.endswith((".md", ".txt")):
                        continue
                    fp = os.path.join(base, name)
                    if os.path.isdir(fp):
                        continue
                    try:
                        mtime = os.path.getmtime(fp)
                    except Exception:
                        continue
                    seen = self._index.get("ingested", {}).get(
                        os.path.relpath(fp, BRAIN_ROOT))
                    if seen == round(mtime, 1):
                        continue
                    files.append((fp, mtime))
            except Exception:
                continue
        if not files:
            return 0
        before = int(self.stats().get("facts", 0))
        for fp, mtime in files:
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                    body = f.read()
                if not body.strip():
                    continue
                body = body[-max_bytes:]
                prompt = (
                    "You are NIGHTMARE reading your own memory notes. Extract durable, "
                    "reusable knowledge: facts about the user, technical solutions, environment, "
                    "and lessons learned that NIGHTMARE should never have to re-learn.\n"
                    "Rules: skip one-off requests and trivia. Only timeless, reusable facts.\n"
                    "Return ONLY JSON, no markdown: "
                    '{"facts": [{"topic": "short_topic", "fact": "one memorable, self-contained fact"}], '
                    '"insight": "one sentence insight from these notes"}\n\n'
                    f"NOTES ({os.path.relpath(fp, BRAIN_ROOT)}):\n{body}"
                )
                raw = complete(prompt)
                if not raw:
                    continue
                data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
                for it in (data.get("facts") or []):
                    self.learn(str(it.get("topic", "")), str(it.get("fact", "")), source="self")
                insight = str(data.get("insight") or "").strip()
                if insight:
                    self._append_insight("## self\n- " + insight)
                with _lock:
                    self._index.setdefault("ingested", {})[
                        os.path.relpath(fp, BRAIN_ROOT)] = round(mtime, 1)
                    self._save_index()
            except Exception as e:
                _log(f"ingest error {fp}: {e}")
        after = int(self.stats().get("facts", 0))
        return max(0, after - before)

    def _append_insight(self, text):
        try:
            _mkdirs()
            with _lock:
                with open(os.path.join(INSIGHT_DIR, f"{self.month}.md"), "a", encoding="utf-8") as f:
                    f.write(f"{text}\n")
        except Exception as e:
            _log(f"insight append error: {e}")

    def self_identity(self, max_chars=800):
        """A compact, always-carried sense of self: what it has learned about the user,
        itself, and recent insights. Injected into the system prompt every turn."""
        lines = []
        try:
            profile = os.path.join(LEARNED_DIR, "self_profile.md")
            if os.path.exists(profile):
                facts = [l.strip()[2:] for l in open(profile, "r", encoding="utf-8").read().splitlines()
                         if l.strip().startswith("- ")]
                if facts:
                    lines.append("My self-model:")
                    lines.extend("  - " + f for f in facts[-6:])
        except Exception:
            pass
        try:
            _mkdirs()
            insight_files = sorted([f for f in os.listdir(INSIGHT_DIR) if f.endswith(".md")])
            if insight_files:
                last = os.path.join(INSIGHT_DIR, insight_files[-1])
                bullets = [l.strip()[2:] for l in open(last, "r", encoding="utf-8").read().splitlines()
                           if l.strip().startswith("- ")]
                if bullets:
                    lines.append("Recent insights I gained:")
                    lines.extend("  - " + b for b in bullets[-4:])
        except Exception:
            pass
        if not lines:
            return ""
        block = "\n".join(lines)
        return block[:max_chars]

    # ---------------------------------------------------------------- consolidation

    def consolidate(self, complete=None, min_exchanges=12):
        with _lock:
            total = int(self._index.get("exchanges", 0))
            done = int(self._index.get("last_consolidated", 0))
            if total - done < min_exchanges:
                return
            exchanges = self.recent_exchanges(limit=400)
        if not exchanges:
            return
        if complete is None:
            return
        log_block = "\n".join(f"[{s}] Q: {q}\nA: {a}" for s, q, a in exchanges)
        try:
            prompt = (
                "You are NIGHTMARE's self-learning core. Analyze these conversation exchanges "
                "and extract durable, reusable knowledge worth keeping permanently in C:\\BRAIN.\n\n"
                "Rules:\n- Extract timeless facts about the user (preferences, identity, goals), technical "
                "facts, solutions, and things NIGHTMARE should not have to re-learn.\n"
                "- Do NOT extract one-off requests or greetings.\n"
                "- Return ONLY JSON, no markdown, in exactly this shape: "
                '{"facts": [{"topic": "short_topic", "fact": "single memorable fact sentence"}], '
                '"insight": "one sentence summarizing a pattern from these exchanges"}\n\n'
                f"EXCHANGES:\n{log_block}"
            )
            raw = complete(prompt)
            if not raw:
                return
            data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
            facts = data.get("facts") or []
            insight = (data.get("insight") or "").strip()
        except Exception as e:
            _log(f"consolidate extract error: {e}")
            return

        if self.learn("self_summary", f"The last session revealed: {insight}", source="consolidate") if insight else False:
            pass
        try:
            _mkdirs()
            with _lock:
                stamp = datetime.date.today().isoformat()
                with open(os.path.join(INSIGHT_DIR, f"{self.month}.md"), "a", encoding="utf-8") as f:
                    f.write(f"## {stamp}\n")
                    if insight:
                        f.write(f"- {insight}\n")
                    for it in facts[:10]:
                        f.write(f"- via {it.get('topic','')}: {it.get('fact','')}\n")
                self._index["last_consolidated"] = total
                self._save_index()
        except Exception as e:
            _log(f"consolidate save error: {e}")

    # ---------------------------------------------------------------- stats

    def stats(self):
        topics = self._index.get("topics", {})
        fact_count = sum(int(t.get("count", 0)) for t in topics.values())
        insight_count = 0
        try:
            _mkdirs()
            insight_count = len([f for f in os.listdir(INSIGHT_DIR) if f.endswith(".md")])
        except Exception:
            pass
        return {
            "topics": len(topics),
            "facts": fact_count,
            "exchanges": int(self._index.get("exchanges", 0)),
            "insights": insight_count,
            "last_consolidated": int(self._index.get("last_consolidated", 0)),
        }