#!/usr/bin/env python3
import os
import sys
import subprocess
import json
import hashlib
import ftplib
import glob
import time

VERIFY_DIR = "verify/sound-20261025_100514"
RAW_DIR = os.path.join(VERIFY_DIR, "raw")
HOST_DIR = os.path.join(VERIFY_DIR, "host")
AUDIO_HOST_DIR = os.path.join(HOST_DIR, "audio_files")
CAM_HOST = os.environ.get("CAM_HOST", "192.168.1.100")

os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs(HOST_DIR, exist_ok=True)
os.makedirs(AUDIO_HOST_DIR, exist_ok=True)

def exec_cam(cmd, raw_filename, timeout=45):
    print(f"[*] Cam exec ({timeout}s): {cmd}")
    try:
        res = subprocess.run(["./tools/cam_ctl.py", "--host", CAM_HOST, "exec", "--timeout", str(timeout), cmd],
                             capture_output=True, text=True, timeout=timeout+10)
        outpath = os.path.join(RAW_DIR, raw_filename)
        with open(outpath, "w", encoding="utf-8") as f:
            f.write(f"# COMMAND: {cmd}\n")
            f.write(res.stdout)
        if res.returncode != 0:
            print(f"Cam exec non-zero exit ({res.returncode}): {res.stderr}")
        return res.stdout
    except Exception as e:
        print(f"Cam exec failed/timeout: {e}")
        outpath = os.path.join(RAW_DIR, raw_filename)
        with open(outpath, "w", encoding="utf-8") as f:
            f.write(f"# COMMAND: {cmd}\n# ERROR: {e}\n")
        return ""

def run_host(cmd, host_filename):
    print(f"[*] Host exec: {cmd}")
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    outpath = os.path.join(HOST_DIR, host_filename)
    with open(outpath, "w", encoding="utf-8") as f:
        f.write(f"# COMMAND: {cmd}\n")
        f.write(res.stdout)
        if res.stderr:
            f.write("\n# STDERR:\n" + res.stderr)
    return res.stdout

# -------------------------------------------------------------
# S0 A1: Which files, which formats?
# -------------------------------------------------------------
print("\n=== S0 A1 ===")
exec_cam("find /usr/share/audio_file -type f", "a1_find_audio_file.txt")
exec_cam("ls -lR /usr/share/audio_file", "a1_ls_r_audio_file.txt")
exec_cam("ls -la /usr/share/audio_file/*/*.aac", "a1_ls_audio_files.txt")
exec_cam("md5sum /usr/share/audio_file/*/*.aac", "a1_md5sums_audio_files.txt")

# Fetch all audio files via FTP if not already present
print("[*] Checking / Fetching all audio files via FTP...")
need_fetch = any(not os.path.exists(os.path.join(AUDIO_HOST_DIR, s)) or len(os.listdir(os.path.join(AUDIO_HOST_DIR, s))) == 0 for s in ["common", "simplecn", "us"])
if need_fetch:
    ftp = ftplib.FTP(CAM_HOST, timeout=10)
    ftp.login(user="root", passwd="")
    ftp.voidcmd("TYPE I")
    for subdir in ["common", "simplecn", "us"]:
        local_sub = os.path.join(AUDIO_HOST_DIR, subdir)
        os.makedirs(local_sub, exist_ok=True)
        rem_sub = f"/usr/share/audio_file/{subdir}"
        for fname in ftp.nlst(rem_sub):
            bname = os.path.basename(fname)
            lpath = os.path.join(local_sub, bname)
            rem_file = f"{rem_sub}/{bname}"
            with open(lpath, "wb") as f:
                ftp.retrbinary(f"RETR {rem_file}", f.write)
    ftp.quit()
    print("[*] Fetched all files via FTP.")
else:
    print("[*] All 34 audio files already present on host.")

# Probe every audio file on host
audio_table = []
for root, _, files in sorted(os.walk(AUDIO_HOST_DIR)):
    for f in sorted(files):
        if not f.endswith(".aac"): continue
        fpath = os.path.join(root, f)
        relpath = os.path.relpath(fpath, HOST_DIR)
        size = os.path.getsize(fpath)
        with open(fpath, "rb") as afile:
            head16 = afile.read(16)
        hex16 = " ".join(f"{b:02x}" for b in head16)
        
        # ffprobe
        res = subprocess.run(
            ["ffprobe", "-hide_banner", "-v", "error", "-show_streams", "-show_format", "-of", "json", fpath],
            capture_output=True, text=True
        )
        dur = "?"
        sr = "?"
        channels = "?"
        codec = "?"
        profile = "?"
        try:
            data = json.loads(res.stdout)
            if "streams" in data and len(data["streams"]) > 0:
                s = data["streams"][0]
                codec = s.get("codec_name", "?")
                profile = s.get("profile", "?")
                sr = s.get("sample_rate", "?")
                channels = s.get("channels", "?")
            if "format" in data:
                dur = data["format"].get("duration", "?")
        except Exception as e:
            pass
        
        audio_table.append({
            "relpath": relpath,
            "filename": f,
            "category": os.path.basename(root),
            "size": size,
            "hex16": hex16,
            "codec": codec,
            "profile": profile,
            "sample_rate": sr,
            "channels": channels,
            "duration": dur
        })

with open(os.path.join(HOST_DIR, "a1_audio_files_analysis.json"), "w") as jf:
    json.dump(audio_table, jf, indent=2)

with open(os.path.join(HOST_DIR, "a1_audio_files_table.txt"), "w") as tf:
    tf.write(f"{'Pfad':<35} | {'Größe':<7} | {'Codec':<6} | {'Profil':<12} | {'Rate':<6} | {'Ch':<3} | {'Dauer (s)':<9} | {'Erste 16 Bytes Hex'}\n")
    tf.write("-" * 125 + "\n")
    for row in audio_table:
        dur_str = f"{float(row['duration']):<9.3f}" if row['duration'] != "?" else "?        "
        tf.write(f"{row['relpath']:<35} | {row['size']:<7} | {row['codec']:<6} | {row['profile']:<12} | {row['sample_rate']:<6} | {row['channels']:<3} | {dur_str} | {row['hex16']}\n")

# -------------------------------------------------------------
# S0 A2: Who plays audio, when, how?
# -------------------------------------------------------------
print("\n=== S0 A2 ===")
exec_cam("grep -r -n -i -E 'audio_file|poweron|connectting|wifi_connected|\\.aac|aplay|ak_ao|play|sound|voice|prompt' /etc /usr/sbin /usr/bin /mnt/custom 2>/dev/null", "a2_grep_audio.txt", timeout=60)
exec_cam("ls -l /proc/[0-9]*/fd 2>/dev/null | grep -i -E 'snd|audio|dsp|/ao|pcm'", "a2_open_audio_fds.txt")
exec_cam("ls -la /dev | grep -i -E 'snd|audio|dsp|ao|adec|pcm'", "a2_dev_audio.txt")
exec_cam("ls -la /sys/user-gpio/", "a2_sys_user_gpio.txt")
exec_cam("ls -la /mnt /mnt/custom /mnt/_Factory 2>/dev/null", "a2_sd_scripts.txt")
exec_cam("dmesg | grep -i -E 'audio|sound|pcm|dac|codec|ao|ai|speaker|spk'", "a2_dmesg_audio.txt")

# Strings of anyka_ipc (from extracted squashfs usr/bin/anyka_ipc)
run_host("strings /tmp/sq5/root/bin/anyka_ipc | grep -i -E 'audio_file|\\.aac|didi|poweron|connectting|wifi_connected|yi_play_audio|ak_ao|spk_pa'", "a2_strings_anyka_ipc_audio.txt")
run_host("strings /tmp/sq5/root/bin/anyka_ipc | grep -E '^/usr|^/tmp|^/mnt|^/etc'", "a2_strings_anyka_ipc_paths.txt")

# -------------------------------------------------------------
# S0 A3: Configurability instead of Mount
# -------------------------------------------------------------
print("\n=== S0 A3 ===")
exec_cam("grep -i -E 'vol|gain|voice|speak|sound|audio|prompt|tone|mute|ao' /etc/jffs2/anyka_cfg.ini /etc/jffs2/yi_cfg.ini /etc/jffs2/gpio.conf /etc/jffs2/hw.conf 2>/dev/null", "a3_ini_audio_search.txt")
run_host("strings /tmp/sq5/root/bin/anyka_ipc | grep -i -E 'volume|mute|speak|prompt|voice|alarm_sound|audio_out_digi_gain|audio_in_digi_gain|spk' | sort -u", "a3_anyka_ipc_audio_config_keys.txt")

# -------------------------------------------------------------
# S0 A5: Dependency WLAN <-> anyka_ipc
# -------------------------------------------------------------
print("\n=== S0 A5 ===")
exec_cam("ps w", "a5_ps_w.txt")
exec_cam(r"for d in /proc/[0-9]*; do [ -d \"$d\" ] && echo \"${d#/proc/}: PPID=\$(awk '{print \$4}' \$d/stat 2>/dev/null) CMD=\$(tr '\0' ' ' < \$d/cmdline 2>/dev/null)\"; done", "a5_process_tree.txt")
exec_cam("cat /usr/sbin/service.sh", "a5_service_sh.txt")
exec_cam("cat /usr/sbin/anyka_ipc.sh", "a5_anyka_ipc_sh.txt")
exec_cam("cat /usr/sbin/wifi_manage.sh 2>/dev/null", "a5_wifi_manage_sh.txt")
exec_cam("cat /usr/sbin/wifi_run.sh 2>/dev/null", "a5_wifi_run_sh.txt")
run_host("strings /tmp/sq5/root/bin/anyka_ipc | grep -i -E 'wpa_supplicant|udhcpc|wlan0|wifi_manage|wifi_run|8188fu'", "a5_strings_anyka_ipc_wlan.txt")

# -------------------------------------------------------------
# S0 A6: Sequence & Timing
# -------------------------------------------------------------
print("\n=== S0 A6 ===")
exec_cam("cat /etc/init.d/rc.local", "a6_rc_local.txt")
exec_cam("cat /etc/init.d/rcS", "a6_rcS.txt")
exec_cam("cat /mnt/anyka_webui/boot.log", "a6_boot_log.txt")
exec_cam("uptime", "a6_uptime.txt")

# -------------------------------------------------------------
# S0 A7: Mount mechanics & side effects
# -------------------------------------------------------------
print("\n=== S0 A7 ===")
exec_cam("ls -l /proc/[0-9]*/fd 2>/dev/null | grep audio_file || echo 'NO_OPEN_AUDIO_FILES'", "a7_check_open_audio_files.txt")
exec_cam("which mount; which umount; /bin/busybox | head -n 2", "a7_mount_tools.txt")
exec_cam("cat /etc/profile", "a7_etc_profile.txt")

# -------------------------------------------------------------
# S0 A8: RTSP Microphone Audio Baseline
# -------------------------------------------------------------
print("\n=== S0 A8 ===")
run_host("ffprobe -hide_banner -rtsp_transport tcp -v error -show_streams -show_format -of json rtsp://" + CAM_HOST + ":554/vs0", "a8_rtsp_vs0_ffprobe.json")
run_host("ffmpeg -y -hide_banner -rtsp_transport tcp -t 10 -i rtsp://" + CAM_HOST + ":554/vs0 -af astats=metadata=1:reset=1 -f null -", "a8_rtsp_vs0_astats.txt")

# -------------------------------------------------------------
# S0 A9 & A10: Rollback & Rescue paths
# -------------------------------------------------------------
print("\n=== S0 A9 & A10 ===")
exec_cam("cat /etc/jffs2/time_zone.sh", "a9_current_time_zone_sh.txt")
exec_cam("cat /etc/jffs2/time_zone.sh.orig 2>/dev/null", "a9_orig_time_zone_sh.txt")
exec_cam("diff -u /etc/jffs2/time_zone.sh.orig /etc/jffs2/time_zone.sh 2>/dev/null || true", "a9_diff_orig_vs_current.txt")
exec_cam("df -k /etc/jffs2", "a9_df_jffs2.txt")
exec_cam("ls -la /mnt/update 2>/dev/null || echo 'NO_UPDATE_DIR'", "a10_mnt_update.txt")

print("\nAll initial tests completed.")
