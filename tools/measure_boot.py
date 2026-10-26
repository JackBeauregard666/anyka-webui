#!/usr/bin/env python3
import sys
import os
import time
import socket
import urllib.request
import subprocess
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cam_ctl import AnykaTelnet

HOST = os.environ.get("CAM_HOST", "192.168.1.100")
PORT_TELNET = 23
PORT_HTTP = 80
PORT_RTSP = 554

def check_port(host, port, timeout=0.3):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False

def check_http(host, timeout=0.4):
    try:
        url = f"http://{host}/"
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False

def test_ffprobe(host, timeout=6):
    url = f"rtsp://{host}:{PORT_RTSP}/vs0"
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "stream=codec_name",
        "-of", "default=noprint_wrappers=1:nokey=1",
        "-rtsp_transport", "tcp",
        url
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        lines = [l.strip() for l in p.stdout.splitlines() if l.strip()]
        return ("h264" in lines), lines
    except Exception as e:
        return False, str(e)

def test_ptz(host, timeout=4):
    url = f"http://{host}/cgi-bin/api.cgi?action=left&step=1"
    req = urllib.request.Request(url, method="POST", data=b"")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return ('"ok":true' in body or '"ok": true' in body), body
    except Exception as e:
        return False, str(e)

def is_camera_alive():
    p = subprocess.run(["ping", "-c", "1", "-W", "1", HOST], capture_output=True)
    if p.returncode == 0:
        return True
    return check_port(HOST, PORT_TELNET, timeout=0.5)

def wait_for_power_off():
    print("Warte darauf, dass der Strom getrennt wird...", flush=True)
    down_count = 0
    while True:
        if not is_camera_alive():
            down_count += 1
            if down_count >= 3:
                print("Kamera ist stromlos!", flush=True)
                return True
        else:
            down_count = 0
        time.sleep(1)

def wait_for_down(timeout=30):
    t0 = time.time()
    print("Warte auf Verbindungsabbruch (Reboot)...")
    while time.time() - t0 < timeout:
        if not check_port(HOST, PORT_TELNET, timeout=0.3):
            print(f"Kamera getrennt nach {time.time()-t0:.1f}s.")
            return True
        time.sleep(0.3)
    print("FEHLER: Kamera hat nicht neu gestartet (Telnet blieb offen)!")
    return False

def trigger_reboot():
    print("Sende 'sync && reboot' an Kamera...")
    try:
        subprocess.run(["./tools/cam_ctl.py", "--host", HOST, "exec", "sync && reboot"], timeout=5)
    except Exception:
        pass

def monitor_boot(max_wait=90):
    t0 = time.time()
    print("Warte auf Wiederverbindung...")
    
    # 1. Wait for Telnet port to open
    while time.time() - t0 < max_wait:
        if check_port(HOST, PORT_TELNET, timeout=0.3):
            print(f"Telnet-Port 23 offen nach {time.time()-t0:.1f}s!")
            break
        time.sleep(0.2)
    else:
        print("FEHLER: Telnet-Port nicht erreichbar!")
        return None

    # Connect persistent telnet
    tn = None
    for attempt in range(5):
        try:
            tn = AnykaTelnet(HOST, PORT_TELNET, timeout=5)
            tn.login("root", "")
            break
        except Exception as e:
            print(f"Telnet-Login Versuch {attempt+1} fehlgeschlagen ({e}), warte 0.5s...")
            time.sleep(0.5)

    def query_uptime():
        nonlocal tn
        for _ in range(3):
            try:
                if tn is None:
                    tn = AnykaTelnet(HOST, PORT_TELNET, timeout=3)
                    tn.login("root", "")
                rc, out = tn.run("cat /proc/uptime", timeout=2)
                if rc == 0:
                    parts = out.strip().split()
                    if len(parts) >= 1:
                        return float(parts[0])
            except Exception:
                try:
                    if tn:
                        tn.close()
                except Exception:
                    pass
                tn = None
                time.sleep(0.2)
        return None

    init_upt = query_uptime()
    print(f"Kamera-Uptime bei erstem Telnet-Login: {init_upt}s")

    http_up_at = None
    rtsp_port_up_at = None
    
    # 2. Poll HTTP and RTSP until both are up
    loop_start = time.time()
    while time.time() - loop_start < max_wait:
        if http_up_at is None and check_http(HOST, timeout=0.3):
            http_up_at = query_uptime()
            print(f"WebUI antwortet (HTTP 200) bei Uptime ~{http_up_at}s")
            
        if rtsp_port_up_at is None and check_port(HOST, PORT_RTSP, timeout=0.3):
            rtsp_port_up_at = query_uptime()
            print(f"Port 554 (RTSP) lauscht bei Uptime ~{rtsp_port_up_at}s")
            
        if http_up_at is not None and rtsp_port_up_at is not None:
            break
        time.sleep(0.25)

    # 3. Wait 3 seconds for stream to start pumping frames
    print("Warte 3s zur Puffer- und Streamstabilisierung...")
    time.sleep(3)

    # 4. Test ffprobe
    print("Teste ffprobe H.264...")
    ff_ok, ff_out = test_ffprobe(HOST, timeout=8)
    print(f"ffprobe H.264: {ff_ok} ({ff_out})")

    # 5. Test PTZ
    print("Teste PTZ...")
    ptz_ok, ptz_out = test_ptz(HOST, timeout=5)
    print(f"PTZ: {ptz_ok} ({ptz_out.strip()})")

    # 6. Checks on Camera
    # Exact user command: ps w | grep -E "anyka_ipc|daemon|cmd_serverd"
    rc, ps_exact = tn.run('ps w | grep -E "anyka_ipc|daemon|cmd_serverd"', timeout=5)
    
    # Filtered command to see if factory daemon/anyka_ipc/cmd_serverd is running:
    rc, ps_filtered = tn.run('ps w | grep -E "anyka_ipc|[ /]daemon|cmd_serverd" | grep -v grep', timeout=5)
    
    # grep -ci busy /tmp/rtsp.log
    rc, busy_out = tn.run('grep -ci busy /tmp/rtsp.log', timeout=5)
    busy_count = None
    for line in busy_out.splitlines():
        if line.strip().isdigit():
            busy_count = int(line.strip())
            break
            
    # Read supervisor log
    rc, slog = tn.run('cat /mnt/anyka_webui/rtsp_supervisor.log', timeout=5)
    
    # Read boot.log from start_webui.sh
    rc, bootlog = tn.run('cat /mnt/anyka_webui/boot.log', timeout=5)

    tn.close()

    # Parse last supervisor session
    sessions = slog.split("=== Supervisor Start ===")
    last_session = sessions[-1] if len(sessions) > 1 else slog
    
    rtsp_started_upt = None
    anyka_stop_duration = None
    restarts = 0
    
    for line in last_session.splitlines():
        if "rtsp gestartet" in line:
            if "[" in line and "s]" in line:
                try:
                    rtsp_started_upt = float(line.split("[")[1].split("s]")[0])
                except Exception:
                    pass
        if "anyka_ipc beendet" in line:
            if "nach " in line and "s" in line:
                try:
                    anyka_stop_duration = line.split("nach ")[1].split("s")[0] + "s"
                except Exception:
                    pass
            else:
                anyka_stop_duration = "vorhanden"
        if "rtsp beendet" in line:
            restarts += 1

    result = {
        "rtsp_started_upt": rtsp_started_upt,
        "rtsp_port_up_at": rtsp_port_up_at,
        "http_up_at": http_up_at,
        "ffprobe_h264": ff_ok,
        "ffprobe_streams": ff_out,
        "ptz_ok": ptz_ok,
        "ptz_resp": ptz_out.strip(),
        "ps_exact_raw": ps_exact.strip(),
        "unauthorized_procs_filtered": ps_filtered.strip(),
        "busy_count": busy_count,
        "restarts": restarts,
        "anyka_stop_duration": anyka_stop_duration,
        "raw_supervisor_session": last_session.strip(),
        "raw_boot_log": bootlog.strip()
    }
    return result

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "reboot"
    if mode == "reboot":
        trigger_reboot()
        if not wait_for_down():
            sys.exit(1)
    elif mode == "coldboot":
        print("Kaltstart-Modus: Warte auf Trennung der Kamera (Strom ziehen)...", flush=True)
        wait_for_power_off()
        print("Kamera ist stromlos. Warte auf Wiederverbindung nach dem Einstecken...", flush=True)
        res = monitor_boot(max_wait=300)
        print("\n--- RESULT JSON ---", flush=True)
        print(json.dumps(res, indent=2), flush=True)
        sys.exit(0)
    elif mode == "test":
        print("Test-Modus (kein Reboot)...")

    res = monitor_boot(max_wait=180)
    print("\n--- RESULT JSON ---")
    print(json.dumps(res, indent=2))
