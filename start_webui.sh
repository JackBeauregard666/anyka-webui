#!/bin/sh
# ===== $SD_MOUNT/anyka_webui/start_webui.sh =====
# Aufruf durch den Boot-Hook:  sh start_webui.sh "$SD_MOUNT"
# Jeder Schritt ist unabhaengig; Telnet/FTP laufen unberuehrt.

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
# DISABLE_WEBUI = Rueckkehr zum Ausgangszustand: KEINE Isolation, KEIN Cloud-Kill.
if [ -e "$SD_MOUNT/DISABLE_WEBUI" ]; then
    log "DISABLE_WEBUI gefunden -> Abbruch (Telnet/FTP laufen weiter, Werkszustand)"
    sync
    exit 0
fi

export LD_LIBRARY_PATH="$SD_MOUNT/custom/lib:/usr/lib:/lib"
BUSYBOX_BIN="$SD_MOUNT/custom/busybox"

# ---------- Web-Root nach tmpfs spiegeln ----------
# Niemals rm -rf /tmp/www, um das Arbeitsverzeichnis eines evtl. laufenden httpd nicht zu zerstoeren!
mkdir -p /tmp/www/cgi-bin 2>/dev/null
cp -f "$BASE/www/index.html" /tmp/www/ 2>/dev/null || log "FEHLER: index.html kopieren"
cp -f "$BASE/www/cgi-bin"/* /tmp/www/cgi-bin/ 2>/dev/null || log "FEHLER: cgi-bin kopieren"
chmod 755 /tmp/www/cgi-bin/* 2>/dev/null
log "www gespiegelt"

# ---------- Warten auf WLAN-Verbindung durch anyka_ipc (max. 45 s) ----------
# anyka_ipc initialisiert den Realtek-WLAN-Treiber, WPA und DHCP.
# Wir muessen warten, bis wlan0 eine IP hat, BEVOR anyka_ipc beendet wird!
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

# ---------- WebUI- & PTZ-Dienste zuerst starten (sofortige Erreichbarkeit) ----------
# PTZ-Daemon (FIFO /tmp/ptz.daemon)
pidof ptz_daemon >/dev/null 2>&1 || "$SD_MOUNT/custom/ptz_daemon" </dev/null >/tmp/ptz.log 2>&1 &
log "ptz_daemon gestartet"

# BusyBox httpd (Port 80)
pidof httpd >/dev/null 2>&1 || $BUSYBOX_BIN httpd -p 80 -h /tmp/www </dev/null >/dev/null 2>&1 &
log "httpd auf Port 80 gestartet"

# ---------- RTSP-Supervisor starten (entkoppelt im Hintergrund) ----------
# Beendet anyka_ipc sauber, ueberwacht rtsp und startet bei Abbruch automatisch neu
"$BASE/rtsp_supervisor.sh" </dev/null >/dev/null 2>&1 &
log "rtsp_supervisor gestartet"

# ---------- LAN-only Isolation anwenden ----------
cp -f "$BASE/bin/udhcpc_lanonly.sh" /tmp/udhcpc_lanonly.sh 2>/dev/null
chmod 755 /tmp/udhcpc_lanonly.sh 2>/dev/null
[ -r "$BASE/lan_routes.conf" ] && cp -f "$BASE/lan_routes.conf" /tmp/udhcpc_lanonly.conf 2>/dev/null

# Methode B: Bind-Mount ueber die Werks-udhcpc-Skripte
mount --bind /tmp/udhcpc_lanonly.sh /usr/share/udhcpc/default.script 2>/dev/null
mount --bind /tmp/udhcpc_lanonly.sh /usr/sbin/default.script 2>/dev/null

# Default-Gateways entfernen
n=0
while [ "$n" -lt 10 ]; do
    route del default 2>/dev/null || break
    n=$((n + 1))
done

# DNS leeren
printf "# LAN-ONLY MODE\n" > /etc/jffs2/resolv.conf 2>/dev/null

# Rollback-Check: Pruefen ob IP noch anliegt
if ! ifconfig wlan0 2>/dev/null | grep -q 'inet addr:'; then
    log "FEHLER: keine IP an wlan0 -> Rollback"
    umount /usr/share/udhcpc/default.script 2>/dev/null
    umount /usr/sbin/default.script 2>/dev/null
    udhcpc -i wlan0 </dev/null >/dev/null 2>&1 &
else
    log "LAN-only aktiv (kein Gateway, DNS geleert)"
fi

# Optional: Lokale Zeituebernahme aus LAN-NTP
[ -f /mnt/anyka_webui/ntp.conf ] && ntpd -q -p "$(cat /mnt/anyka_webui/ntp.conf)" >/dev/null 2>&1 &

log "start_webui.sh erfolgreich abgeschlossen"
sync
exit 0
