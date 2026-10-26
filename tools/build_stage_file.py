#!/usr/bin/env python3
import os
import difflib

# Read current active file from camera copy
with open("verify/sound-20261025_100514/raw/a9_current_time_zone_sh.txt") as f:
    lines = f.readlines()

# Strip command header and shell prompt footer
clean_lines = []
for line in lines:
    if line.startswith("# COMMAND:") or line.startswith("[@anyka"):
        continue
    clean_lines.append(line)

current_content = "".join(clean_lines).strip() + "\n"

# Octal string
with open("verify/sound-20261025_100514/host/a4_octal.txt") as f:
    octal_str = f.read().strip()

silence_block = f"""
# ---------- BOOT-SOUND STUMMSCHALTUNG (Stufe 1: poweron.aac) ----------
(
    [ -e /etc/jffs2/DISABLE_SILENCE ] && exit 0
    [ -e /etc/jffs2/SILENCE_FAILED ] && exit 0
    [ -e /tmp/.silence_applied ] && exit 0
    is_mounted() {{
        while read -r _ mp _; do
            [ "$mp" = "$1" ] && return 0
        done < /proc/mounts
        return 1
    }}
    SIL=/tmp/silent.aac
    printf '{octal_str}' > "$SIL" || exit 0
    for f in /usr/share/audio_file/common/poweron.aac; do
        [ -f "$f" ] || continue
        is_mounted "$f" && continue
        mount --bind "$SIL" "$f" 2>/dev/null
    done
    read -r up _ < /proc/uptime
    echo "$up" > /tmp/early_hook_uptime
    : > /tmp/.silence_applied

    if [ ! -e /tmp/.silence_guard_started ]; then
        : > /tmp/.silence_guard_started
        (
            sleep 65
            if ! ifconfig wlan0 >/dev/null 2>&1 || ! pidof wpa_supplicant >/dev/null 2>&1; then
                : > /etc/jffs2/SILENCE_FAILED
                sync
                for mf in /usr/share/audio_file/common/poweron.aac; do
                    umount "$mf" 2>/dev/null
                done
                reboot
            fi
        ) </dev/null >/dev/null 2>&1 &
    fi
)
"""

# Insert silence block right after the anchor
# The anchor ends after tcpsvd ...
anchor_end = "pidof tcpsvd >/dev/null 2>&1 || pidof ftpd >/dev/null 2>&1 || /usr/bin/tcpsvd 0 21 ftpd -w / -t 600 >/dev/null 2>&1 &"
assert anchor_end in current_content, "Anchor not found in current content!"

parts = current_content.split(anchor_end)
new_content = parts[0] + anchor_end + "\n" + silence_block + parts[1]

# Save to staging
os.makedirs("verify/sound-20261025_100514/staging", exist_ok=True)
with open("verify/sound-20261025_100514/staging/time_zone.sh.current", "w") as f:
    f.write(current_content)

with open("verify/sound-20261025_100514/staging/time_zone.sh.new", "w") as f:
    f.write(new_content)

# Also generate unified diff
diff_lines = list(difflib.unified_diff(
    current_content.splitlines(keepends=True),
    new_content.splitlines(keepends=True),
    fromfile="/etc/jffs2/time_zone.sh (aktuell)",
    tofile="/etc/jffs2/time_zone.sh.new (Stufe 1)",
    n=3
))
diff_str = "".join(diff_lines)

with open("verify/sound-20261025_100514/staging/time_zone.diff", "w") as f:
    f.write(diff_str)

print("Unified diff:")
print(diff_str)
