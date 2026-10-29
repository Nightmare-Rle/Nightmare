import os
import json
import platform
import re
import subprocess
import datetime
import psutil


def _last_crash(max_age_hours=24):
    """Most recent uncaught error recorded by the app's own crash hooks.

    Returns a one-line summary, or None when there is no fresh error. This is
    how diagnostics can answer 'did anything break since I last looked?'
    without the user hunting for nai_crash.log.
    """
    try:
        from modules.memory import config_dir
        path = os.path.join(config_dir(), "nai_crash.log")
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            tail = f.read()[-4096:]
        hits = re.findall(r"^\[([0-9:.\-T]+)\] (.*)$", tail, re.M)
        if not hits:
            return None
        stamp, head = hits[-1]
        when = datetime.datetime.fromisoformat(stamp)
        if (datetime.datetime.now() - when).total_seconds() > max_age_hours * 3600:
            return None
        return "%s (%s)" % (head.strip(), when.strftime("%Y-%m-%d %H:%M"))
    except Exception:
        return None


def _event_log(level, count=6):
    lines = []
    try:
        import win32evtlog

        handle = win32evtlog.OpenEventLog(None, "System")
        flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ
        shown = 0
        for record in win32evtlog.ReadEventLog(handle, flags, 0):
            if record.EventType not in (level,):  # 1=Error 2=Warning
                continue
            try:
                name = str(record.SourceName)
            except Exception:
                name = "?"
            lines.append(f"  - {record.TimeGenerated} {name}: {str(record.StringInserts)[:140] if record.StringInserts else '(no detail)'}")
            shown += 1
            if shown >= count:
                break
        win32evtlog.CloseEventLog(handle)
    except Exception:
        return ["  - (event log unavailable)"]
    return lines or ["  - (no matching events)"]


def _top_processes(n=5):
    out = []
    try:
        for p in sorted(psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']),
                        key=lambda p: p.info['cpu_percent'] or 0, reverse=True)[:n]:
            out.append(f"  - {p.info['name']} (PID {p.info['pid']}) CPU {p.info['cpu_percent']:.1f}% "
                       f"MEM {p.info['memory_percent']:.1f}%")
    except Exception:
        pass
    return out


def _format_disk():
    lines = []
    try:
        for part in psutil.disk_partitions(all=False):
            if os.name == "nt" and ("cdrom" in part.opts or part.fstype == ""):
                continue
            try:
                use = psutil.disk_usage(part.mountpoint)
                pct = use.percent
                flag = "WARNING" if pct >= 90 else "normal"
                lines.append(f"  - {part.mountpoint} {use.used/1073741824:.0f}/{use.total/1073741824:.0f} GB "
                             f"({pct:.1f}%) [{flag}]")
            except Exception:
                pass
    except Exception:
        pass
    return lines


def run_diagnostics():
    """Full system health report in JARVIS's 'running the diagnostics' style."""
    try:
        lines = []
        lines.append("NIGHTMARE diagnostic report")
        lines.append(f"  Host     : {platform.node()} ({platform.system()} {platform.release()})")
        lines.append(f"  Processor: {platform.processor() or os.environ.get('PROCESSOR_IDENTIFIER', 'unknown')}")

        try:
            load1 = psutil.getloadavg()[0] if hasattr(psutil, 'getloadavg') else None
        except Exception:
            load1 = None
        cpu = psutil.cpu_percent(interval=1)
        lines.append(f"  CPU      : {cpu:.1f}% in use"
                     + (f", load {load1:.2f}" if load1 is not None else ""))

        vm = psutil.virtual_memory()
        status = "WARNING" if vm.percent >= 90 else "nominal"
        lines.append(f"  Memory   : {vm.percent:.1f}% used ({vm.used/1073741824:.1f}/{vm.total/1073741824:.1f} GB) [{status}]")

        for d in _format_disk():
            lines.append(d)

        try:
            bat = psutil.sensors_battery()
            if bat:
                lines.append(f"  Power    : {bat.percent:.0f}% battery"
                             + (" (charging)" if bat.power_plugged else " (on battery)"))
        except Exception:
            pass

        try:
            draw = _event_log(1, 6)
            lines.append("  System errors (recent):")
            lines.extend(draw)
        except Exception:
            pass

        crash = _last_crash()
        if crash:
            lines.append(f"  App error (last): {crash}")

        lines.append("  Top load:")
        lines.extend(_top_processes() or ["  - (none)"])

        try:
            boot = psutil.boot_time()
            up = datetime.datetime.now() - datetime.datetime.fromtimestamp(boot)
            lines.append(f"  Uptime   : {up.days}d {up.seconds//3600}h {(up.seconds//60)%60}m")
        except Exception:
            pass

        lines.append("VERDICT: " + _verdict())
        return "\n".join(lines)
    except Exception as e:
        return f"Diagnostics failed: {e}"


def _verdict():
    parts = []
    try:
        if psutil.cpu_percent(interval=0.2) >= 80:
            parts.append("the CPU is strained")
    except Exception:
        pass
    try:
        if psutil.virtual_memory().percent >= 90:
            parts.append("memory is under pressure")
    except Exception:
        pass
    return ("Systems nominal. Everything is as it should be."
            if not parts else "Attention is advised: " + " and ".join(parts) + ".")