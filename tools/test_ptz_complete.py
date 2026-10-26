#!/usr/bin/env python3
import subprocess
import time
import urllib.request
import json
from PIL import Image

HOST = os.environ.get("CAM_HOST", "192.168.1.100")
BASE_URL = f"http://{HOST}/cgi-bin/api.cgi"

def grab_frame(path):
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp",
        "-i", f"rtsp://{HOST}:554/vs1", "-frames:v", "1", "-y", path
    ]
    subprocess.run(cmd, check=True, timeout=10)

def frame_diff(p1, p2):
    im1 = Image.open(p1).convert("L")
    im2 = Image.open(p2).convert("L")
    px1 = list(im1.getdata())
    px2 = list(im2.getdata())
    diff = sum(abs(a - b) for a, b in zip(px1, px2)) / len(px1)
    return diff

print("=== PTZ MOVEMENT VERIFICATION VIA RTSP FRAMES ===")
grab_frame("verify/current/media/ptz_0_baseline.png")
print("Grabbed baseline frame")

# Send LEFT step=1
req = urllib.request.Request(f"{BASE_URL}?action=left&step=1", data=b"", method="POST")
with urllib.request.urlopen(req, timeout=5) as resp:
    res_left = json.loads(resp.read().decode("utf-8"))
print("Sent LEFT step=1:", res_left)
time.sleep(1.5)
grab_frame("verify/current/media/ptz_1_after_left.png")
diff_left = frame_diff("verify/current/media/ptz_0_baseline.png", "verify/current/media/ptz_1_after_left.png")
print(f"Frame diff baseline vs left: {diff_left:.2f}")

# Send RIGHT step=2
req = urllib.request.Request(f"{BASE_URL}?action=right&step=2", data=b"", method="POST")
with urllib.request.urlopen(req, timeout=5) as resp:
    res_right = json.loads(resp.read().decode("utf-8"))
print("Sent RIGHT step=2:", res_right)
time.sleep(1.5)
grab_frame("verify/current/media/ptz_2_after_right.png")
diff_right = frame_diff("verify/current/media/ptz_1_after_left.png", "verify/current/media/ptz_2_after_right.png")
print(f"Frame diff left vs right: {diff_right:.2f}")

# Send UP step=1
req = urllib.request.Request(f"{BASE_URL}?action=up&step=1", data=b"", method="POST")
with urllib.request.urlopen(req, timeout=5) as resp:
    res_up = json.loads(resp.read().decode("utf-8"))
print("Sent UP step=1:", res_up)
time.sleep(1.5)
grab_frame("verify/current/media/ptz_3_after_up.png")
diff_up = frame_diff("verify/current/media/ptz_2_after_right.png", "verify/current/media/ptz_3_after_up.png")
print(f"Frame diff right vs up: {diff_up:.2f}")

# Send DOWN step=1
req = urllib.request.Request(f"{BASE_URL}?action=down&step=1", data=b"", method="POST")
with urllib.request.urlopen(req, timeout=5) as resp:
    res_down = json.loads(resp.read().decode("utf-8"))
print("Sent DOWN step=1:", res_down)
time.sleep(1.5)
grab_frame("verify/current/media/ptz_4_after_down.png")
diff_down = frame_diff("verify/current/media/ptz_3_after_up.png", "verify/current/media/ptz_4_after_down.png")
print(f"Frame diff up vs down: {diff_down:.2f}")

print("\n=== PTZ SECURITY & REJECTION TESTS ===")
sec_tests = [
    ("GET reject", f"{BASE_URL}?action=left", "GET", {}, None),
    ("Bad Referer", f"{BASE_URL}?action=left&step=1", "POST", {"Referer": "http://evil.com/"}, b""),
    ("Good Referer", f"{BASE_URL}?action=left&step=1", "POST", {"Referer": f"http://{HOST}/"}, b""),
    ("Injection action=left;id", f"{BASE_URL}?action=left;id&step=1", "POST", {}, b""),
    ("Injection action=*", f"{BASE_URL}?action=*&step=1", "POST", {}, b""),
    ("Step out-of-bounds step=9", f"{BASE_URL}?action=left&step=9", "POST", {}, b""),
    ("Step out-of-bounds step=0", f"{BASE_URL}?action=left&step=0", "POST", {}, b""),
    ("Very long query", f"{BASE_URL}?action={'A'*500}", "POST", {}, b""),
]

sec_results = []
for name, url, method, headers, data in sec_tests:
    try:
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8")
            res = (resp.status, body)
    except Exception as e:
        res = ("ERR", str(e))
    print(f"[{name}] {method} -> {res}")
    sec_results.append((name, method, url, res))

with open("verify/current/host/ptz_verification.txt", "w") as f:
    f.write(f"diff_left={diff_left:.2f}\ndiff_right={diff_right:.2f}\ndiff_up={diff_up:.2f}\ndiff_down={diff_down:.2f}\n")
    for r in sec_results:
        f.write(f"{r[0]}: {r[1]} {r[2]} -> {r[3]}\n")

print("Saved verify/current/host/ptz_verification.txt")
