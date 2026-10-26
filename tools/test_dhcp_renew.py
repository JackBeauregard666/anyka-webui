#!/usr/bin/env python3
import subprocess
import time

HOST = os.environ.get("CAM_HOST", "192.168.1.100")
LOG_FILE = "verify/current/host/dhcp_renew_test.txt"

print("Starting background continuous ping...")
ping_proc = subprocess.Popen(["ping", "-i", "0.2", HOST], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

out_lines = []
out_lines.append("=== DHCP RENEWAL TEST WITH CONTINUOUS PING ===")

def run_cam(cmd):
    res = subprocess.run(["python3", "tools/cam_ctl.py", "--host", HOST, "exec", cmd], capture_output=True, text=True)
    return res.stdout.strip()

try:
    time.sleep(1) # let ping start
    out_lines.append(f"UDHCPC PID: {run_cam('pidof udhcpc')}")
    out_lines.append("--- PRE-RENEW STATUS ---")
    out_lines.append(run_cam("cat /proc/net/route; cat /etc/resolv.conf; ifconfig wlan0 | grep 'inet addr'"))

    # Renew 1
    print("Triggering Renew 1...")
    out_lines.append("\n--- TRIGGERING RENEW 1 (SIGUSR1) ---")
    out_lines.append(run_cam("kill -USR1 $(pidof udhcpc)"))
    time.sleep(3)
    out_lines.append("--- POST-RENEW 1 STATUS ---")
    out_lines.append(run_cam("cat /proc/net/route; cat /etc/resolv.conf; ifconfig wlan0 | grep 'inet addr'"))

    # Renew 2
    print("Triggering Renew 2...")
    out_lines.append("\n--- TRIGGERING RENEW 2 (SIGUSR1) ---")
    out_lines.append(run_cam("kill -USR1 $(pidof udhcpc)"))
    time.sleep(3)
    out_lines.append("--- POST-RENEW 2 STATUS ---")
    out_lines.append(run_cam("cat /proc/net/route; cat /etc/resolv.conf; ifconfig wlan0 | grep 'inet addr'"))

finally:
    ping_proc.terminate()
    ping_out, ping_err = ping_proc.communicate()
    out_lines.append("\n--- PING STATISTICS ---")
    out_lines.append(ping_out)

with open(LOG_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(out_lines) + "\n")

print(f"Saved {LOG_FILE}")
