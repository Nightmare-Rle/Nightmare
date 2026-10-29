import tkinter as tk
import threading
import sys
import os
import re
import time
import math
import traceback
import sounddevice as sd

# Fix for __file__ when running as exe or via exec
try:
    __file__
except NameError:
    __file__ = "nai_protocol.pyw"

# Get base path for resources (works for exe and script)
if getattr(sys, 'frozen', False):
    BASE_PATH = sys._MEIPASS
else:
    BASE_PATH = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, BASE_PATH)

import tempfile
from tkinter import messagebox

from modules.voice_input import listen, AudioMeter
from modules.voice_output import speak, VOICE_OPTIONS
from modules.time_utils import get_greeting
from modules.system import open_app, open_url
from modules.ai_brain import AIBrain
from modules.google_search import search_and_summarize
from modules.memory import Memory
from modules.vitals import get_vitals, get_monitor
from modules.diagnostics import run_diagnostics
from modules.security_ops import security_scan
from modules.protocols import list_protocols
from modules.language import LANGUAGES, normalize, name_of, t as tr
try:
    from modules import facelock
    FACELOCK_AVAILABLE = True
except Exception:
    facelock = None
    FACELOCK_AVAILABLE = False

# At logon the webcam is frequently still held by another starting app, so a
# camera fault is retried patiently -- it is a technical problem, not an alarm.
FACE_CAMERA_TRIES = 4
FACE_CAMERA_RETRY_MS = 20000
# A face that is not recognised is confirmed twice before anything irreversible
# happens. This is what stands between a bad frame and a lockout.
FACE_CONFIRM_TRIES = 2
FACE_CONFIRM_DELAY_MS = 8000
try:
    from modules import media_view
    MEDIA_AVAILABLE = True
except Exception:
    media_view = None
    MEDIA_AVAILABLE = False

THEMES = {
    "red": {"name": "Red / Black", "primary": "#ff3b3b", "secondary": "#ff9e9e", "dim": "#a51212",
            "bg": "#0d0709", "panel": "#160a0d", "border": "#42161a", "ring": "#4a0f12",
            "text": "#f2d7d7", "sub": "#9a6a6a", "scan": "#ff2a2a", "act": "#ffb000", "rest": "#ff6b6b"},
    "crimson": {"name": "Crimson", "primary": "#e01e37", "secondary": "#ff8a7a", "dim": "#7a0f1c",
                "bg": "#0a0304", "panel": "#160a0b", "border": "#4a1220", "ring": "#3a0a0f",
                "text": "#f7dcd8", "sub": "#9a5f5f", "scan": "#ff2030", "act": "#ffb000", "rest": "#ff6b6b"},
    "cyan": {"name": "Cyber Cyan", "primary": "#00d8ff", "secondary": "#7df9ff", "dim": "#0a6a8a",
             "bg": "#070b12", "panel": "#0b1420", "border": "#143047", "ring": "#0e2c3d",
             "text": "#cfe3f5", "sub": "#5a7a8f", "scan": "#00d8ff", "act": "#ffd600", "rest": "#61dafb"},
    "emerald": {"name": "Emerald", "primary": "#00ff9d", "secondary": "#8effd7", "dim": "#0e7a4d",
                "bg": "#07100b", "panel": "#0d1a12", "border": "#103a2a", "ring": "#0b2b1d",
                "text": "#d7f2e6", "sub": "#5f8f78", "scan": "#00ff9d", "act": "#ffd600", "rest": "#3dffb0"},
    "gold": {"name": "Gold / Amber", "primary": "#ffb000", "secondary": "#ffe08a", "dim": "#8f5f00",
             "bg": "#0d0905", "panel": "#181005", "border": "#3d2b0e", "ring": "#2b1d07",
             "text": "#f5ecdc", "sub": "#9f8a55", "scan": "#ffb000", "act": "#ff7b00", "rest": "#ffd24d"},
    "violet": {"name": "Violet", "primary": "#b388ff", "secondary": "#d6b9ff", "dim": "#5f3ea8",
               "bg": "#0b0713", "panel": "#140e20", "border": "#2e1d4d", "ring": "#1f1140",
               "text": "#e9dcf7", "sub": "#8a72ad", "scan": "#b388ff", "act": "#ffd600", "rest": "#c79fff"},
}


class ChatBox(tk.Text):
    """Message input that grows taller as you type instead of hiding text.

    A one-line Entry scrolls a long message off the right edge, and the window
    is fixed size, so the text simply becomes unreachable. This wraps on word
    boundaries and raises its own height line by line up to MAX_LINES, then
    scrolls internally. Enter sends; Shift+Enter inserts a real newline.
    """

    MAX_LINES = 6

    def __init__(self, master, on_send, **kw):
        self.on_send = on_send
        self._fit_job = None
        # A Text requests 80 columns by default, which is wide enough to claim
        # the whole input row and squeeze the launcher button out of existence.
        # Request a modest width and let expand=True hand it the slack.
        kw.setdefault("wrap", "word")
        kw.setdefault("width", 20)
        kw.setdefault("height", 1)
        kw.setdefault("bd", 0)
        kw.setdefault("relief", "flat")
        kw.setdefault("highlightthickness", 2)
        kw.setdefault("padx", 10)
        kw.setdefault("pady", 10)
        kw.setdefault("undo", True)
        kw.setdefault("exportselection", False)
        kw.setdefault("insertwidth", 2)
        super().__init__(master, **kw)
        self.bind("<Return>", self._on_return)
        self.bind("<KP_Enter>", self._on_return)
        self.bind("<<Modified>>", self._on_modified)
        self.after_idle(self.fit)

    # -------------------------------------------------------------- measuring

    def content_lines(self):
        """How many wrapped rows the current text needs.

        winfo_reqheight() is useless here: for a Text it reports the requested
        height, which is driven by the very 'height' option being solved for, so
        feeding it back grows the box on every pass. Ask Tk to count the display
        lines instead. tkinter's own count() puts its options after the indices
        where Tcl wants them first, hence the raw call.
        """
        try:
            self.update_idletasks()
            n = int(self.tk.call(self._w, "count", "-displaylines",
                                 "1.0", "end-1c"))
            # the count excludes the row holding the final character
            return max(1, min(self.MAX_LINES, n + 1))
        except Exception:
            try:
                return max(1, int(self.cget("height")))
            except Exception:
                return 1

    def fit(self):
        """Resize the box to the rows it needs, no more."""
        self._fit_job = None
        try:
            rows = self.content_lines()
            if int(self.cget("height")) != rows:
                self.configure(height=rows)
            if rows >= self.MAX_LINES:
                self.see("insert")      # capped: keep the caret in view
        except Exception:
            pass

    def _schedule_fit(self):
        # defer so one keystroke re-measures once, not once per character
        if self._fit_job is None:
            try:
                self._fit_job = self.after_idle(self.fit)
            except Exception:
                self.fit()

    # -------------------------------------------------------------- events

    def _on_modified(self, _evt=None):
        if self.edit_modified():
            self.edit_modified(False)
            self._schedule_fit()

    def _on_return(self, event):
        if event.state & 0x0001:        # Shift: let the newline through
            return None
        self.on_send()
        return "break"                  # never let Return add a blank line

    # -------------------------------------------------------------- helpers

    def text_content(self):
        return self.get("1.0", "end-1c")

    def clear(self):
        self.delete("1.0", "end")
        self.fit()


class NightmareAI_GUI:
    def __init__(self, root):
        self.root = root
        self.root.title("NIGHTMARE — N.AI Protocol")
        self.root.geometry("1000x800")
        self.root.resizable(False, False)
        self.root.configure(bg="#0d0709")
        self.root.attributes("-topmost", False)

        self.brain = AIBrain()
        self.brain.set_growth_callback(self._on_grow)
        threading.Thread(target=self.brain.consolidate_pending, daemon=True).start()
        self.is_listening = False
        self.is_processing = False
        self._queued = []
        self._face_busy = False
        self._face_cam_tries = 0
        self._face_confirms = 0
        self.voice_available = self._check_voice()
        self.current_lang = "en"
        self.is_muted = False
        self.mic_enabled = True
        self.master_access = True  # Unrestricted mode

        self.memory = Memory()
        settings = self.memory.settings
        if settings.get("proactive", True):
            self._start_proactive_watcher()
        self.brain.warm_up()
        self.wake_word = str(settings.get("wake_word", "nightmare")).lower()
        self.wake_mode = True
        if settings.get("always_on_top"):
            self.root.attributes("-topmost", True)

        # Sentinel: always-on arc-reactor monitoring (JARVIS presence)
        self.proactive = bool(settings.get("proactive", True))
        self.latest_vitals = None
        if self.proactive:
            mon = get_monitor()
            mon.on_anomaly(self._on_vital_alert)
            mon.start()
        self._poll_vitals()

        # Applied theme
        theme_name = str(settings.get("theme", "red"))
        if theme_name not in THEMES:
            theme_name = "red"
        self.theme_name = theme_name
        self.theme = THEMES[theme_name]
        self._set_theme_tokens()

        # Voice preferences
        self.tts_voice = str(settings.get("tts_voice") or settings.get("edge_voice") or "")
        try:
            self.voice_speed = int(settings.get("voice_speed", 0) or 0)
        except Exception:
            self.voice_speed = 0
        self.voice_speed = max(-30, min(30, self.voice_speed))

        # Audio devices
        self.input_devices, self.output_devices = self._query_devices()
        stored_in = settings.get("input_device")
        self.mic_device = stored_in if isinstance(stored_in, int) and any(
            i == stored_in for i, _ in self.input_devices) else None
        stored_out = str(settings.get("output_device", "") or "")
        self.out_device = stored_out if any(stored_out == n for _, n in self.output_devices) else ""

        # Animation state
        self.ui_state = "idle"          # idle | busy | listening | speaking
        self.ring_a = 0
        self.ring_b = 90
        self.ripples = []
        self._last_ripple = 0.0
        self._speak_timer = None
        self._scan_y = 0
        self._fu_locked = False
        # Audio visualizer state
        self.audio_level = 0.0
        self.viz_level = 0.0
        self.speak_energy = 0.0

        self.LANGUAGES = LANGUAGES

        self._setup_ui()
        # Closing the window must close everything NIGHTMARE started, not
        # just the window.
        try:
            self.root.protocol("WM_DELETE_WINDOW", self._shutdown)
        except Exception:
            pass
        # When unlocked via fingerprint/Windows auth, re-scan face
        try:
            self.root.bind("<Visibility>", lambda e: self._face_rescan_on_unlock())
        except Exception:
            pass
        self.meter = AudioMeter(level_cb=self._set_audio_level, device_index=self.mic_device)
        self.meter.start()
        self._greet()
        # let the greeting land before the camera takes over the start-up
        self.root.after(1500, self._face_gate)
        try:
            self._fu_locked = False
            threading.Thread(target=self._wake_loop, daemon=True).start()
            if hasattr(self, 'wake_btn'):
                try:
                    self.wake_btn.config(text="O", fg="#00ff00")
                except Exception:
                    pass
            try:
                threading.Thread(target=self._mood_check_loop, daemon=True).start()
            except Exception:
                pass
            try:
                threading.Thread(target=self._user_model_loop, daemon=True).start()
            except Exception:
                pass
            try:
                threading.Thread(target=self._proactive_loop, daemon=True).start()
            except Exception:
                pass
        except Exception:
            pass

    # ------------------------------------------------------------- face lock

    def _face_say(self, key, sender="N.AI", tag="sys", **kw):
        text = tr(self.current_lang, key, **kw)
        self.root.after(0, lambda: self._append(sender, text, tag))

    def _unlock_how_text(self):
        """Say what will *actually* unlock the machine.

        The old copy always promised fingerprint-only, but this machine's own
        face_lock.log shows 'fingerprint-state: not_enrolled' - so Windows
        falls back to PIN/password and the old message was simply wrong.
        """
        try:
            if facelock and facelock.fingerprint_fallback_state() == "ready":
                return "Only fingerprint will unlock."
        except Exception:
            pass
        return "Windows will require your PIN or password."

    def _face_gate(self):
        """Startup identity check. Runs on a worker thread; never blocks the UI."""
        if not FACELOCK_AVAILABLE or self._face_busy:
            return
        if facelock.override_active():
            self._face_say("face_override", "SENTINEL",
                           env="%s=1" % facelock.OVERRIDE_ENV)
            return
        if not facelock.is_enabled():
            return
        # The Windows Camera app holds the webcam exclusively. If it is
        # already running, OpenCV cannot open the device and the scan fails
        # for a reason that has nothing to do with the user's face.
        try:
            if facelock:
                facelock.close_camera_app()
        except Exception:
            pass
        self._face_busy = True
        self._face_last_scan = time.time()
        threading.Thread(target=self._face_gate_worker, daemon=True).start()

    def _shutdown(self):
        """Close NIGHTMARE properly.

        Everything that belongs to NIGHTMARE goes with it: the Camera app it
        opened, the applications it launched, and the model of the user it
        has been building. Processes that were already running when it woke
        up are left alone.
        """
        if getattr(self, "_shutting_down", False):
            return
        self._shutting_down = True
        try:
            self._append("N.AI", "Shutting down.", "sys")
        except Exception:
            pass
        # the Camera app holds the webcam; it goes first
        try:
            if facelock:
                facelock.close_camera_app()
        except Exception:
            pass
        try:
            from modules import child_processes
            closed = child_processes.kill_all()
            if closed:
                self._append("N.AI", "Closed: %s" % ", ".join(closed), "sys")
        except Exception:
            pass
        # keep what was learned
        try:
            from modules.user_model import get_user_model
            get_user_model().save()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def _show_camera_live(self, duration_ms=15000):
        """Put the Windows Camera app on screen after a scan.

        The scan itself needs the webcam to itself, so the app is opened
        afterwards - the user sees the live view and the photo that was
        just taken, and the device is released again a few seconds later.
        """
        try:
            if not facelock:
                return
            facelock.open_camera_app()

            def _later():
                try:
                    facelock.close_camera_app()
                except Exception:
                    pass
            self.root.after(duration_ms, _later)
        except Exception:
            pass

    def _face_gate_worker(self):
        try:
            self._face_gate_scan()
        finally:
            self._show_camera_live()

    def _face_gate_scan(self):
        enrolled = facelock.is_enrolled()
        if enrolled:
            result = facelock.verify(max_seconds=12.0)
            status = result.get("status")

            if status == facelock.MATCH:
                # a good read resets the rejection counters: the two-look
                # rule is about *consecutive* bad reads, not a lifetime
                # tally that lets one stray bad read lock later
                self._face_confirms = 0
                self._face_cam_tries = 0
                self._face_last_welcome = time.time()
                self._face_say("face_matched", "SENTINEL")
                try:
                    self.root.after(0, lambda: self._append('NIGHTMARE', 'Welcome, owner.', 'text'))
                    self.root.after(0, lambda: self._speak('Welcome, owner.'))
                except Exception:
                    pass
                self.root.after(0, self._refresh_face_status)
                return

            if status in (facelock.NOMATCH, facelock.NOFACE):
                # Never lock on a single look. NIGHTMARE now starts at every
                # logon, and a bad moment -- half-turned head, backlit window,
                # another app briefly holding the webcam -- would otherwise
                # lock the owner out of their own machine on a guess. Look
                # again before doing anything irreversible.
                if self._face_confirms < FACE_CONFIRM_TRIES:
                    self._face_confirms += 1
                    self._face_busy = False
                    self.root.after(FACE_CONFIRM_DELAY_MS, self._face_gate)
                    return
                unlock_how = self._unlock_how_text()
                if status == facelock.NOMATCH:
                    try:
                        self.root.after(0, lambda: self._append('NIGHTMARE', 'Unknown face detected. Intruder alert. Auto-locking. ' + unlock_how, 'sys'))
                        self.root.after(0, lambda: self._speak('Unknown face detected. Intruder alert. ' + unlock_how))
                    except Exception:
                        pass
                else:
                    try:
                        self.root.after(0, lambda: self._append('NIGHTMARE', 'No one detected. Intruder alert. Auto-locking. ' + unlock_how, 'sys'))
                        self.root.after(0, lambda: self._speak('No one detected. ' + unlock_how))
                    except Exception:
                        pass
                key = ("face_nomatch" if status == facelock.NOMATCH
                       else "face_noface")
                self._face_say(key, "SENTINEL", tag="sys")
                self.root.after(0, lambda: self._append(
                    "N.AI", tr(self.current_lang, "face_locked"), "sys"))
                try:
                    facelock._force_max_volume()
                except Exception:
                    pass
                facelock.escalate(status)
                self._face_confirms = 0
                return

            # anything else -- camera/model trouble -- must not lock anyone out
            if result.get("fault") == "camera" and self._face_cam_tries < FACE_CAMERA_TRIES:
                # at logon the webcam is often still held by whatever else
                # starts with Windows; give it a few chances before giving up
                self._face_cam_tries += 1
                self._face_busy = False
                self.root.after(FACE_CAMERA_RETRY_MS, self._face_gate)
                return

            self._face_say("face_failopen", "SENTINEL",
                           reason=result.get("detail") or status)
            return

        # not enrolled yet: enrol from the camera, then let the session in
        self._face_say("face_enroll_needed", "SENTINEL")
        self._face_say("face_enrolling", "N.AI")
        ok, info = facelock.enroll(max_seconds=25.0)
        if ok:
            self._face_say("face_enrolled", "SENTINEL",
                           samples=info.get("members", 0))
            self._face_say("face_matched", "N.AI")
        else:
            self._face_say("face_enroll_failed", "SENTINEL",
                           reason=info.get("reason", "unknown"))
        self.root.after(0, self._refresh_face_status)

    def _manual_enroll(self):
        """Settings button: enrol on demand."""
        if not FACELOCK_AVAILABLE:
            self._append("N.AI", "Face lock module is unavailable.", "sys")
            return
        if self._face_busy:
            self._append("N.AI", "A face check is already running.", "sys")
            return
        self._face_busy = True
        facelock.set_enabled(True)
        if hasattr(self, "face_lock_var"):
            self.face_lock_var.set(True)
        self._face_say("face_enrolling", "N.AI")

        def work():
            ok, info = facelock.enroll(max_seconds=25.0)
            if ok:
                self._face_say("face_enrolled", "N.AI",
                               samples=info.get("members", 0))
            else:
                self._face_say("face_enroll_failed", "N.AI",
                               reason=info.get("reason", "unknown"))
            self.root.after(0, self._face_done)

        threading.Thread(target=work, daemon=True).start()

    def _manual_forget(self):
        if not FACELOCK_AVAILABLE:
            return
        self._face_say("face_override", "SENTINEL",
                       env="%s=1" % facelock.OVERRIDE_ENV)
        facelock.forget()
        self._refresh_face_status()
        self._append("N.AI", "Enrolled face deleted. "
                              "It will ask to enrol again on the next start.",
                     "sys")

    def _face_done(self):
        self._face_busy = False
        self._refresh_face_status()

    def _refresh_face_status(self):
        if not hasattr(self, "face_status_label") or not FACELOCK_AVAILABLE:
            return
        try:
            if not facelock.is_enabled():
                text, colour = "OFF — no face check at start-up", self.SUB
            elif not facelock.available():
                text, colour = ("UNAVAILABLE — %s" % (facelock.model_error() or
                                                      "models missing"), self.SUB)
            elif facelock.override_active():
                text, colour = "BYPASSED for this run", self.SUB
            elif facelock.is_enrolled():
                text, colour = ("ENROLLED %s — locks on an unrecognised face"
                                % facelock.enrolled_at(), self.PRIMARY)
            else:
                text, colour = "ON but not enrolled yet", self.SECONDARY
            self.face_status_label.config(text=text, fg=colour)
        except Exception:
            pass

    def _refresh_face_fallback(self):
        """Say plainly how you get back in if NIGHTMARE locks the screen.

        Windows decides what the sign-in surface offers; the app can only report
        it accurately. A working sensor with nothing enrolled is the trap worth
        calling out -- it looks like fingerprint is available and is not.
        """
        if not hasattr(self, "face_fallback_label") or not FACELOCK_AVAILABLE:
            return
        try:
            state = facelock.fingerprint_fallback_state()
            if state == "ready":
                text, colour = ("Get back in with your FINGERPRINT on the sensor "
                                "next to the touchpad.", self.SECONDARY)
            elif state == "not_enrolled":
                text, colour = ("NO FINGERPRINT ENROLLED — the sensor works, but "
                                "Windows has no template, so locking drops you to "
                                "PIN/password. Enrol one in Settings > Accounts > "
                                "Sign-in options.", self.SECONDARY)
            else:
                text, colour = ("No fingerprint reader — locking drops you to "
                                "PIN/password.", self.SUB)
            self.face_fallback_label.config(text=text, fg=colour)
        except Exception:
            pass

    # ------------------------------------------------------------------ helpers

    def _check_voice(self):
        try:
            import sounddevice
            return True
        except ImportError:
            return False

    def _set_theme_tokens(self):
        T = self.theme
        self.PRIMARY, self.SECONDARY, self.DIM = T["primary"], T["secondary"], T["dim"]
        self.BG, self.PANEL, self.BORDER = T["bg"], T["panel"], T["border"]
        self.TXT, self.SUB, self.SCAN = T["text"], T["sub"], T["scan"]
        self.ACT, self.REST = T["act"], T["rest"]
        self.RING = T["ring"]

    def _query_devices(self):
        ins, outs = [], []
        try:
            devs = sd.query_devices()
            ins = [(i, d["name"]) for i, d in enumerate(devs) if d.get("max_input_channels", 0) > 0]
            outs = [(i, d["name"]) for i, d in enumerate(devs) if d.get("max_output_channels", 0) > 0]
        except Exception:
            pass
        return ins, outs

    def _short(self, name, n=34):
        return name if len(name) <= n else name[: n - 1] + "…"

    # ------------------------------------------------------------------ UI

    def _setup_ui(self):
        # ---------- Header: arc reactor + centered equalizer ----------
        hdr = tk.Canvas(self.root, bg=self.BG, highlightthickness=0, bd=0, height=220)
        hdr.pack(fill="x", padx=12, pady=(8, 0))
        self.header = hdr
        self.rc = hdr
        self.viz = hdr

        cx, cy = 488, 130
        self.ctx, self.cty = cx, cy
        self.viz_base = cy
        self.viz_top = cy - 72

        # --- new reactor layers (behind the arcs) ---
        # soft outer bloom, stepped ovals so it reads as depth not a flat disc
        self._bloom = []
        for i, (rad, wid) in enumerate(((96, 1), (88, 1), (80, 1))):
            self._bloom.append(hdr.create_oval(
                cx - rad, cy - rad, cx + rad, cy + rad,
                outline=self.RING, width=wid))

        # tick marks around the collar: the mechanical read-out
        self._ticks = []
        for i in range(36):
            a = math.radians(i * 10)
            r0, r1 = 92, 99
            long_tick = (i % 3 == 0)
            self._ticks.append({
                "item": hdr.create_line(
                    cx + math.cos(a) * (r0 if long_tick else r1 + 2),
                    cy + math.sin(a) * (r0 if long_tick else r1 + 2),
                    cx + math.cos(a) * 99,
                    cy + math.sin(a) * 99,
                    fill=self.PRIMARY if long_tick else self.RING,
                    width=2 if long_tick else 1),
                "phase": i * 0.17,
            })

        # orbiting particles: two rings on independent axes
        self._orbiters = []
        for ring, count, radius, speed, size in (
                (0, 5, 62, 1.00, 3),
                (1, 4, 80, -0.62, 2)):
            for i in range(count):
                self._orbiters.append({
                    "item": hdr.create_oval(0, 0, size, size,
                                            fill=self.SECONDARY if i % 2 else self.PRIMARY,
                                            outline=""),
                    "ring": ring, "radius": radius,
                    "phase": (i * (2 * math.pi / count)) + (0.8 if ring else 0.0),
                    "speed": speed, "size": size})

        self.u_glow1 = hdr.create_oval(cx - 84, cy - 84, cx + 84, cy + 84,
                                       outline=self.RING, width=2)
        self.u_glow2 = hdr.create_oval(cx - 74, cy - 74, cx + 74, cy + 74,
                                       outline=self.RING, width=1)
        self.u_main = hdr.create_oval(cx - 38, cy - 38, cx + 38, cy + 38,
                                      outline=self.PRIMARY, width=2)
        self.core = hdr.create_oval(cx - 16, cy - 16, cx + 16, cy + 16,
                                    fill=self.DIM, outline="")
        self.core_hot = hdr.create_oval(cx - 7, cy - 7, cx + 7, cy + 7,
                                        fill=self.PRIMARY, outline="")
        self.arc_a = hdr.create_arc(cx - 38, cy - 38, cx + 38, cy + 38, start=self.ring_a,
                                    extent=70, style=tk.ARC, outline=self.PRIMARY, width=5)
        self.arc_b = hdr.create_arc(cx - 38, cy - 38, cx + 38, cy + 38, start=self.ring_b,
                                    extent=120, style=tk.ARC, outline=self.SECONDARY, width=8)
        self.arc_c = hdr.create_arc(cx - 74, cy - 74, cx + 74, cy + 74, start=0,
                                    extent=52, style=tk.ARC, outline=self.RING, width=2)
        # thinking bracket: four corner arcs that close in while the model works
        self._think_arcs = []
        for extent in (34, 34, 34, 34):
            self._think_arcs.append(
                hdr.create_arc(cx - 60, cy - 60, cx + 60, cy + 60, start=0,
                               extent=extent, style=tk.ARC, outline=self.PRIMARY,
                               width=3, stipple="gray25"))
        self.u_title = hdr.create_text(cx, 26, text="NIGHTMARE", fill=self.TXT,
                                       font=("Segoe UI", 20, "bold"))
        self.status_item = hdr.create_text(8, 8, anchor="nw", text="", fill=self.REST,
                                           font=("Segoe UI", 8, "bold"))

        # ---- explicit state pill: says THINKING or IDLE in words ----
        pill = tk.Frame(hdr, bg=self.BG)
        pill.place(relx=0.5, y=54, anchor="n")
        self.state_pill = pill
        self.state_dot = tk.Canvas(pill, width=13, height=13, bg=self.BG,
                                   highlightthickness=0, bd=0)
        self.state_dot.pack(side="left", padx=(0, 7))
        self.state_dot_item = self.state_dot.create_oval(2, 2, 11, 11,
                                                         fill=self.REST, outline="")
        self.state_lbl = tk.Label(pill, text="IDLE", bg=self.BG, fg=self.REST,
                                  font=("Segoe UI", 9, "bold"))
        self.state_lbl.pack(side="left")
        self._state_pulse = 0.0

        self._build_viz_bars()

        lang_box = tk.Frame(hdr, bg=self.BG)
        lang_box.place(relx=1.0, x=-12, y=10, anchor="ne")
        tk.Label(lang_box, text="LANG", bg=self.BG, fg=self.SUB,
                 font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0, 6))
        self.lang_var = tk.StringVar(value="English")
        self.lang_dropdown = tk.OptionMenu(lang_box, self.lang_var, *self.LANGUAGES.keys(),
                                           command=self._change_language)
        self._style_dropdown(self.lang_dropdown)
        self.lang_dropdown.pack(side="left")

        # ---------- message feed (tile-based HUD) ----------
        self.feed = tk.Canvas(self.root, bg=self.BG, highlightthickness=0, bd=0)
        self.feed.pack(fill="both", expand=True, padx=12, pady=(6, 4))
        self.brackets = self._draw_feed_brackets(self.feed, width=976, height=430)
        self.feed_inner = tk.Frame(self.feed, bg=self.BG)
        self.feed_window = self.feed.create_window((0, 0), window=self.feed_inner, anchor="nw",
                                                   width=960)
        self.feed_inner.bind("<Configure>", lambda e: self.feed.configure(
            scrollregion=self.feed.bbox("all")))
        self.feed.bind("<Configure>", self._fit_feed_chrome)
        self.feed.bind_all("<MouseWheel>", self._on_feed_wheel)

        self.scan_line = self.feed.create_line(0, 0, 976, 0, fill=self.SCAN, width=1,
                                               stipple="gray50")
        self.feed.tag_lower(self.scan_line)

        # ---------- input row ----------
        input_frame = tk.Frame(self.root, bg=self.BG)
        input_frame.pack(fill="x", padx=12, pady=(0, 14))
        self.input_frame = input_frame

        self.entry = ChatBox(
            input_frame, on_send=self._handle_text,
            bg=self.PANEL, fg=self.TXT, insertbackground=self.PRIMARY,
            font=("Segoe UI", 12),
            highlightbackground=self.BORDER, highlightcolor=self.PRIMARY)
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # ---------- pop-left action launcher ----------
        self.icons_overlay = tk.Frame(self.root, bg=self.PANEL, highlightthickness=2,
                                      highlightbackground=self.BORDER)

        self.btn_style = dict(font=("Segoe UI Emoji", 15), bg=self.PANEL, fg=self.SECONDARY,
                              relief="flat", activebackground=self.BG,
                              activeforeground=self.PRIMARY, cursor="hand2", width=3)

        def icon(text, cmd):
            b = tk.Button(self.icons_overlay, text=text, **self.btn_style, command=cmd)
            b.pack(side="left", ipady=7, padx=(3, 3))
            return b

        self.mic_btn = icon("\U0001f3a4", self._toggle_mic)
        if not self.voice_available:
            self.mic_btn.configure(state="disabled", fg="#3a2424")
        self.reset_btn = icon("\U0001f504", self._reset_chat)
        self.mute_btn = icon("\U0001f50a", self._toggle_mute)
        self.screen_btn = icon("\U0001f5b1", self._analyze_screen)
        self.master_btn = icon("\U0001f513", self._toggle_master_access)
        self.wake_btn = icon("\U0001f319", self._toggle_wake)
        if not self.voice_available:
            self.wake_btn.configure(state="disabled", fg="#3a2424")
        # Settings used to live only inside the hidden action strip, so it read
        # as missing. Pinned to the top-left corner where it is always visible
        # and reachable without opening the launcher first.
        self.settings_btn = tk.Button(
            hdr, text="\u2699", command=self._toggle_settings,
            font=("Segoe UI Emoji", 15), bg=self.BG, fg=self.SECONDARY,
            relief="flat", activebackground=self.PANEL,
            activeforeground=self.PRIMARY, cursor="hand2", width=3)
        self.settings_btn.place(x=14, y=10)
        self.diag_btn = icon("\U0001f6e1", self._run_diagnostics)
        self.cam_btn = icon("\U0001f4f7", self._scan_mood)
        self.media_btn = icon("\U0001f3ac", self._open_media_studio)
        if not MEDIA_AVAILABLE:
            self.media_btn.configure(state="disabled", fg="#3a2424")
        self.icons_overlay.place_forget()

        self.launcher_btn = tk.Button(input_frame, text="\u2630", font=self.btn_style["font"],
                                      command=self._toggle_icons, bg=self.BG,
                                      fg=self.SECONDARY, relief="flat",
                                      activebackground=self.PANEL,
                                      activeforeground=self.PRIMARY, cursor="hand2", width=3)
        self.launcher_btn.pack(side="right", ipady=9, padx=(0, 8), anchor="s")

        self._build_settings_panel()
        self._refresh_voice_options()
        self._restore_settings()
        self._update_status()
        self.root.after(30, self._animate)

    def _restore_settings(self):
        saved = str(self.memory.settings.get("language") or "en")
        saved = saved.replace("#", "").lower()
        for name, code in self.LANGUAGES.items():
            if saved in (code, code.replace("#", "").lower()):
                self._change_language(name)
                return
        try:
            self.lang_var.set([k for k, v in self.LANGUAGES.items() if v == "en"][0])
        except Exception:
            pass

    def _build_viz_bars(self):
        self.viz_bars = []
        self.viz_x = []
        cx = self.ctx
        lo = 16
        hi = 976
        xranges = []
        for x in range(lo, cx - 100, 12):
            xranges.append(x)
        for x in range(cx + 100, hi, 12):
            xranges.append(x)
        for x in xranges:
            self.viz_x.append(x)
            r = self.viz.create_rectangle(x, self.viz_base, x + 8, self.viz_base,
                                          fill=self.PRIMARY if len(self.viz_bars) % 2 == 0
                                          else self.DIM, outline="")
            self.viz_bars.append(r)

    def _draw_feed_brackets(self, canvas, width, height):
        """Corner brackets around the feed.

        These are anchored to the feed's edges, so they must be re-fitted
        whenever the feed resizes: the chat box growing shrinks the feed.
        """
        c = self.BORDER
        self._bracket_m = 14
        self._bracket_b = 26
        return [canvas.create_line(*p, fill=c, width=2)
                for p in self._bracket_points(width, height)]

    def _bracket_points(self, width, height):
        m = getattr(self, "_bracket_m", 14)
        b = getattr(self, "_bracket_b", 26)
        return [(m, m, m + b, m),
                (m, m, m, m + b),
                (width - m, m, width - m - b, m),
                (width - m, m, width - m, m + b),
                (m, height - m, m + b, height - m),
                (m, height - m, m, height - m - b),
                (width - m, height - m, width - m - b, height - m),
                (width - m, height - m, width - m, height - m - b)]

    def _fit_feed_chrome(self, _evt=None):
        """Keep brackets and the scan line pinned to the live feed size."""
        w = self.feed.winfo_width()
        h = self.feed.winfo_height()
        if w <= 1 or h <= 1:
            return
        try:
            self.feed.itemconfig(self.feed_window, width=w - 16)
            for i, p in enumerate(self._bracket_points(w, h)):
                self.feed.coords(self.brackets[i], *p)
            self.feed.coords(self.scan_line, 0, self._scan_y, w, self._scan_y)
        except Exception:
            pass

    def _style_dropdown(self, om):
        om.config(bg=self.PANEL, fg=self.PRIMARY, activebackground=self.BG,
                  activeforeground=self.SECONDARY, font=("Segoe UI", 9),
                  relief="flat", highlightthickness=1, highlightbackground=self.BORDER)
        om["menu"].config(bg=self.PANEL, fg=self.TXT, activebackground=self.BORDER,
                          activeforeground="#000000", font=("Segoe UI", 9))

    def _style_settings_controls(self):
        for w in (self.settings_overlay,):
            w.configure(bg="#0b0203", highlightbackground=self.PRIMARY)
        for label in self.ov_section_labels:
            label.configure(bg=self.PANEL, fg=self.SECONDARY)
        for label in self.ov_caption_labels:
            label.configure(bg=self.PANEL, fg=self.SUB)
        self.ov_title.configure(bg="#120405", fg=self.TEXT_SAFE if hasattr(self, "TEXT_SAFE") else self.TXT)
        for om in self.ov_menus:
            self._style_dropdown(om)
        self.ov_speed.configure(bg=self.PANEL, fg=self.TXT, troughcolor=self.BORDER,
                                highlightthickness=0, activebackground=self.PRIMARY)
        self.ov_speed_label.configure(bg=self.PANEL, fg=self.PRIMARY)
        for b in self.ov_buttons:
            b.configure(bg=self.PANEL, fg=self.SECONDARY, activebackground=self.BG,
                        activeforeground=self.PRIMARY)

    # ------------------------------------------------------------ settings overlay

    def _settings_wheel(self, event):
        """Scroll the settings panel. Returns "break" so the chat feed's own
        wheel binding never also fires while the panel is under the pointer."""
        canvas = getattr(self, "_settings_canvas", None)
        if canvas is None:
            return "break"
        try:
            canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        except Exception:
            return "break"
        return "break"

    def _bind_settings_wheel(self):
        """Bind the wheel across the whole panel.

        Tk sends a wheel event to the widget under the pointer only, so binding
        just the canvas leaves every label, row and dropdown dead. The previous
        Enter/Leave approach called unbind_all, which silently removed the chat
        feed's own <MouseWheel> binding for the rest of the session, so the
        panel is bound once here and never unbound globally.
        """
        if getattr(self, "_wheel_bound", False):
            return
        self._wheel_bound = True

        def bind_tree(w):
            try:
                w.bind("<MouseWheel>", self._settings_wheel, add="+")
            except Exception:
                pass
            for child in w.winfo_children():
                bind_tree(child)

        bind_tree(self.settings_overlay)

    def _rebind_settings_wheel(self, _event=None):
        # Widgets created after the first open (the live fingerprint warning)
        # still need the wheel, so refresh the tree each time it is shown.
        self._wheel_bound = False
        self._bind_settings_wheel()

    def _on_mic_device(self, _evt=None):
        """Save the chosen microphone so the next launch stops guessing."""
        picked = None
        label = (self.mic_var.get() if hasattr(self, "mic_var") else "") or ""
        if "[" in label and label.endswith("]"):
            try:
                picked = int(label.rsplit("[", 1)[1].rstrip("]").strip())
            except Exception:
                picked = None
        self.mic_device = picked
        try:
            self.memory.settings["input_device"] = picked if picked is not None else ""
            self.memory.save_settings()
        except Exception:
            pass
        try:
            self.meter.device_index = picked
        except Exception:
            pass
        self._mic_status("Microphone set to: %s" % (label or "system default"))

    def _mic_status(self, text, colour=None):
        try:
            self.mic_status_label.config(text=text,
                                         fg=colour or self.SUB)
        except Exception:
            pass

    def _test_mic(self):
        """Record a second and report the peak level, so 'it can't hear me'
        becomes a number on screen instead of a guess."""
        if getattr(self, "_mic_testing", False):
            return
        self._mic_testing = True
        self._mic_status("Listening for 3 seconds — say something…", self.PRIMARY)

        def work():
            import numpy as np
            peak = 0.0
            detail = ""
            try:
                from modules.voice_input import SoundDeviceMicrophone, _default_input_device
                dev = self.mic_device
                if dev is None:
                    dev = _default_input_device()
                chunks = []
                with SoundDeviceMicrophone(device_index=dev, sample_rate=16000) as mic:
                    import time as _t
                    end = _t.time() + 3.0
                    while _t.time() < end:
                        chunks.append(mic.read(1600))
                data = b"".join(chunks)
                a = np.frombuffer(data, dtype=np.int16).astype("float64") / 32768.0
                if len(a):
                    peak = float(np.abs(a).max())
                detail = "device %s" % dev
            except Exception as e:
                detail = "%s: %s" % (type(e).__name__, str(e)[:60])
            self.root.after(0, lambda: self._mic_test_done(peak, detail))

        threading.Thread(target=work, daemon=True).start()

    def _mic_test_done(self, peak, detail):
        self._mic_testing = False
        if peak <= 0.00002:
            self._mic_status("No sound at all — wrong microphone, or it is muted "
                             "in Windows. (%s)" % detail, self.SUB)
        elif peak < 0.01:
            self._mic_status("Very quiet — it can hear something but barely. "
                             "Raise input volume in Windows. (peak %.3f)" % peak, self.SECONDARY)
        else:
            self._mic_status("Microphone works. (peak %.3f, %s)" % (peak, detail),
                             self.PRIMARY)

    def _build_settings_panel(self):
        ov = tk.Frame(self.root, bg="#0b0203", highlightthickness=2,
                      highlightbackground=self.PRIMARY)
        self.settings_overlay = ov

        head = tk.Frame(ov, bg="#120405")
        head.pack(fill="x", pady=(8, 0), padx=8)
        self.ov_title = tk.Label(head, text="⚙  SYSTEM SETTINGS", bg="#120405", fg=self.TXT,
                                 font=("Segoe UI", 13, "bold"))
        self.ov_title.pack(side="left", padx=6)
        tk.Button(head, text="✕", font=("Segoe UI", 11, "bold"), bg="#120405", fg=self.PRIMARY,
                  relief="flat", activebackground="#2a0e12", activeforeground="#ffffff",
                  cursor="hand2", command=self._toggle_settings).pack(side="right", padx=4)

        # The settings stack is taller than the window, so the lower sections
        # were simply unreachable. Everything lives on one canvas window so the
        # whole panel scrolls, and the wheel only scrolls while the pointer is
        # over it.
        wrap = tk.Frame(ov, bg=self.PANEL)
        wrap.pack(fill="both", expand=True, padx=6, pady=6)

        canvas = tk.Canvas(wrap, bg=self.PANEL, highlightthickness=0, bd=0)
        self._settings_canvas = canvas
        vbar = tk.Scrollbar(wrap, orient="vertical", command=canvas.yview,
                            bg=self.PANEL, troughcolor=self.BG,
                            activebackground=self.PRIMARY, relief="flat",
                            highlightthickness=0, bd=0, width=11)
        canvas.configure(yscrollcommand=vbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        vbar.pack(side="right", fill="y")

        body = tk.Frame(canvas, bg=self.PANEL)
        self._settings_body = body
        body_win = canvas.create_window((0, 0), window=body, anchor="nw")

        def _sync_scrollregion(_evt=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _sync_width(evt):
            canvas.itemconfigure(body_win, width=evt.width)

        body.bind("<Configure>", _sync_scrollregion)
        canvas.bind("<Configure>", _sync_width)

        self.ov_section_labels, self.ov_caption_labels, self.ov_menus = [], [], []
        self.ov_buttons = []

        def section(text):
            sec = tk.Label(body, text=text, bg=self.PANEL, fg=self.SECONDARY,
                           font=("Segoe UI", 9, "bold"))
            sec.pack(fill="x", pady=(3, 0))
            self.ov_section_labels.append(sec)

        def row(text):
            f = tk.Frame(body, bg=self.PANEL)
            f.pack(fill="x", pady=2)
            tk.Label(f, text=text, bg=self.PANEL, fg=self.SUB,
                     font=("Segoe UI", 8)).pack(side="left")
            return f

        section("ENGINE")
        r = row("AI ENGINE")
        self.engine_var = tk.StringVar()
        self.st_engine = tk.OptionMenu(r, self.engine_var,
                                       "LOCAL (Ollama)", "GROQ (Fast)",
                                       command=self._on_engine)
        self._style_dropdown(self.st_engine)
        self.st_engine.pack(side="right", ipady=1, padx=(10, 0))
        self.ov_menus.append(self.st_engine)
        eng_lbl = "GROQ (Fast)" if self.brain.config.get("engine", "groq") != "ollama" else "LOCAL (Ollama)"
        self.engine_var.set(eng_lbl)

        section("VOICE ENGINE")
        r = row("TTS VOICE")
        self.voice_var = tk.StringVar()
        self.st_voice = tk.OptionMenu(r, self.voice_var, "en-US-GuyNeural",
                                      command=self._on_voice)
        self._style_dropdown(self.st_voice)
        self.st_voice.pack(side="right", ipady=1, padx=(10, 0))
        self.ov_menus.append(self.st_voice)

        r = row("VOICE SPEED")
        self.ov_speed_label = tk.Label(r, text=f"± {self.voice_speed:+d}%", bg=self.PANEL,
                                       fg=self.PRIMARY, font=("Segoe UI", 9, "bold"))
        self.ov_speed_label.pack(side="right", padx=(10, 0))
        self.ov_speed = tk.Scale(body, from_=-30, to=30, resolution=1, orient="horizontal",
                                 bg=self.PANEL, fg=self.TXT, troughcolor=self.BORDER,
                                 highlightthickness=0, activebackground=self.PRIMARY,
                                 command=self._on_speed, length=300)
        self.ov_speed.set(self.voice_speed)
        self.ov_speed.pack(fill="x", pady=(0, 2))

        test = tk.Button(body, text="▶  TEST VOICE", bg=self.PANEL, fg=self.SECONDARY,
                         relief="flat", activebackground=self.BG, activeforeground=self.PRIMARY,
                         cursor="hand2", command=self._test_voice)
        test.pack(fill="x", ipady=4, pady=(3, 0))
        self.ov_buttons.append(test)

        r = row("MICROPHONE")
        self.mic_var = tk.StringVar()
        mic_names = ([f"{n}  [{i}]" for i, n in self.input_devices] or ["default"])
        self.st_mic = tk.OptionMenu(r, self.mic_var, *mic_names,
                                    command=self._on_mic_device)
        self._style_dropdown(self.st_mic)
        self.st_mic.pack(side="right", ipady=1, padx=(10, 0))
        self.ov_menus.append(self.st_mic)
        try:
            if self.mic_device is not None:
                self.mic_var.set(f"{self.input_devices[self.mic_device][1]}  "
                                 f"[{self.mic_device}]")
            else:
                self.mic_var.set(mic_names[0])
        except Exception:
            self.mic_var.set(mic_names[0])

        self.mic_status_label = tk.Label(body, text="", bg=self.PANEL, fg=self.SUB,
                                         anchor="w", font=("Segoe UI", 8, "italic"),
                                         wraplength=380, justify="left")
        self.mic_status_label.pack(fill="x", pady=(2, 0))
        self.ov_caption_labels.append(self.mic_status_label)

        mt = tk.Button(body, text="🎤  TEST MICROPHONE", bg=self.PANEL, fg=self.SECONDARY,
                       relief="flat", activebackground=self.BG, activeforeground=self.PRIMARY,
                       cursor="hand2", command=self._test_mic)
        mt.pack(fill="x", ipady=4, pady=(3, 0))
        self.ov_buttons.append(mt)

        section("INTERFACE")
        r = row("THEME")
        self.theme_var = tk.StringVar(value=THEMES[self.theme_name]["name"])
        self.st_theme = tk.OptionMenu(r, self.theme_var,
                                      *[t["name"] for t in THEMES.values()],
                                      command=self._on_theme)
        self._style_dropdown(self.st_theme)
        self.st_theme.pack(side="right", ipady=1, padx=(10, 0))
        self.ov_menus.append(self.st_theme)

        section("AUDIO DEVICES")
        self.in_options = [("Default", None)] + [(f"{i} — {self._short(n)}", i) for i, n in self.input_devices]
        self.in_var = tk.StringVar()
        r = row("MIC INPUT")
        self.st_in = tk.OptionMenu(r, self.in_var, *[lbl for lbl, _ in self.in_options],
                                   command=self._on_input)
        self._style_dropdown(self.st_in)
        self.st_in.pack(side="right", ipady=1, padx=(10, 0))
        self.ov_menus.append(self.st_in)
        self._select_in_var()

        self.out_options = [("Default", "")] + [(f"{i} — {self._short(n)}", n) for i, n in self.output_devices]
        self.out_var = tk.StringVar()
        r = row("SPK OUTPUT")
        self.st_out = tk.OptionMenu(r, self.out_var, *[lbl for lbl, _ in self.out_options],
                                    command=self._on_output)
        self._style_dropdown(self.st_out)
        self.st_out.pack(side="right", ipady=1, padx=(10, 0))
        self.ov_menus.append(self.st_out)
        self._select_out_var()

        section("SECURITY")
        self.face_lock_var = tk.BooleanVar(
            value=bool(facelock.is_enabled()) if FACELOCK_AVAILABLE else False)
        chk = tk.Checkbutton(body, text="LOCK LAPTOP IF FACE NOT RECOGNISED",
                             variable=self.face_lock_var, bg=self.PANEL,
                             fg=self.SUB, selectcolor=self.BG, anchor="w",
                             activebackground=self.PANEL,
                             activeforeground=self.SUB, highlightthickness=0,
                             bd=0, font=("Segoe UI", 8),
                             command=self._toggle_face_lock)
        chk.pack(fill="x", pady=(1, 0))
        self.ov_buttons.append(chk)

        self.face_status_label = tk.Label(body, text="", bg=self.PANEL,
                                          fg=self.SUB, anchor="w",
                                          font=("Segoe UI", 8, "italic"))
        self.face_status_label.pack(fill="x", pady=(1, 0))
        self.ov_caption_labels.append(self.face_status_label)

        btns = tk.Frame(body, bg=self.PANEL)
        btns.pack(fill="x", pady=(2, 0))
        enrol = tk.Button(btns, text="ENROL MY FACE", bg=self.PANEL,
                          fg=self.SECONDARY, relief="flat",
                          activebackground=self.BG, activeforeground=self.PRIMARY,
                          font=("Segoe UI", 8, "bold"), cursor="hand2",
                          command=self._manual_enroll)
        enrol.pack(side="left", ipady=3, expand=True, fill="x")
        forget = tk.Button(btns, text="FORGET", bg=self.PANEL, fg=self.SUB,
                           relief="flat", activebackground=self.BG,
                           activeforeground=self.PRIMARY, font=("Segoe UI", 8),
                           cursor="hand2", command=self._manual_forget)
        forget.pack(side="left", ipady=3, expand=True, fill="x", padx=(6, 0))

        self.face_fallback_label = tk.Label(body, text="", bg=self.PANEL,
                                            fg=self.SUB, anchor="w",
                                            font=("Segoe UI", 8, "italic"),
                                            wraplength=380, justify="left")
        self.face_fallback_label.pack(fill="x", pady=(6, 0))
        self.ov_caption_labels.append(self.face_fallback_label)
        self._refresh_face_fallback()
        self.ov_buttons.extend([enrol, forget])

        self.ov_note_label = tk.Label(body, text="Changes apply automatically.",
                                       bg=self.PANEL, fg=self.PRIMARY,
                                       font=("Segoe UI", 8, "italic"))
        self.ov_note_label.pack(anchor="w", pady=(4, 0))
        self.ov_caption_labels.append(self.ov_note_label)

        save = tk.Button(body, text="\U0001f4be  SAVE SETTINGS", bg=self.PANEL,
                         fg=self.PRIMARY, relief="flat", font=("Segoe UI", 9, "bold"),
                         activebackground=self.BG, activeforeground="#00ff00",
                         cursor="hand2", command=self._save_settings)
        save.pack(fill="x", ipady=4, pady=(6, 2))
        self.ov_buttons.append(save)

        self.settings_overlay.place_forget()

    def _toggle_face_lock(self):
        if not FACELOCK_AVAILABLE:
            self.face_lock_var.set(False)
            self._append("N.AI", "Face lock module is unavailable.", "sys")
            return
        on = bool(self.face_lock_var.get())
        facelock.set_enabled(on)
        self._refresh_face_status()
        self._append("N.AI", "Face lock is ON. An unrecognised face locks the "
                             "laptop at start-up." if on else
                             "Face lock is OFF. The laptop will not be locked.",
                     "sys")

    def _select_in_var(self):
        for lbl, val in self.in_options:
            if val == self.mic_device:
                self.in_var.set(lbl)
                return
        self.in_var.set("Default")

    def _select_out_var(self):
        for lbl, val in self.out_options:
            if val == self.out_device:
                self.out_var.set(lbl)
                return
        self.out_var.set("Default")

    def _toggle_icons(self):
        p = self.icons_overlay
        if p.winfo_ismapped():
            p.place_forget()
            return
        p.update_idletasks()
        w = p.winfo_reqwidth()
        h = p.winfo_reqheight()
        x0 = self.launcher_btn.winfo_rootx() - self.root.winfo_rootx()
        y0 = self.launcher_btn.winfo_rooty() - self.root.winfo_rooty()
        x = x0 - w - 6
        y = y0 + (self.launcher_btn.winfo_height() - h) // 2
        if x < 8:
            x = 8
        if x + w > self.root.winfo_width() - 8:
            x = self.root.winfo_width() - w - 8
        p.place(x=x, y=y)

    def _toggle_settings(self):
        ov = self.settings_overlay
        if ov.winfo_ismapped():
            ov.place_forget()
            return
        self._refresh_face_status()
        self._bind_settings_wheel()
        ov.update_idletasks()
        w = 420
        # The rows now live inside a canvas window, so they no longer count
        # towards the overlay's requested height. Sizing the panel from
        # winfo_reqheight() alone therefore squeezed every setting into the
        # canvas's small default request. Measure the real content instead and
        # only fall back to scrolling when it exceeds the window.
        body = getattr(self, "_settings_body", None)
        canvas = getattr(self, "_settings_canvas", None)
        if body is not None and canvas is not None:
            chrome = max(0, ov.winfo_reqheight() - canvas.winfo_reqheight())
            natural = body.winfo_reqheight() + chrome + 2
        else:
            natural = ov.winfo_reqheight()
        avail = self.root.winfo_height() - 16
        h = max(260, min(natural, avail))
        x0 = self.settings_btn.winfo_rootx() - self.root.winfo_rootx()
        y0 = self.settings_btn.winfo_rooty() - self.root.winfo_rooty()
        # anchored under the gear, which now lives in the top-left corner
        x = x0
        y = y0 + self.settings_btn.winfo_height() + 6
        if x + w > self.root.winfo_width() - 8:
            x = max(8, self.root.winfo_width() - w - 8)
        if y + h > self.root.winfo_height() - 8:
            y = max(8, self.root.winfo_height() - h - 8)
        ov.place(x=x, y=y, width=w, height=h)
        self._style_settings_controls()
        self._select_in_var()
        self._select_out_var()

    # ------------------------------------------------------------ theme

    def _on_theme(self, name_label):
        for tname, t in THEMES.items():
            if t["name"] == name_label:
                self._apply_theme(tname)
                break

    def _apply_theme(self, name):
        self.theme_name = name
        self.theme = THEMES[name]
        self._set_theme_tokens()
        self.memory.settings["theme"] = name
        self.memory.save_settings()

        self.root.configure(bg=self.BG)
        self.header.configure(bg=self.BG)
        self.input_frame.configure(bg=self.BG)
        self.viz.configure(bg=self.BG)
        self.rc.configure(bg=self.BG)
        self.feed.configure(bg=self.BG)
        self.feed_inner.configure(bg=self.BG)

        self.rc.itemconfig(self.u_glow1, outline=self.RING)
        self.rc.itemconfig(self.u_glow2, outline=self.RING)
        self.rc.itemconfig(self.u_main, outline=self.PRIMARY)
        self.rc.itemconfig(self.core, fill=self.DIM)
        self.rc.itemconfig(self.arc_a, outline=self.PRIMARY)
        self.rc.itemconfig(self.arc_b, outline=self.SECONDARY)
        self.rc.itemconfig(self.arc_c, outline=self.RING)
        self.rc.itemconfig(self.u_title, fill=self.TXT)
        self.feed.itemconfig(self.scan_line, fill=self.SCAN)
        for bid in self.brackets:
            self.feed.itemconfig(bid, fill=self.BORDER)
        for i, rid in enumerate(self.viz_bars):
            self.viz.itemconfig(rid, fill=self.PRIMARY if i % 2 == 0 else self.DIM)

        self.entry.configure(bg=self.PANEL, fg=self.TXT, insertbackground=self.PRIMARY,
                             highlightbackground=self.BORDER, highlightcolor=self.PRIMARY,
                             selectbackground=self.RING, selectforeground=self.TXT)
        self.lang_var.set([k for k, v in self.LANGUAGES.items() if v == self.current_lang][0])
        self._style_dropdown(self.lang_dropdown)
        for b in (self.mic_btn, self.reset_btn, self.mute_btn, self.screen_btn,
                  self.master_btn, self.wake_btn, self.diag_btn,
                  self.cam_btn, self.media_btn):
            b.configure(bg=self.PANEL, fg=self.SECONDARY, activebackground=self.BG,
                        activeforeground=self.PRIMARY)
        if not MEDIA_AVAILABLE:
            self.media_btn.configure(fg="#3a2424")
        # the reactor's extra layers recolour themselves every frame in _animate,
        # but the pill is a plain widget and needs telling
        for w in (getattr(self, "state_pill", None), self.state_dot, self.state_lbl):
            if w is not None:
                w.configure(bg=self.BG)
        self.icons_overlay.configure(bg=self.PANEL, highlightbackground=self.BORDER)
        self.launcher_btn.configure(bg=self.BG, fg=self.SECONDARY, activebackground=self.PANEL,
                                    activeforeground=self.PRIMARY)
        # the gear sits on the reactor canvas, so it matches the launcher, not
        # the launcher-strip buttons
        self.settings_btn.configure(bg=self.BG, fg=self.SECONDARY,
                                    activebackground=self.PANEL,
                                    activeforeground=self.PRIMARY)
        self._style_settings_controls()
        self._update_status()

    # ------------------------------------------------------------ voice/device settings

    def _refresh_voice_options(self):
        opts = VOICE_OPTIONS.get(self.current_lang, VOICE_OPTIONS["en"])
        menu = self.st_voice["menu"]
        menu.delete(0, "end")
        for o in opts:
            menu.add_command(label=o, command=tk._setit(self.voice_var, o, self._on_voice))
        if self.tts_voice not in opts:
            self.tts_voice = opts[0]
            # Keep the saved voice in step with the language. Without this the
            # stale voice stays in settings.json, gets written back on the next
            # save, and speaks the wrong language for everything that reads it
            # back rather than using the live value.
            self.memory.settings["tts_voice"] = self.tts_voice
            self.memory.settings["edge_voice"] = self.tts_voice
        self.voice_var.set(self.tts_voice)

    def _on_voice(self, vname):
        self.tts_voice = vname
        self.memory.settings["tts_voice"] = vname
        self.memory.settings["edge_voice"] = vname
        self.memory.save_settings()

    def _on_speed(self, val):
        try:
            v = int(val)
        except Exception:
            v = 0
        self.voice_speed = max(-30, min(30, v))
        self.memory.settings["voice_speed"] = self.voice_speed
        self.memory.save_settings()
        self.ov_speed_label.config(text=f"± {self.voice_speed:+d}%")

    def _on_input(self, label):
        for lbl, val in self.in_options:
            if lbl == label:
                self.mic_device = val
                break
        self.memory.settings["input_device"] = self.mic_device
        self.memory.save_settings()
        self._restart_meter()

    def _on_output(self, label):
        for lbl, val in self.out_options:
            if lbl == label:
                self.out_device = val
                break
        self.memory.settings["output_device"] = self.out_device
        self.memory.save_settings()

    def _start_proactive_watcher(self):
        def loop():
            while True:
                time.sleep(120)
                try:
                    import psutil
                    bat = psutil.sensors_battery()
                    if bat is not None and not bat.power_plugged and bat.percent <= 20:
                        pct = int(bat.percent)
                        self.root.after(0, lambda p=pct: self._append(
                            "SYSTEM", f"Battery is at {p}% and not charging.", "sys"))
                    vm = psutil.virtual_memory()
                    if vm.percent >= 90:
                        pct = int(vm.percent)
                        self.root.after(0, lambda p=pct: self._append(
                            "SYSTEM", f"RAM usage is at {p}%.", "sys"))
                except Exception:
                    pass
                try:
                    from modules import autonomy
                    for label, msg in autonomy.tick():
                        self.root.after(0, lambda l=label, m=msg: self._append(
                            "AUTONOMY" if l != "WATCH" else "WATCH", m, "sys"))
                except Exception:
                    pass
        threading.Thread(target=loop, daemon=True).start()

    def _on_engine(self, label):
        eng = "ollama" if label.startswith("LOCAL") else "groq"
        if eng == self.brain.config.get("engine", "groq"):
            return
        self.brain.set_engine(eng)
        label_txt = "local Ollama (uncensored, slower)" if eng == "ollama" else "Groq (fast, cloud)"
        self._append("N.AI", f"Engine set to {label_txt}. Conversation reset.", "sys")
        self._update_status()

    def _save_settings(self):
        s = self.memory.settings
        v = self.voice_var.get()
        s["tts_voice"] = v
        s["edge_voice"] = v
        try:
            sp = int(self.ov_speed.get())
        except Exception:
            sp = 0
        sp = max(-30, min(30, sp))
        self.voice_speed = sp
        s["voice_speed"] = sp
        for tname, t in THEMES.items():
            if t["name"] == self.theme_var.get():
                s["theme"] = tname
                break
        for lbl, val in self.in_options:
            if lbl == self.in_var.get():
                s["input_device"] = val
                break
        for lbl, val in self.out_options:
            if lbl == self.out_var.get():
                s["output_device"] = val
                break
        try:
            s["language"] = self.LANGUAGES[self.lang_var.get()]
        except Exception:
            pass
        self.memory.save_settings()
        try:
            self.ov_note_label.config(text="\u2713  Settings saved.")
            self.root.after(1800, lambda: self.ov_note_label.config(text="Changes apply automatically."))
        except Exception:
            pass

    def _restart_meter(self):
        self._pause_meter()
        self.meter = AudioMeter(level_cb=self._set_audio_level, device_index=self.mic_device)
        self._resume_meter()

    def _test_voice(self):
        self._speak(f"Voice test. I am {self.tts_voice or 'your assistant'}, speaking at "
                    f"{self.voice_speed:+.0f} percent speed.", self.current_lang)

    # ------------------------------------------------------------ feed

    def _on_feed_wheel(self, event):
        # bound with bind_all, so this fires for the entire window. The chat box
        # is a Text that can scroll once it hits its line cap, so let the widget
        # under the pointer handle its own wheel instead of yanking the feed.
        try:
            w = self.root.winfo_containing(event.x_root, event.y_root)
        except Exception:
            w = None
        while w is not None and w is not self.root:
            if isinstance(w, tk.Text):
                return
            w = getattr(w, "master", None)
        if event.delta > 0:
            self.feed.yview_scroll(-3, "units")
        else:
            self.feed.yview_scroll(3, "units")

    def _feed_scroll_px(self):
        try:
            self.feed.yview_moveto(1.0)
        except Exception:
            pass

    def _make_tile(self, sender, tag_type="text"):
        """Create the message tile chrome and return (tile, body label).

        Shared by normal replies and streamed ones so a streaming reply is
        visually identical to a completed one.
        """
        FONT = "Segoe UI"
        styles = {
            "user": (self.BORDER, self.SECONDARY, self.TXT),
            "jarvis": (self.BORDER, self.PRIMARY, self.TXT),
            "text": (None, None, self.TXT),
            "search": (None, None, self.SECONDARY),
            "action": (None, None, self.ACT),
            "sys": (None, None, self.SUB),
        }
        if sender == "You":
            badge_bg, badge_fg = styles["user"][0], styles["user"][1]
        else:
            badge_bg, badge_fg = styles["jarvis"][0], styles["jarvis"][1]
        body_fg = styles.get(tag_type, styles["text"])[2]

        tile = tk.Frame(self.feed_inner, bg=self.PANEL, highlightthickness=1,
                        highlightbackground=self.BORDER)
        tile.pack(fill="x", padx=6, pady=6)

        head = tk.Frame(tile, bg=self.PANEL)
        head.pack(fill="x", padx=12, pady=(7, 2))
        tk.Label(head, text=f"  {sender.upper()}  ", bg=badge_bg, fg=badge_fg,
                 font=(FONT, 8, "bold")).pack(side="left")
        tk.Label(head, text=time.strftime("%H:%M:%S"), bg=self.PANEL, fg=self.SUB,
                 font=(FONT, 8)).pack(side="right")

        body = tk.Label(tile, text="", bg=self.PANEL, fg=body_fg, font=(FONT, 11),
                        justify="left", anchor="w", wraplength=self._tile_width(),
                        padx=12, pady=8)
        body.configure(font=(FONT, 10, "italic") if tag_type in ("action", "sys") else (FONT, 11))
        body.pack(fill="x")
        return tile, body

    def _open_stream_tile(self, sender="N.AI", tag_type="text"):
        """Open a reply tile that later chunks fill in, rather than animating."""
        tile, body = self._make_tile(sender, tag_type)
        self._feed_scroll_px()
        return tile, body

    def _close_stream_tile(self, tile, body, text, sender="N.AI"):
        if body is not None:
            try:
                body.configure(text=text or "")
            except Exception:
                pass
        self._media_cards(tile, text, sender)
        self.root.after(20, self._feed_scroll_px)

    def _append(self, sender, text, tag_type="text"):
        if not text:
            return
        tile, body = self._make_tile(sender, tag_type)

        if sender != "You":
            self._stream_text(body, text)
        else:
            body.configure(text=text)
        self._media_cards(tile, text, sender)
        self.root.after(20, self._feed_scroll_px)

    def _tile_width(self):
        try:
            w = self.feed.winfo_width()
        except Exception:
            w = 0
        return max(260, (w or 976) - 64)

    def _stream_text(self, label, full):
        n = len(full)
        if n <= 120:
            label.configure(text=full)
            label.update_idletasks()
            return
        chunk = max(4, n // 150)
        delay = max(6, 38 - len(full) // 90)
        pos = 0

        def step():
            nonlocal pos
            pos += chunk
            label.configure(text=full[:pos])
            if pos < n:
                self.root.after(delay, step)
            else:
                self.root.after(20, self._feed_scroll_px)

        step()
        self.root.after(20, self._feed_scroll_px)

    def _clear_feed(self):
        for child in self.feed_inner.winfo_children():
            child.destroy()

    # ------------------------------------------------------------ media studio

    def _open_media_studio(self, path=None):
        """Open (or raise) the media studio, optionally focused on a file."""
        if not MEDIA_AVAILABLE:
            self._append("N.AI", "Media studio is unavailable on this build.",
                         "sys")
            return None
        try:
            if not self.root.winfo_exists():
                return None
        except Exception:
            return None
        if getattr(self, "_studio", None) is not None:
            try:
                if self._studio.win.winfo_exists():
                    self._studio.win.lift()
                    self._studio.win.focus_force()
                    if path:
                        self._studio.folder = os.path.dirname(
                            os.path.abspath(path)) or self._studio.folder
                        self._studio.refresh()
                        if os.path.abspath(path) not in self._studio.files:
                            self._studio.files.insert(0, os.path.abspath(path))
                            self._studio.listbox.insert(0, os.path.basename(path))
                        self._studio.open_path(os.path.abspath(path))
                    return self._studio
            except Exception:
                self._studio = None
        try:
            self._studio = media_view.MediaStudio(
                self.root,
                {"primary": self.PRIMARY, "secondary": self.SECONDARY, "dim": self.DIM,
                 "bg": self.BG, "panel": self.PANEL, "border": self.BORDER,
                 "ring": self.RING, "text": self.TXT, "sub": self.SUB,
                 "scan": self.SCAN, "act": self.ACT, "rest": self.REST,
                 "info": self.SUB, "action": self.ACT, "error": self.REST},
                folder=(os.path.dirname(os.path.abspath(path)) if path else None),
                on_note=self._studio_note)
            if path:
                target = os.path.abspath(path)
                if target not in self._studio.files:
                    self._studio.files.insert(0, target)
                    self._studio.listbox.insert(0, os.path.basename(target))
                self._studio.open_path(target)
            return self._studio
        except Exception as e:
            self._append("N.AI", f"Could not open the media studio: {e}", "sys")
            return None

    def _studio_note(self, text, kind="info"):
        self._append("STUDIO", str(text), "sys")

    _MEDIA_RE = re.compile(
        r"[^\s\"'<>|,;()\[\]]*?\.(?:png|jpe?g|bmp|gif|webp|tiff?|mp4|avi|mkv|mov|webm|m4v)\b",
        re.I)

    # characters that may legitimately appear inside a path, used when growing a
    # candidate leftwards past the space in "my clip.mp4"
    _PATH_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
                      "0123456789 _\\/-:.~")

    def _media_candidates(self, text):
        """Find real media files named in a message.

        A regex alone is not enough. It cannot span the space in a path like
        'my media folder\\my clip.mp4', and it happily includes leading prose.
        So the token ending in the extension is grown leftwards one character at
        a time and checked against disk: exactly one candidate can be the real
        file, so the first one that exists is the answer.
        """
        from modules import media as M
        found, seen = [], set()
        text = text or ""
        for m in self._MEDIA_RE.finditer(text):
            end = m.end()
            start = m.start()
            hit = None
            # the token exactly as matched is the shortest candidate: check it
            # first, otherwise a path at the very start of the message (or one
            # sitting right after a quote) never gets tested at all
            cand = text[start:end].strip()
            if cand and os.path.isfile(os.path.abspath(os.path.expanduser(cand))) \
                    and M.is_media(cand):
                hit = cand
            while hit is None and start > 0 and (end - start) < 300:
                ch = text[start - 1]
                if ch not in self._PATH_CHARS:
                    break
                start -= 1
                try:
                    cand = os.path.abspath(
                        os.path.expanduser(text[start:end].strip()))
                except Exception:
                    continue
                if os.path.isfile(cand) and M.is_media(cand):
                    hit = cand
            if hit:
                ap = os.path.abspath(os.path.expanduser(hit))
                key = os.path.normcase(ap)
                if key not in seen:
                    seen.add(key)
                    found.append(ap)
        return found

    def _media_cards(self, parent, text, sender):
        """Attach clickable cards for any media file mentioned in a reply."""
        try:
            if not MEDIA_AVAILABLE or not text or sender == "You":
                return
            for ap in self._media_candidates(text)[:4]:
                self._media_card(parent, ap)
        except Exception:
            pass

    def _media_card(self, tile, path):
        """One inline preview: thumbnail, label, and a button into the studio."""
        from modules import media as M
        try:
            kind = M.kind_of(path)
            thumb = M.thumbnail(path, 300)
            card = tk.Frame(tile, bg=self.PANEL)
            card.pack(fill="x", padx=10, pady=(0, 10))

            shot = None
            if thumb is not None:
                from PIL import ImageTk
                shot = ImageTk.PhotoImage(thumb)
            holder = tk.Frame(card, bg="#000000", highlightthickness=1,
                              highlightbackground=self.BORDER)
            holder.pack(side="left", padx=(0, 10))
            if shot is not None:
                lbl = tk.Label(holder, image=shot, bg="#000000", bd=0)
                lbl.image = shot          # keep the reference alive
                lbl.pack()
                lbl.bind("<Button-1>", lambda e, p=path: self._open_media_studio(p))
            else:
                tk.Label(holder, text="no preview", bg="#000000", fg=self.SUB,
                         font=("Segoe UI", 8), width=18).pack(padx=8, pady=14)

            info = tk.Frame(card, bg=self.PANEL)
            info.pack(side="left", fill="both", expand=True)
            name = os.path.basename(path)
            tk.Label(info, text=name[:46], bg=self.PANEL,
                     fg=self.TXT, font=("Segoe UI", 9, "bold"),
                     anchor="w").pack(fill="x")
            # build the caption from probe() fields: describe() joins with
            # "name: ...", so slicing it just leaves a stray colon behind
            detail = ""
            try:
                meta = M.probe(path)
                if not meta.get("exists"):
                    detail = "not found"
                elif meta.get("error"):
                    detail = str(meta.get("error"))
                else:
                    bits = ["%sx%s" % (meta.get("width"), meta.get("height"))]
                    if meta.get("kind") == "image":
                        if meta.get("format"):
                            bits.append(str(meta.get("format")))
                        if meta.get("animated"):
                            bits.append("%s frames" % meta.get("frames"))
                    else:
                        bits.append("%.1fs" % float(meta.get("duration") or 0))
                        bits.append("%.2ffps" % float(meta.get("fps") or 0))
                    detail = ", ".join(bits)
            except Exception:
                detail = ""
            tk.Label(info, text=detail[:70], bg=self.PANEL, fg=self.SUB,
                     font=("Segoe UI", 8), anchor="w").pack(fill="x")
            badge = "VIDEO" if kind == "video" else "IMAGE"
            acts = tk.Frame(info, bg=self.PANEL)
            acts.pack(fill="x", pady=(6, 0))
            tk.Label(acts, text=badge, bg=self.PANEL, fg=self.ACT,
                     font=("Segoe UI", 7, "bold")).pack(side="left", padx=(0, 8))
            tk.Button(acts, text="OPEN" + (" ▶" if kind == "video" else ""),
                      command=lambda p=path: self._open_media_studio(p),
                      bg=self.PANEL, fg=self.SECONDARY, activebackground=self.BG,
                      activeforeground=self.PRIMARY, relief="flat",
                      font=("Segoe UI", 8, "bold"), cursor="hand2", bd=0,
                      highlightthickness=1, highlightbackground=self.BORDER,
                      padx=8, pady=2).pack(side="left")
            if kind == "video":
                tk.Button(acts, text="EXTERN",
                          command=lambda p=path: self._open_externally(p),
                          bg=self.PANEL, fg=self.SUB, activebackground=self.BG,
                          activeforeground=self.PRIMARY, relief="flat",
                          font=("Segoe UI", 8), cursor="hand2", bd=0,
                          highlightthickness=1, highlightbackground=self.BORDER,
                          padx=8, pady=2).pack(side="left", padx=(6, 0))
        except Exception:
            pass

    def _open_externally(self, path):
        try:
            if os.name == "nt":
                os.startfile(path)          # noqa: S606 - user-initiated
            elif sys.platform == "darwin":
                os.system('open "%s"' % path)
            else:
                os.system('xdg-open "%s"' % path)
        except Exception as e:
            self._append("N.AI", f"Could not open {os.path.basename(path)}: {e}",
                         "sys")

    # ------------------------------------------------------------ state + animation

    def _set_state(self, state):
        self.ui_state = state
        self._update_status()

    _STATE_WORDS = {"idle": "IDLE", "busy": "THINKING", "thinking": "THINKING",
                    "listening": "LISTENING", "speaking": "SPEAKING"}

    def _update_status(self):
        tag = {"idle": self.REST, "busy": self.ACT, "listening": self.PRIMARY,
               "speaking": self.SECONDARY, "thinking": self.ACT}.get(
                   self.ui_state, self.REST)
        self.rc.itemconfig(self.status_item, fill=tag)
        word = self._STATE_WORDS.get(self.ui_state, "IDLE")
        try:
            self.state_lbl.configure(text=word, fg=tag)
            self.state_dot.itemconfig(self.state_dot_item, fill=tag)
        except Exception:
            pass
        self._state_pulse = 0.0

    def _poll_vitals(self):
        try:
            self.latest_vitals = get_vitals()
            self._update_status()
        except Exception:
            pass
        self.root.after(20000, self._poll_vitals)

    def _on_vital_alert(self, msg):
        if (self.is_processing or self.is_listening or not self.proactive):
            return
        self.root.after(0, lambda: self._append("SENTINEL", f"⚠ {msg}", "sys"))
        try:
            self._speak(msg)
        except Exception:
            pass

    def _run_diagnostics(self):
        def work():
            report = run_diagnostics()
            self.root.after(0, lambda: self._append("DIAGNOSTICS", report, "action"))
            try:
                self._speak("Diagnostics complete. Vitals nominal for now.")
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _scan_mood(self):
        if self.is_processing:
            return
        self._append("N.AI", "Taking a look at you...", "text")
        self.is_processing = True
        threading.Thread(target=self._do_mood_scan, daemon=True).start()

    def _do_mood_scan(self):
        try:
            from modules.vision import analyze_mood
            reading = analyze_mood()
            self.root.after(0, lambda r=reading: self._append("SENSES", r, "action"))
            self._speak(str(reading))
        except Exception as e:
            self.root.after(0, lambda: self._append("SENSES", f"Camera error: {e}", "sys"))
        finally:
            self.is_processing = False
            self.root.after(400, self._drain_queue)

    def _on_grow(self, new_facts):
        self.root.after(0, lambda: self._append(
            "BRAIN", f"🧠 logged {new_facts} new fact(s) to C:\\BRAIN", "sys"))

    def _mark_speaking(self, text):
        if text:
            self.speak_energy = min(1.0, 0.35 + len(text) / 260)
            self._set_state("speaking")
            if self._speak_timer:
                self.root.after_cancel(self._speak_timer)
            dur = 3 + min(45, int(len(text) / 14))
            self._speak_timer = self.root.after(int(dur * 1000), self._speak_done)

    def _speak_done(self):
        self._set_state("busy" if self.is_processing else "idle")
        if self.wake_mode and not self.is_processing and not self.is_listening:
            self.root.after(600, self._try_followup)

    def _animate(self):
        cx, cy = self.ctx, self.cty
        now = time.monotonic()
        state = self.ui_state
        thinking = state in ("busy", "thinking")
        speed = {"idle": 1.4, "busy": 6.0, "thinking": 6.0, "listening": 8.5,
                 "speaking": 5.0}.get(state, 1.5)
        self.ring_a = (self.ring_a + speed) % 360
        self.ring_b = (self.ring_b - speed * 0.6) % 360
        self.rc.itemconfig(self.arc_a, start=self.ring_a)
        self.rc.itemconfig(self.arc_b, start=self.ring_b)
        self.rc.itemconfig(self.arc_c, start=self.ring_a * 0.5)

        if state == "idle":
            self.rc.itemconfig(self.core_hot,
                               fill=self.DIM if int(self.ring_a) % 2 == 0 else self.PRIMARY)
        else:
            self.rc.itemconfig(self.core_hot,
                               fill=self.SECONDARY if state == "listening" else self.PRIMARY)

        # ---- breathing bloom: the core inhales when idle, flares when busy ----
        base_r = 84 if thinking else (92 if state in ("listening", "speaking") else 80)
        breath = math.sin(now * (3.4 if thinking else 1.1)) * (7 if thinking else 3)
        for i, item in enumerate(self._bloom):
            r = base_r + breath + i * 4
            self.rc.coords(item, cx - r, cy - r, cx + r, cy + r)
            self.rc.itemconfig(
                item, fill="",
                outline=self.PRIMARY if thinking else self.RING,
                width=1)

        # ---- collar ticks sweep; fast while thinking ----
        sweep = now * (2.6 if thinking else 0.5)
        for tick in self._ticks:
            lit = (math.sin(sweep + tick["phase"]) > 0.55)
            self.rc.itemconfig(
                tick["item"],
                fill=self.PRIMARY if lit else self.RING)

        # ---- orbiting particles ----
        for orb in self._orbiters:
            spd = orb["speed"] * (2.4 if thinking else 1.0)
            ang = orb["phase"] + now * spd
            wob = math.sin(now * 1.7 + orb["phase"]) * 3
            r = orb["radius"] + wob
            px = cx + math.cos(ang) * r
            py = cy + math.sin(ang) * r * 0.92      # slight ellipse
            s = orb["size"]
            self.rc.coords(orb["item"], px - s / 2, py - s / 2, px + s / 2, py + s / 2)
            bright = 0.55 + 0.45 * math.sin(now * 3.0 + orb["phase"] * 2)
            self.rc.itemconfig(
                orb["item"],
                fill=self.SECONDARY if bright > 0.75 else self.PRIMARY)

        # ---- thinking brackets: contract, then snap open, over and over ----
        for i, item in enumerate(self._think_arcs):
            if thinking:
                phase = (now * 0.9 + i * 0.25) % 1.0
                extent = 22 + 62 * abs(math.sin(now * 3.2 + i * 1.6))
                start = 45 + i * 90 + phase * 24
                self.rc.itemconfig(item, start=start, extent=extent,
                                   outline=self.ACT, stipple="")
                self.rc.coords(item, cx - 60, cy - 60, cx + 60, cy + 60)
            else:
                self.rc.itemconfig(item, outline=self.RING, stipple="gray25")

        if thinking and now - self._last_ripple > 0.16:
            self._last_ripple = now
            self.ripples.append({"item": self.rc.create_oval(
                cx, cy, cx, cy, outline=self.ACT, width=2), "t": now})
        if state in ("listening", "speaking") and now - self._last_ripple > 0.4:
            self._last_ripple = now
            self.ripples.append({"item": self.rc.create_oval(
                cx, cy, cx, cy, outline=self.PRIMARY, width=2), "t": now})
        kept = []
        for rp in self.ripples:
            age = now - rp["t"]
            if age <= 1.1:
                r = 6 + age * 88
                if r <= 102:
                    self.rc.coords(rp["item"], cx - r, cy - r, cx + r, cy + r)
                    self.rc.itemconfig(rp["item"], width=max(1, int(9 - age * 8)))
                    kept.append(rp)
                else:
                    self.rc.delete(rp["item"])
            else:
                self.rc.delete(rp["item"])
        self.ripples = kept

        # ---- state pill pulse: the dot throbs so "thinking" is unmissable ----
        try:
            self._state_pulse += 0.09
            amp = 0.5 + 0.5 * math.sin(self._state_pulse * (0.14 if thinking else 0.05))
            r = 4 + amp * (2.5 if thinking else 1.2)
            self.state_dot.coords(self.state_dot_item, 6.5 - r, 6.5 - r,
                                  6.5 + r, 6.5 + r)
        except Exception:
            pass

        # ---- audio visualizer ----
        if state == "speaking":
            peak = self.speak_energy * (0.6 + 0.4 * math.sin(now * 11))
        elif state == "listening":
            peak = self.audio_level
        else:
            peak = self.audio_level * 0.5
        self.viz_level = self.viz_level * 0.78 + peak * 0.22
        self.speak_energy = max(0.0, self.speak_energy - 0.004)
        for i, rid in enumerate(self.viz_bars):
            wave = 0.5 + 0.5 * math.sin(now * 1.3 + i * 0.55)
            maxh = self.viz_base - self.viz_top - 6
            hgt = 3 + self.viz_level * maxh * (0.3 + 0.7 * wave)
            x = self.viz_x[i]
            self.viz.coords(rid, x, self.viz_base - hgt, x + 8, self.viz_base)

        h = self.feed.winfo_height()
        w = self.feed.winfo_width()
        if h > 0:
            self._scan_y = (self._scan_y + 2.2) % max(h, 1)
            self.feed.coords(self.scan_line, 0, self._scan_y, w, self._scan_y)

        self.root.after(33, self._animate)

    def _set_audio_level(self, v):
        self.audio_level = min(1.0, v)

    def _pause_meter(self):
        try:
            self.meter.stop()
        except Exception:
            pass

    def _resume_meter(self):
        try:
            self.meter.start()
        except Exception:
            pass

    # ------------------------------------------------------------ interaction

    def _greet(self):
        greeting = tr(self.current_lang, "greeting")
        self._append("NIGHTMARE", greeting, "text")
        self._speak(greeting)

    def _toggle_wake(self):
        if not self.wake_mode:
            self.wake_mode = True
            self._fu_locked = False
            self.wake_btn.config(text="O", fg="#00ff00")
            self._append("N.AI", f"Wake mode ON. Say \"{self.wake_word}\" to activate.", "sys")
            self._speak(f"Wake mode on. Always listening for {self.wake_word}.")
            threading.Thread(target=self._wake_loop, daemon=True).start()
        else:
            self.wake_mode = True
            self._fu_locked = True
            self.wake_btn.config(text="\U0001f319", fg=self.SECONDARY)
            self._append("N.AI", "Wake mode OFF.", "sys")
            self._speak("Wake mode off.")
        self._update_status()

    def _wake_loop(self):
        while self.wake_mode:
            if self.is_processing or self.is_listening or not self.voice_available:
                time.sleep(0.5)
                continue
            try:
                self._pause_meter()
                try:
                    heard = listen(self.current_lang, level_cb=self._set_audio_level,
                                   device_index=self.mic_device)
                finally:
                    self._resume_meter()
            except Exception:
                heard = ""
            if not heard:
                continue
            if self.wake_word in heard:
                self._fu_locked = False
                self.root.after(0, lambda: self._append("N.AI", "Wake word detected. Listening...", "sys"))
                try:
                    self._pause_meter()
                    try:
                        cmd = listen(self.current_lang, level_cb=self._set_audio_level,
                                     device_index=self.mic_device)
                    finally:
                        self._resume_meter()
                except Exception:
                    cmd = ""
                if cmd and cmd != "exit" and not self.is_processing:
                    self._process(cmd)

    def _handle_text(self):
        text = self.entry.text_content().strip()
        if self._kill_code(text):
            return
        if not text:
            return
        self.entry.clear()
        if self.is_processing:
            self._queued.append(text)
            self._append("N.AI", f"[queued] {text}", "sys")
            return
        self._fu_locked = True
        self._process(text)

    def _drain_queue(self):
        if self.is_processing or self.is_listening or not self._queued:
            return
        nxt = self._queued.pop(0)
        if self._kill_code(nxt):
            return
        self._process(nxt)

    def _toggle_mic(self):
        self.mic_enabled = not getattr(self, 'mic_enabled', True)
        if self.mic_enabled:
            self.mic_btn.configure(bg=self.PANEL, fg=self.SECONDARY)
            self._append("N.AI", "Microphone ON.", "sys")
            if self.voice_available:
                self.mic_btn.bind("<Enter>", lambda e: self._tip("Click to speak (voice input)"))
            self._set_state("idle")
        else:
            if self.is_listening:
                self.is_listening = False
            self.mic_btn.configure(bg=self.BG, fg="#ff4444")
            self._append("N.AI", "Microphone OFF.", "sys")
            self.mic_btn.bind("<Enter>", lambda e: self._tip("Microphone OFF - click to turn ON"))
            self._set_state("idle")

    def _toggle_voice(self):
        if getattr(self, 'mic_enabled', True) is False:
            self.mic_btn.configure(bg=self.BG, fg="#ff4444")
            self._append("N.AI", "Microphone OFF. Toggle it ON first.", "sys")
            return
        if self.is_listening or self.is_processing or not self.voice_available:
            return
        self.is_listening = True
        self.mic_btn.configure(bg=self.PRIMARY, fg="#ffffff")
        self._append("N.AI", "Listening...", "text")
        self._set_state("listening")
        self._pause_meter()
        threading.Thread(target=self._listen_voice, daemon=True).start()

    def _listen_voice(self):
        text = None
        try:
            text = listen(self.current_lang, level_cb=self._set_audio_level,
                          device_index=self.mic_device)
        except Exception as e:
            self.root.after(0, lambda: self._append("N.AI", f"Voice error: {str(e)}", "sys"))
        finally:
            self.is_listening = False
            self._resume_meter()
            self.root.after(0, lambda: self.mic_btn.configure(bg=self.PANEL, fg=self.SECONDARY))
            self.root.after(0, lambda: self._set_state("idle"))
        if text and text != "exit":
            if self._kill_code(text):
                return
            self._process(text)
        elif not text:
            # Previously this branch did nothing at all, so a failed
            # recognition looked exactly like "the mic ignored me".
            self.root.after(0, lambda: self._append(
                "N.AI", "I didn't catch that. Your mic level looks fine, so this "
                        "was a speech-recognition failure - see voice.log", "sys"))

    def _kill_code(self, text):
        if text and "daydream" in str(text).lower().split():
            try:
                self._speak("Shutting down.")
            except Exception:
                pass
            os._exit(0)
            return True
        return False

    def _process(self, text):
        self._append("You", text, "text")
        self.is_processing = True
        self._set_state("busy")
        threading.Thread(target=self._route, args=(text,), daemon=True).start()

    def _route(self, text):
        text_lower = text.lower()

        if any(w in text_lower for w in ["exit", "quit", "goodbye", "shut down"]):
            self.root.after(0, lambda: self._append("N.AI", "Shutting down.", "text"))
            self._speak("Shutting down.")
            self.is_processing = False
            self.root.after(2000, self._shutdown)
            return

        box = {"tile": None, "body": None, "opened": False}

        def on_text(full):
            # called on the brain's worker thread; hand it to tkinter
            def apply(f=full):
                try:
                    if not box["opened"]:
                        box["tile"], box["body"] = self._open_stream_tile("N.AI", "text")
                        box["opened"] = True
                    if box["body"] is not None:
                        box["body"].configure(text=f)
                        self._feed_scroll_px()
                except Exception:
                    pass
            try:
                self.root.after(0, apply)
            except Exception:
                pass

        try:
            try:
                self.brain.set_stream_sink(on_text)
            except Exception:
                pass
            response = self.brain.ask(text)
        except Exception as e:
            self.root.after(0, lambda: self._append("N.AI", f"Error: {str(e)}", "text"))
            return
        finally:
            try:
                self.brain.set_stream_sink(None)
            except Exception:
                pass
            self.is_processing = False

        def finish():
            try:
                if box["opened"]:
                    # never leave a half-typed tile behind if the model changed
                    # its mind after the first token
                    self._close_stream_tile(box["tile"], box["body"], response, "N.AI")
                else:
                    self._append("N.AI", response, "text")
                self._speak(response)
            except Exception:
                pass

        self.root.after(0, finish)

        def _settle():
            if self.ui_state == "busy":
                self._set_state("idle")

        self.root.after(0, _settle)
        self.root.after(400, self._drain_queue)

    def _try_followup(self):
        if (not self.wake_mode or self.is_processing or self.is_listening
                or self._fu_locked or not self.voice_available):
            return
        self._fu_locked = True
        self._pause_meter()
        self._set_state("listening")
        self.root.after(0, lambda: self._append("N.AI", "Listening for follow-up...", "sys"))

        def grab():
            try:
                cmd = listen(self.current_lang, level_cb=self._set_audio_level,
                             device_index=self.mic_device)
            except Exception:
                cmd = ""
            finally:
                self._resume_meter()
                self._fu_locked = False
                self.root.after(0, lambda: self._set_state("idle"))
            if cmd and cmd not in ("", "exit") and not self.is_processing:
                if self.wake_word in cmd:
                    cmd = cmd.replace(self.wake_word, "", 1).strip()
                if cmd:
                    self._process(cmd)

        threading.Thread(target=grab, daemon=True).start()

    def _mood_check_loop(self):
        from modules import vision
        import random
        while True:
            try:
                time.sleep(random.randint(8, 15))
                if self.is_processing or self.is_listening:
                    continue
                try:
                    res = vision.analyze_mood()
                    txt = str(res).lower()
                    # Nothing worth saying, or the camera is busy - stay quiet.
                    if ('no face' in txt or 'room' in txt
                            or txt.startswith('i can see')
                            or 'no camera device' in txt
                            or 'returned no frames' in txt
                            or 'poorly lit' in txt):
                        continue
                    # the mood is part of the model of the user
                    try:
                        from modules.user_model import get_user_model
                        um = get_user_model()
                        for word in ('happy', 'content', 'neutral', 'composed'):
                            if word in txt:
                                um.note_mood(word)
                                break
                    except Exception:
                        pass
                    # sarcastic comments
                    snark = [
                        f'Hm. {res} Interesting.',
                        f'Caught you. {res}',
                        f"Ah, so that's your face right now. {res}",
                        f'Yeah, I see that. {res}',
                        f'Thought so. {res}',
                        f'Not fooling me. {res}',
                        f'{res} ...what are you plotting?',
                        f'{res} Don\'t look at me like that.',
                    ]
                    out = random.choice(snark)
                    self.root.after(0, lambda o=out: self._append('NIGHTMARE', o, 'text'))
                except Exception:
                    pass
            except Exception:
                time.sleep(10)

    def _proactive_loop(self):
        """Notice things before being asked - rarely.

        Jarvis observes. The rules that keep this from being annoying: at
        most one observation every 20 minutes, each kind of problem on its
        own cooldown (so a low battery never spams), and only thresholds
        that changed into trouble - never a running commentary.
        """
        try:
            from modules.vitals import get_vitals
        except Exception:
            return
        cooldown = {}
        try:
            while not getattr(self, "_shutting_down", False):
                time.sleep(300)
                if getattr(self, "_shutting_down", False):
                    break
                now = time.time()
                if now - getattr(self, "_proactive_last", 0.0) < 1200:
                    continue
                try:
                    issues = get_vitals().anomalies()
                except Exception:
                    continue
                for kind, text in issues:
                    if now - cooldown.get(kind, 0.0) < self._proactive_cooldown(kind):
                        continue
                    cooldown[kind] = now
                    self._proactive_last = now
                    try:
                        self.root.after(0, lambda t=text: self._append('NIGHTMARE', t, 'sys'))
                        self.root.after(0, lambda t=text: self._speak(t))
                    except Exception:
                        pass
                    break       # one observation per window, never a stream
        except Exception:
            pass

    def _proactive_cooldown(self, kind):
        return {"battery": 1800, "temp": 3600, "cpu": 3600, "ram": 3600,
                "disk": 43200}.get(kind, 3600)

    def _face_rescan_on_unlock(self):
        """Re-scan face after unlock (e.g. fingerprint unlock).

        The <Visibility> event fires on every overlap change, not only on a
        real unlock, so this used to run back-to-back scans - each one
        speaking "Welcome, owner." again - and, worse, it escalated on a
        single bad read while the start-up gate demands two. Throttled to
        one look per 45s; the two-look rule is enforced in the worker.
        """
        try:
            if not FACELOCK_AVAILABLE or not facelock.is_enabled():
                return
            if getattr(self, "_face_rescanning", False):
                return
            now = time.time()
            if now - getattr(self, "_face_last_scan", 0.0) < 45.0:
                return
            self._face_last_scan = now
            self._face_rescanning = True
            threading.Thread(target=self._face_rescan_worker, daemon=True).start()
        except Exception:
            self._face_rescanning = False

    def _face_rescan_worker(self):
        try:
            import time as _t
            _t.sleep(1)
            if not facelock.is_enrolled():
                return
            res = facelock.verify(max_seconds=8.0)
            st = res.get("status")
            if st == facelock.MATCH:
                # a good read resets the counter, and the welcome is announced
                # at most once per two minutes instead of on every event
                self._face_confirms = 0
                if _t.time() - getattr(self, "_face_last_welcome", 0.0) > 120.0:
                    self._face_last_welcome = _t.time()
                    self.root.after(0, lambda: self._append('NIGHTMARE', 'Welcome, owner. (re-scanned)', 'text'))
                    self.root.after(0, lambda: self._speak('Welcome, owner.'))
            elif st in (facelock.NOMATCH, facelock.NOFACE):
                # Same standard as start-up: never lock on a single look.
                # This path used to escalate immediately on one bad read,
                # which is exactly how the machine got locked at 17:50 after
                # clean matches seconds earlier.
                self._face_confirms = getattr(self, "_face_confirms", 0) + 1
                if self._face_confirms < FACE_CONFIRM_TRIES:
                    self.root.after(0, lambda: self._append('NIGHTMARE', 'Unverified look - checking again before deciding.', 'sys'))
                    _t.sleep(FACE_CONFIRM_DELAY_MS / 1000.0)
                    res2 = facelock.verify(max_seconds=8.0)
                    st2 = res2.get("status")
                    if st2 == facelock.MATCH:
                        self._face_confirms = 0
                        if _t.time() - getattr(self, "_face_last_welcome", 0.0) > 120.0:
                            self._face_last_welcome = _t.time()
                            self.root.after(0, lambda: self._append('NIGHTMARE', 'Welcome, owner.', 'text'))
                            self.root.after(0, lambda: self._speak('Welcome, owner.'))
                        return
                    if st2 in (facelock.NOMATCH, facelock.NOFACE):
                        self._face_confirms += 1
                    else:
                        # good or technical read in between: the streak is over
                        self._face_confirms = 0
                if self._face_confirms < FACE_CONFIRM_TRIES:
                    return      # still unproven either way: let it be
                self._face_confirms = 0
                try:
                    unlock_how = self._unlock_how_text()
                    self.root.after(0, lambda: self._append('NIGHTMARE', 'Unverified after unlock. Auto-locking. ' + unlock_how, 'sys'))
                    facelock.escalate(res.get("status"))
                except Exception:
                    pass
            # ERROR / camera fault / not-enrolled: fail open, as at start-up
        except Exception:
            pass
        finally:
            try:
                self._face_rescanning = False
            except Exception:
                pass

    def _user_model_loop(self):
        """Build the model of the user passively, without being asked.

        Every half minute it samples the foreground window and folds what it
        sees into the user model. Nothing is said out loud; it is background
        bookkeeping so that later questions can be answered from what already
        happened instead of asking again.
        """
        try:
            from modules.user_model import get_user_model
            um = get_user_model()
        except Exception:
            return
        while True:
            try:
                time.sleep(30)
                if self.is_processing:
                    continue
                um.observe_context()
                um.save()
            except Exception:
                time.sleep(30)

    def _change_language(self, lang_name):
        code = normalize(self.LANGUAGES[lang_name])
        self.current_lang = code
        self.lang_var.set(lang_name)
        self.brain.set_language(code, lang_name)
        self._refresh_voice_options()
        self.memory.settings["language"] = code
        self.memory.save_settings()
        self._append("N.AI", tr(code, "lang_switched", name=lang_name), "sys")
        self._update_status()

    def _reset_chat(self):
        self.brain.reset()
        self._clear_feed()
        self._append("N.AI", tr(self.current_lang, "reset"), "text")

    def _toggle_master_access(self):
        if not self.master_access:
            self.master_access = True
            self.master_btn.config(text="🔓", fg="#00ff00")
            self.brain.set_master_access(True)
            self._append("N.AI", "Master Access enabled. Full system control granted.", "action")
            self._speak("Master Access enabled.")
        else:
            self.master_access = False
            self.master_btn.config(text="🔒", fg="#ff4444")
            self.brain.set_master_access(False)
            self._append("N.AI", "Master Access disabled.", "sys")
            self._speak("Master Access disabled.")
        self._update_status()

    def _toggle_mute(self):
        self.is_muted = not self.is_muted
        self.mute_btn.config(text="\U0001f507" if self.is_muted else "\U0001f50a",
                             fg="#ff4444" if self.is_muted else self.SECONDARY)
        self._append("N.AI", f"Voice {'muted' if self.is_muted else 'unmuted'}.", "sys")

    def _analyze_screen(self):
        if self.is_processing:
            return
        self._append("N.AI", "Analyzing screen...", "text")
        self.is_processing = True
        threading.Thread(target=self._do_screen_analysis, daemon=True).start()

    def _do_screen_analysis(self):
        try:
            response = self.brain.ask("Call execute_action with action='analyze_screen' and params={'prompt': 'Describe EVERYTHING visible on this screen in extreme detail - all windows, text, UI elements, icons, menus, open applications, running processes visible, taskbar items, system tray icons, any notifications, and anything else you can see. Be comprehensive and detailed.'} to see what's currently on my screen and describe it in detail.")
            self.root.after(0, lambda r=response: self._append("N.AI", r, "text"))
            self._speak(response)
        except Exception as e:
            self.root.after(0, lambda: self._append("N.AI", f"Error: {str(e)}", "text"))
        finally:
            self.is_processing = False
            self.root.after(400, self._drain_queue)

    def _speak(self, text, lang=None):
        if self.is_muted or not text:
            return
        lang = lang or self.current_lang
        voice = self.tts_voice or None

        def _run():
            speak(text, language=lang, voice=voice, rate=self.voice_speed,
                  device=(self.out_device or None))

        threading.Thread(target=_run, daemon=True).start()
        self.root.after(0, lambda: self._mark_speaking(text))


def _crash_log_path():
    """Always writable, even inside the read-only PyInstaller temp dir."""
    try:
        from modules.memory import config_dir
        d = config_dir()
    except Exception:
        d = os.path.expanduser("~")
    try:
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "nai_crash.log")
    except Exception:
        return os.path.join(os.path.expanduser("~"), "nai_crash.log")


def _log_crash(prefix, exc=None):
    import traceback
    import datetime
    path = _crash_log_path()
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n[%s] %s\n" % (datetime.datetime.now().isoformat(timespec="seconds"),
                                      prefix))
            if exc is not None:
                traceback.print_exception(type(exc), exc, exc.__traceback__, file=f)
    except Exception:
        pass
    return path


def _install_crash_hooks():
    """Route every uncaught error to the crash log.

    A windowed build has no console (sys.stderr is None), so an exception in
    a worker thread -- voice, autonomy, face lock, speaking -- used to
    evaporate: nothing was written anywhere and the feature it belonged to
    silently stopped working. These hooks give every crash a traceback on disk.
    """
    def _hook(exc_type, exc, tb):
        try:
            if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
                return
            _log_crash("uncaught %s" % getattr(exc_type, "__name__", exc_type), exc)
        except Exception:
            pass

    def _thread_hook(args):
        try:
            th = getattr(args, "thread", None)
            _log_crash("thread '%s' died" % (th.name if th else "?"),
                       getattr(args, "exc_value", None))
        except Exception:
            pass

    sys.excepthook = _hook
    threading.excepthook = _thread_hook


_install_crash_hooks()


def _clean_stale_mei(max_age_hours=2):
    """PyInstaller never cleans its _MEI temp dir when the app is killed or
    crashes, so they pile up (38 dirs / 5.73 GB on this machine). Remove any
    that is not ours and is older than max_age_hours."""
    import glob
    import shutil
    import time
    removed, freed = 0, 0
    mine = getattr(sys, "_MEIPASS", None)
    try:
        entries = glob.glob(os.path.join(tempfile.gettempdir(), "_MEI*"))
    except Exception:
        return 0, 0
    now = time.time()
    for d in entries:
        try:
            if not os.path.isdir(d) or d == mine:
                continue
            if now - os.path.getmtime(d) < max_age_hours * 3600:
                continue
            size = 0
            for root, _dirs, files in os.walk(d):
                for fn in files:
                    try:
                        size += os.path.getsize(os.path.join(root, fn))
                    except OSError:
                        pass
            shutil.rmtree(d, ignore_errors=True)
            if not os.path.isdir(d):
                removed += 1
                freed += size
        except Exception:
            continue
    if removed:
        try:
            with open(_crash_log_path(), "a", encoding="utf-8") as f:
                f.write("[cleanup] removed %d stale PyInstaller temp dirs (%.2f GB)\n"
                        % (removed, freed / 1024 ** 3))
        except Exception:
            pass
    return removed, freed


def _focus_existing_instance():
    """Raise the window of an already-running NIGHTMARE, if there is one."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.FindWindowW.restype = wintypes.HWND
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    hwnd = user32.FindWindowW("TkTopLevel", "NIGHTMARE - N.AI Protocol")
    if hwnd:
        user32.ShowWindow(hwnd, 9)               # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    return bool(hwnd)


def _guard_log(msg):
    """Append one line to the startup audit log. Never raises."""
    try:
        from modules.memory import config_dir
        path = os.path.join(config_dir(), "startup.log")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("[%s] pid=%s %s\n"
                     % (time.strftime("%Y-%m-%d %H:%M:%S"), os.getpid(), msg))
    except Exception:
        pass


def _other_instance_running():
    """True if another copy of this executable is already running.

    Process enumeration is the authoritative check. A mutex alone is not enough:
    the logon task runs NIGHTMARE elevated, and a medium-integrity process is
    refused write access to a mutex created at high integrity, so the mutex let
    a second window through. Two windows then competed for one webcam, one got
    partial frames, and it locked the workstation on a false 'nomatch'.
    """
    try:
        import psutil
    except Exception as exc:
        _guard_log("GUARD psutil unavailable (%s: %s) -> allowing launch"
                   % (type(exc).__name__, exc))
        return False
    if not getattr(sys, "frozen", False):
        _guard_log("GUARD not frozen (running from source) -> allowing launch")
        return False
    mine = os.path.normcase(os.path.abspath(sys.executable))
    me = os.getpid()
    seen = 0
    for proc in psutil.process_iter(["pid", "exe"]):
        try:
            seen += 1
            if proc.info["pid"] == me:
                continue
            path = proc.info.get("exe") or ""
            if os.path.normcase(os.path.abspath(path)) == mine:
                _guard_log("GUARD found other instance pid=%s -> BLOCKING launch"
                           % proc.info["pid"])
                return True
        except Exception:
            continue
    _guard_log("GUARD no other instance (frozen, exe=%s, scanned %d procs)"
               % (os.path.basename(mine), seen))
    return False


def _acquire_single_instance():
    """Return True if this process is the one allowed to run.

    NIGHTMARE is auto-started at logon, so a second launch (double-click, a task
    retrigger, a re-run) would open a second window and take a second grab on
    the webcam. The existing instance is brought forward instead.
    """
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    handle = kernel32.CreateMutexW(None, True, "NIGHTMARE_NAI_SINGLETON")
    err = ctypes.get_last_error()
    if err == 183:                                # ERROR_ALREADY_EXISTS
        _guard_log("GUARD mutex already held -> BLOCKING launch")
        return False
    _guard_log("GUARD mutex created (handle=%s err=%s)" % (bool(handle), err))
    return not _other_instance_running()


if __name__ == "__main__":
    try:
        if not _acquire_single_instance():
            _focus_existing_instance()
            # a windowed PyInstaller build has sys.stderr == None, so writing to
            # it raises AttributeError; that used to be swallowed by the except
            # below, which let the duplicate window open anyway
            _guard_log("GUARD duplicate blocked, existing window raised")
            if sys.stderr is not None:
                sys.stderr.write("[startup] NIGHTMARE is already running\n")
            raise SystemExit(0)
    except SystemExit:
        raise
    except Exception:
        _guard_log("GUARD failed unexpectedly, continuing: %s" % traceback.format_exc())
        pass                      # never let the guard block startup

    try:
        _n, _g = _clean_stale_mei()
        if _n:
            print("[startup] cleaned %d stale PyInstaller temp dirs" % _n)
    except Exception:
        _log_crash("startup cleanup failed")

    try:
        root = tk.Tk()
        app = NightmareAI_GUI(root)
        root.mainloop()
    except SystemExit:
        raise
    except BaseException as e:
        p = _log_crash("FATAL", e)
        try:
            messagebox.showerror(
                "NIGHTMARE stopped",
                "NIGHTMARE hit an unexpected error and closed.\n\n"
                "%s: %s\n\nFull details were written to:\n%s" % (type(e).__name__, e, p))
        except Exception:
            pass
        raise
    finally:
        try:
            _clean_stale_mei(max_age_hours=0)
        except Exception:
            pass