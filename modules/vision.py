import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from memory import find_nightmare_dir

_detector_cache = {}
_recognizer_cache = {}

# Order matters: the default backend picked this machine's camera and actually
# delivered frames, while CAP_DSHOW only warned and produced nothing useful.
_CAM_BACKENDS = (cv2.CAP_ANY, cv2.CAP_MSMF, cv2.CAP_DSHOW)
_last_cam = None          # (index, backend) that worked last time


def _detector(input_size=(640, 480)):
    key = f"{input_size[0]}x{input_size[1]}"
    if key not in _detector_cache:
        model = os.path.join(find_nightmare_dir(), "models", "face_detection_yunet_2023mar.onnx")
        fd = cv2.FaceDetectorYN_create(model, "", input_size)
        fd.setInputSize(input_size)
        _detector_cache[key] = fd
    return _detector_cache[key]


def _recognizer():
    if "sf" not in _recognizer_cache:
        model = os.path.join(find_nightmare_dir(), "models",
                             "face_recognition_sface_2021dec.onnx")
        if not os.path.exists(model):
            _recognizer_cache["sf"] = None
        else:
            try:
                _recognizer_cache["sf"] = cv2.FaceRecognizerSF.create(model, "")
            except Exception:
                _recognizer_cache["sf"] = None
    return _recognizer_cache["sf"]


def parse_face_row(row):
    """Return (score, landmarks) from one YuNet detection row.

    The column layout is not stable across OpenCV builds: some emit
    [x, y, w, h, score, l0..l9], others [x, y, w, h, l0..l9, score]. Guessing
    wrong silently yields garbage landmarks that still look plausible, so pick
    whichever end actually looks like a confidence and sanity-check the
    landmarks against the box.

    Returns (None, None) for a row that cannot be read.
    """
    row = np.asarray(row, dtype=np.float32).reshape(-1)
    if row.size < 15:
        return None, None
    first, last = float(row[4]), float(row[14])
    if first > 1.0 and last <= 1.0:
        score, raw = last, row[4:14]
    else:
        score, raw = first, row[5:15]

    pts = raw.reshape(5, 2)
    x, y, w, h = float(row[0]), float(row[1]), float(row[2]), float(row[3])
    pad = 0.5 * max(w, h) + 5.0
    inside = ((pts[:, 0] >= x - pad) & (pts[:, 0] <= x + w + pad) &
              (pts[:, 1] >= y - pad) & (pts[:, 1] <= y + h + pad))
    if int(inside.sum()) < 4:
        return None, None
    return score, pts


def open_camera(index=None, warmup=5, size=(640, 480)):
    """Open a usable camera, or return (None, None).

    A capture that opens is not a capture that works: DirectShow reports
    success and then hands back nothing. So every candidate is read from before
    being accepted, and a frame is only returned once real pixels arrive.
    """
    global _last_cam
    if index is not None:
        pairs = [(index, b) for b in _CAM_BACKENDS]
    elif _last_cam is not None:
        # probing every dead index x backend costs ~8s, which is far too slow
        # for a gate that runs at startup
        pairs = [_last_cam] + [(i, b) for i in range(4) for b in _CAM_BACKENDS
                               if (i, b) != _last_cam]
    else:
        pairs = [(i, b) for i in range(4) for b in _CAM_BACKENDS]

    seen = set()
    for i, backend in pairs:
        if (i, backend) in seen:
            continue
        seen.add((i, backend))
        try:
            cap = cv2.VideoCapture(i, backend)
        except Exception:
            continue
        if not cap.isOpened():
            cap.release()
            continue
        if size:
            try:
                cur_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            except Exception:
                cur_w = 0
            # Asking a UVC camera to set its frame size renegotiates the
            # format, which on this machine costs ~4s. Only touch it when the
            # camera is not already delivering a usable width.
            if not cur_w or cur_w < size[0]:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, size[0])
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])
        frame = None
        for _ in range(max(1, warmup)):
            ok, img = cap.read()
            if ok and img is not None and img.size:
                frame = img
            else:
                break
        if frame is not None:
            _last_cam = (i, backend)
            return cap, i
        cap.release()
    return None, None


def _find_camera():
    cap, idx = open_camera(warmup=3)
    if cap is not None:
        cap.release()
    return idx


def list_cameras():
    found = []
    for i in range(4):
        for backend in _CAM_BACKENDS:
            cap = None
            try:
                cap = cv2.VideoCapture(i, backend)
            except Exception:
                continue
            if not cap.isOpened():
                if cap is not None:
                    cap.release()
                continue
            ok, frame = cap.read()
            h, w = frame.shape[:2] if (ok and frame is not None) else (0, 0)
            cap.release()
            if w:
                found.append(f"  - camera {i} ({w}x{h})")
                break
    if not found:
        return "No camera devices detected."
    return "Camera devices:\n" + "\n".join(found)


def _smile_ratio(landmarks):
    try:
        re_, le = landmarks[0], landmarks[2]
        rm, lm = landmarks[6], landmarks[8]
        eye_d = float(np.hypot(re_[0] - le[0], re_[1] - le[1]))
        mouth_d = float(np.hypot(rm[0] - lm[0], rm[1] - lm[1]))
        if eye_d <= 0:
            return 0.0
        return mouth_d / eye_d
    except Exception:
        return 0.0


def _mood_word(ratio):
    if ratio >= 0.62:
        return "in high spirits", "a clear smile", "happy"
    if ratio >= 0.5:
        return "content", "a mild smile", "content"
    return "composed", "a neutral expression", "neutral"


def analyze_mood(index=None, max_faces=3):
    cap, cam_idx = open_camera(index)
    if cap is None:
        return "I cannot see you - no camera device is available."

    try:
        frame = None
        for _ in range(8):
            ok, img = cap.read()
            if ok and img is not None and img.size:
                frame = img
            else:
                break
        if frame is None:
            return f"Camera {cam_idx} returned no frames."
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w = frame.shape[:2]
        fd = _detector((w, h))
        retval, faces = fd.detect(frame)
    finally:
        cap.release()

    if faces is None or len(faces) == 0:
        return "I can see the room, but no face to read. I'll keep watching."

    moods = []
    smiling = 0
    emotions = []
    for row in faces[:max_faces]:
        conf, pts = parse_face_row(row)
        if conf is None or conf < 0.5:
            continue
        ratio = _smile_ratio(pts)
        word, evidence, emotion = _mood_word(ratio)
        moods.append(word)
        emotions.append(emotion)
        if ratio >= 0.5:
            smiling += 1

    if not moods:
        return "A face is there, but poorly lit or out of frame. Hard to read."

    overall = "in good spirits" if smiling and smiling >= len(moods) * 0.5 else (
        "as calm as ever" if all(m == "composed" for m in moods) else "content")
    n = len(moods)
    dominant = emotions[0] if emotions else "neutral"
    line = (f"I see you. {n} face(s) detected; current mood: {dominant} (expression: {overall}). "
            f"You look {overall}. "
            "Shall I note anything you are feeling for the long-term record?")
    return line