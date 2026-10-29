import os
import sys
import json
import ctypes
import tempfile
import threading
import asyncio
import time

EDGE_VOICES = {
    "en": "en-US-GuyNeural",
    "es": "es-ES-AlvaroNeural",
    "fr": "fr-FR-HenriNeural",
    "de": "de-DE-ConradNeural",
    "it": "it-IT-DiegoNeural",
    "pt": "pt-BR-AntonioNeural",
    "ja": "ja-JP-KeitaNeural",
    "ko": "ko-KR-InJoonNeural",
    "zh": "zh-CN-YunxiNeural",
    "ru": "ru-RU-DmitryNeural",
    "ar": "ar-SA-HamedNeural",
    "hi": "hi-IN-MadhurNeural",
    "tl": "fil-PH-AngeloNeural",
    "vi": "vi-VN-NamMinhNeural",
    "th": "th-TH-NiwatNeural",
}

VOICE_OPTIONS = {
    "en": ["en-US-GuyNeural", "en-US-JennyNeural", "en-GB-RyanNeural",
           "en-GB-SoniaNeural", "en-AU-NatashaNeural", "en-CA-LiamNeural",
           "en-IN-PrabhatNeural"],
    "tl": ["fil-PH-AngeloNeural", "fil-PH-BlessicaNeural"],
    "es": ["es-ES-AlvaroNeural", "es-ES-ElviraNeural", "es-MX-JorgeNeural"],
    "fr": ["fr-FR-HenriNeural", "fr-FR-DeniseNeural"],
    "de": ["de-DE-ConradNeural", "de-DE-KatjaNeural"],
    "it": ["it-IT-DiegoNeural", "it-IT-ElsaNeural"],
    "pt": ["pt-BR-AntonioNeural", "pt-BR-FranciscaNeural"],
    "ja": ["ja-JP-KeitaNeural", "ja-JP-NanamiNeural"],
    "ko": ["ko-KR-InJoonNeural", "ko-KR-SunHiNeural"],
    "zh": ["zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural"],
    "ru": ["ru-RU-DmitryNeural", "ru-RU-SvetlanaNeural"],
    "ar": ["ar-SA-HamedNeural", "ar-SA-ZariyahNeural"],
    "hi": ["hi-IN-MadhurNeural", "hi-IN-SwaraNeural"],
    "vi": ["vi-VN-NamMinhNeural", "vi-VN-HoaiMyNeural"],
    "th": ["th-TH-NiwatNeural", "th-TH-PremwadeeNeural"],
}

_lock = threading.Lock()
_output_file = os.path.join(tempfile.gettempdir(), "nightmare_tts.mp3")


def _log(text):
    try:
        print(text, encoding="utf-8", errors="replace")
    except Exception:
        pass


def _settings():
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from memory import Memory
        return Memory().settings
    except Exception:
        return {}


def _edge_voice_for(language):
    settings = _settings()
    if settings.get("edge_voice"):
        return settings.get("edge_voice")
    return EDGE_VOICES.get(language, EDGE_VOICES["en"])


def _play_mp3(path, device=None):
    # Prefer decoding via soundfile and playing on a selectable output device.
    try:
        import soundfile as sf
        import numpy as np
        import sounddevice as sd
        data, sr = sf.read(path, dtype="float32", always_2d=True)
        data = np.asarray(data)
        if data.shape[1] > 1:
            data = np.mean(data, axis=1, keepdims=True)
        sd.play(data, sr, device=(device or None), blocking=True)
        return True
    except Exception:
        pass
    # Fallback: MCI on the default output device.
    try:
        winmm = ctypes.windll.winmm
        winmm.mciSendStringW(f'open "{path}" type mpegvideo alias nmt', None, 0, None)
        winmm.mciSendStringW("play nmt wait", None, 0, None)
        winmm.mciSendStringW("close nmt", None, 0, None)
        return True
    except Exception:
        return False


def _edge_say(text, voice, rate):
    import edge_tts
    rate_str = f"{rate:+d}%" if isinstance(rate, (int, float)) else "+0%"
    communicate = edge_tts.Communicate(text, voice, rate=rate_str)
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(communicate.save(_output_file))
    finally:
        loop.close()


def _pyttsx3_say(text, speed=0):
    import pyttsx3
    engine = pyttsx3.init()
    engine.setProperty("rate", max(80, 180 - speed * 8))
    engine.setProperty("volume", 1.0)
    voices = engine.getProperty("voices")
    if voices:
        for v in voices:
            if "male" in v.name.lower() or "david" in v.name.lower() or "english" in v.name.lower():
                engine.setProperty("voice", v.id)
                break
        else:
            engine.setProperty("voice", voices[0].id)
    engine.say(text)
    engine.runAndWait()


_play_ticket = 0


def speak(text, language="en", voice=None, rate=None, device=None):
    _log(f"N.AI: {text}")
    settings = _settings()
    speed = rate if rate is not None else int(settings.get("voice_speed", 0) or 0)
    try:
        selected = voice or _edge_voice_for(language)
        _edge_say(text, selected, speed)
        if _play_mp3(_output_file, device):
            return
    except Exception:
        pass
    try:
        with _lock:
            _pyttsx3_say(text, speed)
    except Exception:
        pass