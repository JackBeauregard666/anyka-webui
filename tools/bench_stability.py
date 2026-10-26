#!/usr/bin/env python3
import subprocess
import time
import urllib.request
import json
import sys

HOST = os.environ.get("CAM_HOST", "192.168.1.100")
DURATION_SEC = 180  # 3 minutes intensive stability run
LOG_FILE = "verify/current/host/stability_test.txt"

print(f"Starting {DURATION_SEC}s Stability Test against {HOST}...")

# Start 2 RTSP clients
ff_vs0 = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp", "-i", f"rtsp://{HOST}:554/vs0", "-t", str(DURATION_SEC), "-f", "null", "-"])
ff_vs1 = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp", "-i", f"rtsp://{HOST}:554/vs1", "-t", str(DURATION_SEC), "-f", "null", "-"])

t_start = time.time()
last_ptz = 0
last_status = 0
last_sample = 0
last_uptime = 0

req_ok = 0
req_err = 0
samples = []
out_lines = []
out_lines.append(f"=== STABILITY TEST LOG ({DURATION_SEC}s) ===")

try:
    while time.time() - t_start < DURATION_SEC:
        now = time.time()
        elapsed = now - t_start

        # HTTP polling every 500ms
        try:
            with urllib.request.urlopen(f"http://{HOST}/", timeout=2) as r:
                if r.status == 200: req_ok += 1
                else: req_err += 1
        except Exception:
            req_err += 1

        # Status polling every 5s
        if now - last_status >= 5:
            last_status = now
            try:
                with urllib.request.urlopen(f"http://{HOST}/cgi-bin/api.cgi?action=status", timeout=3) as r:
                    j = json.loads(r.read().decode("utf-8"))
                    if j.get("ok"): req_ok += 1
                    else: req_err += 1
            except Exception:
                req_err += 1

        # PTZ movement every 30s
        if now - last_ptz >= 30:
            last_ptz = now
            act = "left" if (int(elapsed / 30) % 2 == 0) else "right"
            print(f"[{round(elapsed)}s] Sending PTZ {act}...")
            try:
                req = urllib.request.Request(f"http://{HOST}/cgi-bin/api.cgi?action={act}&step=1", data=b"", method="POST")
                with urllib.request.urlopen(req, timeout=3) as r:
                    j = json.loads(r.read().decode("utf-8"))
                    if j.get("ok"): req_ok += 1
                    else: req_err += 1
            except Exception:
                req_err += 1

        # System check every 15s
        if now - last_sample >= 15:
            last_sample = now
            res = subprocess.run(["python3", "tools/cam_ctl.py", "--host", HOST, "exec", "cat /proc/uptime; grep -E 'MemFree|Buffers|Cached|Shmem' /proc/meminfo; cat /proc/loadavg"], capture_output=True, text=True, timeout=10)
            raw = res.stdout.strip().replace("\n", " | ")
            print(f"[{round(elapsed)}s] Sample: {raw[:90]}...")
            samples.append((round(elapsed), raw))
            
            # Rule 7 check: Uptime must be monotonic
            parts = res.stdout.strip().split()
            if parts:
                try:
                    cur_up = float(parts[0])
                    if last_uptime > 0 and cur_up < last_uptime:
                        print(f"ABORT: Uptime dropped from {last_uptime} to {cur_up}!")
                        sys.exit(1)
                    last_uptime = cur_up
                except ValueError:
                    pass

        time.sleep(0.5)

finally:
    ff_vs0.terminate()
    ff_vs1.terminate()
    ff_vs0.wait()
    ff_vs1.wait()

out_lines.append(f"Duration: {round(time.time() - t_start, 1)}s")
out_lines.append(f"HTTP Requests: OK={req_ok}, ERR={req_err}")
out_lines.append(f"RTSP vs0 exit code: {ff_vs0.returncode}")
out_lines.append(f"RTSP vs1 exit code: {ff_vs1.returncode}")
out_lines.append("--- SAMPLES ---")
for s in samples:
    out_lines.append(f"[{s[0]}s] {s[1]}")

with open(LOG_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(out_lines) + "\n")

print(f"Stability test complete. Saved {LOG_FILE}")
