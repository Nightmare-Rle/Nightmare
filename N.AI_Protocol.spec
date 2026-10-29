# -*- mode: python ; coding: utf-8 -*-
#
# ONEDIR build.
#
# The onefile build extracted the whole app to %TEMP%\_MEIxxxxx on every start
# and never cleaned up when the process was killed, which left 38 orphaned
# folders totalling 5.73 GB on this machine. An onedir build has no temp
# extraction at all: faster startup, no disk leak, and an easier crash to
# diagnose (the log and code sit on disk instead of vanishing).

import os

# media editing keeps a video's original audio by muxing it with FFmpeg.
# imageio-ffmpeg ships ffmpeg.exe inside its own package directory and resolves it
# at runtime by path, so PyInstaller's normal analysis never sees the binary and
# a build without it exports mute videos with no warning. Copy it into the exact
# location imageio_ffmpeg.get_ffmpeg_exe() looks in.
_extra_binaries = []
try:
    import imageio_ffmpeg
    _ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    if _ffmpeg_exe and os.path.isfile(_ffmpeg_exe):
        _extra_binaries.append((_ffmpeg_exe, 'imageio_ffmpeg/binaries'))
        print('[spec] bundling ffmpeg:', _ffmpeg_exe)
    else:
        print('[spec] WARNING: ffmpeg binary not found; video exports will lose audio')
except Exception as _e:
    print('[spec] WARNING: imageio_ffmpeg unavailable (%s); '
          'video exports will lose audio' % _e)

# Offline speech recognition. The 68 MB vosk model already ships inside
# .nightmare, but nothing could load it because the vosk engine was never
# bundled -- so speech recognition silently depended on Google's endpoint and
# failed completely whenever that call did not return text. vosk loads its
# native library through cffi, which PyInstaller cannot see, so ship the
# DLLs alongside it.
try:
    import vosk as _vosk
    _vosk_dir = os.path.dirname(_vosk.__file__)
    for _dll in ('libvosk.dll', 'libstdc++-6.dll', 'libgcc_s_seh-1.dll',
                 'libwinpthread-1.dll'):
        _src = os.path.join(_vosk_dir, _dll)
        if os.path.isfile(_src):
            _extra_binaries.append((_src, 'vosk'))
        else:
            print('[spec] WARNING: vosk DLL missing:', _dll)
    print('[spec] bundling offline speech recognition (vosk)')
except Exception as _e:
    print('[spec] WARNING: vosk unavailable (%s); voice input will need '
          'internet' % _e)

a = Analysis(
    ['nai_protocol.pyw'],
    pathex=[],
    binaries=_extra_binaries,
    datas=[('modules', 'modules'), ('Nightmare.png', '.'), ('config.json', '.')],
    hiddenimports=['pyautogui', 'PIL', 'PIL.Image', 'PIL.ImageTk', 'pyttsx3', 'psutil', 'requests', 'speech_recognition', 'sounddevice', 'soundfile', 'numpy', 'bs4', 'wikipedia', 'edge_tts', 'uiautomation', 'comtypes', 'win32gui', 'win32api', 'pytesseract', 'cv2', 'imageio_ffmpeg', 'vosk', 'cffi', '_cffi_backend', 'modules.media', 'modules.media_view', 'modules.facelock', 'modules.vision', 'modules.language', 'modules.memory', 'modules.user_model', 'modules.child_processes'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Nightmare',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Nightmare',
)
