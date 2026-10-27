#!/bin/sh
# ===== $SD_MOUNT/anyka_webui/start_webui.sh =====
# Aufruf durch Boot-Hook: sh start_webui.sh "$SD_MOUNT"

SD_MOUNT="$1"
[ -n "$SD_MOUNT" ] || exit 0
BASE="$SD_MOUNT/anyka_webui"
LOG="$BASE/boot.log"

# Pfade der Kamera; nur fuer Host-Tests (tests/test_start_webui.sh) ueberschreibbar
T="${WEBUI_TMP_DIR:-/tmp}"
JFFS2="${WEBUI_JFFS2_DIR:-/etc/jffs2}"
PROC_ROUTE="${WEBUI_PROC_ROUTE:-/proc/net/route}"
PROC_UPTIME="${WEBUI_PROC_UPTIME:-/proc/uptime}"
WIFI_MANAGE="${WEBUI_WIFI_MANAGE:-/usr/sbin/wifi_manage.sh}"
# Werks-DHCP-Skripte, die durch udhcpc_lanonly.sh ueberdeckt werden
DHCP_SCRIPTS="${WEBUI_DHCP_SCRIPTS:-/usr/share/udhcpc/default.script /usr/sbin/default.script}"
LANONLY="$T/udhcpc_lanonly.sh"

log() { read -r _up _ < "$PROC_UPTIME"; echo "[${_up%.*}s] $*" >> "$LOG" 2>/dev/null; }
: > "$LOG" 2>/dev/null
log "start_webui.sh gestartet (SD_MOUNT=$SD_MOUNT)"

# ---------- Hilfsfunktionen (ohne Fork, ohne regulaere Ausdruecke) ----------
# Existiert ein IPv4-Default-Gateway? (Route-Tabelle: Destination und Mask 00000000)
route_has_default() {
    while read -r _ dest _ _ _ _ _ mask _; do
        if [ "$dest" = "00000000" ] && [ "$mask" = "00000000" ]; then
            return 0
        fi
    done < "$PROC_ROUTE"
    return 1
}

strip_default_routes() {
    _n=0
    while [ "$_n" -lt 10 ] && route_has_default; do
        route del default 2>/dev/null || break
        _n=$((_n + 1))
    done
}

# udhcpc_lanonly.sh nach /tmp kopieren und ueber die Werks-DHCP-Skripte legen.
# Geprueft wird der INHALT des Ziels: /proc/mounts zeigt bei einem Bind-Mount
# einer Datei nicht den Quellpfad, ein grep darauf waere wirkungslos.
# Eine bereits kopierte Datei wird nicht erneut geschrieben (kein leeres Skript,
# falls udhcpc es gerade ausfuehrt). Rueckgabe 0 = alle vorhandenen Ziele ueberdeckt.
install_lanonly() {
    [ -f "$LANONLY" ] || cp -f "$BASE/bin/udhcpc_lanonly.sh" "$LANONLY" 2>/dev/null
    chmod 755 "$LANONLY" 2>/dev/null
    if [ -r "$BASE/lan_routes.conf" ] && [ ! -f "$T/udhcpc_lanonly.conf" ]; then
        cp -f "$BASE/lan_routes.conf" "$T/udhcpc_lanonly.conf" 2>/dev/null
    fi
    BOUND=0
    MISSING=0
    for _t in $DHCP_SCRIPTS; do
        [ -e "$_t" ] || continue
        if ! grep -q 'udhcpc_lanonly' "$_t" 2>/dev/null; then
            mount --bind "$LANONLY" "$_t" 2>/dev/null
        fi
        if grep -q 'udhcpc_lanonly' "$_t" 2>/dev/null; then
            BOUND=$((BOUND + 1))
        else
            MISSING=$((MISSING + 1))
        fi
    done
    [ "$BOUND" -gt 0 ] && [ "$MISSING" -eq 0 ]
}

# ---------- Singleton-Guard ----------
if [ -f "$T/start_webui_done" ]; then
    log "Bereits ausgefuehrt -> Abbruch (Singleton)"
    exit 0
fi
touch "$T/start_webui_done"

# ---------- Notbremse ----------
if [ -e "$SD_MOUNT/DISABLE_WEBUI" ]; then
    log "DISABLE_WEBUI gefunden -> Abbruch (Werkszustand)"
    sync
    exit 0
fi

export LD_LIBRARY_PATH="$SD_MOUNT/custom/lib:/usr/lib:/lib"
BUSYBOX_BIN="$SD_MOUNT/custom/busybox"

# ---------- Web-Root nach tmpfs spiegeln ----------
mkdir -p "$T/www/cgi-bin" 2>/dev/null
cp -f "$BASE/www/index.html" "$T/www/" 2>/dev/null || log "FEHLER: index.html kopieren"
cp -f "$BASE/www/cgi-bin"/* "$T/www/cgi-bin/" 2>/dev/null || log "FEHLER: cgi-bin kopieren"
chmod 755 "$T"/www/cgi-bin/* 2>/dev/null
log "www gespiegelt"

# ---------- Optional: Isolation VOR dem ersten DHCP-Lease ----------
# Nur mit Datei EARLY_ISOLATION im Wurzelverzeichnis der SD-Karte. Das DHCP-Skript
# wird dann ersetzt, bevor anyka_ipc die WLAN-Verbindung aufbaut; der erste Lease
# setzt dadurch gar keinen Default-Gateway (kein Zeitfenster mit Internetroute).
# Standardmaessig AUS, bis es auf der Kamera per Kaltstart geprueft wurde.
if [ -e "$SD_MOUNT/EARLY_ISOLATION" ]; then
    if install_lanonly; then
        log "EARLY_ISOLATION: DHCP-Skript vor dem ersten Lease ersetzt ($BOUND Ziel(e))"
    else
        log "WARNUNG: EARLY_ISOLATION konnte das DHCP-Skript nicht ersetzen (ersetzt=$BOUND, fehlgeschlagen=$MISSING)"
    fi
fi

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
    "$WIFI_MANAGE" start </dev/null >/dev/null 2>&1 &
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

# Messwert fuer das Boot-Zeitfenster: Gab es bis jetzt eine Internetroute?
if route_has_default; then
    log "Default-Route vor der Isolation: JA (Boot-Zeitfenster mit Gateway)"
else
    log "Default-Route vor der Isolation: NEIN"
fi

# ---------- LAN-only Isolation (VOR Start der Dienste) ----------
install_lanonly
strip_default_routes

# DNS leeren (nur schreiben wenn abweichend)
if [ "$(cat "$JFFS2/resolv.conf" 2>/dev/null)" != "# LAN-ONLY MODE" ]; then
    printf "# LAN-ONLY MODE\n" > "$JFFS2/resolv.conf" 2>/dev/null
fi

# Isolation verifizieren
BIND_OK=0
install_lanonly && BIND_OK=1
HAS_DEFAULT_ROUTE=0
route_has_default && HAS_DEFAULT_ROUTE=1

if [ "$BIND_OK" -eq 1 ] && [ "$HAS_DEFAULT_ROUTE" -eq 0 ]; then
    log "LAN-only aktiv (kein Gateway, DHCP-Skript ersetzt, DNS geleert)"
else
    log "WARNUNG: Isolation unvollstaendig (DHCP-Skript ersetzt=$BIND_OK, DefaultRoute=$HAS_DEFAULT_ROUTE)"
fi

# Zweite Absicherung: Hintergrundschleife alle 60s
(
    while true; do
        sleep 60
        strip_default_routes
    done
) </dev/null >/dev/null 2>&1 &

# ---------- WebUI- & PTZ-Dienste starten ----------
# PTZ-Daemon (FIFO /tmp/ptz.daemon)
if pidof ptz_daemon >/dev/null 2>&1; then
    log "ptz_daemon lief bereits"
else
    "$SD_MOUNT/custom/ptz_daemon" </dev/null >"$T/ptz.log" 2>&1 &
    log "ptz_daemon gestartet (PID $!)"
fi

# BusyBox httpd (Port 80)
if pidof httpd >/dev/null 2>&1; then
    log "httpd lief bereits (Port 80 wird nicht neu gestartet)"
else
    $BUSYBOX_BIN httpd -p 80 -h "$T/www" </dev/null >/dev/null 2>&1 &
    log "httpd auf Port 80 gestartet (PID $!)"
fi

# ---------- RTSP-Supervisor starten (per sh aufrufen) ----------
SD_MOUNT="$SD_MOUNT" sh "$BASE/rtsp_supervisor.sh" </dev/null >/dev/null 2>&1 &
log "rtsp_supervisor gestartet (PID $!)"

# Optional: Lokale Zeituebernahme aus LAN-NTP
[ -f "$BASE/ntp.conf" ] && ntpd -q -p "$(cat "$BASE/ntp.conf")" >/dev/null 2>&1 &

log "start_webui.sh erfolgreich abgeschlossen"
sync
exit 0
