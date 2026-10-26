#!/usr/bin/env python3
import socket
import subprocess
import time

HOST = os.environ.get("CAM_HOST", "192.168.1.100")

def percentile(vals, p):
    k = (len(vals) - 1) * p
    f = int(k)
    c = f + 1
    if c < len(vals):
        return sorted(vals)[f] + (sorted(vals)[c] - sorted(vals)[f]) * (k - f)
    return sorted(vals)[f]

# 1. Measure 20 DESCRIBE latencies
describe_times_vs0 = []
describe_times_vs1 = []

print("Measuring 20 DESCRIBE times for vs0 and vs1...")
for _ in range(20):
    for path, d_list in [("vs0", describe_times_vs0), ("vs1", describe_times_vs1)]:
        t0 = time.perf_counter()
        s = socket.create_connection((HOST, 554), timeout=3)
        req = (
            f"DESCRIBE rtsp://{HOST}:554/{path} RTSP/1.0\r\n"
            f"CSeq: 2\r\n"
            f"Accept: application/sdp\r\n\r\n"
        )
        s.sendall(req.encode("utf-8"))
        resp = s.recv(2048).decode("utf-8", errors="replace")
        s.close()
        t1 = time.perf_counter()
        if "200 OK" in resp:
            d_list.append((t1 - t0) * 1000.0)
    time.sleep(0.05)

p95_vs0 = round(percentile(describe_times_vs0, 0.95), 1)
p95_vs1 = round(percentile(describe_times_vs1, 0.95), 1)
print(f"DESCRIBE vs0: p95={p95_vs0} ms, n={len(describe_times_vs0)}")
print(f"DESCRIBE vs1: p95={p95_vs1} ms, n={len(describe_times_vs1)}")

# 2. Test UDP Transport
print("Testing UDP Transport for 5 seconds...")
res_udp = subprocess.run(
    ["ffmpeg", "-hide_banner", "-rtsp_transport", "udp", "-i", f"rtsp://{HOST}:554/vs1", "-t", "5", "-f", "null", "-"],
    capture_output=True, text=True, timeout=15
)
udp_supported = (res_udp.returncode == 0)
print(f"UDP Transport supported: {udp_supported}")

# 3. Test 60s stream packet/frame drops (TCP)
print("Testing 60s continuous stream for packet/frame losses...")
t_start = time.time()
res_60s = subprocess.run(
    ["ffmpeg", "-hide_banner", "-rtsp_transport", "tcp", "-i", f"rtsp://{HOST}:554/vs0", "-t", "60", "-f", "null", "-"],
    capture_output=True, text=True, timeout=80
)
duration = round(time.time() - t_start, 1)
print(f"60s stream completed in {duration}s, returncode={res_60s.returncode}")
print(f"ffmpeg stderr tail: {res_60s.stderr[-300:]}")

with open("verify/current/host/rtsp_verification.txt", "w") as f:
    f.write(f"DESCRIBE_vs0_p95_ms={p95_vs0}\n")
    f.write(f"DESCRIBE_vs1_p95_ms={p95_vs1}\n")
    f.write(f"UDP_supported={udp_supported}\n")
    f.write(f"Stream_60s_rc={res_60s.returncode}\n")
    f.write(f"Stream_60s_duration={duration}\n")
    f.write(f"Stream_60s_stderr={res_60s.stderr}\n")

print("Saved verify/current/host/rtsp_verification.txt")
