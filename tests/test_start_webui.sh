#!/bin/sh
set -e

# Host-Test fuer start_webui.sh (POSIX sh).
# Die Kamera-Kommandos (ifconfig, route, mount, pidof, sleep, sync) werden durch
# Stubs ersetzt, alle Pfade zeigen in ein temporaeres Verzeichnis. Es wird nichts
# am Host veraendert und nichts aus dem Netz gelesen.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

WORK="$(mktemp -d /tmp/test_start_webui.XXXXXX)"
trap 'touch "$WORK/stop" 2>/dev/null; sleep 0.3; rm -rf "$WORK"' EXIT INT TERM

STUBS="$WORK/stubs"
mkdir -p "$STUBS"

cat > "$STUBS/ifconfig" <<'EOF'
#!/bin/sh
echo "wlan0     Link encap:Ethernet  HWaddr 00:11:22:33:44:55"
echo "          inet addr:192.168.1.50  Bcast:192.168.1.255  Mask:255.255.255.0"
EOF

cat > "$STUBS/route" <<'EOF'
#!/bin/sh
# Emuliert "route del default": entfernt die erste Default-Zeile aus der Fake-Routentabelle
[ "$1" = "del" ] && [ "$2" = "default" ] || exit 1
awk '$2=="00000000" && $8=="00000000"{f=1} END{exit !f}' "$WEBUI_PROC_ROUTE" || exit 1
awk 'BEGIN{d=0} { if (!d && $2=="00000000" && $8=="00000000") { d=1; next } print }' \
    "$WEBUI_PROC_ROUTE" > "$WEBUI_PROC_ROUTE.new"
mv "$WEBUI_PROC_ROUTE.new" "$WEBUI_PROC_ROUTE"
EOF

cat > "$STUBS/mount" <<'EOF'
#!/bin/sh
# Emuliert "mount --bind QUELLE ZIEL" durch Kopieren; STUB_MOUNT_FAIL=1 laesst es scheitern
[ "$1" = "--bind" ] || exit 1
[ -n "$STUB_MOUNT_FAIL" ] && exit 1
echo "$2 $3" >> "$WORK_DIR/mount_calls"
cp "$2" "$3"
EOF

cat > "$STUBS/pidof" <<'EOF'
#!/bin/sh
exit 1
EOF

cat > "$STUBS/sleep" <<'EOF'
#!/bin/sh
# Beendet die aufrufende Hintergrundschleife, sobald die Stop-Datei existiert
[ -e "$WORK_DIR/stop" ] && kill "$PPID" 2>/dev/null
exec /bin/sleep 0.05
EOF

cat > "$STUBS/sync" <<'EOF'
#!/bin/sh
exit 0
EOF

cat > "$STUBS/wifi_manage.sh" <<'EOF'
#!/bin/sh
echo "$@" >> "$WORK_DIR/wifi_manage_calls"
EOF
chmod +x "$STUBS"/*

DEFAULT_ROUTE_LINE="wlan0 00000000 0100A8C0 0003 0 0 0 00000000"
LAN_ROUTE_LINE="wlan0 0000A8C0 00000000 0001 0 0 0 00FFFFFF"

# new_case NAME: frische SD-Karte, Fake-Rootfs und Routentabelle anlegen
new_case() {
    CASE="$WORK/$1"
    rm -rf "$CASE"
    mkdir -p "$CASE/sd/anyka_webui/bin" "$CASE/sd/anyka_webui/www/cgi-bin" "$CASE/sd/custom" \
             "$CASE/tmp" "$CASE/jffs2" "$CASE/rootfs"
    SD="$CASE/sd"
    cp "$REPO_ROOT/bin/udhcpc_lanonly.sh" "$SD/anyka_webui/bin/"
    cp "$REPO_ROOT/webui/www/index.html" "$SD/anyka_webui/www/"
    cp "$REPO_ROOT/webui/www/cgi-bin/api.cgi" "$SD/anyka_webui/www/cgi-bin/"
    printf '#!/bin/sh\necho started > "%s/supervisor_started"\n' "$CASE" > "$SD/anyka_webui/rtsp_supervisor.sh"
    printf '#!/bin/sh\necho started > "%s/ptz_started"\n' "$CASE" > "$SD/custom/ptz_daemon"
    printf '#!/bin/sh\necho "$@" > "%s/httpd_args"\n' "$CASE" > "$SD/custom/busybox"
    chmod +x "$SD/custom/ptz_daemon" "$SD/custom/busybox"
    printf '#!/bin/sh\n# Werksskript\n' > "$CASE/rootfs/default1.script"
    printf '#!/bin/sh\n# Werksskript\n' > "$CASE/rootfs/default2.script"
    printf 'Iface Destination Gateway Flags RefCnt Use Metric Mask\n%s\n%s\n%s\n' \
        "$LAN_ROUTE_LINE" "$DEFAULT_ROUTE_LINE" "$DEFAULT_ROUTE_LINE" > "$CASE/route"
    echo "35.2 20.0" > "$CASE/uptime"
    printf 'nameserver 8.8.8.8\n' > "$CASE/jffs2/resolv.conf"
    rm -f "$WORK/stop" "$WORK/mount_calls"
}

# run_case [Umgebungsvariablen...]: start_webui.sh mit Stubs ausfuehren
run_case() {
    env PATH="$STUBS:$PATH" \
        WORK_DIR="$WORK" \
        WEBUI_TMP_DIR="$CASE/tmp" \
        WEBUI_JFFS2_DIR="$CASE/jffs2" \
        WEBUI_PROC_ROUTE="$CASE/route" \
        WEBUI_PROC_UPTIME="$CASE/uptime" \
        WEBUI_WIFI_MANAGE="$STUBS/wifi_manage.sh" \
        WEBUI_DHCP_SCRIPTS="$CASE/rootfs/default1.script $CASE/rootfs/default2.script" \
        "$@" \
        sh "$REPO_ROOT/start_webui.sh" "$SD"
    # Hintergrundschleifen beenden und kurz warten, bis Stubs fertig geschrieben haben
    touch "$WORK/stop"
    sleep 0.4
}

assert_log() {
    if ! grep -F -- "$1" "$SD/anyka_webui/boot.log" >/dev/null; then
        echo "FEHLER: boot.log enthaelt nicht: $1"
        echo "--- boot.log ---"; cat "$SD/anyka_webui/boot.log"
        exit 1
    fi
}

assert_no_log() {
    if grep -F -- "$1" "$SD/anyka_webui/boot.log" >/dev/null; then
        echo "FEHLER: boot.log enthaelt unerwartet: $1"
        echo "--- boot.log ---"; cat "$SD/anyka_webui/boot.log"
        exit 1
    fi
}

assert_file() {
    [ -e "$1" ] || { echo "FEHLER: Datei fehlt: $1"; exit 1; }
}

assert_no_default_route() {
    if awk '$2=="00000000" && $8=="00000000"{f=1} END{exit !f}' "$CASE/route"; then
        echo "FEHLER: Default-Route ist noch vorhanden:"; cat "$CASE/route"; exit 1
    fi
}

echo "=== Test 1: Normalstart entfernt alle Default-Routen, ueberdeckt beide DHCP-Skripte, startet Dienste ==="
new_case t1
run_case
assert_log "Default-Route vor der Isolation: JA"
assert_log "LAN-only aktiv"
assert_no_log "WARNUNG"
assert_no_default_route
grep -q "$LAN_ROUTE_LINE" "$CASE/route" || { echo "FEHLER: LAN-Route wurde faelschlich entfernt"; exit 1; }
grep -q 'udhcpc_lanonly' "$CASE/rootfs/default1.script"
grep -q 'udhcpc_lanonly' "$CASE/rootfs/default2.script"
assert_file "$CASE/tmp/www/index.html"
assert_file "$CASE/tmp/www/cgi-bin/api.cgi"
assert_file "$CASE/ptz_started"
assert_file "$CASE/supervisor_started"
grep -q "httpd -p 80 -h $CASE/tmp/www" "$CASE/httpd_args"
[ "$(cat "$CASE/jffs2/resolv.conf")" = "# LAN-ONLY MODE" ]

echo "=== Test 2: Ohne EARLY_ISOLATION wird erst nach dem WLAN-Aufbau gebunden (je Ziel einmal) ==="
assert_no_log "EARLY_ISOLATION"
[ "$(wc -l < "$WORK/mount_calls")" -eq 2 ] || { echo "FEHLER: unerwartete mount-Aufrufe:"; cat "$WORK/mount_calls"; exit 1; }

echo "=== Test 3: EARLY_ISOLATION ersetzt das DHCP-Skript VOR dem Warten auf das WLAN ==="
new_case t3
touch "$SD/EARLY_ISOLATION"
run_case
assert_log "EARLY_ISOLATION: DHCP-Skript vor dem ersten Lease ersetzt (2 Ziel(e))"
early_line=$(grep -n 'EARLY_ISOLATION:' "$SD/anyka_webui/boot.log" | head -n 1 | cut -d: -f1)
wlan_line=$(grep -n 'WLAN-Verbindung steht' "$SD/anyka_webui/boot.log" | head -n 1 | cut -d: -f1)
[ "$early_line" -lt "$wlan_line" ] || { echo "FEHLER: EARLY_ISOLATION nicht vor dem WLAN-Schritt"; exit 1; }
# Es wird genau einmal pro Ziel gebunden (zweiter Durchlauf erkennt das ueberdeckte Skript)
[ "$(wc -l < "$WORK/mount_calls")" -eq 2 ] || { echo "FEHLER: unerwartete mount-Aufrufe:"; cat "$WORK/mount_calls"; exit 1; }
assert_no_default_route

echo "=== Test 4: Scheitert der Bind-Mount, meldet das Log eine unvollstaendige Isolation ==="
new_case t4
run_case STUB_MOUNT_FAIL=1
assert_log "WARNUNG: Isolation unvollstaendig (DHCP-Skript ersetzt=0, DefaultRoute=0)"
assert_no_default_route

echo "=== Test 5: Fehlt ein Werksskript, genuegt das vorhandene ==="
new_case t5
rm -f "$CASE/rootfs/default2.script"
run_case
assert_log "LAN-only aktiv"
grep -q 'udhcpc_lanonly' "$CASE/rootfs/default1.script"

echo "=== Test 6: DISABLE_WEBUI bricht ab (Werkszustand), nichts wird veraendert ==="
new_case t6
touch "$SD/DISABLE_WEBUI"
run_case
assert_log "DISABLE_WEBUI gefunden"
[ ! -e "$CASE/tmp/www" ] || { echo "FEHLER: www wurde trotz DISABLE_WEBUI gespiegelt"; exit 1; }
[ ! -e "$CASE/ptz_started" ] || { echo "FEHLER: ptz_daemon wurde gestartet"; exit 1; }
grep -q "$DEFAULT_ROUTE_LINE" "$CASE/route" || { echo "FEHLER: Default-Route wurde entfernt"; exit 1; }
if grep -q 'udhcpc_lanonly' "$CASE/rootfs/default1.script"; then
    echo "FEHLER: Werksskript wurde trotz DISABLE_WEBUI ueberdeckt"; exit 1
fi

echo "=== Test 7: Singleton - ein zweiter Start laeuft nicht erneut ==="
new_case t7
run_case
rm -f "$CASE/ptz_started" "$CASE/supervisor_started"
rm -f "$WORK/stop"
run_case
assert_log "Bereits ausgefuehrt"
[ ! -e "$CASE/ptz_started" ] || { echo "FEHLER: zweiter Start hat Dienste erneut gestartet"; exit 1; }

echo "=== Alle 7 Start-Skript-Tests erfolgreich bestanden ==="
