#!/usr/bin/env python3
import sys
import os
import time
import socket

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cam_ctl import AnykaTelnet

HOST = os.environ.get("CAM_HOST", "192.168.1.100")

def run_cmd(tn, cmd, timeout=30):
    rc, out = tn.run(cmd, timeout=timeout)
    return out.strip()

def test_move(tn, pan, tilt):
    # Set target via FIFO
    print(f"\n--- Fahre auf ({pan}, {tilt}) ---", flush=True)
    t0 = time.time()
    # Write t2p command with 3<> descriptor so it never blocks
    cmd = f"{{ printf 't2p {pan} {tilt}\\n' >&3; }} 3<>/tmp/ptz.daemon"
    run_cmd(tn, cmd)
    
    # Poll ptz.ini
    target_str = f"{pan} {tilt}"
    while time.time() - t0 < 30:
        res = run_cmd(tn, "cat /etc/jffs2/ptz.ini 2>/dev/null", timeout=3)
        lines = [l.strip() for l in res.splitlines() if l.strip()]
        if lines and lines[0] == target_str:
            elapsed = time.time() - t0
            print(f"Ziel ({pan}, {tilt}) erreicht nach {elapsed:.2f}s!", flush=True)
            return elapsed
        time.sleep(0.15)
    print("TIMEOUT!", flush=True)
    return None

def main():
    tn = AnykaTelnet(HOST, 23, timeout=15)
    tn.login("root", "")
    
    print("Aktuelle Position:", run_cmd(tn, "cat /etc/jffs2/ptz.ini"))
    
    # 1. Zuerst auf Ausgangsposition für Test (180, 70)
    test_move(tn, 180, 70)
    time.sleep(1)
    
    # 2. Kleine Fahrt (±10° Pan): 180 -> 190
    print("\n[MESSUNG 1] Kleine Fahrt: Pan 180 -> 190 (Delta 10°)")
    dur_small = test_move(tn, 190, 70)
    time.sleep(1)
    
    # Zurück auf 180
    test_move(tn, 180, 70)
    time.sleep(1)
    
    # 3. Vorbereitung Pan-Test: Fahre auf Pan 15
    print("\nVorbereitung: Fahre auf Pan 15...")
    test_move(tn, 15, 70)
    time.sleep(1)
    
    # [MESSUNG 2] Pan 15 -> 335 (Delta 320°)
    print("\n[MESSUNG 2] Große Pan-Fahrt: Pan 15 -> 335 (Delta 320°)")
    dur_pan = test_move(tn, 335, 70)
    time.sleep(1)
    
    # 4. Vorbereitung Tilt-Test: Fahre auf Tilt 15
    print("\nVorbereitung: Fahre auf Tilt 15...")
    test_move(tn, 335, 15)
    time.sleep(1)
    
    # [MESSUNG 3] Tilt 15 -> 110 (Delta 95°)
    print("\n[MESSUNG 3] Tilt-Fahrt: Tilt 15 -> 110 (Delta 95°)")
    dur_tilt = test_move(tn, 335, 110)
    time.sleep(1)
    
    # [MESSUNG 4] Kombinierte Fahrt: Pan 335 -> 15 und Tilt 110 -> 15
    print("\n[MESSUNG 4] Kombinierte Fahrt: (335, 110) -> (15, 15) (Delta Pan 320°, Delta Tilt 95°)")
    dur_kombi = test_move(tn, 15, 15)
    time.sleep(1)
    
    # Zurück auf Normalposition (180, 70)
    print("\nFahre zurück auf Normalposition (180, 70)...")
    test_move(tn, 180, 70)
    
    tn.close()
    
    print("\n=== ZUSAMMENFASSUNG DER MESSUNGEN ===")
    print(f"Kleine Fahrt 10°: {dur_small}s -> {10/dur_small:.2f}°/s")
    print(f"Pan 320°: {dur_pan}s -> {320/dur_pan:.2f}°/s")
    print(f"Tilt 95°: {dur_tilt}s -> {95/dur_tilt:.2f}°/s")
    print(f"Kombiniert (Pan 320°, Tilt 95°): {dur_kombi}s")

if __name__ == "__main__":
    main()
