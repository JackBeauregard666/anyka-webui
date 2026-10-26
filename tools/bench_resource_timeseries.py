#!/usr/bin/env python3
import subprocess
import time
import urllib.request

HOST = os.environ.get("CAM_HOST", "192.168.1.100")
LOG_FILE = "verify/current/host/resource_timeseries.csv"

def get_snapshot(phase_label):
    cmd = (
        "cat /proc/uptime; "
        "grep -E 'MemFree|Buffers|Cached|Shmem' /proc/meminfo; "
        "df -k /tmp | tail -n 1; "
        "cat /proc/loadavg; "
        "grep -E 'wlan0:' /proc/net/wireless 2>/dev/null; "
        "for p in $(pidof rtsp ptz_daemon httpd 2>/dev/null); do "
        "echo \"PID $p $(cat /proc/$p/comm 2>/dev/null): $(grep VmRSS /proc/$p/status 2>/dev/null)\"; done"
    )
    res = subprocess.run(["python3", "tools/cam_ctl.py", "--host", HOST, "exec", cmd], capture_output=True, text=True)
    lines = res.stdout.strip().splitlines()
    data = {"phase": phase_label, "raw": " | ".join(lines)}
    return data

results = []
print("=== STARTING RESOURCE TIMESERIES: 5 SAMPLES BASELINE ===")
for i in range(5):
    snap = get_snapshot(f"baseline_{i+1}")
    print(f"[Baseline {i+1}/5] {snap['raw'][:100]}...")
    results.append(snap)
    time.sleep(5)

print("\n=== GENERATING LOAD: 2 RTSP CLIENTS (vs0 + vs1) + 200 HTTP REQUESTS ===")
# Start 2 ffmpeg RTSP clients in background
ff_vs0 = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp", "-i", f"rtsp://{HOST}:554/vs0", "-t", "45", "-f", "null", "-"])
ff_vs1 = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp", "-i", f"rtsp://{HOST}:554/vs1", "-t", "45", "-f", "null", "-"])

# Send 100 requests to / and 100 requests to status-API
for i in range(100):
    try:
        urllib.request.urlopen(f"http://{HOST}/", timeout=3).read()
        urllib.request.urlopen(f"http://{HOST}/cgi-bin/api.cgi?action=status", timeout=3).read()
    except Exception:
        pass
    if i % 25 == 0:
        print(f"  Sent {i*2} requests...")

ff_vs0.wait()
ff_vs1.wait()
print("Load finished.")

print("\n=== RESOURCE TIMESERIES: 5 SAMPLES POST-LOAD ===")
for i in range(5):
    snap = get_snapshot(f"postload_{i+1}")
    print(f"[Postload {i+1}/5] {snap['raw'][:100]}...")
    results.append(snap)
    time.sleep(5)

with open(LOG_FILE, "w") as f:
    f.write("phase,raw_data\n")
    for r in results:
        f.write(f"{r['phase']},\"{r['raw']}\"\n")

print(f"Saved {LOG_FILE}")
