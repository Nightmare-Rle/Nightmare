import os
import json
import sys
import random
import math
import time
import subprocess
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from memory import find_nightmare_dir

_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\courbd.ttf", r"C:\Windows\Fonts\segoeui.ttf",
]


def _font(size):
    for c in _FONT_CANDIDATES:
        if os.path.exists(c):
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _out_dir():
    return output_dir()


def output_dir():
    """Where NIGHTMARE keeps generated and edited media."""
    d = os.path.join(find_nightmare_dir(), "media")
    os.makedirs(d, exist_ok=True)
    return d


def _resolve(path):
    return os.path.abspath(path)


# ------------------------------------------------------------------ GUI support

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff")
VIDEO_EXT = (".mp4", ".avi", ".mkv", ".mov", ".webm", ".wmv", ".m4v", ".gif")

_IMAGE_EXT_SET = set(IMAGE_EXT)
_VIDEO_EXT_SET = set(VIDEO_EXT)


def kind_of(path):
    """'image', 'video' or '' for a path, by extension."""
    ext = os.path.splitext(str(path or ""))[1].lower()
    if ext in _IMAGE_EXT_SET:
        return "image"
    if ext in _VIDEO_EXT_SET:
        return "video"
    return ""


def is_media(path):
    return kind_of(path) != ""


def list_media(folder=None, recursive=True, limit=400):
    """Media files in a folder, newest first. Used to populate the studio."""
    folder = os.path.abspath(os.path.expanduser(folder or _out_dir()))
    if not os.path.isdir(folder):
        return []
    hits = []
    try:
        if recursive:
            for dirpath, _dirs, files in os.walk(folder):
                for fn in files:
                    p = os.path.join(dirpath, fn)
                    if kind_of(fn):
                        try:
                            hits.append((os.path.getmtime(p), p))
                        except OSError:
                            hits.append((0.0, p))
        else:
            for fn in os.listdir(folder):
                p = os.path.join(folder, fn)
                if os.path.isfile(p) and kind_of(fn):
                    try:
                        hits.append((os.path.getmtime(p), p))
                    except OSError:
                        hits.append((0.0, p))
    except OSError:
        return []
    hits.sort(reverse=True)
    return [p for _m, p in hits[:limit]]


def probe(path):
    """Metadata for the viewer's title bar. Returns a dict, never raises."""
    path = _resolve(str(path or ""))
    out = {"path": path, "kind": kind_of(path), "exists": os.path.isfile(path),
           "name": os.path.basename(path)}
    if not out["exists"]:
        return out
    try:
        out["size"] = os.path.getsize(path)
    except OSError:
        out["size"] = 0
    if out["kind"] == "image":
        try:
            with Image.open(path) as im:
                out["width"], out["height"] = im.width, im.height
                out["format"] = (im.format or "").upper()
                out["animated"] = bool(getattr(im, "is_animated", False))
                out["frames"] = int(getattr(im, "n_frames", 1) or 1)
        except Exception as e:
            out["error"] = f"cannot read image: {e}"
    elif out["kind"] == "video":
        cap = None
        try:
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                out["error"] = "cannot open video (codec unavailable)"
                return out
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
            frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            out["width"] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            out["height"] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            out["fps"] = round(fps, 3) if fps else 0.0
            out["frames"] = frames
            out["duration"] = round(frames / fps, 3) if (fps and frames) else 0.0
        except Exception as e:
            out["error"] = f"cannot read video: {e}"
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
    return out


def describe(path):
    """One-line human summary, e.g. '1920x1080 mp4, 12.4s, 30fps'."""
    m = probe(path)
    if not m.get("exists"):
        return f"not found: {m.get('name') or path}"
    if m.get("error"):
        return f"{m['name']}: {m['error']}"
    if m["kind"] == "image":
        extra = f", {m['frames']} frames" if m.get("animated") else ""
        return f"{m['name']}: {m.get('width')}x{m.get('height')} {m.get('format','')}{extra}"
    return (f"{m['name']}: {m.get('width')}x{m.get('height')}, "
            f"{m.get('duration', 0):.1f}s, {m.get('fps', 0):.2f}fps")


def thumbnail(path, width=320):
    """PIL thumbnail as an RGB image, letterboxed onto a dark canvas.

    The GUI hands the result to ImageTk; returning a PIL image (not a Tk one)
    keeps this importable with no display, so it stays unit-testable.
    """
    path = _resolve(str(path or ""))
    if not os.path.isfile(path):
        return None
    try:
        if kind_of(path) == "video":
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                return None
            ok, frame = cap.read()
            cap.release()
            if not ok:
                return None
            im = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        else:
            im = Image.open(path)
            im.load()
            im = im.convert("RGB")
        ratio = float(width) / im.width
        im = im.resize((max(1, int(width)), max(1, int(im.height * ratio))),
                       Image.LANCZOS)
        return im
    except Exception:
        return None


def image_frames(path):
    """Iterate an image (or GIF) as PIL frames for playback.

    Yields (index, PIL RGB image). GIFs with several frames play like a clip.
    """
    path = _resolve(str(path or ""))
    if not os.path.isfile(path):
        return
    try:
        im = Image.open(path)
        im.load()
    except Exception:
        return
    n = int(getattr(im, "n_frames", 1) or 1)
    for i in range(n):
        try:
            im.seek(i)
            yield i, im.convert("RGB")
        except (EOFError, ValueError):
            break


def video_frame_at(path, index=0):
    """Single decoded frame as a PIL image, for scrub and thumbnails."""
    path = _resolve(str(path or ""))
    # cv2 will happily 'play' a PNG as a one-frame clip and spray ffmpeg errors
    # doing it. Refuse non-video extensions up front.
    if kind_of(path) != "video":
        return None
    cap = None
    try:
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            return None
        idx = max(0, int(index))
        if idx:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok and idx:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = cap.read()
        if not ok:
            return None
        return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    except Exception:
        return None
    finally:
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass


# ------------------------------------------------------------------ image generation

_PALETTES = {
    "neon": [(255, 0, 102), (0, 255, 255), (37, 0, 255), (255, 255, 0)],
    "ember": [(255, 30, 0), (255, 120, 0), (40, 8, 2), (255, 60, 20)],
    "void": [(10, 10, 18), (46, 46, 92), (90, 90, 160), (200, 200, 255)],
    "data": [(0, 255, 127), (0, 90, 60), (6, 20, 14), (140, 255, 200)],
    "cold": [(0, 150, 255), (20, 40, 120), (120, 200, 255), (10, 10, 40)],
    "sunset": [(255, 150, 40), (255, 50, 90), (90, 20, 80), (255, 220, 150)],
}

_GEOMETRIES = ["waves", "grid", "rings", "slices", "diamond", "orbital", "matrix", "scan"]


def _style_for(prompt):
    low = prompt.lower()
    for key in ("ember", "fire", "warm", "red"):
        if key in low:
            return random.choice((1, 5))
    for key in ("cold", "ice", "blue", "water"):
        if key in low:
            return 4
    for key in ("data", "code", "matrix", "hacker", "green"):
        return 3
    for key in ("neon", "cyber", "synth", "future", "night"):
        return 0
    for key in ("void", "dark", "black", "space"):
        return 2
    if "sunset" in low:
        return 5
    return random.randrange(len(_PALETTES))


def _pal(prompt):
    return list(_PALETTES.values())[_style_for(prompt)]


def _canvas(w, h, seed=None):
    rng = random.Random(seed)
    img = Image.new("RGB", (w, h), (8, 6, 10))
    return img, rng


def _fast_tone(w, h, p0, p1, rng):
    rows = []
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(p0[0] + (p1[0] - p0[0]) * t)
        g = int(p0[1] + (p1[1] - p0[1]) * t)
        b = int(p0[2] + (p1[2] - p0[2]) * t)
        rows.append(bytes((r, g, b)) * w)
    return Image.frombytes("RGB", (w, h), b"".join(rows))


_UNIQUE = set()


def _savename(prefix, ext="png"):
    name = f"{prefix}_{int(time.time() * 1000) % 100000}.{ext}"
    if name in _UNIQUE:
        time.sleep(0.001)
        name = f"{prefix}_{int(time.time() * 1000000)}.{ext}"
    _UNIQUE.add(name)
    return name


def generate_image(prompt="neon nebula", width=800, height=600, seed=None):
    try:
        prompt = str(prompt or "abstract art")
        rng = random.Random(seed if seed is not None else random.random())
        p = _pal(prompt)
        low = prompt.lower()
        w, h = int(width), int(height)
        style = rng.choice(_GEOMETRIES)
        if "grid" in low:
            style = "grid"
        if "waves" in low or "wave" in low:
            style = "waves"
        if "portal" in low or "ring" in low or "neon" in low:
            style = "rings"
        if "matrix" in low or "rain" in low or "data" in low:
            style = "matrix"
        if "sun" in low or "day" in low:
            style = "orbital"

        img = _fast_tone(w, h, p[2], p[3], rng)
        d = ImageDraw.Draw(img, "RGBA")

        if style == "grid":
            step = max(24, w // 16)
            for x in range(0, w, step):
                d.line((x, 0, x, h), fill=p[0] + (60,), width=2)
            for y in range(0, h, step):
                d.line((0, y, w, y), fill=p[0] + (60,), width=2)
            for _ in range(rng.randint(20, 60)):
                d.rectangle((rng.randrange(w), rng.randrange(h),
                             rng.randrange(w), rng.randrange(h)),
                            outline=p[1] + (rng.randint(40, 160),))
        elif style == "waves":
            for i in range(h):
                off = int(60 * math.sin(i / 14) + rng.randint(-8, 8))
                for j in range(0, w, 6):
                    d.point((j, i), fill=p[0 if (j // 6 + i // 10) % 2 == 0 else 1] + (200,))
                d.line((0, i, w, i), fill=p[0] + (20,), width=1)
        elif style == "rings":
            cx, cy = w // 2, h // 2
            for k in range(1, rng.randint(8, 16)):
                r = k * (min(w, h) // (rng.randint(9, 20)))
                d.ellipse((cx - r, cy - r, cx + r, cy + r),
                          outline=p[k % 2] + (rng.randint(80, 200),),
                          width=rng.randint(1, 6))
                d.ellipse((cx - r + 4, cy - r + 4, cx + r - 4, cy + r - 4),
                          fill=p[(k + 1) % 2] + (60,))
        elif style == "orbital":
            cx, cy = w // 2, h // 2
            for k in range(rng.randint(1, 5)):
                d.ellipse((cx - 40 - k * 60, cy - 40 - k * 60, cx + 40 + k * 60, cy + 40 + k * 60),
                          outline=p[k % 2] + (150,), width=3)
            for _ in range(rng.randint(3, 8)):
                a = rng.uniform(0, 6.28)
                r = rng.randint(60, min(w, h) // 2)
                d.ellipse((cx + r * math.cos(a) - 6, cy + r * math.sin(a) - 6,
                           cx + r * math.cos(a) + 6, cy + r * math.sin(a) + 6),
                          fill=p[0] + (255,))
        elif style == "matrix":
            font = _font(16)
            for _ in range(w // 6):
                x = rng.randrange(w)
                y = 0
                while y < h:
                    d.text((x, y), random.choice("01アイウエオカキクケ"), fill=p[0] + (rng.randint(40, 220),), font=font)
                    y += rng.randint(18, 40)
        else:  # slices
            for _ in range(rng.randint(12, 30)):
                y = rng.randrange(h)
                she = rng.randint(-60, 60)
                box = img.crop((0, y, w, min(y + rng.randint(2, 14), h)))
                img.paste(box, (she, y))

        if rng.random() < 0.6:
            font = _font(max(24, w // 22))
            txt = prompt.upper()[:40]
            tw, th = d.textbbox((0, 0), txt, font=font)[2:4]
            d.rectangle((w // 2 - tw // 2 - 12, h - th - 26, w // 2 + tw // 2 + 12, h - 8),
                        fill=(6, 6, 10, 200))
            d.text((w // 2 - tw // 2, h - th - 18), txt, fill=p[1] + (255,), font=font)

        out = os.path.join(_out_dir(), _savename("gen"))
        img.save(out)
        return f"Generated image: {out} ({w}x{h}, {style} art from '{prompt}')"
    except Exception as e:
        return f"generate_image error: {e}"


# ------------------------------------------------------------------ image editing

_IMAGE_OPS = {
    "resize": lambda im, p: im.resize((int(p.get("width", im.width)), int(p.get("height", im.height)))),
    "crop": lambda im, p: im.crop((int(p["x"]), int(p["y"]), int(p["x2"]), int(p["y2"]))),
    "rotate": lambda im, p: im.rotate(float(p.get("angle", 90)), expand=bool(p.get("expand", True))),
    "flip": lambda im, p: im.transpose(Image.FLIP_LEFT_RIGHT if p.get("axis") == "h" else Image.FLIP_TOP_BOTTOM),
    "gray": lambda im, p: ImageOps.grayscale(im).convert("RGB"),
    "invert": lambda im, p: ImageOps.invert(im),
    "brightness": lambda im, p: ImageEnhance.Brightness(im).enhance(float(p.get("factor", 1.2))),
    "contrast": lambda im, p: ImageEnhance.Contrast(im).enhance(float(p.get("factor", 1.2))),
    "blur": lambda im, p: im.filter(ImageFilter.GaussianBlur(float(p.get("radius", 3)))),
    "sharpen": lambda im, p: im.filter(ImageFilter.UnsharpMask(radius=float(p.get("radius", 2)))),
    "posterize": lambda im, p: ImageOps.posterize(im, max(1, min(8, int(p.get("bits", 4))))).convert("RGB"),
    "solarize": lambda im, p: ImageOps.solarize(im, threshold=int(p.get("threshold", 128))),
    "noise": lambda im, p: _noise(im, int(p.get("amount", 40))),
    "colorize": lambda im, p: ImageOps.colorize(ImageOps.grayscale(im),
                                                black=p.get("black", (20, 20, 40)),
                                                white=tuple(int(x) for x in p.get("white", (255, 60, 120)))),
    "thumbnail": lambda im, p: im.resize((
        max(1, int(im.width * float(p.get("scale", 0.5)))),
        max(1, int(im.height * float(p.get("scale", 0.5)))))) if p.get("scale") else _thumb(im, int(p.get("width", 256))),
    "glitch": lambda im, p: _glitch(im, int(p.get("lines", 12)), int(p.get("shift", 40))),
    "watermark": lambda im, p: _watermark(im, str(p.get("text", "NIGHTMARE"))),
    "saturation": lambda im, p: _saturation(im, float(p.get("factor", 1.3))),
    "vignette": lambda im, p: _vignette(im, float(p.get("strength", 0.7))),
}


def _thumb(im, width):
    r = width / im.width
    return im.resize((width, max(1, int(im.height * r))))


def _glitch(im, lines, shift):
    arr = np.array(im).copy()
    h, w = arr.shape[:2]
    for _ in range(lines):
        y = random.randrange(h)
        n = random.randrange(2, 14)
        amt = random.randint(-shift, shift)
        arr[y:y + n, :, :] = np.roll(arr[y:y + n, :, :], amt, axis=1)
    return Image.fromarray(arr)


def _watermark(im, text):
    d = ImageDraw.Draw(im)
    f = _font(max(14, im.width // 20))
    d.text((12, 12), text, fill=(255, 255, 255, 160), font=f)
    return im


def _noise(im, amount):
    """Add per-pixel grain. Shape comes from the array, not from im.size,
    which is (width, height) and only broadcast by accident on square images."""
    arr = np.asarray(im.convert("RGB")).astype("int16")
    amount = max(0, int(amount))
    if amount:
        grain = np.random.randint(-amount, amount + 1, arr.shape)
        arr = np.clip(arr + grain, 0, 255).astype("uint8")
    return Image.fromarray(arr)


def _saturation(im, factor):
    """Boost or drain colour. 0.0 is greyscale, 1.0 leaves it alone."""
    arr = np.asarray(im.convert("RGB")).astype("float32")
    grey = arr.mean(axis=2, keepdims=True)
    arr = grey + (arr - grey) * float(factor)
    return Image.fromarray(np.clip(arr, 0, 255).astype("uint8"))


def _vignette(im, strength):
    """Darken the edges toward the centre, the cheap cinematic look."""
    w, h = im.size
    yy, xx = np.mgrid[0:h, 0:w].astype("float32")
    cx, cy = max(w / 2.0, 1e-6), max(h / 2.0, 1e-6)
    d = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2)
    mask = np.clip(1.0 - float(strength) * d ** 2, 0.0, 1.0)[:, :, None]
    arr = np.asarray(im.convert("RGB")).astype("float32") * mask
    return Image.fromarray(np.clip(arr, 0, 255).astype("uint8"))


def _apply_ops(img, ops):
    for op in ops or []:
        name = (op or {}).get("op", "")
        p = op.get("params", {}) or {}
        if name in _IMAGE_OPS:
            img = _IMAGE_OPS[name](img, p)
        elif name == "draw_text":
            d = ImageDraw.Draw(img)
            d.text((int(p.get("x", 10)), int(p.get("y", 10))), str(p.get("text", "")),
                   fill=tuple(int(x) for x in p.get("fill", (255, 255, 255))) + (255,),
                   font=_font(int(p.get("size", 28))))
        elif name == "rectangle":
            d = ImageDraw.Draw(img)
            d.rectangle((int(p["x"]), int(p["y"]), int(p["x2"]), int(p["y2"])),
                        outline=tuple(int(x) for x in p.get("fill", (255, 0, 100))), width=int(p.get("width", 3)))
        elif name == "convert":
            pass  # handled after full pass
        else:
            return None, f"unknown image op: {name}"
    return img, None


def _concat(images, direction="h"):
    ims = []
    for path in images:
        try:
            ims.append(Image.open(_resolve(str(path))).convert("RGB"))
        except Exception:
            continue
    if not ims:
        return None
    w = sum(i.width for i in ims)
    h = max(i.height for i in ims)
    if direction == "v":
        w, h = h, w
    canvas = Image.new("RGB", (w, h), (6, 6, 10))
    x = y = 0
    for im in ims:
        if direction == "v":
            canvas.paste(im, (0, y))
            y += im.height
        else:
            canvas.paste(im, (x, 0))
            x += im.width
    return canvas


def edit_image(path, ops, out=None, images=None):
    try:
        src = _resolve(str(path))
        if not os.path.isfile(src):
            return f"Image not found: {src}"
        img = Image.open(src)
        img.load()
        fmt = (img.format or "PNG").upper()
        if ops and isinstance(ops, str):
            try:
                ops = json.loads(ops)
            except Exception:
                return "ops must be a JSON array of {op, params}."
        concat = False
        if images and len(images) > 1:
            img = _concat(list(images) + [src], str(images[0]).lower() != "v" and "h" or "h")
            concat = True
        img, err = _apply_ops(img, ops)
        if err:
            return err
        target_fmt = None
        for op in ops or []:
            if (op or {}).get("op") == "convert":
                target_fmt = str((op or {}).get("params", {}).get("format", "png")).lower()
        if target_fmt is None:
            target_fmt = "png" if fmt in ("PNG", "WEBP", "GIF", "BMP") else "jpg"
        ext = "jpg" if target_fmt == "jpg" else target_fmt
        out = out or os.path.join(_out_dir(), _savename("edit", ext))
        if target_fmt == "jpg":
            img = img.convert("RGB")
        img.save(out, format={"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG",
                              "webp": "WEBP", "bmp": "BMP", "tiff": "TIFF", "gif": "GIF"}.get(ext, "PNG"))
        return f"Edited image saved: {out} ({img.width}x{img.height}, {ext})"
    except Exception as e:
        return f"edit_image error: {e}"


def analyze_image(path):
    try:
        src = _resolve(str(path))
        if not os.path.isfile(src):
            return f"Image not found: {src}"
        img = Image.open(src).convert("RGB")
        w, h = img.size
        q = img.quantize(colors=4, method=Image.Quantize.MEDIANCUT)
        pal = q.getpalette()
        counts = sorted(q.getcolors(), reverse=True)[:4]
        colors = []
        for cnt, idx in counts:
            colors.append(f"#{pal[idx * 3]:02x}{pal[idx * 3 + 1]:02x}{pal[idx * 3 + 2]:02x}")
        edges = np.array(img.convert("L").filter(ImageFilter.FIND_EDGES))
        sharpness = round(float(edges.mean()) / 255, 2)
        lum = np.array(img.convert("L")).mean() / 255
        faces = _count_faces(src)
        return (f"Image analysis of {src}\n"
                f"  Size: {w}x{h} ({w * h / 1e6:.1f} MP)\n"
                f"  dominant colors: {', '.join(colors)}\n"
                f"  brightness: {lum:.0%}, sharpness/complexity: {sharpness}\n"
                f"  faces detected: {faces}\n"
                f"  notes: {'high detail' if sharpness > 0.22 else ('clean/flat' if sharpness < 0.08 else 'typical')}, "
                f"{'bright scene' if lum > 0.6 else ('dim scene' if lum < 0.3 else 'balanced lighting')}")
    except Exception as e:
        return f"analyze_image error: {e}"


def _count_faces(path):
    try:
        src = _to_cv(path)
        if src is None:
            return 0
        h, w = src.shape[:2]
        model = os.path.join(find_nightmare_dir(), "models", "face_detection_yunet_2023mar.onnx")
        if not os.path.exists(model):
            return 0
        fd = cv2.FaceDetectorYN_create(model, "", (w, h))
        fd.setInputSize((w, h))
        _, faces = fd.detect(src)
        return 0 if faces is None else int(len(faces))
    except Exception:
        return 0


def _to_cv(path):
    try:
        arr = np.array(Image.open(_resolve(path)).convert("RGB"))
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    except Exception:
        return None


# ------------------------------------------------------------------ video generation

def _new_writer(out, fps, w, h):
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    return cv2.VideoWriter(out, fourcc, float(fps), (w, h))


def generate_video(mode="pulse", duration=5, fps=24, images=None, out=None):
    try:
        mode = str(mode or "pulse")
        w, h = 640, 400
        frames = max(1, int(float(duration) * float(fps)))
        out = out or os.path.join(_out_dir(), _savename("gen", "mp4"))
        writer = _new_writer(out, int(fps), w, h)
        if writer is None or not writer.isOpened():
            return "generate_video: failed to open video writer (codec unavailable)."
        slide = []
        if images:
            for p in list(images if isinstance(images, list) else [images])[:40]:
                try:
                    im = Image.open(_resolve(str(p))).convert("RGB").resize((w, h))
                    slide.append(cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR))
                except Exception:
                    continue
        for i in range(frames):
            t = i / fps
            frame = np.zeros((h, w, 3), dtype=np.uint8)
            if mode == "rain":
                rng = random.Random(int(t * fps))
                frame[:] = (8, 10, 8)
                for _ in range(150):
                    x, y = rng.randrange(w), rng.randrange(h)
                    cv2.line(frame, (x, y), (x, y + rng.randint(10, 40)), (90, 220, 90), 1)
            elif mode == "hyperspace":
                rng = random.Random(int(t * fps))
                frame[:] = (5, 5, 10)
                for _ in range(220):
                    x, y = rng.randrange(w), rng.randrange(h)
                    L = rng.randint(3, 30)
                    rgb = (255, 255, 255) if rng.random() < 0.2 else (150, 160, 255)
                    cv2.line(frame, (x, y), (x + int((x - w / 2) * L / 40), y + int((y - h / 2) * L / 40)), rgb, 1)
            elif mode == "scan":
                p = (abs(math.sin(t * 2))) / 1.0
                for y in range(h):
                    val = int(30 + 130 * math.exp(-((y / h - 0.5) ** 2) * 30))
                    frame[y, :] = (30, 30, 60)
                    if abs(y / h - p) < 0.02:
                        frame[y, :] = (90, 220, 140)
            elif mode == "slide" and slide:
                frame = slide[i % len(slide)]
            else:  # pulse
                v = int(60 + 90 * (0.5 + 0.5 * math.sin(t * 2)))
                r, g, b = v, max(10, v // 3), max(20, v // 2)
                frame[:] = (b, g // 2, r)
                cv2.circle(frame, (w // 2, h // 2),
                           int(60 + 50 * (0.5 + 0.5 * math.sin(t * 3))), (200, 160 if 0 else b + 20, 150), 3)
            writer.write(frame)
        writer.release()
        return f"Generated video: {out} ({int(fps)}fps, {duration}s, {mode})"
    except Exception as e:
        return f"generate_video error: {e}"


# ------------------------------------------------------------------ video editing

def _read_video(path):
    cap = cv2.VideoCapture(_resolve(str(path)))
    if not cap.isOpened():
        return None, "video not found or unsupported format"
    return cap, None


def _writer_from_cap(cap, out, fps):
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    return cv2.VideoWriter(out, fourcc, float(fps), (w, h)), w, h


def _transform(frame, op, p):
    if op == "resize":
        h, w = frame.shape[:2]
        return cv2.resize(frame, (int(p.get("width", w)), int(p.get("height", h))))
    if op == "crop":
        h, w = frame.shape[:2]
        x, y = int(p.get("x", 0)), int(p.get("y", 0))
        x2, y2 = int(p.get("x2", w)), int(p.get("y2", h))
        return cv2.resize(frame[y:y2, x:x2], (w, h))
    if op == "rotate":
        return cv2.rotate(frame, {"90": cv2.ROTATE_90_CLOCKWISE, "180": cv2.ROTATE_180,
                                  "270": cv2.ROTATE_90_COUNTERCLOCKWISE}.get(str(p.get("angle", "90")), cv2.ROTATE_90_CLOCKWISE))
    if op == "mirror":
        return cv2.flip(frame, 1 if p.get("axis") == "h" else 0)
    if op == "gray":
        return cv2.cvtColor(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    if op == "invert":
        return 255 - frame
    if op == "brightness":
        return cv2.convertScaleAbs(frame, alpha=float(p.get("factor", 1.2)))
    if op == "contrast":
        f = float(p.get("factor", 1.2))
        return cv2.convertScaleAbs(frame, alpha=f, beta=(1.0 - f) * 128)
    if op == "blur":
        return cv2.GaussianBlur(frame, (0, 0), float(p.get("sigma", 3)))
    if op == "sharpen":
        blur = cv2.GaussianBlur(frame, (0, 0), float(p.get("sigma", 1.5)))
        a = float(p.get("amount", 1.5))
        return cv2.addWeighted(frame, 1 + a, blur, -a, 0)
    if op == "saturation":
        f = float(p.get("factor", 1.3))
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype("float32")
        hsv[..., 1] = np.clip(hsv[..., 1] * f, 0, 255)
        return cv2.cvtColor(hsv.astype("uint8"), cv2.COLOR_HSV2BGR)
    if op == "solarize":
        t = int(p.get("threshold", 128))
        return np.where(frame < t, frame, 255 - frame).astype("uint8")
    if op == "vignette":
        h, w = frame.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w].astype("float32")
        cx, cy = w / 2.0, h / 2.0
        d = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2)
        k = float(p.get("strength", 0.7))
        mask = np.clip(1.0 - k * d ** 2, 0.0, 1.0)[:, :, None]
        return (frame.astype("float32") * mask).astype("uint8")
    if op == "edge":
        return cv2.Canny(frame, 60, 160)
    if op == "watermark":
        return cv2.putText(frame, str(p.get("text", "NIGHTMARE")),
                           (int(p.get("x", 12)), int(p.get("y", 34))),
                           cv2.FONT_HERSHEY_SIMPLEX,
                           float(p.get("scale", 1.0)),
                           (255, 255, 255), int(p.get("thickness", 2)))
    return frame


def _atempo_chain(speed):
    """atempo only accepts 0.5-2.0, so chain factors to reach any rate."""
    parts = []
    remaining = float(speed)
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    parts.append("atempo=%.6f" % remaining)
    return ",".join(parts)


def _mux_audio(video_out, src, start=0.0, end=None, speed=1.0):
    """Copy the source audio onto a re-encoded video, best effort.

    cv2 writes picture only, so without this every edit came out mute. Video is
    stream-copied (no second re-encode); only the audio is encoded. Writes to a
    temp file and swaps on success, so a failure can never leave a half-written
    result. Returns True if audio was restored.
    """
    tmp = video_out + ".audio.mp4"
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return False
    if not exe or not os.path.isfile(exe):
        return False
    if not (os.path.isfile(video_out) and os.path.isfile(src)):
        return False
    cmd = [exe, "-hide_banner", "-loglevel", "error", "-y"]
    if start:
        cmd += ["-ss", "%.3f" % max(0.0, float(start))]
    if end:
        try:
            length = float(end) - float(start)
        except Exception:
            length = 0.0
        if length > 0.05:
            cmd += ["-t", "%.3f" % length]
    cmd += ["-i", src, "-i", video_out,
            "-map", "0:a:0", "-map", "1:v:0",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "160k"]
    if abs(float(speed) - 1.0) > 1e-3:
        cmd += ["-filter:a", _atempo_chain(speed)]
    cmd += ["-shortest", tmp]
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=900)
    except Exception:
        return False
    if getattr(res, "returncode", 1) != 0 or not os.path.isfile(tmp) \
            or os.path.getsize(tmp) < 1024:
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False
    try:
        if os.path.getsize(tmp) < os.path.getsize(video_out) // 3:
            os.remove(tmp)
            return False
        os.replace(tmp, video_out)
        return True
    except Exception:
        return False


def edit_video(path, ops, out=None, keep_audio=True):
    try:
        src = _resolve(str(path))
        cap, err = _read_video(src)
        if err:
            return err
        if ops and isinstance(ops, str):
            ops = json.loads(ops)
        speed = 1.0
        extra = []
        for op in ops or []:
            if op.get("op") == "speed":
                speed = max(0.25, min(4.0, float(op.get("params", {}).get("factor", 1))))
            if op.get("op") in ("trim", "extract"):
                extra.append(op)
        out = out or os.path.join(_out_dir(), _savename("edit", "mp4"))
        fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        dur = total / fps if (fps and total) else 0.0
        trim = next((o.get("params", {}) for o in extra if o.get("op") == "trim"), {})
        start_s = max(0.0, float(trim.get("start", 0) or 0))
        end_s = float(trim.get("end", dur) or dur)
        if not dur:
            end_s = max(end_s, start_s)
        start = int(start_s * fps)
        end = int(end_s * fps)
        end = min(end, total) if total else end
        extract_dir = None
        for o in extra:
            if o.get("op") == "extract":
                extract_dir = str(o.get("params", {}).get("dir") or os.path.join(_out_dir(), "frames", os.path.splitext(os.path.basename(src))[0]))
                os.makedirs(extract_dir, exist_ok=True)
        writer = None
        written = 0
        idx = 0
        # Output duration must be source_duration / speed. Keeping every frame
        # and raising the frame rate achieves that: duration = N / (fps*speed).
        # A codec will not take an absurd frame rate, so past the ceiling we
        # drop frames instead, which leaves the duration identical.
        out_fps = float(fps) * float(speed)
        step = 1
        if out_fps > 120.0:
            step = int(math.ceil(out_fps / 120.0))
            out_fps = out_fps / float(step)
        out_fps = max(1.0, out_fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start)
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            pos = start + idx
            if end and pos > end:
                break
            if idx % step == 0:
                f2 = frame
                for op in ops or []:
                    f2 = _transform(f2, op.get("op"), op.get("params", {}) or {})
                if writer is None:
                    h, w = f2.shape[:2]
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    writer = cv2.VideoWriter(out, fourcc, out_fps, (w, h))
                if not writer.isOpened():
                    cap.release()
                    return "edit_video: writer failed (codec unavailable)."
                writer.write(f2)
                written += 1
            if extract_dir and pos % max(1, int(fps // 2)) == 0:
                cv2.imwrite(os.path.join(extract_dir, f"f{pos:05d}.jpg"), frame)
            idx += 1
        cap.release()
        if writer:
            writer.release()
        if not written:
            return "edit_video: nothing was written (empty range or undecodable file)."
        audio_note = ""
        if keep_audio:
            if _mux_audio(out, src, start_s, end_s if dur else None, speed):
                audio_note = " + audio"
            else:
                audio_note = " (no audio track found)"
        if extract_dir:
            frames_n = len([f for f in os.listdir(extract_dir) if f.lower().endswith((".jpg", ".png"))])
            return (f"Edited video saved: {out} ({written} frames, {speed:g}x speed"
                    f"{audio_note}) + extracted {frames_n} frames to {extract_dir}")
        return (f"Edited video saved: {out} ({written} frames, "
                f"{speed:g}x speed{audio_note})")
    except Exception as e:
        return f"edit_video error: {e}"


def analyze_video(path):
    try:
        src = _resolve(str(path))
        cap, err = _read_video(src)
        if err:
            return err
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        dur = total / fps if fps else 0.0
        scene_changes = 0
        sample_brightness = []
        prev = None
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        step = max(1, total // 40) if total else 1
        seen = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if seen % step == 0:
                sample_brightness.append(float(frame.mean()) / 255)
                if prev is not None:
                    diff = float(np.mean(np.abs(cv2.absdiff(frame, prev))) / 255)
                    if diff > 0.45:
                        scene_changes += 1
                prev = frame
            seen += 1
        cap.release()
        brightness = sum(sample_brightness) / max(1, len(sample_brightness))
        fourcc = None
        try:
            cap2, _ = _read_video(src)
            val = cap2.get(cv2.CAP_PROP_FOURCC)
            if val:
                fourcc = "".join(chr(int((val >> (8 * i)) & 0xFF)) for i in range(4))
            cap2.release()
        except Exception:
            pass
        return (f"Video analysis of {src}\n"
                f"  Resolution: {w}x{h}, fps: {fps:.0f}, duration: {dur:.1f}s ({total} frames)\n"
                f"  codec: {fourcc or 'unknown'}\n"
                f"  average brightness: {brightness:.0%}\n"
                f"  scene changes (sampled): {scene_changes}"
                f"{' - dynamic footage' if scene_changes > 8 else (' - static/cut footage' if scene_changes < 3 else ' - moderate edits')}")
    except Exception as e:
        return f"analyze_video error: {e}"


def convert_image(path, out_format="png", out=None):
    return edit_image(path, [{"op": "convert", "params": {"format": out_format}}], out=out)