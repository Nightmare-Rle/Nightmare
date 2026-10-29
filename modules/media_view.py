"""Media studio for NIGHTMARE: view, play, and edit images and video in the GUI.

Design notes
------------
* Playback decodes exactly one frame per Tk tick via root.after(), so the UI
  never blocks. Reading a single frame is a few milliseconds; re-encoding never
  happens on the Tk thread.
* Exports run on a worker thread and report back through a queue polled by
  after(), because a long trim is many seconds of CPU.
* Live preview edits a downscaled copy. Full resolution is only touched on save,
  so dragging a blur slider stays interactive on a 4K photo.
* All Tk calls are guarded: a bad frame or a closed window must degrade to a
  message, never take the app down.
"""

import os
import queue
import threading
import time

import tkinter as tk
from tkinter import filedialog, ttk

import numpy as np
import cv2
from PIL import Image, ImageTk

from modules import media as M

VIDEO_EXTS = M.VIDEO_EXT
IMAGE_EXTS = M.IMAGE_EXT

# status tokens
ST_IDLE = "idle"
ST_THINKING = "thinking"
ST_PLAYING = "playing"


def _fmt_time(sec):
    try:
        sec = max(0.0, float(sec or 0))
    except Exception:
        sec = 0.0
    m, s = divmod(sec, 60)
    h, m = divmod(int(m), 60)
    if h:
        return "%d:%02d:%04.1f" % (h, m, s)
    return "%d:%04.1f" % (m, s)


def fit_size(src_w, src_h, box_w, box_h):
    """Largest (w, h) <= box that keeps the aspect ratio. Never returns 0."""
    src_w = max(1, int(src_w or 1))
    src_h = max(1, int(src_h or 1))
    box_w = max(1, int(box_w or 1))
    box_h = max(1, int(box_h or 1))
    s = min(box_w / src_w, box_h / src_h)
    return max(1, int(src_w * s)), max(1, int(src_h * s))


class MediaPlayer(tk.Frame):
    """Shows one image or plays one video. Callbacks: on_status, on_meta."""

    def __init__(self, parent, colors, on_status=None, on_meta=None,
                 box_w=640, box_h=360):
        super().__init__(parent, bg=colors["bg"])
        self.C = colors
        self.on_status = on_status
        self.on_meta = on_meta
        self.box_w, self.box_h = box_w, box_h

        self.path = ""
        self.kind = ""
        self.meta = {}
        self.cap = None
        self.photo = None
        self.playing = False
        self.frame_idx = 0
        self.total_frames = 1
        self.fps = 12.0
        self.zoom = 1.0
        self.auto_fit = True
        self.rot = 0
        self._after_id = None
        self._frames_cache = None      # animated GIF frames
        self._last_pil = None          # most recent *prepared* frame (on canvas)
        self._last_raw = None          # most recent *untransformed* frame
        self._syncing = False          # True while pushing the seek bar

        self.canvas = tk.Canvas(self, bg="#000000", highlightthickness=1,
                                highlightbackground=colors["border"], bd=0)
        self.canvas.pack(fill="both", expand=True, padx=(0, 0), pady=(0, 6))
        self.canvas.bind("<Configure>", lambda e: self._redraw_last())

        # ---- transport row
        bar = tk.Frame(self, bg=colors["panel"])
        bar.pack(fill="x", pady=(0, 4))

        def btn(parent, text, cmd, width=3):
            b = tk.Button(parent, text=text, bg=colors["panel"],
                          fg=colors["secondary"], activebackground=colors["bg"],
                          activeforeground=colors["primary"], relief="flat",
                          font=("Segoe UI", 10), cursor="hand2", width=width,
                          command=cmd, bd=0, highlightthickness=0)
            b.pack(side="left", padx=2, ipady=3)
            return b

        btn(bar, "\u25b6", self.toggle_play)      # play
        btn(bar, "\u23f8", self.stop)             # stop
        btn(bar, "\u25c0", lambda: self.step(-1))  # prev frame
        btn(bar, "\u25b6\u2500", lambda: self.step(1))  # next frame

        self.seek = tk.Scale(bar, from_=0, to=1000, orient="horizontal",
                             bg=colors["panel"], fg=colors["text"],
                             troughcolor=colors["bg"],
                             activebackground=colors["primary"],
                             highlightthickness=0, bd=0, sliderrelief="flat",
                             command=self._on_seek, showvalue=False,
                             length=220)
        self.seek.pack(side="left", fill="x", expand=True, padx=8)

        self.time_lbl = tk.Label(bar, text="--:--", bg=colors["panel"],
                                 fg=colors["text"], font=("Consolas", 9))
        self.time_lbl.pack(side="left", padx=4)

        btn(bar, "+", lambda: self._zoom_by(0.25), 2)
        btn(bar, "-", lambda: self._zoom_by(-0.25), 2)
        btn(bar, "FIT", self.fit, 4)
        btn(bar, "1:1", lambda: self._set_zoom(1.0), 3)
        self.rot_btn = btn(bar, "\u21bb", self.rotate, 2)

        self.canvas.bind("<Button-1>", lambda e: self.toggle_play())
        self.canvas.bind("<Configure>", lambda e: None)
        for w in (self, self.canvas):
            w.bind("<space>", lambda e: self.toggle_play())
            w.bind("<Left>", lambda e: self.step(-1))
            w.bind("<Right>", lambda e: self.step(1))
            w.bind("<f>", lambda e: self.fit())

        self._last_pil = None
        self._clear_msg("no media loaded")

    # -------------------------------------------------------------- plumbing

    def _clear_msg(self, text):
        self.canvas.delete("all")
        self.canvas.create_text(self.canvas.winfo_width() / 2 or 320,
                                self.canvas.winfo_height() / 2 or 180,
                                text=text, fill=self.C["sub"],
                                font=("Segoe UI", 10))

    def _status(self, token, detail=""):
        if self.on_status:
            try:
                self.on_status(token, detail)
            except Exception:
                pass

    def _meta(self):
        if self.on_meta:
            try:
                self.on_meta(self.meta)
            except Exception:
                pass

    # -------------------------------------------------------------- loading

    def load(self, path):
        self.stop()
        self._close_cap()
        self._frames_cache = None
        self._last_pil = None
        self.zoom = 1.0
        self.auto_fit = True
        self.rot = 0
        self.path = os.path.abspath(str(path or ""))
        self.meta = M.probe(self.path)
        self.kind = self.meta.get("kind", "")
        self.frame_idx = 0

        if not self.meta.get("exists"):
            self._clear_msg("file not found")
            self._meta()
            return False
        if self.meta.get("error"):
            self._clear_msg(self.meta["error"])
            self._meta()
            self._status(ST_IDLE, self.meta["error"])
            return False
        if not self.kind:
            self._clear_msg("unsupported media type")
            self._meta()
            return False

        if self.kind == "video":
            self.total_frames = max(1, int(self.meta.get("frames") or 1))
            self.fps = float(self.meta.get("fps") or 24.0) or 24.0
            self.seek.configure(to=max(1, self.total_frames))
            self.seek.set(0)
            ok = self._show_video(0)
            self._meta()
            self._status(ST_IDLE, "")
            return ok
        # image (GIFs included)
        self._frames_cache = list(M.image_frames(self.path))
        if not self._frames_cache:
            self._clear_msg("cannot decode image")
            self._meta()
            return False
        self.total_frames = max(1, len(self._frames_cache))
        self.fps = 8.0
        self.seek.configure(to=max(1, self.total_frames))
        self.seek.set(0)
        self._show_image(0)
        self._meta()
        self._status(ST_IDLE, "")
        return True

    def _open_cap(self):
        if self.cap is not None:
            return self.cap.isOpened()
        try:
            cap = cv2.VideoCapture(self.path)
            if cap.isOpened():
                self.cap = cap
                return True
        except Exception:
            pass
        self.cap = None
        return False

    def _close_cap(self):
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

    # -------------------------------------------------------------- drawing

    def _prep(self, im):
        """Apply rotation, then scale for the current zoom/fit, letterboxed."""
        if im is None:
            return None
        try:
            if self.rot:
                im = im.rotate(-self.rot, expand=True)
            cw = max(1, self.canvas.winfo_width() - 8)
            ch = max(1, self.canvas.winfo_height() - 8)
            if self.auto_fit:
                tw, th = fit_size(im.width, im.height, cw, ch)
            else:
                tw = max(1, int(im.width * self.zoom))
                th = max(1, int(im.height * self.zoom))
            if (tw, th) != (im.width, im.height):
                resample = Image.LANCZOS
                im = im.resize((tw, th), resample)
            return im
        except Exception:
            return None

    def _show_pil(self, im):
        """Put a prepared image on the canvas. Returns True on success."""
        if im is None:
            return False
        try:
            self.photo = ImageTk.PhotoImage(im)
            self.canvas.delete("img")
            self.canvas.create_image(self.canvas.winfo_width() / 2,
                                     self.canvas.winfo_height() / 2,
                                     image=self.photo, anchor="center", tags="img")
            self._last_pil = im
            return True
        except Exception:
            return False

    def _show_image(self, idx):
        if not self._frames_cache:
            return False
        idx = max(0, min(len(self._frames_cache) - 1, int(idx)))
        _i, im = self._frames_cache[idx]
        self.frame_idx = idx
        self._last_raw = im
        ok = self._show_pil(self._prep(im))
        self._sync_time()
        return ok

    def _show_video(self, idx, sequential=False):
        if not self._open_cap():
            self._clear_msg("cannot open video")
            return False
        idx = max(0, int(idx))
        try:
            read_ok, frame = False, None
            if sequential and idx == self.frame_idx + 1:
                # the capture is already parked on this frame, so read straight
                # through: calling cap.set() on every tick makes playback crawl
                read_ok, frame = self.cap.read()
                if not read_ok:                       # stream ended early
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                    read_ok, frame = self.cap.read()
            else:
                if idx:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                read_ok, frame = self.cap.read()
            if not read_ok and idx:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                read_ok, frame = self.cap.read()
            if not read_ok:
                return False
            self.frame_idx = idx
            im = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            self._last_raw = im
            ok = self._show_pil(self._prep(im))
            self._sync_time()
            return ok
        except Exception:
            return False

    def _redraw_last(self):
        # redraw from the *raw* frame: re-preparing an already prepared image
        # would stack another rotation and another rescale on every zoom
        src = self._last_raw if self._last_raw is not None else self._last_pil
        if src is not None:
            self._show_pil(self._prep(src))

    def _sync_time(self):
        try:
            fps = self.fps if self.fps else 12.0
            cur = self.frame_idx / fps
            total = self.total_frames / fps
            label = "%s / %s" % (_fmt_time(cur), _fmt_time(total))
            if self.meta.get("width"):
                label += "   %dx%d" % (self.meta["width"], self.meta["height"])
            self.time_lbl.configure(text=label)
            # setting the Scale fires its command, which would seek and re-enter
            # this method; the guard stops that feedback loop
            self._syncing = True
            try:
                self.seek.set(max(0, min(self.total_frames, self.frame_idx)))
            finally:
                self._syncing = False
        except Exception:
            self._syncing = False

    # -------------------------------------------------------------- controls

    def toggle_play(self):
        if self.playing:
            self.pause()
        else:
            self.play()

    def play(self):
        if not self.path or not self.kind:
            return
        if self.kind == "video" and not self._open_cap():
            self._clear_msg("cannot open video")
            return
        if self.frame_idx >= self.total_frames - 1:
            self.seek_to(0)
        self.playing = True
        self._status(ST_PLAYING, os.path.basename(self.path))
        self._tick()

    def pause(self):
        self.playing = False
        self._cancel()
        self._status(ST_IDLE, "")

    def stop(self):
        self.playing = False
        self._cancel()
        if self.path and self.kind:
            try:
                self.seek_to(0)
            except Exception:
                pass

    def _cancel(self):
        if self._after_id is not None:
            try:
                self.winfo_toplevel().after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _tick(self):
        self._cancel()
        if not self.playing:
            return
        nxt = self.frame_idx + 1
        if nxt >= self.total_frames:
            nxt = 0
        ok = (self._show_video(nxt, sequential=True) if self.kind == "video"
              else self._show_image(nxt))
        if not ok:
            self.playing = False
            self._status(ST_IDLE, "playback stopped")
            return
        delay = max(10, int(1000.0 / max(1.0, self.fps)))
        try:
            self._after_id = self.winfo_toplevel().after(delay, self._tick)
        except Exception:
            self.playing = False

    def step(self, n):
        self.pause()
        self.seek_to(self.frame_idx + n)

    def seek_to(self, idx):
        idx = max(0, min(self.total_frames - 1, int(idx)))
        if self.kind == "video":
            self._show_video(idx)
        else:
            self._show_image(idx)

    def _on_seek(self, val):
        try:
            idx = int(float(val))
        except Exception:
            return
        if self.playing or self._syncing:
            return
        self.seek_to(idx)

    def _set_zoom(self, z):
        self.auto_fit = False
        self.zoom = max(0.1, min(8.0, float(z)))
        self._redraw_last()

    def _zoom_by(self, dz):
        self._set_zoom((1.0 if self.auto_fit else self.zoom) + dz)

    def fit(self):
        self.auto_fit = True
        self._redraw_last()

    def rotate(self):
        self.rot = (self.rot + 90) % 360
        self.seek_to(self.frame_idx)

    def destroy(self):
        self.pause()
        self._close_cap()
        self.photo = None
        try:
            super().destroy()
        except Exception:
            pass


class ImageEditor(tk.Frame):
    """Op controls with a live downscaled preview. Save applies at full size."""

    MAX_PREVIEW = 860

    def __init__(self, parent, colors, on_saved=None, on_status=None):
        super().__init__(parent, bg=colors["panel"])
        self.C = colors
        self.on_saved = on_saved
        self.on_status = on_status
        self.src = None            # full-res PIL image (lazy)
        self.preview_base = None   # downscaled for interactive editing
        self.saved_path = ""
        self._debounce = None
        self._busy = False

        self.op_widgets = {}

        left = tk.Frame(self, bg=colors["panel"])
        left.pack(side="left", fill="y")
        right = tk.Frame(self, bg=colors["bg"])
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))

        self._build_controls(left)
        self._build_preview(right)
        self._set_enabled(False)

    # -------------------------------------------------------------- layout

    def _lab(self, parent, text, **kw):
        return tk.Label(parent, text=text, bg=self.C["panel"], fg=self.C["sub"],
                        font=("Segoe UI", 8, "bold"), anchor="w", **kw)

    def _slider(self, parent, name, label, lo, hi, default, fmt="%.2f"):
        row = tk.Frame(parent, bg=self.C["panel"])
        row.pack(fill="x", padx=8, pady=2)
        self._lab(row, label).pack(side="left")
        var = tk.DoubleVar(value=default)
        val = tk.Label(row, text=fmt % default, bg=self.C["panel"],
                       fg=self.C["primary"], font=("Consolas", 8), width=6,
                       anchor="e")
        val.pack(side="right")
        s = tk.Scale(row, from_=lo, to=hi, orient="horizontal", variable=var,
                     bg=self.C["panel"], fg=self.C["text"],
                     troughcolor=self.C["bg"], activebackground=self.C["primary"],
                     highlightthickness=0, bd=0, showvalue=False, sliderrelief="flat",
                     command=lambda v, n=name, l=val, f=fmt: self._on_slider(n, v, l, f))
        s.pack(side="right", fill="x", expand=True, padx=6)
        self.op_widgets[name] = {"type": "slider", "var": var, "label": val, "fmt": fmt}
        return row

    def _toggle(self, parent, name, label):
        var = tk.BooleanVar(value=False)
        c = tk.Checkbutton(parent, text=label, variable=var, bg=self.C["panel"],
                           fg=self.C["text"], selectcolor=self.C["bg"],
                           activebackground=self.C["panel"],
                           activeforeground=self.C["primary"],
                           font=("Segoe UI", 9), anchor="w", bd=0,
                           highlightthickness=0,
                           command=lambda n=name: self._schedule())
        c.pack(fill="x", padx=8, pady=1)
        self.op_widgets[name] = {"type": "bool", "var": var}
        return c

    def _choice(self, parent, name, label, options, default):
        row = tk.Frame(parent, bg=self.C["panel"])
        row.pack(fill="x", padx=8, pady=2)
        self._lab(row, label).pack(side="left")
        var = tk.StringVar(value=default)
        om = tk.OptionMenu(row, var, *options,
                           command=lambda n=name: self._schedule())
        om.configure(bg=self.C["panel"], fg=self.C["secondary"],
                     activebackground=self.C["bg"], highlightthickness=0,
                     bd=0, relief="flat", font=("Segoe UI", 8))
        om["menu"].configure(bg=self.C["panel"], fg=self.C["text"],
                             activebackground=self.C["bg"],
                             activeforeground=self.C["primary"],
                             font=("Segoe UI", 9))
        om.pack(side="right")
        self.op_widgets[name] = {"type": "choice", "var": var}
        return row

    def _build_controls(self, parent):
        head = tk.Frame(parent, bg=self.C["panel"])
        head.pack(fill="x", padx=8, pady=(6, 4))
        tk.Label(head, text="IMAGE OPS", bg=self.C["panel"], fg=self.C["primary"],
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        self.info = tk.Label(head, text="", bg=self.C["panel"], fg=self.C["sub"],
                             font=("Segoe UI", 8))
        self.info.pack(side="right")

        self._slider(parent, "brightness", "BRIGHT", 0.3, 2.5, 1.0)
        self._slider(parent, "contrast", "CONTRAST", 0.3, 2.5, 1.0)
        self._slider(parent, "saturation", "SATUR", 0.0, 2.5, 1.0)
        self._slider(parent, "blur", "BLUR", 0, 14, 0, "%.0f")
        self._slider(parent, "sharpen", "SHARP", 0, 5, 0, "%.0f")
        self._slider(parent, "vignette", "VIGNET", 0.0, 1.0, 0.0)

        self._choice(parent, "rotate", "ROTATE", ("0", "90", "180", "270"), "0")
        self._choice(parent, "convert", "FORMAT",
                     ("png", "jpg", "webp", "bmp", "tiff", "gif"), "png")

        self._toggle(parent, "gray", "grayscale")
        self._toggle(parent, "invert", "invert colours")
        self._toggle(parent, "mirror", "flip horizontal")
        self._toggle(parent, "flipv", "flip vertical")
        self._toggle(parent, "posterize", "posterize (4 bit)")
        self._toggle(parent, "solarize", "solarize")
        self._toggle(parent, "colorize", "duotone (pink/teal)")
        self._toggle(parent, "noise", "add noise")
        self._toggle(parent, "glitch", "glitch lines")
        self._toggle(parent, "wm", "watermark text")

        wmrow = tk.Frame(parent, bg=self.C["panel"])
        wmrow.pack(fill="x", padx=8, pady=2)
        self._lab(wmrow, "WATERMARK").pack(side="left")
        self.wm_var = tk.StringVar(value="NIGHTMARE")
        tk.Entry(wmrow, textvariable=self.wm_var, bg=self.C["bg"],
                 fg=self.C["text"], insertbackground=self.C["primary"],
                 relief="flat", font=("Segoe UI", 9),
                 highlightthickness=1, highlightbackground=self.C["border"],
                 highlightcolor=self.C["primary"]).pack(side="left", fill="x",
                                                       expand=True, padx=6)
        self.op_widgets["wmtext"] = {"type": "text", "var": self.wm_var}
        self.wm_var.trace_add("write", lambda *a: self._schedule())

        acts = tk.Frame(parent, bg=self.C["panel"])
        acts.pack(fill="x", padx=8, pady=(8, 4))
        self.apply_btn = tk.Button(acts, text="APPLY & SAVE", command=self.apply_save,
                                   bg=self.C["primary"], fg="#0d0709",
                                   activebackground=self.C["secondary"],
                                   relief="flat", font=("Segoe UI", 9, "bold"),
                                   cursor="hand2", bd=0, pady=5)
        self.apply_btn.pack(side="left", fill="x", expand=True)
        self.reset_btn = tk.Button(acts, text="RESET", command=self.reset,
                                   bg=self.C["panel"], fg=self.C["secondary"],
                                   activebackground=self.C["bg"], relief="flat",
                                   font=("Segoe UI", 9), cursor="hand2", bd=0,
                                   pady=5, highlightthickness=1,
                                   highlightbackground=self.C["border"])
        self.reset_btn.pack(side="left", padx=(6, 0))

        self.status = tk.Label(parent, text="load an image to edit",
                               bg=self.C["panel"], fg=self.C["sub"],
                               font=("Segoe UI", 8), wraplength=250,
                               justify="left", anchor="w")
        self.status.pack(fill="x", padx=8, pady=(4, 8))

    def _build_preview(self, parent):
        self.canvas = tk.Canvas(parent, bg="#000000", highlightthickness=1,
                                highlightbackground=self.C["border"])
        self.canvas.pack(fill="both", expand=True, pady=(6, 6))
        self.photo = None
        self.canvas.bind("<Configure>", lambda e: self._redraw())

    def _set_enabled(self, on):
        state = "normal" if on else "disabled"
        for name, w in self.op_widgets.items():
            try:
                if w["type"] == "slider":
                    for c in w.get("children", []):
                        pass
            except Exception:
                pass
        self._enabled = bool(on)

    # -------------------------------------------------------------- op list

    def collect_ops(self, full=True):
        """Build the media.edit_image op list from the controls."""
        ops = []

        def val(name):
            w = self.op_widgets.get(name)
            if not w:
                return None
            try:
                return w["var"].get()
            except Exception:
                return None

        b = float(val("brightness") or 1.0)
        if abs(b - 1.0) > 0.01:
            ops.append({"op": "brightness", "params": {"factor": b}})
        c = float(val("contrast") or 1.0)
        if abs(c - 1.0) > 0.01:
            ops.append({"op": "contrast", "params": {"factor": c}})
        bl = float(val("blur") or 0)
        if bl > 0:
            ops.append({"op": "blur", "params": {"radius": bl}})
        sh = float(val("sharpen") or 0)
        if sh > 0:
            ops.append({"op": "sharpen", "params": {"radius": sh}})
        vg = float(val("vignette") or 0.0)
        if vg > 0.01:
            ops.append({"op": "vignette", "params": {"strength": vg}})
        sat = float(val("saturation") or 1.0)
        if abs(sat - 1.0) > 0.01:
            ops.append({"op": "saturation", "params": {"factor": sat}})
        rot = str(val("rotate") or "0")
        if rot != "0":
            ops.append({"op": "rotate", "params": {"angle": int(rot)}})
        if val("mirror"):
            ops.append({"op": "flip", "params": {"axis": "h"}})
        if val("flipv"):
            ops.append({"op": "flip", "params": {"axis": "v"}})
        if val("gray"):
            ops.append({"op": "gray", "params": {}})
        if val("invert"):
            ops.append({"op": "invert", "params": {}})
        if val("posterize"):
            ops.append({"op": "posterize", "params": {"bits": 4}})
        if val("solarize"):
            ops.append({"op": "solarize", "params": {"threshold": 128}})
        if val("colorize"):
            ops.append({"op": "colorize",
                        "params": {"black": (12, 8, 20), "white": (255, 60, 120)}})
        if val("noise"):
            ops.append({"op": "noise", "params": {"amount": 28}})
        if val("glitch"):
            ops.append({"op": "glitch", "params": {"lines": 14, "shift": 46}})
        if val("wm"):
            ops.append({"op": "watermark",
                        "params": {"text": str(self.wm_var.get() or "NIGHTMARE")}})
        fmt = str(val("convert") or "png")
        if full:
            ops.append({"op": "convert", "params": {"format": fmt}})
        return ops

    # -------------------------------------------------------------- preview

    def load(self, path):
        self.src_path = os.path.abspath(str(path or ""))
        try:
            im = Image.open(self.src_path)
            im.load()
        except Exception as e:
            self.status.configure(text=f"cannot open: {e}", fg=self.C["rest"])
            self._enabled = False
            return False
        self.src = im.convert("RGB")
        scale = min(1.0, float(self.MAX_PREVIEW) / max(1, self.src.width))
        self.preview_base = self.src if scale >= 1.0 else self.src.resize(
            (max(1, int(self.src.width * scale)),
             max(1, int(self.src.height * scale))), Image.LANCZOS)
        self._enabled = True
        self.saved_path = ""
        self.info.configure(text="%dx%d" % (self.src.width, self.src.height))
        self.reset()
        return True

    def _on_slider(self, name, value, label, fmt):
        try:
            label.configure(text=fmt % float(value))
        except Exception:
            pass
        self._schedule()

    def _schedule(self):
        """Debounce: sliders fire continuously while dragging."""
        if self._debounce is not None:
            try:
                self.after_cancel(self._debounce)
            except Exception:
                pass
        self._debounce = self.after(130, self._render_preview)

    def _render_preview(self):
        self._debounce = None
        self._redraw()

    def _redraw(self):
        if not getattr(self, "_enabled", False) or self.preview_base is None:
            return
        try:
            ops = self.collect_ops(full=False)
            im, err = M._apply_ops(self.preview_base.copy(), ops)
            if err or im is None:
                self.status.configure(text=f"preview: {err}", fg=self.C["rest"])
                return
            cw = max(1, self.canvas.winfo_width() - 8)
            ch = max(1, self.canvas.winfo_height() - 8)
            tw, th = fit_size(im.width, im.height, cw, ch)
            im = im.resize((tw, th), Image.LANCZOS)
            self.photo = ImageTk.PhotoImage(im)
            self.canvas.delete("all")
            self.canvas.create_image(self.canvas.winfo_width() / 2,
                                     self.canvas.winfo_height() / 2,
                                     image=self.photo, anchor="center")
        except Exception as e:
            self.status.configure(text=f"preview error: {e}", fg=self.C["rest"])

    def reset(self):
        for name, w in self.op_widgets.items():
            try:
                if w["type"] == "bool":
                    w["var"].set(False)
                elif w["type"] == "choice":
                    w["var"].set("0" if name == "rotate" else "png")
                elif w["type"] == "slider":
                    default = {"brightness": 1.0, "contrast": 1.0, "saturation": 1.0,
                               "blur": 0, "sharpen": 0, "vignette": 0.0}.get(name, 1.0)
                    w["var"].set(default)
            except Exception:
                pass
        try:
            self.wm_var.set("NIGHTMARE")
        except Exception:
            pass
        self.status.configure(text="preview reset", fg=self.C["sub"])
        self._redraw()

    # -------------------------------------------------------------- saving

    def apply_save(self, ask=True):
        if self._busy:
            return
        if not getattr(self, "_enabled", False) or not self.src_path:
            self.status.configure(text="load an image first", fg=self.C["rest"])
            return
        ops = self.collect_ops(full=True)
        if not [o for o in ops if o["op"] != "convert"]:
            self.status.configure(text="nothing changed - move a slider first",
                                  fg=self.C["act"])
            return
        target = None
        if ask:
            ext = str(self.op_widgets["convert"]["var"].get() or "png")
            picked = filedialog.asksaveasfilename(
                parent=self, title="Save edited image",
                defaultextension="." + ext,
                filetypes=[(ext.upper(), "*." + ext), ("All files", "*.*")])
            if not picked:
                self.status.configure(text="save cancelled", fg=self.C["sub"])
                return
            target = picked
        self._busy = True
        self.status.configure(text="writing full resolution...", fg=self.C["act"])
        src, oplist, cb = self.src_path, ops, self.on_saved

        def work():
            try:
                res = M.edit_image(src, oplist, out=target)
            except Exception as e:
                res = f"edit_image error: {e}"
            self.after(0, lambda: self._saved(res))

        threading.Thread(target=work, daemon=True).start()

    def _saved(self, result):
        self._busy = False
        text = str(result or "")
        ok = text.startswith("Edited image saved")
        self.status.configure(text=text, fg=self.C["primary"] if ok else self.C["rest"])
        if ok:
            path = text.split(":", 1)[1].split("(")[0].strip()
            self.saved_path = path
            if self.on_saved:
                try:
                    self.on_saved(path, text)
                except Exception:
                    pass


class VideoEditor(tk.Frame):
    """Trim / speed / filter controls. Export runs off the Tk thread."""

    FILTERS = [
        ("none", "Original"), ("brightness", "Brighter"), ("contrast", "Contrast"),
        ("gray", "Grayscale"),
        ("invert", "Invert"), ("blur", "Blur"), ("edge", "Edge detect"),
        ("mirror", "Mirror"), ("saturation", "Punchy"), ("vignette", "Vignette"),
        ("solarize", "Solarize"), ("sharpen", "Sharpen"),
    ]

    def __init__(self, parent, colors, on_saved=None, on_status=None,
                 get_player=None):
        super().__init__(parent, bg=colors["panel"])
        self.C = colors
        self.on_saved = on_saved
        self.on_status = on_status
        self.get_player = get_player
        self.path = ""
        self.meta = {}
        self._busy = False
        self._job_q = queue.Queue()

        left = tk.Frame(self, bg=colors["panel"])
        left.pack(side="left", fill="y")
        right = tk.Frame(self, bg=colors["bg"])
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))

        self._build_controls(left)
        self._build_preview(right)
        self._set_enabled(False)

    def _lab(self, parent, text):
        return tk.Label(parent, text=text, bg=self.C["panel"], fg=self.C["sub"],
                        font=("Segoe UI", 8, "bold"), anchor="w")

    def _build_controls(self, parent):
        head = tk.Frame(parent, bg=self.C["panel"])
        head.pack(fill="x", padx=8, pady=(6, 4))
        tk.Label(head, text="VIDEO OPS", bg=self.C["panel"], fg=self.C["primary"],
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        self.vinfo = tk.Label(head, text="", bg=self.C["panel"], fg=self.C["sub"],
                              font=("Segoe UI", 8))
        self.vinfo.pack(side="right")

        self._lab(parent, "FILTER").pack(fill="x", padx=8, pady=(4, 1))
        self.filter_var = tk.StringVar(value="none")
        grid = tk.Frame(parent, bg=self.C["panel"])
        grid.pack(fill="x", padx=8)
        for i, (key, label) in enumerate(self.FILTERS):
            b = tk.Radiobutton(grid, text=label, value=key,
                               variable=self.filter_var, bg=self.C["panel"],
                               fg=self.C["text"], selectcolor=self.C["bg"],
                               activebackground=self.C["panel"],
                               activeforeground=self.C["primary"],
                               font=("Segoe UI", 8), anchor="w", bd=0,
                               highlightthickness=0,
                               command=self._render_preview)
            b.grid(row=i // 2, column=i % 2, sticky="w")
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        self.strength = tk.Scale(parent, from_=0, to=2, orient="horizontal",
                                 resolution=0.05, bg=self.C["panel"],
                                 fg=self.C["text"], troughcolor=self.C["bg"],
                                 activebackground=self.C["primary"],
                                 highlightthickness=0, bd=0, showvalue=False,
                                 sliderrelief="flat",
                                 command=lambda v: self._render_preview())
        self.strength.set(1.2)
        # the slider was built but never given a parent slot, so filter strength
        # was silently unadjustable
        srow = tk.Frame(parent, bg=self.C["panel"])
        srow.pack(fill="x", padx=8, pady=(4, 2))
        self._lab(srow, "STRENGTH").pack(side="left")
        self.strength.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self._strength_lbl = tk.Label(srow, text="1.20", bg=self.C["panel"],
                                      fg=self.C["sub"], font=("Consolas", 8),
                                      width=4, anchor="e")
        self._strength_lbl.pack(side="right", padx=(4, 0))
        self.strength.configure(
            command=lambda v: (self._strength_lbl.configure(text="%.2f" % float(v)),
                               self._render_preview()))

        trim = tk.Frame(parent, bg=self.C["panel"])
        trim.pack(fill="x", padx=8, pady=(6, 2))
        self._lab(trim, "TRIM  start / end (s)").pack(side="left")
        self.start_var = tk.StringVar(value="0")
        self.end_var = tk.StringVar(value="0")
        self.start_e = tk.Entry(trim, textvariable=self.start_var, width=6,
                                bg=self.C["bg"], fg=self.C["text"],
                                insertbackground=self.C["primary"], relief="flat",
                                font=("Consolas", 9), highlightthickness=1,
                                highlightbackground=self.C["border"],
                                highlightcolor=self.C["primary"])
        self.start_e.pack(side="left", padx=4)
        tk.Label(trim, text="-", bg=self.C["panel"], fg=self.C["sub"]).pack(side="left")
        self.end_e = tk.Entry(trim, textvariable=self.end_var, width=6,
                              bg=self.C["bg"], fg=self.C["text"],
                              insertbackground=self.C["primary"], relief="flat",
                              font=("Consolas", 9), highlightthickness=1,
                              highlightbackground=self.C["border"],
                              highlightcolor=self.C["primary"])
        self.end_e.pack(side="left", padx=4)

        sp = tk.Frame(parent, bg=self.C["panel"])
        sp.pack(fill="x", padx=8, pady=2)
        self._lab(sp, "SPEED").pack(side="left")
        self.speed_var = tk.StringVar(value="1.0")
        tk.Spinbox(sp, from_=0.25, to=4.0, increment=0.25, textvariable=self.speed_var,
                   width=6, bg=self.C["bg"], fg=self.C["text"], relief="flat",
                   font=("Consolas", 9), highlightthickness=1,
                   highlightbackground=self.C["border"],
                   highlightcolor=self.C["primary"],
                   buttonbackground=self.C["panel"]).pack(side="left", padx=4)

        self.audio_var = tk.BooleanVar(value=True)
        tk.Checkbutton(parent, text="keep original audio", variable=self.audio_var,
                       bg=self.C["panel"], fg=self.C["text"],
                       selectcolor=self.C["bg"], activebackground=self.C["panel"],
                       activeforeground=self.C["primary"], font=("Segoe UI", 8),
                       anchor="w", bd=0, highlightthickness=0).pack(
            fill="x", padx=8, pady=(4, 2))

        acts = tk.Frame(parent, bg=self.C["panel"])
        acts.pack(fill="x", padx=8, pady=(8, 2))
        self.export_btn = tk.Button(acts, text="EXPORT", command=self.export,
                                    bg=self.C["primary"], fg="#0d0709",
                                    activebackground=self.C["secondary"],
                                    relief="flat", font=("Segoe UI", 9, "bold"),
                                    cursor="hand2", bd=0, pady=5)
        self.export_btn.pack(side="left", fill="x", expand=True)
        self.frames_btn = tk.Button(acts, text="FRAMES", command=self.extract_frames,
                                    bg=self.C["panel"], fg=self.C["secondary"],
                                    activebackground=self.C["bg"], relief="flat",
                                    font=("Segoe UI", 9), cursor="hand2", bd=0,
                                    pady=5, highlightthickness=1,
                                    highlightbackground=self.C["border"])
        self.frames_btn.pack(side="left", padx=(6, 0))

        self.vstatus = tk.Label(parent, text="load a video to edit",
                                bg=self.C["panel"], fg=self.C["sub"],
                                font=("Segoe UI", 8), wraplength=250,
                                justify="left", anchor="w")
        self.vstatus.pack(fill="x", padx=8, pady=(4, 8))

        self.after(120, self._poll)

    def _build_preview(self, parent):
        tk.Label(parent, text="FILTER PREVIEW (current frame)",
                 bg=self.C["bg"], fg=self.C["sub"],
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(6, 2))
        self.canvas = tk.Canvas(parent, bg="#000000", highlightthickness=1,
                                highlightbackground=self.C["border"])
        self.canvas.pack(fill="both", expand=True)
        self.photo = None

    def _set_enabled(self, on):
        self._enabled = bool(on)
        state = "normal" if on else "disabled"
        for b in (self.export_btn, self.frames_btn, self.start_e, self.end_e):
            try:
                b.configure(state=state)
            except Exception:
                pass

    def load(self, path):
        self.path = os.path.abspath(str(path or ""))
        self.meta = M.probe(self.path)
        if not self.meta.get("exists") or self.meta.get("kind") != "video":
            self.vstatus.configure(text="not a readable video", fg=self.C["rest"])
            self._set_enabled(False)
            return False
        dur = float(self.meta.get("duration") or 0)
        self.start_var.set("0")
        self.end_var.set(("%g" % dur) if dur else "0")
        self._set_enabled(True)
        self.vinfo.configure(text="%dx%d  %s" % (self.meta.get("width", 0),
                                                 self.meta.get("height", 0),
                                                 _fmt_time(dur)))
        self.vstatus.configure(text="ready to edit", fg=self.C["sub"])
        self._render_preview()
        return True

    def _note_filter_unsupported(self, name):
        try:
            self.vstatus.configure(text="filter %r is not implemented - ignored" % name,
                                   fg=self.C["rest"])
        except Exception:
            pass

    def _current_frame_index(self):
        pl = self.get_player() if self.get_player else None
        return int(getattr(pl, "frame_idx", 0) or 0) if pl else 0

    def _build_ops(self, include_timing=True):
        ops = []
        f = self.filter_var.get()
        s = float(self.strength.get() or 1.2)
        if f and f != "none":
            # every entry here must be an op the backend actually implements,
            # otherwise the radio button silently exports nothing
            if f in ("brightness", "invert", "saturation"):
                ops.append({"op": f, "params": {"factor": s}})
            elif f == "contrast":
                ops.append({"op": "contrast", "params": {"factor": s}})
            elif f == "blur":
                ops.append({"op": "blur", "params": {"sigma": max(0.5, s * 2.0)}})
            elif f == "sharpen":
                ops.append({"op": "sharpen",
                            "params": {"sigma": max(0.5, s),
                                       "amount": max(0.1, s)}})
            elif f == "vignette":
                ops.append({"op": "vignette", "params": {"strength": s}})
            elif f == "solarize":
                ops.append({"op": "solarize", "params": {"threshold": 128}})
            elif f in ("gray", "edge", "mirror"):
                ops.append({"op": f, "params": {}})
            else:
                # never drop timing ops over an unsupported filter: say so
                # instead of exporting the clip as if nothing was chosen
                self._note_filter_unsupported(f)
        if include_timing:
            try:
                start = float(self.start_var.get() or 0)
                end = float(self.end_var.get() or 0)
            except Exception:
                start = end = 0.0
            if start > 0 or end > 0:
                dur = float(self.meta.get("duration") or 0)
                ops.append({"op": "trim", "params": {"start": start,
                                                    "end": end or dur}})
            try:
                speed = float(self.speed_var.get() or 1.0)
            except Exception:
                speed = 1.0
            if abs(speed - 1.0) > 0.01:
                ops.append({"op": "speed", "params": {"factor": speed}})
        return ops

    def _render_preview(self, *_a):
        if not getattr(self, "_enabled", False) or not self.path:
            return
        try:
            im = M.video_frame_at(self.path, self._current_frame_index())
            if im is None:
                return
            ops = self._build_ops(include_timing=False)
            if ops:
                frame = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)
                for op in ops:
                    frame = M._transform(frame, op.get("op"), op.get("params", {}) or {})
                im = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            cw = max(1, self.canvas.winfo_width() - 8)
            ch = max(1, self.canvas.winfo_height() - 8)
            tw, th = fit_size(im.width, im.height, cw, ch)
            im = im.resize((tw, th), Image.LANCZOS)
            self.photo = ImageTk.PhotoImage(im)
            self.canvas.delete("all")
            self.canvas.create_image(self.canvas.winfo_width() / 2,
                                     self.canvas.winfo_height() / 2,
                                     image=self.photo, anchor="center")
        except Exception as e:
            self.vstatus.configure(text=f"preview error: {e}", fg=self.C["rest"])

    # -------------------------------------------------------------- export

    def export(self, ask=True):
        if self._busy or not getattr(self, "_enabled", False):
            return
        ops = self._build_ops(include_timing=True)
        if not ops:
            self.vstatus.configure(text="nothing to change yet", fg=self.C["act"])
            return
        target = None
        if ask:
            picked = filedialog.asksaveasfilename(
                parent=self, title="Export edited video",
                defaultextension=".mp4",
                filetypes=[("MP4 video", "*.mp4"), ("All files", "*.*")])
            if not picked:
                self.vstatus.configure(text="export cancelled", fg=self.C["sub"])
                return
            target = picked
        self._busy = True
        self.export_btn.configure(state="disabled", text="WORKING...")
        self.vstatus.configure(text="encoding - this takes a moment",
                               fg=self.C["act"])
        src, keep = self.path, bool(self.audio_var.get())

        def work():
            t0 = time.time()
            try:
                res = M.edit_video(src, ops, out=target, keep_audio=keep)
            except Exception as e:
                res = f"edit_video error: {e}"
            self._job_q.put(("done", res, time.time() - t0))

        threading.Thread(target=work, daemon=True).start()

    def extract_frames(self):
        if self._busy or not getattr(self, "_enabled", False):
            return
        d = filedialog.askdirectory(parent=self, title="Extract frames into folder")
        if not d:
            return
        self._busy = True
        self.vstatus.configure(text="extracting frames...", fg=self.C["act"])
        src, ops = self.path, self._build_ops(include_timing=True)
        ops = ops + [{"op": "extract", "params": {"dir": os.path.abspath(d)}}]

        def work():
            t0 = time.time()
            try:
                res = M.edit_video(src, ops, out=None, keep_audio=False)
            except Exception as e:
                res = f"edit_video error: {e}"
            self._job_q.put(("done", res, time.time() - t0))

        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, res, dt = self._job_q.get_nowait()
                self._busy = False
                self.export_btn.configure(state="normal", text="EXPORT")
                text = str(res or "")
                ok = "saved" in text.lower() or "extracted" in text.lower()
                self.vstatus.configure(text=text, fg=self.C["primary"] if ok else self.C["rest"])
                if ok and self.on_saved:
                    path = text.split(":", 1)[-1].split("(")[0].strip()
                    try:
                        self.on_saved(path, text)
                    except Exception:
                        pass
        except queue.Empty:
            pass
        except Exception:
            pass
        try:
            self.after(150, self._poll)
        except Exception:
            pass


class MediaStudio:
    """Toplevel window: file list, player, editor tabs."""

    def __init__(self, parent, colors, folder=None, on_note=None):
        self.parent = parent
        self.C = colors
        self.on_note = on_note
        # default to NIGHTMARE's own media folder so the studio opens on the
        # pictures and clips the assistant already generated, not an empty list
        if not folder:
            try:
                folder = M.output_dir()
            except Exception:
                folder = None
        self.folder = folder or None
        self.files = []
        self.current = ""

        self.win = tk.Toplevel(parent)
        self.win.title("NIGHTMARE — Media Studio")
        self.win.configure(bg=colors["bg"])
        self.win.geometry("1180x780")
        self.win.minsize(940, 640)
        try:
            self.win.iconbitmap()
        except Exception:
            pass
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        self._build()
        self.refresh()
        self._auto_open()

    # -------------------------------------------------------------- note

    def note(self, text, kind="info"):
        if self.on_note:
            try:
                self.on_note(text, kind)
            except Exception:
                pass
        try:
            self.status.configure(text=text, fg=self.C.get(kind, self.C["sub"]))
        except Exception:
            pass

    # -------------------------------------------------------------- layout

    def _button(self, parent, text, cmd, primary=False, width=None):
        b = tk.Button(parent, text=text, command=cmd,
                      bg=self.C["primary"] if primary else self.C["panel"],
                      fg="#0d0709" if primary else self.C["secondary"],
                      activebackground=self.C["secondary"] if primary else self.C["bg"],
                      activeforeground=self.C["primary"],
                      relief="flat", font=("Segoe UI", 9, "bold" if primary else "normal"),
                      cursor="hand2", bd=0, pady=4, highlightthickness=0,
                      width=width)
        b.pack(side="left", padx=3)
        return b

    def _build(self):
        colors = self.C

        # ---- toolbar
        top = tk.Frame(self.win, bg=colors["panel"])
        top.pack(fill="x", padx=8, pady=(8, 4))
        self._button(top, "OPEN FILES", self.open_files, primary=True)
        self._button(top, "OPEN FOLDER", self.open_folder)
        self._button(top, "REFRESH", self.refresh)
        self.path_lbl = tk.Label(top, text="", bg=colors["panel"], fg=colors["sub"],
                                 font=("Segoe UI", 8), anchor="e")
        self.path_lbl.pack(side="right", padx=6)

        body = tk.Frame(self.win, bg=colors["bg"])
        body.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        # ---- left: file list
        left = tk.Frame(body, bg=colors["panel"], width=210)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Label(left, text="LIBRARY", bg=colors["panel"], fg=colors["primary"],
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x", padx=8,
                                                                pady=(8, 2))
        listwrap = tk.Frame(left, bg=colors["panel"])
        listwrap.pack(fill="both", expand=True, padx=4)
        sb = tk.Scrollbar(listwrap, orient="vertical", width=10,
                          bg=colors["bg"], troughcolor=colors["panel"],
                          activebackground=colors["primary"], bd=0,
                          highlightthickness=0)
        self.listbox = tk.Listbox(listwrap, bg=colors["bg"], fg=colors["text"],
                                  selectbackground=colors["primary"],
                                  selectforeground="#0d0709", bd=0,
                                  highlightthickness=1,
                                  highlightbackground=colors["border"],
                                  font=("Segoe UI", 8), activestyle="none",
                                  exportselection=False, yscrollcommand=sb.set)
        sb.config(command=self.listbox.yview)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.listbox.bind("<<ListboxSelect>>", self._on_pick)

        # ---- right: player + editors
        right = tk.Frame(body, bg=colors["bg"])
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))

        self.player = MediaPlayer(right, colors, on_status=self._on_player_status,
                                  on_meta=self._on_meta, box_w=760, box_h=380)
        self.player.pack(fill="both", expand=True)

        nb = tk.Frame(right, bg=colors["bg"])
        nb.pack(fill="both", expand=False, pady=(6, 0))
        self.tabs = {}
        self.tab_buttons = {}
        names = [("image", "IMAGE EDIT"), ("video", "VIDEO EDIT"), ("info", "INFO")]
        head = tk.Frame(nb, bg=colors["bg"])
        head.pack(fill="x")
        for key, label in names:
            b = tk.Button(head, text=label, command=lambda k=key: self.show_tab(k),
                          bg=colors["panel"], fg=colors["secondary"], relief="flat",
                          font=("Segoe UI", 8, "bold"), cursor="hand2", bd=0,
                          padx=10, pady=3, highlightthickness=0)
            b.pack(side="left", padx=2)
            self.tab_buttons[key] = b
        holder = tk.Frame(nb, bg=colors["bg"], height=230)
        holder.pack(fill="both", expand=True)
        holder.pack_propagate(False)

        self.image_editor = ImageEditor(holder, colors, on_saved=self._on_saved)
        self.video_editor = VideoEditor(holder, colors, on_saved=self._on_saved,
                                        get_player=lambda: self.player)
        self.info_frame = tk.Frame(holder, bg=colors["bg"])
        self.info_text = tk.Label(self.info_frame, text="", bg=colors["bg"],
                                  fg=colors["text"], font=("Consolas", 9),
                                  justify="left", anchor="nw")
        self.info_text.pack(fill="both", expand=True)
        for f in (self.image_editor, self.video_editor, self.info_frame):
            self.tabs[f] = None
        self.tab_frames = {"image": self.image_editor, "video": self.video_editor,
                           "info": self.info_frame}

        self.status = tk.Label(self.win, text="ready", bg=colors["bg"],
                               fg=colors["sub"], font=("Segoe UI", 8), anchor="w")
        self.status.pack(fill="x", padx=10, pady=(2, 6))

        self.show_tab("image")

    # -------------------------------------------------------------- tabs

    def show_tab(self, key):
        for k, frame in self.tab_frames.items():
            try:
                if k == key:
                    frame.pack(fill="both", expand=True)
                else:
                    frame.pack_forget()
            except Exception:
                pass
            try:
                self.tab_buttons[k].configure(
                    bg=self.C["primary"] if k == key else self.C["panel"],
                    fg="#0d0709" if k == key else self.C["secondary"])
            except Exception:
                pass
        if key == "video":
            try:
                self.video_editor._render_preview()
            except Exception:
                pass

    # -------------------------------------------------------------- files

    def refresh(self):
        folder = self.folder
        try:
            self.files = M.list_media(folder) if folder else []
        except Exception:
            self.files = []
        self.listbox.delete(0, "end")
        for p in self.files:
            self.listbox.insert("end", os.path.basename(p))
        self.path_lbl.configure(text=(folder or "no folder")[:70])

    def open_files(self):
        picked = filedialog.askopenfilenames(
            parent=self.win, title="Open media",
            initialdir=self.folder or None,
            filetypes=[("Media", " ".join("*" + e for e in IMAGE_EXTS + VIDEO_EXTS)),
                       ("All files", "*.*")])
        paths = [os.path.abspath(p) for p in (picked or ())]
        if not paths:
            return
        self.folder = os.path.dirname(paths[0])
        self.refresh()
        # open what the user actually picked: it may be absent from the capped
        # listing, and falling through used to open an unrelated newest file
        target = paths[0]
        if target not in self.files:
            self.files.insert(0, target)
            self.listbox.insert(0, os.path.basename(target))
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(0)
        self.listbox.see(0)
        self.open_path(target)

    def open_folder(self):
        picked = filedialog.askdirectory(parent=self.win, title="Open media folder",
                                         initialdir=self.folder or None)
        if picked:
            self.folder = os.path.abspath(picked)
            self.refresh()
            self.note(f"library: {len(self.files)} files", "info")

    def _auto_open(self):
        if not self.files:
            self.note("library is empty - press OPEN FILES", "info")
            return
        self.listbox.selection_set(0)
        self.open_path(self.files[0])

    def _on_pick(self, _evt):
        sel = self.listbox.curselection()
        if sel:
            self.open_path(self.files[sel[0]])

    def open_path(self, path):
        if not path:
            return False
        self.current = path
        kind = M.kind_of(path)
        ok = self.player.load(path)
        self._fill_info()
        if kind == "image":
            self.image_editor.load(path)
            self.show_tab("image")
        elif kind == "video":
            self.video_editor.load(path)
            self.show_tab("video")
        if not ok:
            self.note(f"could not open {os.path.basename(path)}", "error")
        else:
            self.note(M.describe(path), "info")
        return ok

    # -------------------------------------------------------------- callbacks

    def _on_player_status(self, token, detail):
        if token == ST_PLAYING:
            self.note(f"playing {detail}", "info")

    def _on_meta(self, meta):
        self._fill_info()

    def _fill_info(self):
        if not self.current:
            return
        m = M.probe(self.current)
        lines = [
            f"file     : {m.get('name')}",
            f"path     : {m.get('path')}",
            f"type     : {m.get('kind') or 'unknown'}",
            f"exists   : {m.get('exists')}",
        ]
        if m.get("size"):
            lines.append(f"size     : {m['size'] / 1024:.1f} KB")
        if m.get("width"):
            lines.append(f"size     : {m['width']} x {m['height']}"
                         + (f"  ({m.get('format')})" if m.get("format") else ""))
        if m["kind"] == "video":
            lines.append(f"fps      : {m.get('fps')}")
            lines.append(f"frames   : {m.get('frames')}")
            lines.append(f"duration : {_fmt_time(m.get('duration', 0))}")
        if m.get("animated"):
            lines.append(f"frames   : {m.get('frames')} (animated)")
        lines.append("")
        lines.append("describe : " + M.describe(self.current))
        try:
            self.info_text.configure(text="\n".join(lines))
        except Exception:
            pass

    def _on_saved(self, path, message):
        self.note(message, "action")
        self.refresh()
        if path and os.path.isfile(path) and M.kind_of(path):
            self.folder = os.path.dirname(path)
            if path in self.files:
                try:
                    idx = self.files.index(path)
                    self.listbox.selection_clear(0, "end")
                    self.listbox.selection_set(idx)
                except Exception:
                    pass

    # -------------------------------------------------------------- close

    def close(self):
        try:
            self.player.destroy()
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass