"""System/service stats collectors for the home dashboard. Stdlib only."""
import os
import shutil
import subprocess


def _run(cmd, timeout=6):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def get_system():
    try:
        load1, _, _ = os.getloadavg()
    except Exception:
        load1 = 0.0
    temp = None
    out = _run(["vcgencmd", "measure_temp"])
    if "temp=" in out:
        temp = out.split("temp=")[1].split("'")[0]
    else:
        try:
            temp = str(int(open("/sys/class/thermal/thermal_zone0/temp").read().strip()) // 1000)
        except Exception:
            pass
    mem_total = mem_avail = 0
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemTotal:"):
                mem_total = int(line.split()[1]) // 1024
            elif line.startswith("MemAvailable:"):
                mem_avail = int(line.split()[1]) // 1024
    except Exception:
        pass
    disk = shutil.disk_usage("/")
    uptime_s = 0
    try:
        uptime_s = int(float(open("/proc/uptime").read().split()[0]))
    except Exception:
        pass
    days, rem = divmod(uptime_s, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    uptime = f"{days}d {hours}h {mins}m" if days else f"{hours}h {mins}m"
    return {
        "temp": f"{temp}C" if temp else "N/A",
        "load": f"{load1:.2f}",
        "mem": f"{(mem_total - mem_avail) / 1024:.1f} / {mem_total / 1024:.1f} GB" if mem_total else "N/A",
        "mem_pct": round((mem_total - mem_avail) / mem_total * 100) if mem_total else 0,
        "disk": f"{disk.used // 10**9} / {disk.total // 10**9} GB",
        "disk_pct": round(disk.used / disk.total * 100),
        "uptime": uptime,
    }


SERVICES = ["pihole-FTL", "secplatform", "tailscaled", "docker", "mcbot", "dashboard"]


def get_nas():
    """Usage of the external NAS drive (Samsung 990 PRO 1TB @ /mnt/nas)."""
    try:
        usage = shutil.disk_usage("/mnt/nas")
        return {
            "nas": f"{usage.used // 10**9} / {usage.total // 10**9} GB",
            "nas_pct": round(usage.used / usage.total * 100),
        }
    except Exception:
        return {"nas": "N/A", "nas_pct": 0}


def get_services():
    result = []
    for svc in SERVICES:
        state = _run(["systemctl", "is-active", f"{svc}.service"])
        result.append({"name": svc, "active": state == "active"})
    return result


def get_secplatform():
    try:
        import json as js
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=4) as r:
            data = js.loads(r.read().decode())
        return {"ok": True, "version": data.get("version", "?")}
    except Exception:
        return {"ok": False, "version": "down"}


def get_tailscale():
    out = _run(["tailscale", "status"], timeout=8)
    devices = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and "." in parts[0] and parts[0][0].isdigit():
            devices.append({
                "ip": parts[0],
                "name": parts[1],
                "online": "offline" not in line,
            })
    return devices


def get_docker():
    out = _run(["docker", "ps", "--format", "{{.Names}}|{{.Status}}"], timeout=8)
    containers = []
    for line in out.splitlines():
        if "|" in line:
            name, status = line.split("|", 1)
            containers.append({"name": name, "status": status})
    return containers


def _read_cpu_stat():
    cpus = {}
    try:
        with open("/proc/stat") as f:
            for line in f:
                if line.startswith("cpu") and len(line) > 3 and line[3].isdigit():
                    parts = line.split()
                    nums = list(map(int, parts[1:]))
                    cpus[parts[0]] = (sum(nums), nums[3] + nums[4])
    except Exception:
        pass
    return cpus


def get_system_detail():
    import time as _t

    a = _read_cpu_stat()
    _t.sleep(0.4)
    b = _read_cpu_stat()
    cores = []
    for name in sorted(a):
        if name in b:
            dt = b[name][0] - a[name][0]
            di = b[name][1] - a[name][1]
            pct = round((1 - di / dt) * 100) if dt else 0
            cores.append(max(0, min(100, pct)))

    freq = _run(["vcgencmd", "measure_clock", "arm"])
    freq_mhz = "N/A"
    if "=" in freq:
        try:
            freq_mhz = f"{int(freq.split('=')[1]) // 1000000} MHz"
        except Exception:
            pass

    thr = _run(["vcgencmd", "get_throttled"])
    throttled, throttled_ok = "N/A", True
    if "throttled=" in thr:
        val = thr.split("=")[1].strip()
        throttled_ok = val == "0x0"
        throttled = "OK" if throttled_ok else f"WARNING ({val})"

    model = "N/A"
    try:
        model = open("/proc/device-tree/model").read().strip("\x00") or "N/A"
    except Exception:
        pass

    ips = _run(["hostname", "-I"]).split()

    swap_total = swap_free = 0
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("SwapTotal:"):
                swap_total = int(line.split()[1]) // 1024
            elif line.startswith("SwapFree:"):
                swap_free = int(line.split()[1]) // 1024
    except Exception:
        pass

    procs = []
    out = _run(["ps", "-eo", "comm,pcpu,pmem", "--sort=-pcpu"], timeout=8)
    for line in out.splitlines()[1:6]:
        parts = line.split()
        if len(parts) >= 3:
            procs.append({"name": parts[0][:24], "cpu": parts[1], "mem": parts[2]})

    return {
        "cores": cores,
        "freq": freq_mhz,
        "throttled": throttled,
        "throttled_ok": throttled_ok,
        "model": model,
        "ips": ", ".join(ips) if ips else "N/A",
        "swap": f"{swap_total - swap_free} / {swap_total} MB" if swap_total else "none",
        "procs": procs,
    }
