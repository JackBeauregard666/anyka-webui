#!/bin/sh
set -e

# Host-Test fuer rtsp_supervisor.sh (POSIX sh).
# killall/pidof werden durch Stubs ersetzt (damit auf dem Entwicklungsrechner nie ein
# echter Prozess beendet wird); "rtsp" ist eine Attrappe, Port 554 eine Fake-Datei.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

WORK="$(mktemp -d /tmp/test_supervisor.XXXXXX)"
SUP_PIDS=""
cleanup() {
    for _p in $SUP_PIDS; do kill "$_p" 2>/dev/null || true; done
    sleep 0.3
    rm -rf "$WORK"
}
trap cleanup EXIT INT TERM

STUBS="$WORK/stubs"
mkdir -p "$STUBS"
for n in killall pidof; do
    printf '#!/bin/sh\nexit 1\n' > "$STUBS/$n"
done
printf '#!/bin/sh\nexit 0\n' > "$STUBS/killall"
chmod +x "$STUBS"/*

TCP_LISTEN='  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 00000000:022A 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1234 1 0 0 0 10 -1'
TCP_NONE='  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 00000000:0050 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1235 1 0 0 0 10 -1'

# new_case NAME LISTENING(1/0) RTSP_BODY: SD-Attrappe anlegen
new_case() {
    CASE="$WORK/$1"
    rm -rf "$CASE"
    mkdir -p "$CASE/sd/anyka_webui" "$CASE/sd/custom" "$CASE/tmp"
    SD="$CASE/sd"
    if [ "$2" = "1" ]; then echo "$TCP_LISTEN" > "$CASE/tcp"; else echo "$TCP_NONE" > "$CASE/tcp"; fi
    printf '#!/bin/sh\necho "start $$" >> "%s/rtsp_runs"\necho $$ > "%s/rtsp_pid"\n%s\n' "$CASE" "$CASE" "$3" > "$SD/custom/rtsp"
    chmod +x "$SD/custom/rtsp"
}

# start_supervisor [Umgebung...]: Supervisor im Hintergrund starten, PID in SUP_PID
start_supervisor() {
    env PATH="$STUBS:$PATH" SD_MOUNT="$SD" SUP_TMP_DIR="$CASE/tmp" SUP_PROC_TCP="$CASE/tcp" "$@" \
        sh "$REPO_ROOT/rtsp_supervisor.sh" </dev/null >/dev/null 2>&1 &
    SUP_PID=$!
    SUP_PIDS="$SUP_PIDS $SUP_PID"
}

wait_for() {
    # wait_for DATEI MUSTER SEKUNDEN
    _i=0
    while [ "$_i" -lt "$3" ]; do
        grep -q -- "$2" "$1" 2>/dev/null && return 0
        sleep 1
        _i=$((_i + 1))
    done
    echo "FEHLER: '$2' erschien nicht in $1 innerhalb von $3 s"
    [ -f "$1" ] && cat "$1"
    return 1
}

echo "=== Test 1: Supervisor startet rtsp; bei lauschendem Port 554 gibt es keinen Neustart ==="
new_case s1 1 'exec sleep 30'
start_supervisor SUP_HEALTH_DELAY=2
wait_for "$SD/anyka_webui/rtsp_supervisor.log" "rtsp gestartet" 5
sleep 3
if grep -q "Health-Check fehlgeschlagen" "$SD/anyka_webui/rtsp_supervisor.log"; then
    echo "FEHLER: Health-Check schlug trotz lauschendem Port an"; cat "$SD/anyka_webui/rtsp_supervisor.log"; exit 1
fi
[ "$(wc -l < "$CASE/rtsp_runs")" -eq 1 ] || { echo "FEHLER: rtsp wurde mehrfach gestartet"; exit 1; }

echo "=== Test 2: Zweite Instanz wird abgewiesen ==="
env PATH="$STUBS:$PATH" SD_MOUNT="$SD" SUP_TMP_DIR="$CASE/tmp" SUP_PROC_TCP="$CASE/tcp" \
    sh "$REPO_ROOT/rtsp_supervisor.sh" </dev/null >/dev/null 2>&1
grep -q "laeuft bereits" "$SD/anyka_webui/rtsp_supervisor.log"
[ "$(wc -l < "$CASE/rtsp_runs")" -eq 1 ] || { echo "FEHLER: zweite Instanz hat rtsp gestartet"; exit 1; }

echo "=== Test 3: SIGTERM beendet Supervisor und rtsp sauber und entfernt die Lock-Datei ==="
rtsp_pid=$(cat "$CASE/rtsp_pid")
[ -n "$rtsp_pid" ] && kill -0 "$rtsp_pid" 2>/dev/null || { echo "FEHLER: rtsp lief vor dem SIGTERM nicht"; exit 1; }
kill -TERM "$SUP_PID"
sleep 1
if kill -0 "$SUP_PID" 2>/dev/null; then echo "FEHLER: Supervisor laeuft nach SIGTERM weiter"; exit 1; fi
[ ! -e "$CASE/tmp/rtsp_supervisor.pid" ] || { echo "FEHLER: Lock-Datei blieb liegen"; exit 1; }
if kill -0 "$rtsp_pid" 2>/dev/null; then echo "FEHLER: rtsp lief nach SIGTERM weiter"; exit 1; fi

echo "=== Test 4: Lauscht Port 554 nicht, wird rtsp nach der Wartezeit beendet und neu gestartet ==="
new_case s4 0 'exec sleep 30'
start_supervisor SUP_HEALTH_DELAY=2
wait_for "$SD/anyka_webui/rtsp_supervisor.log" "Health-Check fehlgeschlagen" 8
# Backoff bei kurzer Laufzeit: 3 s, danach zweiter Start
wait_for "$CASE/rtsp_runs" "start" 3
_i=0
while [ "$(wc -l < "$CASE/rtsp_runs")" -lt 2 ] && [ "$_i" -lt 8 ]; do sleep 1; _i=$((_i + 1)); done
[ "$(wc -l < "$CASE/rtsp_runs")" -ge 2 ] || { echo "FEHLER: rtsp wurde nicht neu gestartet"; cat "$SD/anyka_webui/rtsp_supervisor.log"; exit 1; }
kill -TERM "$SUP_PID" 2>/dev/null || true
sleep 1

echo "=== Test 5: Beendet sich rtsp frueh, bleibt kein verwaister Health-Check-Prozess zurueck ==="
new_case s5 0 'sleep 1; exit 3'
# Auffaellige Wartezeit (37 s), damit ein verwaistes "sleep" eindeutig erkennbar waere
start_supervisor SUP_HEALTH_DELAY=37
wait_for "$SD/anyka_webui/rtsp_supervisor.log" "rtsp beendet rc=3" 6
sleep 1.5
# Anker ^...$: trifft nur den Prozess "sleep 37", nicht Shells, die den Text enthalten
if pgrep -f '^sleep 37$' >/dev/null 2>&1; then
    echo "FEHLER: verwaister 'sleep 37' gefunden"; pgrep -af '^sleep 37$'; exit 1
fi
kill -TERM "$SUP_PID" 2>/dev/null || true
sleep 1

echo "=== Alle 5 Supervisor-Tests erfolgreich bestanden ==="
