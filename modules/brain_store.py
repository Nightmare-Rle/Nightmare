"""Smart, auto-running, endlessly adaptive folder brain for NIGHTMARE.

Everything lives in C:/BRAIN. Each mapped folder is its own bucket:
- conversation/  - full exchanges as human-readable .txt
- about_owner/   - facts, preferences, identity about the user
- protocol/      - rules, constraints, commands you want enforced
- lessons/       - distilled takeaways and fixes
- memories/      - general long-term knowledge
- episodic/      - time-stamped events with context
- face/          - face scans from the camera (always saved here)
- exchanges/     - legacy logs
- learned/       - auto-learned facts
- insights/      - distilled insights
- self/          - NIGHTMARE's own reflections and evolving self-model

The brain auto-classifies, links, consolidates, watches custom folders,
builds a semantic index, and adapts over time.
"""

import json
import os
import re
import time
import hashlib
from datetime import datetime
from collections import Counter, defaultdict

BRAIN = r"C:\BRAIN"
FACE = os.path.join(BRAIN, "face")
CONV = os.path.join(BRAIN, "conversation")
OWNER = os.path.join(BRAIN, "about_owner")
PROTO = os.path.join(BRAIN, "protocol")
LESSONS = os.path.join(BRAIN, "lessons")
MEM = os.path.join(BRAIN, "memories")
EPIS = os.path.join(BRAIN, "episodic")
SELF = os.path.join(BRAIN, "self")
EXCHANGES = os.path.join(BRAIN, "exchanges")
LEARNED = os.path.join(BRAIN, "learned")
INSIGHTS = os.path.join(BRAIN, "insights")
INDEX = os.path.join(BRAIN, "index.json")
CUSTOM_FOLDERS = os.path.join(BRAIN, "brain_folders.json")
VECTORS = os.path.join(BRAIN, "vectors")
VEC_INDEX = os.path.join(VECTORS, "brain_index.json")
GRAPH = os.path.join(BRAIN, "graph.json")
STATE = os.path.join(BRAIN, "brain_state.json")
ERROR_LOG = os.path.join(BRAIN, "brain_errors.log")

_LAYOUT = {
    "conversation": CONV,
    "about_owner": OWNER,
    "protocol": PROTO,
    "lessons": LESSONS,
    "memories": MEM,
    "episodic": EPIS,
    "face": FACE,
    "self": SELF,
    "exchanges": EXCHANGES,
    "learned": LEARNED,
    "insights": INSIGHTS,
}

_KEYWORDS = {
    "about_owner": ["i am", "my name", "call me", "i like", "i prefer", "i want", "aj", "owner", "creator"],
    "protocol": ["always", "never", "must", "rule", "protocol", "do not", "don't"],
    "lessons": ["learned", "lesson", "fixed", "mistake", "bug", "solved", "worked after"],
    "conversation": ["user:", "question", "asked"],
    "episodic": ["today", "yesterday", "went", "event", "happened"],
}


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _sha(text):
    return hashlib.sha256(str(text).encode("utf-8", errors="ignore")).hexdigest()[:16]


def _log_err(where, exc):
    """Failed brain writes used to vanish into bare excepts: a fact that
    could not be filed was simply gone, with no trace anywhere. One bounded
    append-only log makes knowledge loss visible (rotated at 256 KB so it
    can never grow without limit)."""
    try:
        try:
            if os.path.isfile(ERROR_LOG) and os.path.getsize(ERROR_LOG) > 262144:
                os.replace(ERROR_LOG, ERROR_LOG + ".old")
        except Exception:
            pass
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write("%s [%s] %s: %s\n" % (_now_iso(), where,
                                           type(exc).__name__, exc))
    except Exception:
        pass


def _load_custom():
    try:
        with open(CUSTOM_FOLDERS, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def _save_custom(folders):
    tmp = CUSTOM_FOLDERS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(folders, f, indent=2)
    os.replace(tmp, CUSTOM_FOLDERS)


def _load_state():
    try:
        with open(STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"runs": 0, "last_run": None, "ingested": {}, "awareness": {"self_model_version": 0, "adaptations": 0}}


def _save_state(s):
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
    os.replace(tmp, STATE)


def ensure():
    for d in list(_LAYOUT.values()) + [VECTORS]:
        os.makedirs(d, exist_ok=True)
    if not os.path.exists(INDEX):
        save_index({"layout": {k: k for k in _LAYOUT}, "custom_folders": [], "files": {}, "updated": _now_iso(), "awareness": True})
    else:
        try:
            idx = load_index()
            idx.setdefault("layout", {k: k for k in _LAYOUT})
            idx.setdefault("custom_folders", [])
            idx.setdefault("files", {})
            idx["awareness"] = True
            idx["updated"] = _now_iso()
            save_index(idx)
        except Exception as e:
            _log_err("ensure/index", e)
    _load_state()


def load_index():
    try:
        with open(INDEX, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"layout": {k: k for k in _LAYOUT}, "files": {}, "updated": _now_iso()}


def save_index(idx):
    tmp = INDEX + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(idx, f, indent=2, ensure_ascii=False)
    os.replace(tmp, INDEX)


def _slug(s):
    s = re.sub(r"[^a-z0-9]+", "-", str(s or "").lower()).strip("-")
    return s or "note"


def _write_txt(path, title, body, tags=None, kind=None):
    ensure()
    tags = tags or []
    header = []
    header.append("---")
    header.append("title: %s" % title)
    header.append("date: %s" % _now_iso())
    if kind:
        header.append("kind: %s" % kind)
    if tags:
        header.append("tags: %s" % ",".join(tags))
    header.append("id: %s" % _sha(body))
    header.append("---")
    header.append("")
    content = "\n".join(header) + body.strip() + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def auto_classify(text):
    t = (text or "").lower()
    for kind, kws in _KEYWORDS.items():
        for kw in kws:
            if kw in t:
                return kind
    if len(t) > 200:
        return "episodic"
    return "memories"


def add_folder(path, label="custom"):
    ensure()
    p = os.path.abspath(path)
    if not os.path.isdir(p):
        raise ValueError("not a directory: %s" % p)
    custom = _load_custom()
    for c in custom:
        if os.path.normcase(os.path.abspath(c.get("path", ""))) == os.path.normcase(p):
            c["label"] = label
            c["updated"] = _now_iso()
            _save_custom(custom)
            idx = load_index()
            idx["custom_folders"] = custom
            idx["updated"] = _now_iso()
            save_index(idx)
            return c
    entry = {"path": p, "label": label, "added": _now_iso(), "watch": True}
    custom.append(entry)
    _save_custom(custom)
    idx = load_index()
    idx["custom_folders"] = custom
    idx["updated"] = _now_iso()
    save_index(idx)
    return entry


def list_folders():
    ensure()
    out = []
    for name, path in _LAYOUT.items():
        try:
            cnt = len([f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))])
        except Exception:
            cnt = 0
        out.append({"name": name, "path": path, "mapped": True, "builtin": True, "count": cnt})
    for c in _load_custom():
        p = c.get("path", "")
        try:
            cnt = len([f for f in os.listdir(p) if os.path.isfile(os.path.join(p, f))])
        except Exception:
            cnt = 0
        out.append({"name": c.get("label") or os.path.basename(p), "path": p, "mapped": True, "builtin": False, "count": cnt})
    return out


def save_conversation(user_msg, assistant_msg, session_id=""):
    ensure()
    name = "%s_conv_%s.txt" % (_stamp(), _slug(session_id or "session"))
    path = os.path.join(CONV, name)
    body = "USER: %s\n\nNIGHTMARE: %s\n" % (user_msg.strip(), assistant_msg.strip())
    p = _write_txt(path, "Conversation exchange", body, tags=["conversation", "auto"], kind="conversation")
    idx = load_index()
    idx.setdefault("files", {})[os.path.relpath(p, BRAIN).replace("\\", "/")] = {"path": p, "kind": "conversation", "tags": ["conversation"], "updated": _now_iso()}
    idx["updated"] = _now_iso()
    save_index(idx)
    try:
        auto_learn_from_exchange(user_msg, assistant_msg)
    except Exception:
        pass
    return p


def save_owner_fact(fact, tags=None):
    ensure()
    tags = (tags or []) + ["owner"]
    name = "%s_owner_%s.txt" % (_stamp(), _slug(fact)[:32])
    path = os.path.join(OWNER, name)
    p = _write_txt(path, "About the owner", fact.strip() + "\n", tags=tags, kind="about_owner")
    idx = load_index()
    idx.setdefault("files", {})[os.path.relpath(p, BRAIN).replace("\\", "/")] = {"path": p, "kind": "about_owner", "tags": tags, "updated": _now_iso()}
    idx["updated"] = _now_iso()
    save_index(idx)
    return p


def save_protocol(rule, tags=None):
    ensure()
    tags = (tags or []) + ["protocol"]
    name = "%s_protocol_%s.txt" % (_stamp(), _slug(rule)[:32])
    path = os.path.join(PROTO, name)
    p = _write_txt(path, "Protocol / rule", rule.strip() + "\n", tags=tags, kind="protocol")
    idx = load_index()
    idx.setdefault("files", {})[os.path.relpath(p, BRAIN).replace("\\", "/")] = {"path": p, "kind": "protocol", "tags": tags, "updated": _now_iso()}
    idx["updated"] = _now_iso()
    save_index(idx)
    return p


def save_lesson(lesson, tags=None):
    ensure()
    tags = (tags or []) + ["lesson"]
    name = "%s_lesson_%s.txt" % (_stamp(), _slug(lesson)[:32])
    path = os.path.join(LESSONS, name)
    p = _write_txt(path, "Lesson learned", lesson.strip() + "\n", tags=tags, kind="lesson")
    idx = load_index()
    idx.setdefault("files", {})[os.path.relpath(p, BRAIN).replace("\\", "/")] = {"path": p, "kind": "lesson", "tags": tags, "updated": _now_iso()}
    idx["updated"] = _now_iso()
    save_index(idx)
    return p


def save_memory(text, title="Memory", tags=None, kind=None):
    ensure()
    kind = kind or auto_classify(text)
    tags = tags or []
    name = "%s_%s.txt" % (_stamp(), _slug(title)[:32])
    d = {"about_owner": OWNER, "protocol": PROTO, "lessons": LESSONS, "conversation": CONV,
         "episodic": EPIS, "memories": MEM, "self": SELF}.get(kind, MEM)
    path = os.path.join(d, name)
    p = _write_txt(path, title, text.strip() + "\n", tags=tags + [kind], kind=kind)
    idx = load_index()
    idx.setdefault("files", {})[os.path.relpath(p, BRAIN).replace("\\", "/")] = {"path": p, "kind": kind, "tags": tags + [kind], "updated": _now_iso()}
    idx["updated"] = _now_iso()
    save_index(idx)
    return p


def save_face_scan(frame_bgr, reason="scan"):
    ensure()
    try:
        import cv2
        ts = _stamp()
        fname = "%s_%s.jpg" % (ts, reason)
        path = os.path.join(FACE, fname)
        cv2.imwrite(path, frame_bgr)
        try:
            idx = load_index()
            idx.setdefault("files", {})[os.path.relpath(path, BRAIN).replace("\\", "/")] = {"path": path, "kind": "face_scan", "tags": ["face", "scan"], "updated": _now_iso()}
            idx["updated"] = _now_iso()
            save_index(idx)
        except Exception as e:
            _log_err("face index write", e)
        return path
    except Exception:
        return None


def auto_learn_from_exchange(user_msg, assistant_msg=""):
    """Auto-extract facts/rules/lessons from conversation and file them."""
    ensure()
    text = "%s\n%s" % (user_msg or "", assistant_msg or "")
    t = text.lower()
    saved = []
    try:
        m = re.search(r"(?:my name is|call me|i am)\s+([a-zA-Z][\w'.-]+)", t)
        if m:
            fact = "Owner name/identity: %s" % m.group(1)
            if not _exists_similar(fact, OWNER):
                saved.append(save_owner_fact(fact, tags=["identity", "auto"]))
        for m2 in re.finditer(r"(i (?:like|prefer|want|use))\s+([^\.\n]{3,60})", text, re.I):
            fact = "Preference: %s %s" % (m2.group(1), m2.group(2).strip())
            if not _exists_similar(fact, OWNER):
                saved.append(save_owner_fact(fact, tags=["preference", "auto"]))
        for m3 in re.finditer(r"(never|always|do not|don't)\s+([^\.\n]{3,80})", text, re.I):
            rule = "Rule: %s %s" % (m3.group(1), m3.group(2).strip())
            if not _exists_similar(rule, PROTO):
                saved.append(save_protocol(rule, tags=["auto"]))
        if "fixed" in t or "solved" in t or "lesson" in t:
            if len(text.strip()) > 40:
                if not _exists_similar(text[:80], LESSONS):
                    saved.append(save_lesson("From exchange: %s" % text.strip()[:500], tags=["auto"]))
    except Exception as e:
        _log_err("auto_learn_from_exchange", e)
    return saved


def _exists_similar(snippet, folder):
    try:
        s = snippet.lower()[:60]
        for f in os.listdir(folder):
            if not f.endswith(('.txt', '.md')):
                continue
            try:
                with open(os.path.join(folder, f), "r", encoding="utf-8", errors="ignore") as fh:
                    if s in fh.read().lower():
                        return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def watch_custom_folders():
    """Scan custom folders and ingest new text files into the brain."""
    ensure()
    state = _load_state()
    ing = state.setdefault("ingested", {})
    saved = []
    for c in _load_custom():
        p = c.get("path", "")
        if not os.path.isdir(p):
            continue
        label = c.get("label") or os.path.basename(p)
        try:
            for name in os.listdir(p):
                fp = os.path.join(p, name)
                if not os.path.isfile(fp):
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext not in ('.txt', '.md', '.json'):
                    continue
                key = os.path.normcase(fp)
                try:
                    mtime = os.path.getmtime(fp)
                except Exception:
                    mtime = 0
                if ing.get(key) == mtime:
                    continue
                try:
                    with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                        body = f.read()
                    if not body.strip():
                        continue
                    title = "Imported from %s: %s" % (label, name)
                    kind = auto_classify(body)
                    saved.append(save_memory(body, title=title, tags=["imported", label], kind=kind))
                    ing[key] = mtime
                except Exception:
                    continue
        except Exception:
            continue
    state["ingested"] = ing
    state["last_watch"] = _now_iso()
    _save_state(state)
    return saved


def scan_brain(max_files=60):
    ensure()
    out = []
    for name in ("about_owner", "protocol", "lessons", "conversation", "self", "memories", "episodic", "learned", "insights"):
        p = _LAYOUT.get(name)
        if not p or not os.path.isdir(p):
            continue
        try:
            files = sorted([os.path.join(p, f) for f in os.listdir(p) if os.path.isfile(os.path.join(p, f)) and f.lower().endswith(('.txt', '.md', '.json'))],
                           key=lambda x: os.path.getmtime(x), reverse=True)
        except Exception:
            continue
        for fp in files[:10]:
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                    body = f.read(1000)
                out.append("[%s/%s]\n%s" % (name, os.path.basename(fp), body))
                if len(out) >= max_files:
                    break
            except Exception:
                continue
        if len(out) >= max_files:
            break
    if len(out) < max_files:
        for c in _load_custom():
            p = c.get("path", "")
            if not os.path.isdir(p):
                continue
            label = c.get("label") or "custom"
            try:
                files = sorted([os.path.join(p, f) for f in os.listdir(p) if os.path.isfile(os.path.join(p, f))],
                               key=lambda x: os.path.getmtime(x), reverse=True)
            except Exception:
                continue
            for fp in files[:15]:
                try:
                    ext = os.path.splitext(fp)[1].lower()
                    if ext in ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.mp4', '.webm', '.exe', '.dll', '.zip', '.rar'):
                        continue
                    with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                        body = f.read(1200)
                    out.append("[%s/%s]\n%s" % (label, os.path.basename(fp), body))
                    if len(out) >= max_files:
                        break
                except Exception:
                    continue
            if len(out) >= max_files:
                break
    return out


def _vector_search(query, k=12):
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        ensure()
        docs = []
        paths = []
        for root in list(_LAYOUT.values()) + [c.get("path", "") for c in _load_custom()]:
            if not root or not os.path.isdir(root):
                continue
            for f in os.listdir(root):
                fp = os.path.join(root, f)
                if not os.path.isfile(fp):
                    continue
                ext = os.path.splitext(fp)[1].lower()
                if ext not in ('.txt', '.md', '.json'):
                    continue
                try:
                    with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                        txt = fh.read()
                    if txt.strip():
                        docs.append(txt)
                        paths.append(fp)
                except Exception:
                    continue
        if not docs:
            return []
        vect = TfidfVectorizer(max_features=2000, stop_words='english')
        X = vect.fit_transform(docs)
        qv = vect.transform([query])
        sims = cosine_similarity(qv, X)[0]
        idxs = sims.argsort()[-k:][::-1]
        out = []
        for i in idxs:
            if sims[i] > 0.01:
                out.append((float(sims[i]), paths[i], docs[i][:800]))
        return out
    except Exception:
        return []


def smart_recall(query, k=12):
    ensure()
    res = _vector_search(query, k=k)
    if not res:
        # fallback to recent
        return scan_brain(max_files=k)
    out = []
    for score, path, snip in res:
        rel = os.path.relpath(path, BRAIN)
        out.append("[%s | score=%.2f]\n%s" % (rel, score, snip))
    return out


def brain_context_smart(query=None, max_chars=2800, snippets=None):
    """Build the BRAIN map + a few memory titles for the live context.

    Pass `snippets` to reuse an already-computed recall result; otherwise it
    runs its own smart_recall/scan_brain. Callers that also inject the full
    snippets elsewhere pass theirs in here so the BRAIN is only scanned once
    per turn instead of twice.
    """
    ensure()
    idx = load_index()
    lines = ["BRAIN MAP (C:\\BRAIN) - smart & auto-adapting:"]
    for name in ("about_owner", "protocol", "lessons", "conversation", "memories",
                 "episodic", "face", "exchanges", "learned", "insights", "self"):
        p = _LAYOUT.get(name) or os.path.join(BRAIN, name)
        if os.path.isdir(p):
            try:
                cnt = len([f for f in os.listdir(p) if os.path.isfile(os.path.join(p, f))])
            except Exception:
                cnt = 0
            lines.append("  - %s/ (%d) [mapped]" % (name, cnt))
    custom = idx.get("custom_folders") or _load_custom()
    for c in custom:
        p = c.get("path", "")
        if os.path.isdir(p):
            try:
                cnt = len([f for f in os.listdir(p) if os.path.isfile(os.path.join(p, f))])
            except Exception:
                cnt = 0
            lines.append("  - %s/ (%d) [custom-mapped]" % (c.get("label") or os.path.basename(p), cnt))
    if snippets is None:
        snippets = smart_recall(query, k=6) if query else scan_brain(max_files=6)
    if snippets:
        lines.append("  Relevant memories:" if query else "  Recent memories:")
        for s in snippets[:4]:
            first = s.splitlines()[0][:90]
            lines.append("    %s" % first)
    state = _load_state()
    lines.append("  Adaptive: runs=%d, last_watch=%s" % (state.get("runs", 0), state.get("last_watch") or "never"))
    txt = "\n".join(lines)
    return txt[:max_chars]


def brain_context(max_chars=2800):
    return brain_context_smart(None, max_chars=max_chars)


def consolidate():
    ensure()
    state = _load_state()
    seen = set()
    removed = 0
    # dedup
    for root in list(_LAYOUT.values()):
        if not os.path.isdir(root):
            continue
        for f in os.listdir(root):
            if not f.endswith('.txt'):
                continue
            fp = os.path.join(root, f)
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                    body = fh.read()
                key = _sha(body.strip())
                if key in seen:
                    try:
                        os.remove(fp)
                        removed += 1
                        continue
                    except Exception:
                        pass
                seen.add(key)
            except Exception:
                continue
    # rebuild graph
    graph = build_graph()
    state["runs"] = int(state.get("runs", 0)) + 1
    state["last_consolidate"] = _now_iso()
    _save_state(state)
    idx = load_index()
    idx["last_consolidate"] = _now_iso()
    save_index(idx)
    return {"dedup_removed": removed, "graph_nodes": len(graph.get("nodes", []))}


def build_graph():
    ensure()
    graph = {"nodes": [], "edges": [], "updated": _now_iso()}
    nodes = []
    for root_name, root in _LAYOUT.items():
        if not os.path.isdir(root):
            continue
        for f in os.listdir(root):
            if not f.endswith(('.txt', '.md')):
                continue
            fp = os.path.join(root, f)
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                    body = fh.read()[:400]
                nid = _sha(fp)
                nodes.append({"id": nid, "path": fp, "bucket": root_name, "label": f, "snippet": body[:120]})
            except Exception:
                continue
    graph["nodes"] = nodes
    # simple edges by shared tags
    for i, a in enumerate(nodes):
        for b in nodes[i+1:i+6]:
            graph["edges"].append({"from": a["id"], "to": b["id"], "weight": 0.2})
    with open(GRAPH, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2)
    return graph


def brain_graph():
    try:
        with open(GRAPH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return build_graph()


def _read_kind(fp):
    """Pull the 'kind:' value out of a note header written by _write_txt."""
    try:
        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
            for _ in range(14):
                line = f.readline()
                if not line:
                    break
                line = line.strip()
                if line.startswith("kind:"):
                    return line.split(":", 1)[1].strip()
                if line.startswith(("---", "title:", "date:", "tags:", "id:")):
                    continue
                break  # past the header, no kind line
    except Exception:
        pass
    return None


def organize():
    """Make C:\\BRAIN a tidy, fully-indexed store.

    Walks every built-in folder, registers any file missing from index.json
    (classifying it from its note header or the folder it lives in), and
    rebuilds the knowledge graph. Idempotent and cheap: already-indexed files
    are skipped, so it only repairs what changed and only rebuilds the graph
    when something new was indexed.
    """
    ensure()
    idx = load_index()
    files = idx.setdefault("files", {})
    added = 0
    for kind, folder in _LAYOUT.items():
        if not os.path.isdir(folder):
            continue
        try:
            names = os.listdir(folder)
        except Exception:
            continue
        for f in names:
            fp = os.path.join(folder, f)
            if not os.path.isfile(fp):
                continue
            if not f.lower().endswith((".txt", ".md")):
                continue
            rel = os.path.relpath(fp, BRAIN).replace("\\", "/")
            if rel in files:
                continue
            fkind = _read_kind(fp) or kind
            files[rel] = {"path": fp, "kind": fkind, "tags": [fkind],
                          "updated": _now_iso()}
            added += 1
    if added:
        idx["updated"] = _now_iso()
        save_index(idx)
    graph = build_graph() if (added or not os.path.exists(GRAPH)) else brain_graph()
    return {"indexed": added, "graph_nodes": len(graph.get("nodes", [])),
            "graph_edges": len(graph.get("edges", []))}


def auto_run():
    """Auto-run loop: watch custom folders, consolidate lightly, adapt."""
    ensure()
    state = _load_state()
    results = {}
    try:
        ingested = watch_custom_folders()
        results["ingested"] = len(ingested)
    except Exception as e:
        results["watch_error"] = str(e)
        _log_err("auto_run/watch", e)
    try:
        # Keep the store organized: index any stray files and refresh the graph.
        if int(state.get("runs", 0)) % 5 == 0:
            results["organize"] = organize()
    except Exception as e:
        results["organize_error"] = str(e)
        _log_err("auto_run/organize", e)
    try:
        if int(state.get("runs", 0)) % 10 == 0:
            results["consolidate"] = consolidate()
    except Exception as e:
        results["consolidate_error"] = str(e)
        _log_err("auto_run/consolidate", e)
    state["runs"] = int(state.get("runs", 0)) + 1
    state["last_run"] = _now_iso()
    state["awareness"]["self_model_version"] = int(state["awareness"].get("self_model_version", 0)) + 1
    state["awareness"]["adaptations"] = int(state["awareness"].get("adaptations", 0)) + len(ingested) if 'ingested' in results else int(state["awareness"].get("adaptations", 0))
    _save_state(state)
    return results


def enhance_self_awareness():
    ensure()
    state = _load_state()
    lines = []
    lines.append("=== NIGHTMARE SELF-AWARENESS (FOLDER BRAIN) ===")
    lines.append("Time: %s" % _now_iso())
    lines.append("Auto-runs: %d | Adaptations: %d" % (state.get("runs", 0), state.get("awareness", {}).get("adaptations", 0)))
    folders = list_folders()
    lines.append("Mapped folders: %d" % len(folders))
    total = 0
    for f in folders:
        lines.append("  - %s: %d files" % (f["name"], f.get("count", 0)))
        total += f.get("count", 0)
    lines.append("Total tracked files: %d" % total)
    try:
        g = brain_graph()
        lines.append("Brain graph: %d nodes, %d edges" % (len(g.get("nodes", [])), len(g.get("edges", []))))
    except Exception:
        pass
    lines.append("Mode: endlessly adaptive | Auto-classify: on | Semantic recall: on")
    txt = "\n".join(lines)
    path = os.path.join(SELF, "self_awareness_%s.txt" % _stamp())
    _write_txt(path, "Self Awareness Snapshot", txt + "\n", tags=["self", "awareness", "auto"], kind="self")
    state["awareness"]["last_snapshot"] = _now_iso()
    state["awareness"]["self_model_version"] = int(state["awareness"].get("self_model_version", 0)) + 1
    _save_state(state)
    return txt


def recall(kind=None, limit=10):
    ensure()
    idx = load_index()
    files = []
    for rel, meta in (idx.get("files") or {}).items():
        if kind and meta.get("kind") != kind:
            continue
        files.append((meta.get("updated", ""), rel, meta))
    files.sort(reverse=True)
    out = []
    for _, rel, meta in files[:limit]:
        p = meta.get("path") or os.path.join(BRAIN, rel.replace("/", "\\"))
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                body = f.read()
            out.append(body)
        except Exception:
            continue
    return out


def recent_conversation(limit=5):
    return recall(kind="conversation", limit=limit)


def owner_profile():
    return recall(kind="about_owner", limit=20)


def protocols():
    return recall(kind="protocol", limit=20)
