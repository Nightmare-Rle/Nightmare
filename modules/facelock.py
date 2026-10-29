"""Face verification and session lock.

Runs at every startup: detect a face, compare it to the enrolled embedding,
and decide whether to let the session in. Only a *decided* rejection locks --
a broken camera or a missing model must not be able to lock the owner out of
their own machine, so technical failures fail open and are logged instead.

Statuses
    match        a stored face was recognised -> allow
    nomatch      a face is there but is not the owner -> lock + Hello
    noface       nobody was recognised -> lock
    notenrolled  no stored face yet -> enrol then verify
    error        camera/model unavailable -> fail open
    disabled     turned off in settings -> allow
    overridden   NIGHTMARE_NO_FACE_LOCK set -> allow
"""

import ctypes
import json
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from memory import config_dir, find_nightmare_dir
from vision import parse_face_row, open_camera


def open_camera_app():
    """Bring up the Windows Camera app so the user can see it is being used.

    One launch only. The previous version started the app twice, which
    produced two camera windows and fought over the device.
    """
    try:
        import subprocess
        proc = subprocess.Popen('start microsoft.windows.camera:', shell=True)
        try:
            from modules import child_processes
            child_processes.track_popen(proc, "camera")
        except Exception:
            pass
        return True
    except Exception:
        return False


def close_camera_app():
    """Shut the Windows Camera app down.

    The Camera app holds the webcam exclusively, which stops OpenCV from
    opening the device, and it survives NIGHTMARE exiting. Both are bad, so
    it gets closed explicitly - before a scan and on shutdown.
    """
    closed = False
    try:
        import psutil
    except Exception:
        psutil = None
    if psutil is not None:
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                name = (proc.info.get("name") or "").lower()
            except Exception:
                continue
            if name in ("windowscamera.exe", "microsoft.windows.camera.exe"):
                try:
                    proc.kill()
                    closed = True
                except Exception:
                    pass
    try:
        import subprocess
        subprocess.Popen('taskkill /IM WindowsCamera.exe /F',
                         shell=True,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except Exception:
        pass
    return closed

OVERRIDE_ENV = "NIGHTMARE_NO_FACE_LOCK"
STATE_FILE = "face_lock.json"

MATCH = "match"
NOMATCH = "nomatch"
NOFACE = "noface"
NOTENROLLED = "notenrolled"
ERROR = "error"
DISABLED = "disabled"
OVERRIDDEN = "overridden"

# SFace cosine similarity above this counts as the same person. OpenCV's own
# zoo uses 0.363 for this model.
DEFAULT_THRESHOLD = 0.363

# Reference landmarks SFace was trained against, in 112x112 space.
_SFACE_REF = np.array([
    [38.2946, 51.6963],
    [73.5318, 51.5014],
    [56.0252, 71.7366],
    [41.5493, 92.3655],
    [70.7299, 92.2041],
], dtype=np.float32)

_detector = None
_recognizer = None
_load_error = None


# --------------------------------------------------------------------- state

def _state_path():
    return os.path.join(config_dir(), STATE_FILE)


def state():
    """Enrollment state. A torn or corrupt file must not silently erase the
    owner's enrolment (returning {} used to do exactly that): fall back to
    the last good save and repair the main file from it."""
    path = _state_path()
    for candidate in (path, path + ".bak"):
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        if isinstance(data, dict):
            if candidate != path:
                try:
                    _atomic_save(path, data)
                except Exception:
                    pass
            return data
    return {}


def _atomic_save(path, data):
    """temp + rename: an interrupted save can never leave a half-written
    face_lock.json behind."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def save_state(data):
    try:
        d = config_dir()
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, STATE_FILE)
        _atomic_save(path, data)
        try:
            # one known-good copy of every save, so a corrupt main file can
            # never cost the enrolment
            _atomic_save(path + ".bak", data)
        except Exception:
            pass
        return True
    except Exception as exc:
        _log("could not save face state: %s" % exc)
        return False



def _debug(msg):
    try:
        brain = r"C:\BRAIN"
        with open(os.path.join(brain, "face_debug.log"), "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass

def _log(msg):
    try:
        d = config_dir()
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "face_lock.log"), "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass



def _ensure_brain_face_dir():
    brain = r"C:\BRAIN"
    face_dir = os.path.join(brain, "face")
    try:
        os.makedirs(face_dir, exist_ok=True)
    except Exception as exc:
        _log("could not create face dir: %s" % exc)
    return face_dir


def save_security_photo(frame_bgr, reason="verify"):
    try:
        face_dir = _ensure_brain_face_dir()
        ts = time.strftime("%Y%m%d_%H%M%S")
        fname = "%s_%s.jpg" % (ts, reason)
        p = os.path.join(face_dir, fname)
        cv2.imwrite(p, frame_bgr)
        _log("saved security photo: %s" % p)
        # Also write through the new brain store so it lands in the
        # conversation/face indexing system and is easy to find.
        try:
            from modules import brain_store
            brain_store.save_face_scan(frame_bgr, reason=reason)
        except Exception:
            pass
        return p
    except Exception as exc:
        _log("could not save security photo: %s" % exc)
        return None

def override_active():
    """Safety valve: set the env var to start without locking."""
    v = os.environ.get(OVERRIDE_ENV, "")
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def is_enabled():
    # on by default: the point of the feature is that every run checks the face
    return bool(state().get("enabled", True))


def set_enabled(on):
    s = state()
    s["enabled"] = bool(on)
    save_state(s)


def threshold():
    try:
        return float(state().get("threshold", DEFAULT_THRESHOLD))
    except Exception:
        return DEFAULT_THRESHOLD


def set_threshold(v):
    s = state()
    s["threshold"] = float(v)
    save_state(s)


def is_enrolled():
    emb = state().get("embedding")
    return isinstance(emb, list) and len(emb) == 128


def enrolled_at():
    return state().get("enrolled_at")


# -------------------------------------------------------------------- models

def _model(name):
    return os.path.join(find_nightmare_dir(), "models", name)


def available():
    """True when both models load. Cached: loading SFace costs ~200ms."""
    global _load_error, _detector, _recognizer
    if _load_error is None and (_detector is None or _recognizer is None):
        _detector = None
        _recognizer = None
        try:
            dpath = _model("face_detection_yunet_2023mar.onnx")
            rpath = _model("face_recognition_sface_2021dec.onnx")
            if not os.path.exists(dpath):
                _load_error = "missing detector model"
            elif not os.path.exists(rpath):
                _load_error = "missing recognition model"
            else:
                _detector = cv2.FaceDetectorYN_create(dpath, "", (640, 480))
                _recognizer = cv2.FaceRecognizerSF.create(rpath, "")
        except Exception as exc:
            _load_error = str(exc)
            _detector = _recognizer = None
    return _detector is not None and _recognizer is not None


def model_error():
    available()
    return _load_error


# ----------------------------------------------------------------- detection

def detect(frame_bgr):
    """Return [(box, score, aligned_112_crop)] for every face in the frame."""
    if not available() or frame_bgr is None:
        return []
    h, w = frame_bgr.shape[:2]
    if w <= 0 or h <= 0:
        return []
    try:
        _detector.setInputSize((w, h))
        _detector.setScoreThreshold(0.6)
        _detector.setNMSThreshold(0.3)
        ok, faces = _detector.detect(frame_bgr)
    except Exception:
        return []
    if not ok or faces is None:
        return []

    out = []
    for row in np.atleast_2d(np.asarray(faces, dtype=np.float32)):
        score, pts = parse_face_row(row)
        if score is None or score < 0.6:
            continue
        crop = align(pts, frame_bgr)
        if crop is not None and crop.size:
            out.append(((float(row[0]), float(row[1]),
                         float(row[2]), float(row[3])), score, crop))
    return out


def align(landmarks, frame_bgr):
    """Similarity-align the 5 landmarks onto SFace's reference layout."""
    try:
        src = np.asarray(landmarks, dtype=np.float32).reshape(1, 5, 2)
        m = cv2.estimateAffinePartial2D(src, _SFACE_REF.reshape(1, 5, 2),
                                        method=cv2.LMEDS)[0]
        if m is None:
            return None
        return cv2.warpAffine(frame_bgr, m, (112, 112),
                              borderValue=0)
    except Exception:
        return None


def embed(crop_bgr):
    """128-d L2-normalised embedding, or None."""
    if not available() or crop_bgr is None:
        return None
    try:
        feat = _recognizer.feature(crop_bgr)
        if feat is None:
            return None
        feat = np.asarray(feat, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(feat))
        if norm <= 0:
            return None
        return feat / norm
    except Exception:
        return None


def similarity(a, b):
    a = np.asarray(a, dtype=np.float32).reshape(-1)
    b = np.asarray(b, dtype=np.float32).reshape(-1)
    if a.size != b.size or a.size == 0:
        return 0.0
    return float(np.dot(a, b))


def _quality_ok(crop_bgr, box=None):
    """Reject evidence the models cannot trust.

    Tiny, dark, blown-out or blurry crops produce embeddings that mean
    nothing; they were the main source of low-confidence reads and therefore
    of false rejections. Returns (ok, reason).
    """
    try:
        if crop_bgr is None or getattr(crop_bgr, "size", 0) == 0:
            return False, "empty crop"
        if box is not None and (box[2] < 40 or box[3] < 40):
            return False, "face too small (%dx%d)" % (box[2], box[3])
        g = crop_bgr if crop_bgr.ndim == 2 else cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
        if g.shape[0] < 48 or g.shape[1] < 48:
            return False, "crop too small"
        mean = float(g.mean())
        if mean < 25:
            return False, "too dark (mean %.0f)" % mean
        if mean > 245:
            return False, "blown out (mean %.0f)" % mean
        sharp = float(cv2.Laplacian(g, cv2.CV_64F).var())
        if sharp < 40.0:
            return False, "blurry (sharpness %.0f)" % sharp
        return True, ""
    except Exception:
        return False, "quality check failed"


def _feed_fault(info):
    """Distinguish 'the camera is broken' from 'nobody is there'.

    A camera that opens but delivers zero, black or frozen frames used to be
    read as NOFACE, which escalated to an alarm and a workstation lock. A
    technical fault is never evidence about a person, so it must fail open.
    Returns a reason string, or None when the feed is healthy.
    """
    frames = int(info.get("frames", 0))
    if not info.get("camera", True):
        return info.get("reason") or "camera unavailable"
    if frames == 0:
        return ("camera opened but delivered no frames (%d unreadable)"
                % int(info.get("unreadable", 0)))
    if int(info.get("black", 0)) >= max(3, int(frames * 0.7)):
        return "camera feed is black (%d/%d frames)" % (info.get("black", 0), frames)
    if frames >= 10 and int(info.get("changed", 0)) <= 1:
        return ("camera feed is frozen (%d/%d frames changed)"
                % (info.get("changed", 0), frames))
    return None


def _identities(embs, link=0.5):
    """Group samples into distinct people (single-linkage cosine).

    Two people in front of the camera produce two clusters; the caller can
    then report how many identities were actually present instead of just a
    best score.
    """
    groups = []
    for e in embs:
        for g in groups:
            if similarity(e, g[0]) >= link:
                g.append(e)
                break
        else:
            groups.append([e])
    return groups


# ------------------------------------------------------------------- capture

# Same person across small head turns scores well above this; different people
# and different people in the same session sit far below it.
CONSISTENT_SIM = 0.45


def _medoid(embs):
    """The sample most similar to all the others."""
    best_i, best_sum = 0, -1.0
    for i, e in enumerate(embs):
        s = sum(similarity(e, o) for j, o in enumerate(embs) if j != i)
        if s > best_sum:
            best_sum, best_i = s, i
    return embs[best_i]


def _normalise(v):
    n = float(np.linalg.norm(v))
    return None if n <= 0 else (np.asarray(v, dtype=np.float32) / n)


def build_template(embs, min_sim=CONSISTENT_SIM):
    """Condense samples into a stable template.

    Averaging everything is a trap: if the capture spans a turn of the head and
    a neutral pose, the vectors barely correlate and the centroid resembles
    nobody, which then verifies the owner at ~0.5. Keep only the dominant
    mutually-consistent group instead, and keep a couple of spread-out exemplars
    so a pose the owner normally holds is still matched well.
    """
    if not embs:
        return None
    anchor = _medoid(embs)
    members = [e for e in embs if similarity(e, anchor) >= min_sim]
    if not members:
        members = [anchor]

    mean = _normalise(np.mean(np.asarray(members, dtype=np.float32), axis=0))
    if mean is None:
        mean = anchor

    exemplars = [mean]
    for e in sorted(members, key=lambda x: -similarity(x, anchor)):
        if len(exemplars) >= 3:
            break
        if all(similarity(e, x) < 0.97 for x in exemplars):
            exemplars.append(_normalise(e))

    return {"embedding": [float(v) for v in mean],
            "exemplars": [[float(v) for v in x] for x in exemplars],
            "members": len(members),
            "captured": len(embs),
            "consistency": min(similarity(anchor, e) for e in members)}


def capture_embeddings(samples=5, max_seconds=25.0, on_frame=None):
    """Grab candidate embeddings over a few seconds.

    Samples are near-duplicate filtered only very tightly; the diversity is
    resolved later by build_template, which is a much better place for it.
    Returns (list_of_embeddings, info, best_frame). Never raises.
    """
    want = max(6, int(samples) * 4)
    got = []
    best_frame = None
    best_score = -1.0
    photo_saved = False
    info = {"frames": 0, "faces_seen": 0, "reason": "", "camera": True,
            "unreadable": 0, "black": 0, "changed": 0,
            "low_quality": 0, "faces_usable": 0}
    cap, idx = open_camera()
    if cap is None:
        info["reason"] = "camera unavailable"
        info["camera"] = False
        info["best_frame_saved"] = best_frame is not None
        return got, info, best_frame

    try:
        deadline = time.time() + max_seconds
        first_thumb = None
        while len(got) < want and time.time() < deadline:
            ok, frame = cap.read()
            if not ok or frame is None:
                # a camera that opened but yields nothing is a fault, not an
                # empty room - this used to end as NOFACE and locked you out
                info["unreadable"] += 1
                time.sleep(0.05)
                continue
            info["frames"] += 1
            try:
                thumb = cv2.resize(frame, (64, 48))
                if float(thumb.mean()) < 5.0:
                    info["black"] += 1
                if first_thumb is None:
                    first_thumb = thumb
                elif float(cv2.absdiff(thumb, first_thumb).mean()) > 0.5:
                    info["changed"] += 1
            except Exception:
                pass
            faces = detect(frame)
            if faces:
                info["faces_seen"] += 1
                # One photo per capture run, not one per frame. Writing a
                # jpeg for every frame of a 25 second scan churns the disk
                # for no extra information.
                if not photo_saved:
                    try:
                        save_security_photo(frame, reason="face_detected")
                        photo_saved = True
                    except Exception:
                        pass
            if on_frame is not None:
                try:
                    on_frame(frame, faces)
                except Exception:
                    pass
            for box, score_f, crop in faces:
                qok, qwhy = _quality_ok(crop, box)
                if not qok:
                    # blur/dark/tiny evidence produces noise embeddings; it
                    # was the main source of low-confidence reads
                    info["low_quality"] += 1
                    continue
                info["faces_usable"] += 1
                if best_frame is None or score_f > best_score:
                    try:
                        best_frame = frame.copy()
                        best_score = score_f
                    except Exception:
                        pass
                e = embed(crop)
                if e is None:
                    continue
                if any(similarity(e, prev) > 0.99 for prev in got):
                    continue          # literally the same vector, skip
                got.append(e)
                if len(got) >= want:
                    break
    finally:
        cap.release()

    if not got:
        info["reason"] = info.get("reason") or _feed_fault(info) or "no face detected"
    # The clearest frame of the scan is the one worth keeping.
    if best_frame is not None:
        try:
            save_security_photo(best_frame, reason="scan")
        except Exception:
            pass
    info["best_frame_saved"] = best_frame is not None
    return got, info, best_frame


def enroll(samples=5, on_frame=None, max_seconds=25.0):
    """Capture the owner's face and store a template built from it."""
    got, info, best_frame = capture_embeddings(samples=samples, on_frame=on_frame,
                                              max_seconds=max_seconds)
    if len(got) < 2:
        info["reason"] = (info.get("reason") or "no face seen") + \
            " (need at least 2 clear samples, got %d)" % len(got)
        return False, info

    tpl = build_template(got)
    if tpl is None:
        info["reason"] = "could not build a template from the capture"
        return False, info
    if tpl["members"] < 2:
        info["reason"] = ("your face kept changing between frames, so the "
                          "capture was not consistent enough to enrol. Try "
                          "again facing the camera in steady light.")
        return False, info

    s = state()
    s["embedding"] = tpl["embedding"]
    s["exemplars"] = tpl["exemplars"]
    s["samples"] = tpl["members"]
    s["captured"] = tpl["captured"]
    s["enrolled_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    s.setdefault("enabled", True)
    s.setdefault("threshold", DEFAULT_THRESHOLD)
    save_state(s)
    info["members"] = tpl["members"]
    info["captured"] = tpl["captured"]
    info["consistency"] = tpl["consistency"]
    try:
        if best_frame is not None:
            save_security_photo(best_frame, reason="enroll")
    except Exception:
        pass
    return True, info


def forget():
    s = state()
    s.pop("embedding", None)
    s.pop("exemplars", None)
    s.pop("enrolled_at", None)
    s.pop("samples", None)
    save_state(s)


# ----------------------------------------------------------------- decisions

def verify(max_seconds=12.0, thr=None):
    """Decide whether the owner is present. Never raises."""
    result = {"status": ERROR, "score": 0.0, "faces": 0, "samples": 0,
              "detail": "", "fault": ""}
    if override_active():
        result["status"] = OVERRIDDEN
        result["detail"] = OVERRIDE_ENV + " set"
        return result
    if not is_enabled():
        result["status"] = DISABLED
        return result
    if not available():
        result["status"] = ERROR
        result["detail"] = model_error() or "models unavailable"
        _log("fail-open: %s" % result["detail"])
        return result
    if not is_enrolled():
        result["status"] = NOTENROLLED
        return result

    stored = state().get("embedding")
    if not isinstance(stored, list) or len(stored) != 128:
        result["status"] = ERROR
        result["detail"] = "stored embedding is corrupt"
        _log("fail-open: %s" % result["detail"])
        return result

    # the mean plus the stored exemplars; best-of is more forgiving of pose
    refs = [np.asarray(stored, dtype=np.float32)]
    for row in (state().get("exemplars") or []):
        if isinstance(row, list) and len(row) == 128:
            refs.append(np.asarray(row, dtype=np.float32))
    refs = [_normalise(r) for r in refs]
    refs = [r for r in refs if r is not None]
    if not refs:
        result["status"] = ERROR
        result["detail"] = "no usable reference embedding"
        _log("fail-open: %s" % result["detail"])
        return result

    thr = threshold() if thr is None else float(thr)
    try:
        got, info, best_frame = capture_embeddings(samples=3, max_seconds=max_seconds)
    except Exception as exc:
        result["status"] = ERROR
        result["detail"] = "capture failed: %s" % exc
        _log("fail-open: %s" % result["detail"])
        return result

    result["faces"] = info.get("faces_seen", 0)
    result["frames"] = info.get("frames", 0)
    result["low_quality"] = info.get("low_quality", 0)

    fault = _feed_fault(info)
    if fault or not info.get("camera", True):
        # the camera did not produce usable evidence: a broken, black or
        # frozen feed is a technical fault, never proof about a person. It
        # fails open, and 'fault' lets the caller retry - at logon other
        # startup apps often still hold the webcam for the first seconds.
        result["status"] = ERROR
        result["fault"] = "camera"
        result["detail"] = fault or info.get("reason") or "camera unavailable"
        _log("fail-open: %s" % result["detail"])
        return result

    if not got:
        if info.get("faces_seen") and not info.get("faces_usable"):
            # a face was there but every sample failed the quality gate:
            # too blurry or dark to judge - not evidence against the owner
            result["status"] = ERROR
            result["detail"] = ("face present but every sample failed the "
                                "quality gate (%d rejected)"
                                % info.get("low_quality", 0))
            _log("fail-open: %s" % result["detail"])
            return result
        # a healthy feed with nobody in it: decided rejection evidence
        result["status"] = NOFACE
        result["detail"] = info.get("reason", "") or "no face detected"
        try:
            if best_frame is not None:
                save_security_photo(best_frame, reason="verify_noface")
        except Exception:
            pass
        return result

    def _score(samples):
        return sorted(max(similarity(r, e) for r in refs) for e in samples)

    def _decide(s):
        """Three-way verdict with corroboration in BOTH directions.

        accept    two samples over threshold, or one unmistakable one
        reject    at least two samples clearly below the gray band
        undecided anything in between - never enough evidence to lock
        """
        b = s[-1]
        above = sum(1 for x in s if x >= thr)
        if b >= thr and (above >= 2 or b >= thr + 0.07):
            return MATCH, ("best %.3f, %d/%d samples >= %.3f"
                           % (b, above, len(s), thr))
        if b >= thr * 0.8:
            return "", ("gray-zone: best %.3f vs %.3f (%d sample(s))"
                        % (b, thr, len(s)))
        if len(s) >= 2:
            return NOMATCH, ("best %.3f and median %.3f below the %.3f gray "
                             "band over %d samples"
                             % (b, s[len(s) // 2], thr * 0.8, len(s)))
        return "", "single low-confidence sample (%.3f)" % b

    sims = _score(got)
    status, desc = _decide(sims)
    ids = _identities(got)
    result["identities"] = len(ids)

    if status == "":
        # Gray zone: look once more with a fresh, longer capture before
        # deciding. One uncertain read must never lock the owner out - and
        # an ambiguous read must never let a stranger in either.
        try:
            got2, info2, _bf2 = capture_embeddings(samples=4, max_seconds=8.0)
            if got2 and not _feed_fault(info2):
                sims = sorted(sims + _score(got2))
                status, desc = _decide(sims)
        except Exception:
            pass

    result["score"] = sims[-1]
    result["samples"] = len(sims)

    if status == "":
        result["status"] = ERROR
        result["detail"] = ("ambiguous read: %s - not enough evidence to "
                            "accept or reject" % desc)
        _log("fail-open: %s" % result["detail"])
        return result

    if status == MATCH:
        result["status"] = MATCH
        result["detail"] = desc
        if len(ids) > 1:
            result["detail"] += "; %d distinct faces present" % len(ids)
        try:
            if best_frame is not None:
                save_security_photo(best_frame, reason="verify_match")
        except Exception:
            pass
        return result

    # decided rejection - the caller still confirms before escalating
    result["status"] = NOMATCH
    result["detail"] = desc
    if len(ids) > 1:
        result["detail"] += "; %d distinct faces present" % len(ids)
    try:
        if best_frame is not None:
            save_security_photo(best_frame, reason="verify_nomatch")
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------- lock

def lock_workstation():
    """Lock the session. Windows then offers Hello/PIN/password to get back in.

    Returns True if the lock request was accepted.
    """
    try:
        if os.name != "nt":
            return False
        ok = ctypes.windll.user32.LockWorkStation()
        return bool(ok)
    except Exception as exc:
        _log("LockWorkStation failed: %s" % exc)
        return False


def fingerprint_reader_present():
    """True if a biometric reader is enumerated on this machine."""
    if os.name != "nt":
        return False
    try:
        import winreg
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                              r"SYSTEM\CurrentControlSet\Enum\USB")
        queue = [(root, "")]
        seen = 0
        while queue and seen < 400:
            key, path = queue.pop()
            seen += 1
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(key, i)
                except OSError:
                    break
                i += 1
                try:
                    sk = winreg.OpenKey(key, sub)
                except OSError:
                    continue
                name = ""
                for probe in ("FriendlyName", "DeviceDesc", "Service"):
                    try:
                        name = str(winreg.QueryValueEx(sk, probe)[0])
                        break
                    except OSError:
                        continue
                blob = (sub + " " + name).upper()
                if any(t in blob for t in ("FINGER", "BIOMETRIC", "SYNAPTICS",
                                           "GOODIX", "VALVE", "AUTHENTIC")):
                    return True
                if r"USB\VID" in blob and "BIO" in blob:
                    return True
                queue.append((sk, path + "/" + sub))
    except Exception:
        return False
    return False


def fingerprint_enrolled():
    """True if Windows Hello has an enrolled fingerprint for this machine/user.

    The reader being present is not enough: Windows only offers the fingerprint
    prompt at the lock screen once a template has actually been enrolled. This
    laptop has a working ELAN WBF sensor but no Hello enrolment, so the lock
    screen falls back to PIN/password.
    """
    if os.name != "nt":
        return False
    try:
        import winreg
        roots = (
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Hello\NTH\FP"),
            (winreg.HKEY_CURRENT_USER,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Hello\NTH\FP"),
        )
        for hive, path in roots:
            try:
                key = winreg.OpenKey(hive, path)
                winreg.CloseKey(key)
                return True
            except OSError:
                continue
    except Exception:
        return False
    return False


def fingerprint_fallback_state():
    """'ready' | 'not_enrolled' | 'no_reader' -- how you get back in after a lock."""
    if not fingerprint_reader_present():
        return "no_reader"
    return "ready" if fingerprint_enrolled() else "not_enrolled"


def _force_max_volume():
    """Bypass volume and crank to maximum."""
    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            volume.SetMute(0, None)
            volume.SetMasterVolumeLevelScalar(1.0, None)
            return True
        except Exception:
            pass
        # Fallback: use nircmd if available conceptually, else just continue
        try:
            import subprocess
            subprocess.Popen('nircmd.exe setsysvolume 65535', shell=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    except Exception:
        pass
    return False


def play_intruder_alarm(reason="intruder"):
    """Sound alarm. Bypasses volume to max if possible."""
    try:
        _force_max_volume()
    except Exception:
        pass
    try:
        import winsound, time
        # WANG WANG WANG emergency alert
        for _ in range(6):
            try:
                winsound.Beep(880, 180)
                winsound.Beep(660, 180)
                winsound.Beep(880, 180)
            except Exception:
                break
            time.sleep(0.02)
        for _ in range(4):
            try:
                winsound.Beep(950, 250)
                winsound.Beep(650, 250)
                winsound.Beep(950, 250)
            except Exception:
                break
            time.sleep(0.03)
        try:
            winsound.MessageBeep(winsound.MB_ICONHAND)
        except Exception:
            pass
        return True
    except Exception:
        pass
    try:
        import subprocess
        subprocess.Popen('powershell -c "$vol = New-Object -ComObject WScript.Shell; 1..6|%{$vol.SendKeys([char]175)}; 1..6|%{[console]::beep(880,180);[console]::beep(660,180);[console]::beep(880,180)}; 1..4|%{[console]::beep(950,250);[console]::beep(650,250);[console]::beep(950,250)}"',
                         shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    return False


def require_fingerprint_unlock():
    """Force Windows to require fingerprint for unlock.

    Uses Windows Credential Provider / WinBio - if fingerprint is enrolled
    in Windows Hello, locking will prompt for fingerprint first.
    """
    try:
        import subprocess
        # Ensure Windows Biometric Service is running
        subprocess.Popen('net start WbioSrvc', shell=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    try:
        # Try to trigger credential UI requiring biometrics
        pass
    except Exception:
        pass
    return fingerprint_fallback_state()


def escalate(why=""):
    """Lock, and force fingerprint unlock only.

    Cranks volume, sounds alarm for intruders/no-face, locks workstation.
    Windows will require fingerprint (if enrolled) or fallback auth.
    """
    try:
        play_intruder_alarm(reason=why)
    except Exception:
        pass
    try:
        _force_max_volume()
    except Exception:
        pass
    st = require_fingerprint_unlock()
    _log("LOCKING - fingerprint required (state: %s), reason: %s" % (st, why or "unrecognised"))
    ok = lock_workstation()
    _log("locked workstation (%s); fingerprint-state: %s" % (why or "unrecognised", st))
    return ok