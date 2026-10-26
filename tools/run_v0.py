#!/usr/bin/env python3
import os
import sys
import subprocess

HOST = os.environ.get("CAM_HOST", "192.168.1.100")
RAW_DIR = "verify/current/raw"

commands = [
    # System
    ("uname_-a.txt", "uname -a"),
    ("proc_cpuinfo.txt", "cat /proc/cpuinfo"),
    ("proc_cmdline.txt", "cat /proc/cmdline"),
    ("proc_version.txt", "cat /proc/version"),
    ("uptime.txt", "uptime"),
    ("proc_loadavg.txt", "cat /proc/loadavg"),
    ("proc_meminfo.txt", "cat /proc/meminfo"),
    ("proc_mtd.txt", "cat /proc/mtd"),
    ("mount.txt", "mount"),
    ("df_-k.txt", "df -k"),
    ("proc_interrupts.txt", "cat /proc/interrupts"),
    ("lsmod.txt", "lsmod"),
    ("ls_l_dev.txt", "ls -l /dev"),
    ("busybox_version.txt", "busybox"),
    ("busybox_list.txt", "busybox --list"),
    ("custom_busybox_version.txt", "/mnt/custom/busybox"),
    ("custom_busybox_list.txt", "/mnt/custom/busybox --list"),

    # Prozesse mit vollständiger Kommandozeile
    ("ps_cmdline.txt", "for d in /proc/[0-9]*; do c=\"$(tr '\\0' ' ' < \"$d/cmdline\" 2>/dev/null)\"; [ -n \"$c\" ] && echo \"${d#/proc/}: $c\"; done"),
    ("daemon_status.txt", "for p in $(pidof rtsp ptz_daemon httpd telnetd tcpsvd ftpd udhcpc wpa_supplicant 2>/dev/null); do echo \"=== PID $p ===\"; grep -E 'VmRSS|VmSize|Threads|Name' /proc/$p/status 2>/dev/null; done"),

    # Netz
    ("ifconfig_-a.txt", "ifconfig -a"),
    ("proc_net_route.txt", "cat /proc/net/route"),
    ("etc_resolv_conf.txt", "cat /etc/resolv.conf"),
    ("proc_net_tcp.txt", "cat /proc/net/tcp"),
    ("proc_net_udp.txt", "cat /proc/net/udp"),
    ("port_fd_map.txt", "for d in /proc/[0-9]*/fd/*; do target=$(ls -l \"$d\" 2>/dev/null | grep -E 'socket:|net'); if [ -n \"$target\" ]; then echo \"$d -> $target\"; fi; done"),
    ("proc_net_wireless.txt", "cat /proc/net/wireless"),
    ("proc_net_if_inet6.txt", "[ -e /proc/net/if_inet6 ] && cat /proc/net/if_inet6 || echo 'kein IPv6'"),
    ("netstat_tupn.txt", "netstat -tupn 2>/dev/null || netstat -tlpn 2>/dev/null || netstat -an 2>/dev/null"),

    # Kernel-Log
    ("dmesg_tail120.txt", "dmesg | tail -n 120"),
    ("dmesg_grep.txt", "dmesg | grep -i -E 'wdt|watchdog|sensor|isp|gpio|ircut|wifi|mmc'"),

    # Boot & Dateisystem
    ("boot_log.txt", "cat /mnt/anyka_webui/boot.log"),
    ("sd_anyka_webui_files.txt", "ls -laR /mnt/anyka_webui/"),
    ("etc_jffs2_ls.txt", "ls -la /etc/jffs2/"),
    ("tmp_ls.txt", "ls -la /tmp /tmp/www /tmp/www/cgi-bin"),
    ("df_k_tmp.txt", "df -k /tmp"),

    # Versionen & Prüfsummen Binaries
    ("binaries_md5.txt", "md5sum /mnt/custom/rtsp /mnt/custom/ptz_daemon /mnt/custom/busybox /usr/bin/tcpsvd /usr/sbin/service.sh /etc/jffs2/time_zone.sh 2>/dev/null")
]

for filename, cmd in commands:
    out_path = os.path.join(RAW_DIR, filename)
    print(f"Executing: {cmd} -> {out_path}")
    proc = subprocess.run(
        ["python3", "tools/cam_ctl.py", "--host", HOST, "exec", cmd],
        capture_output=True,
        text=True
    )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# COMMAND: {cmd}\n")
        f.write(proc.stdout)
        if proc.stderr:
            f.write("\n# STDERR:\n" + proc.stderr)
    if proc.returncode != 0:
        print(f"  Warning: return code {proc.returncode}")

print("V0 raw command collection complete!")
