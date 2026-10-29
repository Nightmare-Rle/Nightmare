"""Remember what NIGHTMARE started, so it can put it away when it closes.

The user asked for one thing on this: when NIGHTMARE is closed, everything
that belongs to NIGHTMARE goes with it. Threads die with the interpreter on
their own, but anything NIGHTMARE launched as a separate process does not -
the Camera app stays open, a calculator stays open, a notepad stays open.

So the rule here is narrow on purpose: a process is only a NIGHTMARE
process if NIGHTMARE started it. Nothing that was already running when
NIGHTMARE woke up is ever touched, because killing the user's own work
because it happened to be open would be unforgivable.

Everything stays in memory. Nothing is written to disk.
"""

import os
import subprocess
import sys
import time

# pid -> {"name": str, "started": ts}
_TRACKED = {}

# Processes that are deliberately shared services and must survive us.
# ollama serve is detached on purpose: it is a machine-wide service, not
# a child of this session, and other tools talk to it too.
_SHARED = ("ollama.exe",)


def track(pid, name=""):
    """Remember a process NIGHTMARE started."""
    try:
        pid = int(pid)
    except Exception:
        return False
    if pid <= 0:
        return False
    _TRACKED[pid] = {"name": str(name or ""), "started": time.time()}
    return True


def track_popen(proc, name=""):
    """Track a Popen object if it actually started something."""
    try:
        pid = proc.pid
    except Exception:
        return False
    return track(pid, name)


def tracked():
    """The list of processes NIGHTMARE is responsible for."""
    return dict(_TRACKED)


def _is_shared(pid):
    try:
        import psutil
        p = psutil.Process(pid)
        base = os.path.basename(p.name() or "").lower()
        if base in _SHARED:
            return True
        # A child that became a parent of a shared service is also shared.
        for child in p.children(recursive=False):
            cbase = os.path.basename(child.name() or "").lower()
            if cbase in _SHARED:
                return True
    except Exception:
        return False
    return False


def kill_all(verbose=False):
    """Terminate every tracked process. Returns the list of what was closed."""
    closed = []
    for pid, meta in list(_TRACKED.items()):
        if _is_shared(pid):
            _TRACKED.pop(pid, None)
            continue
        try:
            import psutil
            p = psutil.Process(pid)
            p.terminate()
            try:
                p.wait(timeout=3)
            except Exception:
                p.kill()
        except Exception:
            try:
                subprocess.run("taskkill /PID %d /F" % pid, shell=True,
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            except Exception:
                pass
        closed.append(meta.get("name") or str(pid))
        _TRACKED.pop(pid, None)
    if verbose and closed:
        try:
            sys.stderr.write("[shutdown] closed: %s\n" % ", ".join(closed))
        except Exception:
            pass
    return closed


def forget(pid):
    """Stop tracking a process without killing it."""
    try:
        _TRACKED.pop(int(pid), None)
    except Exception:
        pass
