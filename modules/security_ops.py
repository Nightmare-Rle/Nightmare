import os
import json
import datetime
import ipaddress
import psutil

_PRIVATE_PREFIXES = ("192.168.", "10.", "127.", "0.", "169.254.", "172.")
_LOOPBACK = ("::1",)


def _is_external(ip):
    if not ip or ip in _LOOPBACK:
        return False
    if ip.startswith("fe80:") or ip.startswith("fd") or ip.startswith("fc"):
        return False
    return not ip.startswith(_PRIVATE_PREFIXES)


def _connections():
    external = []
    listening = []
    try:
        for c in psutil.net_connections(kind="inet"):
            try:
                if c.status == "LISTEN":
                    listening.append(f"{c.laddr.ip}:{c.laddr.port}")
                elif c.raddr and _is_external(c.raddr.ip):
                    external.append(
                        f"{c.raddr.ip}:{c.raddr.port} <-> {c.laddr.ip}:{c.laddr.port} "
                        f"(pid {c.pid} {'name ' + psutil.Process(c.pid).name() if c.pid else ''})".strip())
            except Exception:
                continue
    except Exception:
        pass
    return list(dict.fromkeys(external)), list(dict.fromkeys(listening))


def _failed_logons(hours=24):
    try:
        import win32evtlog
        import win32evtlogutil  # noqa

        handle = win32evtlog.OpenEventLog(None, "Security")
        flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ
        count = 0
        cutoff = datetime.datetime.now() - datetime.timedelta(hours=hours)
        for record in win32evtlog.ReadEventLog(handle, flags, 0):
            evt_id = getattr(record, "EventID", None)
            if evt_id is None:
                continue
            if isinstance(evt_id, int) and evt_id != 4625:
                continue
            try:
                ts = record.TimeGenerated
                if ts and ts < cutoff:
                    break
            except Exception:
                pass
            count += 1
            if count > 12:
                break
        win32evtlog.CloseEventLog(handle)
        return count
    except Exception:
        return None


def security_scan(detail=False):
    """Intrusion sweep — the 'we've been hacked' subsystem."""
    try:
        external, listening = _connections()
        out = ["NIGHTMARE security sweep"]
        if external:
            out.append(f"  Active external connections: {len(external)}")
            for conn in (external[:8] if detail else external[:5]):
                out.append(f"    - {conn}")
            if len(external) > 8 and not detail:
                out.append(f"    ... and {len(external) - 8} more")
        else:
            out.append("  Active external connections: none")
        out.append(f"  Listening ports: {len(listening)}")
        for port in listening[:10]:
            out.append(f"    - {port}")

        failed = _failed_logons()
        if failed is None:
            out.append("  Failed logon events: (log unavailable — requires elevated view)")
        else:
            out.append(f"  Failed logon events in the last 24h: {failed}"
                       + ("  ⚠ Activity confirmed." if failed else ""))

        verdict = "Perimeter quiet. No intruders detected."
        if external and len(external) >= 1:
            verdict = "External traffic detected but within normal range. I am keeping a watchful eye."
        if failed and failed > 3:
            verdict = "Repeated failed logon attempts detected. I recommend you run a diagnostics sweep."
        out.append(f"VERDICT: {verdict}")
        return "\n".join(out)
    except Exception as e:
        return f"Security scan failed: {e}"