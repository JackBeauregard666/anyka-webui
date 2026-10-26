#!/bin/sh
# ===== $SD_MOUNT/anyka_webui/start_webui.sh =====
# Aufruf durch Boot-Hook: sh start_webui.sh "$SD_MOUNT"

SD_MOUNT="$1"
[ -n "$SD_MOUNT" ] || exit 0
BASE="$SD_MOUNT/anyka_webui"
LOG="$BASE/boot.log"

log() { read -r _up _ < /proc/uptime; echo "[${_up%.*}s] $*" >> "$LOG" 2>/dev/null; }
: > "$LOG" 2>/dev/null
log "start_webui.sh gestartet (SD_MOUNT=$SD_MOUNT)"

# ---------- Singleton-Guard ----------
if [ -f /tmp/start_webui_done ]; then
    log "Bereits ausgefuehrt -> Abbruch (Singleton)"
    exit 0
fi
touch /tmp/start_webui_done

# ---------- Notbremse ----------
if [ -e "$SD_MOUNT/DISABLE_WEBUI" ]; then
    log "DISABLE_WEBUI gefunden -> Abbruch (Werkszustand)"
    sync
    exit 0
fi

export LD_LIBRARY_PATH="$SD_MOUNT/custom/lib:/usr/lib:/lib"
BUSYBOX_BIN="$SD_MOUNT/custom/busybox"

# ---------- Web-Root nach tmpfs spiegeln ----------
mkdir -p /tmp/www/cgi-bin 2>/dev/null
cp -f "$BASE/www/index.html" /tmp/www/ 2>/dev/null || log "FEHLER: index.html kopieren"
cp -f "$BASE/www/cgi-bin"/* /tmp/www/cgi-bin/ 2>/dev/null || log "FEHLER: cgi-bin kopieren"
chmod 755 /tmp/www/cgi-bin/* 2>/dev/null
log "www gespiegelt"

# ---------- Warten auf WLAN-Verbindung durch anyka_ipc (max. 45 s) ----------
log "Warte auf IPv4 an wlan0 (anyka_ipc stellt WLAN-Verbindung her)..."
i=0
while [ "$i" -lt 45 ]; do
    ifconfig wlan0 2>/dev/null | grep -q 'inet addr:' && break
    sleep 1
    i=$((i + 1))
done

if ! ifconfig wlan0 2>/dev/null | grep -q 'inet addr:'; then
    log "WARNUNG: wlan0 hat nach 45s noch keine IP -> Fallback: starte wifi_manage.sh"
    /usr/sbin/wifi_manage.sh start </dev/null >/dev/null 2>&1 &
    while [ "$i" -lt 70 ]; do
        ifconfig wlan0 2>/dev/null | grep -q 'inet addr:' && break
        sleep 1
        i=$((i + 1))
    done
fi

if ifconfig wlan0 2>/dev/null | grep -q 'inet addr:'; then
    log "WLAN-Verbindung steht (wlan0 hat IP)"
else
    log "FEHLER: Keine WLAN-Verbindung nach 70s erhalten!"
fi

# ---------- LAN-only Isolation direkt anwenden (VOR Start der Dienste) ----------
cp -f "$BASE/bin/udhcpc_lanonly.sh" /tmp/udhcpc_lanonly.sh 2>/dev/null
chmod 755 /tmp/udhcpc_lanonly.sh 2>/dev/null
[ -r "$BASE/lan_routes.conf" ] && cp -f "$BASE/lan_routes.conf" /tmp/udhcpc_lanonly.conf 2>/dev/null

# Bind-Mount ueber die Werks-udhcpc-Skripte
grep -q '/tmp/udhcpc_lanonly.sh /usr/share/udhcpc/default.script' /proc/mounts 2>/dev/null || \
    mount --bind /tmp/udhcpc_lanonly.sh /usr/share/udhcpc/default.script 2>/dev/null
grep -q '/tmp/udhcpc_lanonly.sh /usr/sbin/default.script' /proc/mounts 2>/dev/null || \
    mount --bind /tmp/udhcpc_lanonly.sh /usr/sbin/default.script 2>/dev/null

# Default-Gateways entfernen
n=0
while [ "$n" -lt 10 ]; do
    route del default 2>/dev/null || break
    n=$((n + 1))
done

# DNS leeren (nur schreiben wenn abweichend)
if [ "$(cat /etc/jffs2/resolv.conf 2>/dev/null)" != "# LAN-ONLY MODE" ]; then
    printf "# LAN-ONLY MODE\n" > /etc/jffs2/resolv.conf 2>/dev/null
fi

# Bind-Mount und Isolation verifizieren
BIND_OK=0
grep -q '/tmp/udhcpc_lanonly.sh' /proc/mounts 2>/dev/null && BIND_OK=1

HAS_DEFAULT_ROUTE=0
while read -r _ dest _ _ _ _ _ mask _; do
    if [ "$dest" = "00000000" ] && [ "$mask" = "00000000" ]; then
        HAS_DEFAULT_ROUTE=1
        break
    fi
done < /proc/net/route

if [ "$BIND_OK" -eq 1 ] && [ "$HAS_DEFAULT_ROUTE" -eq 0 ]; then
    log "LAN-only aktiv (kein Gateway, Bind-Mount aktiv, DNS geleert)"
else
    log "WARNUNG: Isolation unvollstaendig (Bind=$BIND_OK, DefaultRoute=$HAS_DEFAULT_ROUTE)"
fi

# Zweite Absicherung: Hintergrundschleife alle 60s
(
    while true; do
        sleep 60
        if grep -q '^[a-zA-Z0-9_-]\+[[:space:]]\+00000000[[:space:]]' /proc/net/route 2>/dev/null; then
            route del default 2>/dev/null || true
        fi
    done
) </dev/null >/dev/null 2>&1 &

# ---------- WebUI- & PTZ-Dienste starten ----------
# PTZ-Daemon (FIFO /tmp/ptz.daemon)
pidof ptz_daemon >/dev/null 2>&1 || "$SD_MOUNT/custom/ptz_daemon" </dev/null >/tmp/ptz.log 2>&1 &
log "ptz_daemon gestartet"

# BusyBox httpd (Port 80)
pidof httpd >/dev/null 2>&1 || $BUSYBOX_BIN httpd -p 80 -h /tmp/www </dev/null >/dev/null 2>&1 &
log "httpd auf Port 80 gestartet"

# ---------- RTSP-Supervisor starten (per sh aufrufen) ----------
sh "$BASE/rtsp_supervisor.sh" </dev/null >/dev/null 2>&1 &
log "rtsp_supervisor gestartet"

# Optional: Lokale Zeituebernahme aus LAN-NTP
[ -f "$BASE/ntp.conf" ] && ntpd -q -p "$(cat "$BASE/ntp.conf")" >/dev/null 2>&1 &

log "start_webui.sh erfolgreich abgeschlossen"
sync
exit 0
