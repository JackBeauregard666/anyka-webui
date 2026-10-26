#!/usr/bin/env python3
import sys
import time
import urllib.request
import json

HOST = os.environ.get("CAM_HOST", "192.168.1.100")
URL = f"http://{HOST}/cgi-bin/api.cgi?action=status"
SAMPLES = 100

def percentile(vals, p):
    k = (len(vals) - 1) * p
    f = int(k)
    c = f + 1
    if c < len(vals):
        return sorted(vals)[f] + (sorted(vals)[c] - sorted(vals)[f]) * (k - f)
    return sorted(vals)[f]

durations = []
successes = 0

print(f"Collecting {SAMPLES} samples for {URL}...")
for i in range(SAMPLES):
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(URL)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read()
            t1 = time.perf_counter()
            j = json.loads(data.decode("utf-8"))
            if j.get("ok") is True:
                successes += 1
            durations.append((t1 - t0) * 1000.0)
    except Exception as e:
        durations.append(5000.0)
    time.sleep(0.05)

durations_sorted = sorted(durations)
min_val = round(durations_sorted[0], 1)
med_val = round(percentile(durations, 0.50), 1)
p95_val = round(percentile(durations, 0.95), 1)
max_val = round(durations_sorted[-1], 1)

print(f"Results (n={len(durations)}): successes={successes}/{SAMPLES}")
print(f"min={min_val} ms, median={med_val} ms, p95={p95_val} ms, max={max_val} ms")

out_file = sys.argv[1] if len(sys.argv) > 1 else "verify/current/host/status_latency_idle.csv"
with open(out_file, "w") as f:
    f.write("sample,duration_ms\n")
    for i, d in enumerate(durations):
        f.write(f"{i+1},{d:.2f}\n")
    f.write(f"# summary: n={len(durations)}, min={min_val}, median={med_val}, p95={p95_val}, max={max_val}\n")
print(f"Saved {out_file}")
