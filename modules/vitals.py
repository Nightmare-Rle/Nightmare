import os
import time
import threading
import platform
import datetime
import psutil


class Vitals:
    """A single system-vitals snapshot (the arc reactor readout of NIGHTMARE)."""

    def __init__(self):
        self.cpu = round(psutil.cpu_percent(interval=None), 1)
        vm = psutil.virtual_memory()
        self.ram_pct = round(vm.percent, 1)
        self.ram_used_mb = round(vm.used / 1048576.0)
        self.ram_total_mb = round(vm.total / 1048576.0)
        self.disk_pct = {}
        try:
            for part in psutil.disk_partitions(all=False):
                if os.name == "nt" and ("cdrom" in part.opts or part.fstype == ""):
                    continue
                try:
                    use = psutil.disk_usage(part.mountpoint)
                    self.disk_pct[part.mountpoint] = round(use.percent, 1)
                except Exception:
                    pass
        except Exception:
            pass
        self.battery = None
        self.charging = None
        try:
            bat = psutil.sensors_battery()
            if bat:
                self.battery = bat.percent
                self.charging = bat.power_plugged
        except Exception:
            pass
        self.temp_c = None
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                flat = [t.current for sub in temps.values() for t in sub if t.current]
                if flat:
                    self.temp_c = round(max(flat), 1)
        except Exception:
            pass
        self.uptime_h = None
        try:
            boot = psutil.boot_time()
            self.uptime_h = round((time.time() - boot) / 3600.0, 1)
        except Exception:
            pass
        self.net_sent_kb = 0
        self.net_recv_kb = 0
        try:
            io = psutil.net_io_counters()
            self.net_sent_kb = round(io.bytes_sent / 1024.0)
            self.net_recv_kb = round(io.bytes_recv / 1024.0)
        except Exception:
            pass

    def anomalies(self):
        issues = []
        if self.cpu >= 85:
            issues.append(("cpu", f"CPU at {self.cpu:.0f}% — the reactor core is running hot."))
        if self.ram_pct >= 90:
            issues.append(("ram", f"Memory at {self.ram_pct:.0f}% — I suggest clearing some load."))
        for mnt, pct in self.disk_pct.items():
            if pct >= 92:
                issues.append(("disk", f"Storage at {pct:.0f}% on {mnt} — remaining space is getting tight."))
        if self.battery is not None and self.battery <= 15 and not self.charging:
            issues.append(("battery", f"Primary power at {self.battery:.0f}% and unplugged."))
        if self.temp_c is not None and self.temp_c >= 80:
            issues.append(("temp", f"Core temperature reaching {self.temp_c:.0f}°C."))
        return issues

    def dict(self):
        return {
            "cpu": self.cpu, "ram_pct": self.ram_pct,
            "ram_used_mb": self.ram_used_mb, "ram_total_mb": self.ram_total_mb,
            "disk_pct": self.disk_pct, "battery": self.battery,
            "charging": self.charging, "temp_c": self.temp_c,
            "uptime_h": self.uptime_h,
            "net_sent_kb": self.net_sent_kb, "net_recv_kb": self.net_recv_kb,
        }


def get_vitals():
    try:
        return Vitals()
    except Exception:
        # Vitals() itself raised (psutil unavailable/broken). Calling Vitals()
        # again would just raise the same way, so hand back a safe empty
        # snapshot whose anomalies()/dict() still work instead of crashing the
        # monitor or the assistant.
        empty = Vitals.__new__(Vitals)
        empty.cpu = 0.0
        empty.ram_pct = 0.0
        empty.ram_used_mb = 0
        empty.ram_total_mb = 0
        empty.disk_pct = {}
        empty.battery = None
        empty.charging = None
        empty.temp_c = None
        empty.uptime_h = None
        empty.net_sent_kb = 0
        empty.net_recv_kb = 0
        return empty


class VitalsMonitor:
    """Periodic arc-reactor monitoring. Detects anomalies and fires callbacks."""

    def __init__(self):
        self.latest = None
        self._callbacks = []
        self._last_report = {}
        self._cooldown_s = 900
        self._thread = None
        self._stop = threading.Event()

    def on_anomaly(self, cb):
        self._callbacks.append(cb)

    def start(self, interval_s=25):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, args=(max(5, int(interval_s)),), daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self, interval_s):
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass
        while not self._stop.is_set():
            try:
                vit = get_vitals()
                self.latest = vit
                now = time.time()
                for kind, msg in vit.anomalies():
                    if now - self._last_report.get(kind, 0) < self._cooldown_s:
                        continue
                    self._last_report[kind] = now
                    for cb in list(self._callbacks):
                        try:
                            cb(msg)
                        except Exception:
                            pass
            except Exception:
                pass
            self._stop.wait(interval_s)


_MONITOR = None
_MON_LOCK = threading.Lock()


def get_monitor():
    global _MONITOR
    with _MON_LOCK:
        if _MONITOR is None:
            _MONITOR = VitalsMonitor()
        return _MONITOR