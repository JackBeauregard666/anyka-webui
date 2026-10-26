#!/usr/bin/env python3
"""
Automatisierte Test-Matrix gemaess Spec 5.4 fuer Anyka Domecam WebUI.
Misst jeden Endpunkt 20-mal und berechnet p95 Latenz.
"""
import json
import socket
import sys
import time
import urllib.request
import urllib.error

HOST = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CAM_HOST", "192.168.1.100")
BASE_URL = f"http://{HOST}"

def percentile(vals, p):
    if not vals:
        return 0
    k = (len(vals) - 1) * p
    f = int(k)
    c = f + 1
    if c < len(vals):
        return sorted(vals)[f] + (sorted(vals)[c] - sorted(vals)[f]) * (k - f)
    return sorted(vals)[f]

def test_endpoint(name, fn, runs=20):
    durations = []
    successes = 0
    last_val = None
    for _ in range(runs):
        t0 = time.perf_counter()
        ok, res = fn()
        t1 = time.perf_counter()
        dur_ms = (t1 - t0) * 1000.0
        durations.append(dur_ms)
        if ok:
            successes += 1
        last_val = res
        time.sleep(0.02) # kleine Pause
    p95 = percentile(durations, 0.95)
    return {
        "name": name,
        "runs": runs,
        "successes": successes,
        "p95_ms": round(p95, 1),
        "last": last_val
    }

# 1. GET /
def req_get_root():
    try:
        req = urllib.request.Request(f"{BASE_URL}/")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read()
            ct = resp.headers.get("Content-Type", "")
            return (resp.status == 200 and "text/html" in ct and len(data) < 40960), f"{len(data)}B"
    except Exception as e:
        return False, str(e)

# 2. GET /cgi-bin/api.cgi?action=status
def req_get_status():
    try:
        req = urllib.request.Request(f"{BASE_URL}/cgi-bin/api.cgi?action=status")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read()
            j = json.loads(data.decode("utf-8"))
            return (resp.status == 200 and j.get("ok") is True), j
    except Exception as e:
        return False, str(e)

# 3. POST /cgi-bin/api.cgi?action=left&step=1
def req_post_ptz():
    try:
        req = urllib.request.Request(f"{BASE_URL}/cgi-bin/api.cgi?action=left&step=1", data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read()
            j = json.loads(data.decode("utf-8"))
            return (resp.status == 200 and j.get("ok") is True), j
    except Exception as e:
        return False, str(e)

# 4. GET /cgi-bin/api.cgi?action=left (must be rejected)
def req_get_ptz_reject():
    try:
        req = urllib.request.Request(f"{BASE_URL}/cgi-bin/api.cgi?action=left")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read()
            j = json.loads(data.decode("utf-8"))
            return (j.get("ok") is False and j.get("err") == "post_required"), j
    except Exception as e:
        return False, str(e)

# 5. RTSP DESCRIBE Port 554 vs0
def req_rtsp_describe(path="vs0"):
    try:
        s = socket.create_connection((HOST, 554), timeout=3)
        req = (
            f"DESCRIBE rtsp://{HOST}:554/{path} RTSP/1.0\r\n"
            f"CSeq: 2\r\n"
            f"Accept: application/sdp\r\n\r\n"
        )
        s.sendall(req.encode("utf-8"))
        resp = s.recv(2048).decode("utf-8", errors="replace")
        s.close()
        return ("RTSP/1.0 200 OK" in resp and "application/sdp" in resp), "200_OK"
    except Exception as e:
        return False, str(e)

def main():
    print(f"=== STARTE TEST-MATRIX GEGEN {HOST} (je 20 Messungen) ===")
    
    r1 = test_endpoint("GET / (index.html)", req_get_root)
    print(f"[1/5] GET /: {r1['successes']}/{r1['runs']} OK, p95={r1['p95_ms']} ms (Schwelle < 150 ms)")

    r2 = test_endpoint("GET /cgi-bin/api.cgi?action=status", req_get_status)
    print(f"[2/5] Status-API: {r2['successes']}/{r2['runs']} OK, p95={r2['p95_ms']} ms (Schwelle < 100 ms)")

    r3 = test_endpoint("POST /cgi-bin/api.cgi?action=left&step=1", req_post_ptz)
    print(f"[3/5] PTZ POST: {r3['successes']}/{r3['runs']} OK, p95={r3['p95_ms']} ms (Schwelle < 100 ms)")

    r4 = test_endpoint("GET /cgi-bin/api.cgi?action=left (Reject)", req_get_ptz_reject)
    print(f"[4/5] PTZ GET Reject: {r4['successes']}/{r4['runs']} OK, p95={r4['p95_ms']} ms (Schwelle < 100 ms)")

    r5 = test_endpoint("RTSP DESCRIBE (Port 554 /vs0)", lambda: req_rtsp_describe("vs0"))
    print(f"[5/5] RTSP vs0: {r5['successes']}/{r5['runs']} OK, p95={r5['p95_ms']} ms (Schwelle < 500 ms)")

    r6 = test_endpoint("RTSP DESCRIBE (Port 554 /vs1)", lambda: req_rtsp_describe("vs1"))
    print(f"[6/5] RTSP vs1: {r6['successes']}/{r6['runs']} OK, p95={r6['p95_ms']} ms (Schwelle < 500 ms)")

    print("\n=== SICHERHEITSPRUEFUNGEN (Injection & CSRF) ===")
    injections = [
        ("action=left;id", "invalid_action"),
        ("action=left&step=9", "step_capped"),
        ("action=*", "invalid_action"),
        ("bad_referer", "bad_referer")
    ]
    for inj, exp in injections:
        if inj == "bad_referer":
            req = urllib.request.Request(f"{BASE_URL}/cgi-bin/api.cgi?action=left&step=1", data=b"", headers={"Referer": "http://evil.com/"})
        else:
            req = urllib.request.Request(f"{BASE_URL}/cgi-bin/api.cgi?{inj}", data=b"", method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                j = json.loads(resp.read().decode("utf-8"))
                print(f"Injection '{inj}': Antwort={j}")
        except Exception as e:
            print(f"Injection '{inj}': Exception={e}")

if __name__ == "__main__":
    main()
