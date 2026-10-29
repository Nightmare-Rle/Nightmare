import sys
import os
import json
import math
import threading
import time
import numpy as np
import sounddevice as sd

_VOSK_MODEL = None
_VOSK_LOCK = threading.Lock()


def _log(text):
    """Voice problems were invisible: the app is a windowed PyInstaller build,
    so print() goes nowhere. Every failure landed silently on the user."""
    try:
        stamp = time.strftime("%H:%M:%S")
        line = "[%s] %s" % (stamp, text)
        print(line)
    except Exception:
        pass
    try:
        path = os.path.join(_nightmare_dir(), "voice.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
    except Exception:
        pass


def _rms(pcm):
    try:
        a = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
        if a.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(a ** 2)) / 32768.0)
    except Exception:
        return 0.0


def _peak(pcm):
    try:
        a = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
        if a.size == 0:
            return 0.0
        return float(np.abs(a).max() / 32768.0)
    except Exception:
        return 0.0


def _nightmare_dir():
    try:
        if getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for suffix in (".nightmare", "dist\\.nightmare"):
            cand = os.path.join(base, suffix)
            if os.path.isdir(cand):
                return cand
    except Exception:
        pass
    for root in os.environ.get("LOCALAPPDATA", ""), os.path.expanduser("~"):
        cand = os.path.join(root, ".nightmare")
        if os.path.isdir(cand):
            return cand
    return ""


def _stt_backend():
    try:
        p = os.path.join(_nightmare_dir(), "settings.json")
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f).get("stt", "auto")
    except Exception:
        return "auto"


def _vosk_recognize(pcm, lang="en"):
    global _VOSK_MODEL
    try:
        import vosk
        # vosk chats on stdout, which does not exist in the windowed build.
        try:
            vosk.SetLogLevel(-1)
        except Exception:
            pass
    except Exception:
        return ""
    model_dir = os.path.join(_nightmare_dir(), "vosk-model-small-en-us-0.15")
    if not os.path.isdir(model_dir):
        model_dir = os.path.join(os.path.dirname(_nightmare_dir()), "vosk-model-small-en-us-0.15")
    if not os.path.isdir(model_dir):
        return ""
    with _VOSK_LOCK:
        try:
            if _VOSK_MODEL is None:
                _VOSK_MODEL = vosk.Model(model_dir)
            rec = vosk.KaldiRecognizer(_VOSK_MODEL, 16000)
            if rec.AcceptWaveform(pcm):
                j = json.loads(rec.Result())
                return j.get("text", "")
            j = json.loads(rec.FinalResult())
            return j.get("text", "")
        except Exception:
            return ""


def _vosk_available():
    try:
        import vosk  # noqa: F401
        return True
    except Exception:
        return False


def _recognize(pcm, lang_map_lang):
    import speech_recognition as sr
    backend = _stt_backend()
    text = ""
    if backend in ("auto", "google"):
        try:
            audio = sr.AudioData(pcm, 16000, 2)
            text = sr.Recognizer().recognize_google(audio, language=lang_map_lang)
            _log("google ok: %r" % text)
        except sr.UnknownValueError:
            _log("google: could not understand the audio")
            text = ""
        except Exception as e:
            _log("google failed: %s: %s" % (type(e).__name__, str(e)[:120]))
            text = ""
    if not text and backend in ("auto", "vosk"):
        if not _vosk_available():
            _log("vosk unavailable (module not bundled) and no other backend worked")
        else:
            text = _vosk_recognize(pcm)
            _log("vosk: %r" % text)
    if not text:
        _log("no speech recognised (%d bytes of audio)" % len(pcm))
    return text


class SoundDeviceMicrophone:
    def __init__(self, device_index=None, sample_rate=16000, level_cb=None):
        self.sample_rate = sample_rate
        self.device_index = device_index
        self.stream = None
        self.audio_queue = []
        self.level_cb = level_cb

    def __enter__(self):
        self.audio_queue = []
        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype='int16',
            callback=self._audio_callback,
            device=self.device_index,
            blocksize=1024
        )
        self.stream.start()
        return self

    def __exit__(self, *args):
        if self.stream:
            try:
                self.stream.stop()
            except Exception:
                pass
            try:
                self.stream.close()
            except Exception:
                pass

    def _audio_callback(self, indata, frames, time, status):
        self.audio_queue.append(indata[:, 0].copy())
        if self.level_cb:
            try:
                rms = float(np.sqrt(np.mean(indata.astype(np.float64) ** 2)) / 32768.0)
                self.level_cb(rms)
            except Exception:
                pass

    def read(self, frames_count):
        while not self.audio_queue:
            time.sleep(0.01)
        data = np.concatenate(self.audio_queue)
        self.audio_queue = []
        return data.tobytes()

    def get_sample_rate(self):
        return self.sample_rate


def _first_input_device():
    try:
        devs = sd.query_devices()
        for i, d in enumerate(devs):
            if d.get('max_input_channels', 0) > 0:
                return i
    except Exception:
        pass
    return None


class AudioMeter:
    """Continuous mic-level meter used to drive the audio visualizer."""

    # Room noise sits near -60 dBFS and loud speech peaks around -6 dBFS. The
    # raw RMS of normal speech is only ~0.02, and the visualizer multiplied
    # that straight into bar height, so talking moved the bars by a couple of
    # pixels and looked identical to a dead microphone. Mapping decibels onto
    # 0..1 is what makes the visualizer actually show speech.
    FLOOR_DB = -62.0
    CEIL_DB = -8.0

    def __init__(self, level_cb=None, device_index=None):
        self.level_cb = level_cb
        self.device_index = device_index
        self.level = 0.0
        self.rms = 0.0
        self.peak_hold = 0.0
        self.errors = 0
        self._stop = threading.Event()
        self._thread = None

    @classmethod
    def _to_level(cls, rms):
        try:
            db = 20.0 * math.log10(rms + 1e-7)
        except Exception:
            return 0.0
        span = cls.CEIL_DB - cls.FLOOR_DB
        val = (db - cls.FLOOR_DB) / span
        return 0.0 if val < 0.0 else (1.0 if val > 1.0 else val)

    def _cb(self, indata, frames, time, status):
        try:
            rms = float(np.sqrt(np.mean(indata.astype(np.float64) ** 2)) / 32768.0)
        except Exception:
            rms = 0.0
        self.rms = rms
        target = self._to_level(rms)
        # fast attack, slow release, so the bars react the instant you speak
        # instead of easing up from nothing over the whole utterance
        k = 0.55 if target > self.level else 0.16
        self.level += (target - self.level) * k
        self.peak_hold = max(self.level, self.peak_hold - 0.012)
        if self.level_cb:
            try:
                self.level_cb(self.level)
            except Exception:
                pass

    def _run(self):
        device = self.device_index if self.device_index is not None else _default_input_device()
        self._log_state(device)
        while not self._stop.is_set():
            try:
                with sd.InputStream(samplerate=16000, channels=1, dtype='int16',
                                    device=device, blocksize=1024, callback=self._cb):
                    self.errors = 0
                    while not self._stop.is_set():
                        time.sleep(0.2)
            except Exception as e:
                # Never spin silently: a meter that cannot open is the single
                # most likely reason the visualizer looks broken.
                self.errors += 1
                if self.errors in (1, 5):
                    _log("visualizer meter cannot open device %s: %s: %s"
                         % (device, type(e).__name__, str(e)[:100]))
                time.sleep(1.0)

    def _log_state(self, device):
        try:
            name = sd.query_devices(device)['name']
        except Exception:
            name = "?"
        _log("visualizer meter listening on device %s (%s)" % (device, name))

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()


def _capture(device_index=None, level_cb=None, sample_rate=16000,
             start_threshold=0.006, end_threshold=0.004,
             pre_roll=0.35, end_silence=0.85, max_seconds=12.0):
    """Record one utterance: starts when speech sound appears (with pre-roll),
    stops after a quiet gap, capped by max_seconds. Returns int16 PCM bytes."""
    blocks = 1600  # ~0.1s at 16 kHz
    ring = []
    roll_len = max(1, int(pre_roll / (blocks / sample_rate)))
    frames = b""
    started = False
    quiet = 0
    needed_quiet = max(1, int(end_silence / (blocks / sample_rate)))
    t0 = time.time()
    with SoundDeviceMicrophone(device_index=device_index, sample_rate=sample_rate,
                               level_cb=level_cb) as mic:
        while True:
            chunk = mic.read(blocks)
            rms = _rms(chunk)
            if not started:
                ring.append(chunk)
                if len(ring) > roll_len:
                    ring.pop(0)
                if rms >= start_threshold:
                    started = True
                    frames = b"".join(ring) + chunk
                    quiet = 0
            else:
                frames += chunk
                if rms < end_threshold:
                    quiet += 1
                    if quiet >= needed_quiet:
                        break
                else:
                    quiet = 0
            if len(frames) > sample_rate * max_seconds or time.time() - t0 > max_seconds + pre_roll:
                break
    secs = len(frames) / 2 / float(sample_rate)
    if secs < 0.2:
        _log("capture: no speech detected (start threshold %.4f never met)" % start_threshold)
    else:
        _log("capture: %.1fs of audio, peak %.4f" % (secs, _peak(frames)))
    return frames


def _default_input_device():
    """Best guess at the mic to use when the user has not chosen one.

    This used to return the first device with an input channel, which on this
    laptop is index 0, "Microsoft Sound Mapper - Input" -- a virtual passthrough
    that carries no speech. The system default is the real Intel microphone
    array, so prefer that and only fall back to a scan.
    """
    try:
        idx = sd.default.device[0]
        if idx is not None and idx >= 0:
            devs = sd.query_devices()
            if idx < len(devs) and devs[idx].get('max_input_channels', 0) > 0:
                return idx
    except Exception:
        pass
    return _first_input_device()


def listen(language="en", level_cb=None, device_index=None):
    lang_map = {
        "en": "en-US", "es": "es-ES", "fr": "fr-FR", "de": "de-DE",
        "it": "it-IT", "pt": "pt-BR", "ja": "ja-JP", "ko": "ko-KR",
        "zh": "zh-CN", "ru": "ru-RU", "ar": "ar-SA", "hi": "hi-IN",
        "tl": "fil-PH", "vi": "vi-VN", "th": "th-TH"
    }
    lang = lang_map.get(language, "en-US")
    try:
        import sounddevice
        from speech_recognition import AudioData, Recognizer

        try:
            devices = sd.query_devices()
            if device_index is not None:
                try:
                    device_idx = device_index if devices[device_index].get('max_input_channels', 0) > 0 else None
                except Exception:
                    device_idx = None
            else:
                device_idx = _default_input_device()
        except Exception:
            device_idx = None

        _log("Listening...")
        pcm = _capture(device_index=device_idx, level_cb=level_cb)
        if not pcm or _rms(pcm) < 0.001:
            _log("No speech detected")
            return ""

        text = _recognize(pcm, lang)
        if text:
            _log(f"You said: {text}")
            return text.lower().strip()

        _log("Could not understand audio")
        return ""
    except KeyboardInterrupt:
        return "exit"
    except Exception as e:
        _log(f"Microphone error: {e}")
        print("[Voice not available. Type your command below:]")
        try:
            text = input("> ").strip()
            print(f"You said: {text}")
            return text.lower()
        except KeyboardInterrupt:
            return "exit"