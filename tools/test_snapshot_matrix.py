#!/usr/bin/env python3
import socket
import sys
import time
import urllib.request
import urllib.error

HOST = os.environ.get("CAM_HOST", "192.168.1.100")
CANDIDATES = [
    # Port 80
    f"http://{HOST}/snap.jpg",
    f"http://{HOST}/snap.jpg?t={int(time.time()*1000)}",
    f"http://{HOST}/snapshot.jpg",
    f"http://{HOST}/snapshot.jpg?t={int(time.time()*1000)}",
    f"http://{HOST}/jpgcap.cgi",
    f"http://{HOST}/cgi-bin/jpgcap.cgi",
    f"http://{HOST}/cgi-bin/snapshot.cgi",
    f"http://{HOST}/cgi-bin/api.cgi?action=snapshot",
    f"http://{HOST}/image.jpg",
    
    # Port 3000
    f"http://{HOST}:3000/",
    f"http://{HOST}:3000/snap.jpg",
    f"http://{HOST}:3000/snap.jpg?t={int(time.time()*1000)}",
    f"http://{HOST}:3000/snapshot",
    f"http://{HOST}:3000/live.jpg",
    
    # Port 8080 (from old config.sh)
    f"http://{HOST}:8080/",
    f"http://{HOST}:8080/snap.jpg",
]

out_lines = []
out_lines.append("URL,Status,ContentType,ContentLength,First8BytesHex,DurationMs,Result")

print("=== TESTING SNAPSHOT CANDIDATE PATHS ===")
for url in CANDIDATES:
    t0 = time.perf_counter()
    status = "ERR"
    ct = ""
    cl = 0
    hex_head = ""
    res = ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = resp.read()
            t1 = time.perf_counter()
            status = str(resp.status)
            ct = resp.headers.get("Content-Type", "")
            cl = len(data)
            hex_head = data[:8].hex().upper()
            dur_ms = round((t1 - t0) * 1000, 1)
            if data[:3] == b"\xff\xd8\xff":
                res = "JPEG"
            elif data[:2] == b"BM":
                res = "BMP"
            else:
                res = "OTHER"
    except urllib.error.HTTPError as e:
        t1 = time.perf_counter()
        dur_ms = round((t1 - t0) * 1000, 1)
        status = str(e.code)
        ct = e.headers.get("Content-Type", "")
        data = e.read()
        cl = len(data)
        hex_head = data[:8].hex().upper()
        res = f"HTTP_{e.code}"
    except Exception as e:
        t1 = time.perf_counter()
        dur_ms = round((t1 - t0) * 1000, 1)
        status = type(e).__name__
        res = str(e)[:30]

    line = f"{url},{status},{ct},{cl},{hex_head},{dur_ms},{res}"
    print(line)
    out_lines.append(line)

with open("verify/current/host/snapshot_matrix.csv", "w", encoding="utf-8") as f:
    f.write("\n".join(out_lines) + "\n")

print("Saved verify/current/host/snapshot_matrix.csv")
