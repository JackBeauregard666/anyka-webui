#!/bin/sh
set -e

# Test-Suite fuer api.cgi auf dem Host (POSIX sh).
# Alle Pfade der Kamera (FIFO, ptz.ini, /proc, sysfs) werden durch Dateien in
# einem temporaeren Verzeichnis ersetzt; es wird nie auf echter Hardware gearbeitet.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
API_CGI="$REPO_ROOT/webui/www/cgi-bin/api.cgi"

TMP_DIR="$(mktemp -d /tmp/test_api_cgi.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT INT TERM

FAKE_FIFO="$TMP_DIR/ptz.daemon"
FAKE_INI="$TMP_DIR/ptz.ini"
FAKE_LOCK="$TMP_DIR/ptz_lock"
FAKE_BUSY="$TMP_DIR/ptz_busy_until"
FAKE_EXPECT="$TMP_DIR/ptz_expect"
FAKE_LED="$TMP_DIR/WHITE_LED"
FAKE_TCP="$TMP_DIR/tcp"
FAKE_ROUTE="$TMP_DIR/route"
FAKE_MEMINFO="$TMP_DIR/meminfo"
FAKE_UPTIME="$TMP_DIR/uptime"
PROC_WITH_DAEMON="$TMP_DIR/proc_ok"
PROC_WITHOUT_DAEMON="$TMP_DIR/proc_empty"

mkfifo "$FAKE_FIFO"
echo "180 70" > "$FAKE_INI"
echo "0" > "$FAKE_LED"
echo "100.5 50.2" > "$FAKE_UPTIME"
printf "MemFree: 15000 kB\nBuffers: 2000 kB\nCached: 5000 kB\nShmem: 1000 kB\n" > "$FAKE_MEMINFO"
printf "Iface Destination Gateway Flags RefCnt Use Metric Mask\nwlan0 00A8C0 00000000 0001 0 0 0 00FFFFFF\n" > "$FAKE_ROUTE"
printf "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n   0: 00000000:022A 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1234 1 0 0 0 10 -1\n" > "$FAKE_TCP"

# Fake-/proc: ein Prozess "ptz_daemon" bzw. nur fremde Prozesse
mkdir -p "$PROC_WITH_DAEMON/1" "$PROC_WITH_DAEMON/4242" "$PROC_WITHOUT_DAEMON/1" "$PROC_WITHOUT_DAEMON/77"
echo "1 (init) S 0 1 1 0 -1 4194560 0 0 0 0 0 0 0 0 20 0 1 0 1 0 0" > "$PROC_WITH_DAEMON/1/stat"
echo "4242 (ptz_daemon) S 1 4242 4242 0 -1 4194560 0 0 0 0 0 0 0 0 20 0 1 0 5 0 0" > "$PROC_WITH_DAEMON/4242/stat"
echo "1 (init) S 0 1 1 0 -1 4194560 0 0 0 0 0 0 0 0 20 0 1 0 1 0 0" > "$PROC_WITHOUT_DAEMON/1/stat"
echo "77 (not_ptz_daemon_x) S 1 77 77 0 -1 4194560 0 0 0 0 0 0 0 0 20 0 1 0 5 0 0" > "$PROC_WITHOUT_DAEMON/77/stat"

# FIFO-Hintergrundleser: haelt die Pipe offen, damit Schreibzugriffe nicht blockieren
exec 3<>"$FAKE_FIFO"

CUR_PROC="$PROC_WITH_DAEMON"
PASSED=0

# call_cgi METHOD QUERY [REFERER] [CONTENT_TYPE] [HOST] [ORIGIN]
call_cgi() {
    _method="$1"
    _query="$2"
    _referer="NONE"
    [ $# -ge 3 ] && _referer="$3"
    [ "$_referer" = "NONE" ] && _referer="http://testcamera/"
    _ctype="${4:-application/json}"
    _host="${5:-testcamera}"
    _origin="${6:-}"

    PTZ_FIFO="$FAKE_FIFO" \
    PTZ_INI="$FAKE_INI" \
    PTZ_LOCK="$FAKE_LOCK" \
    BUSY_FILE="$FAKE_BUSY" \
    EXPECT_FILE="$FAKE_EXPECT" \
    LED_SYSFS="$FAKE_LED" \
    PROC_TCP="$FAKE_TCP" \
    PROC_ROUTE="$FAKE_ROUTE" \
    PROC_MEMINFO="$FAKE_MEMINFO" \
    PROC_UPTIME="$FAKE_UPTIME" \
    PROC_DIR="$CUR_PROC" \
    REQUEST_METHOD="$_method" \
    QUERY_STRING="$_query" \
    HTTP_REFERER="$_referer" \
    HTTP_HOST="$_host" \
    HTTP_ORIGIN="$_origin" \
    CONTENT_TYPE="$_ctype" \
    "$API_CGI" | sed -n '3,$p'
}

# assert_has TEXT FRAGMENT: FRAGMENT muss woertlich in TEXT vorkommen
assert_has() {
    if ! printf '%s\n' "$1" | grep -F -- "$2" >/dev/null; then
        echo "FEHLER: erwartet wurde: $2"
        echo "Tatsaechliche Ausgabe: $1"
        exit 1
    fi
}

# read_fifo: genau eine Zeile aus dem FIFO lesen (mit Zeitlimit)
read_fifo() {
    timeout 2 head -n 1 <&3
}

step() {
    PASSED=$((PASSED + 1))
    echo "=== Test $PASSED: $1 ==="
}

step "GET statt POST wird abgewiesen"
out=$(call_cgi "GET" "action=turn&dpan=10")
assert_has "$out" '"err":"post_required"'

step "dry per GET wird ebenfalls abgewiesen"
out=$(call_cgi "GET" "action=turn&dpan=10&dry=1")
assert_has "$out" '"err":"post_required"'

step "Fehlender oder fremder Referer wird abgewiesen"
out=$(call_cgi "POST" "action=turn&dpan=10&dry=1" "" "application/json")
assert_has "$out" '"err":"bad_referer"'
out=$(call_cgi "POST" "action=turn&dpan=10&dry=1" "http://evil.com/" "application/json")
assert_has "$out" '"err":"bad_referer"'

step "Referer-Umgehung per Teilstring (Host irgendwo im Referer) wird abgewiesen"
out=$(call_cgi "POST" "action=turn&dpan=10&dry=1" "http://evil.com/?x=//testcamera/" "application/json")
assert_has "$out" '"err":"bad_referer"'
out=$(call_cgi "POST" "action=turn&dpan=10&dry=1" "http://testcamera.evil.com/" "application/json")
assert_has "$out" '"err":"bad_referer"'
out=$(call_cgi "POST" "action=turn&dpan=10&dry=1" "http://testcamera@evil.com/" "application/json")
assert_has "$out" '"err":"bad_referer"'

step "Referer mit Pfad und Query auf dem eigenen Host wird akzeptiert"
out=$(call_cgi "POST" "action=turn&dpan=10&dry=1" "http://testcamera/index.html?x=1" "application/json")
assert_has "$out" '"ok":true'
out=$(call_cgi "POST" "action=turn&dpan=10&dry=1" "http://testcamera" "application/json")
assert_has "$out" '"ok":true'

step "Abweichender Origin-Header wird abgewiesen, passender akzeptiert"
out=$(call_cgi "POST" "action=turn&dpan=10&dry=1" "http://testcamera/" "application/json" "testcamera" "http://evil.com")
assert_has "$out" '"err":"bad_origin"'
out=$(call_cgi "POST" "action=turn&dpan=10&dry=1" "http://testcamera/" "application/json" "testcamera" "null")
assert_has "$out" '"err":"bad_origin"'
out=$(call_cgi "POST" "action=turn&dpan=10&dry=1" "http://testcamera/" "application/json" "testcamera" "http://testcamera")
assert_has "$out" '"ok":true'

step "Ungueltiger Content-Type wird abgewiesen"
out=$(call_cgi "POST" "action=turn&dpan=10&dry=1" "http://testcamera/" "text/plain")
assert_has "$out" '"err":"bad_content_type"'

step "Entfernte Aktion calibrate ist unbekannt"
out=$(call_cgi "POST" "action=calibrate&dry=1")
assert_has "$out" '"err":"invalid_action"'

step "dpan=-015 wird normalisiert (-15, kein Oktalfehler)"
out=$(call_cgi "POST" "action=turn&dpan=-015&dtilt=0&dry=1")
assert_has "$out" '"requested":{"dpan":-15,"dtilt":0}'
assert_has "$out" '"executed":{"dpan":-15,"dtilt":0}'
assert_has "$out" '"clamped":false'

step "dpan=abc wird abgewiesen"
out=$(call_cgi "POST" "action=turn&dpan=abc&dry=1")
assert_has "$out" '"err":"invalid_dpan"'

step "dpan=99999 (Laenge > 4) wird abgewiesen"
out=$(call_cgi "POST" "action=turn&dpan=99999&dry=1")
assert_has "$out" '"err":"invalid_dpan"'

step "Klemmung an den Grenzen (dpan=999 und dtilt=-100)"
out=$(call_cgi "POST" "action=turn&dpan=999&dtilt=-100&dry=1")
assert_has "$out" '"clamped":true'
# 180 + 999 -> geklemmt auf 335 (executed = 155); 70 - 100 -> geklemmt auf 15 (executed = -55)
assert_has "$out" '"executed":{"dpan":155,"dtilt":-55}'

step "Defekte ptz.ini fuehrt zu ptz_invalid"
echo "GARBAGE_DATA" > "$FAKE_INI"
out=$(call_cgi "POST" "action=turn&dpan=10&dry=1")
assert_has "$out" '"err":"ptz_invalid"'
echo "180 70" > "$FAKE_INI"

step "Status liefert JSON inkl. led_on, rtsp_ready und ptz_ready=1"
out=$(call_cgi "GET" "action=status")
assert_has "$out" '"ok":true'
assert_has "$out" '"rtsp_ready":1'
assert_has "$out" '"led_on":0'
assert_has "$out" '"ptz_valid":true'
assert_has "$out" '"ptz_ready":1'

step "Verwaister FIFO ohne laufenden ptz_daemon: ptz_ready=0 und Fahrt abgewiesen"
CUR_PROC="$PROC_WITHOUT_DAEMON"
out=$(call_cgi "GET" "action=status")
assert_has "$out" '"ptz_ready":0'
out=$(call_cgi "POST" "action=turn&dpan=10&dry=1")
assert_has "$out" '"err":"ptz_daemon_not_running"'
out=$(call_cgi "POST" "action=left&dry=1")
assert_has "$out" '"err":"ptz_daemon_not_running"'
# Die LED funktioniert unabhaengig vom PTZ-Daemon
out=$(call_cgi "POST" "action=light_on&dry=1")
assert_has "$out" '"ok":true'
CUR_PROC="$PROC_WITH_DAEMON"

step "Echte Fahrt setzt Expect-Datei und Busy und schreibt t2p in den FIFO"
out=$(call_cgi "POST" "action=turn&dpan=10&dtilt=0")
assert_has "$out" '"ok":true'
test -f "$FAKE_EXPECT"
read -r exp_p exp_t < "$FAKE_EXPECT"
[ "$exp_p $exp_t" = "190 70" ] || { echo "FEHLER: Expect-Datei enthaelt '$exp_p $exp_t'"; exit 1; }
line=$(read_fifo)
[ "$line" = "t2p 190 70" ] || { echo "FEHLER: FIFO-Inhalt war '$line'"; exit 1; }

step "Zweiter Aufruf waehrend Busy wird abgewiesen"
out=$(call_cgi "POST" "action=turn&dpan=10&dtilt=0")
assert_has "$out" '"err":"busy"'

step "Race-Schutz: ptz.ini noch nicht aktualisiert, Zeitfenster laeuft -> busy"
echo "101.0 50.0" > "$FAKE_UPTIME"
out=$(call_cgi "POST" "action=turn&dpan=10&dtilt=0")
assert_has "$out" '"err":"busy"'

step "Race-Schutz: Zeitfenster plus Reserve verstrichen -> ptz.ini gilt als Wahrheit"
echo "200.0 150.0" > "$FAKE_UPTIME"
out=$(call_cgi "POST" "action=turn&dpan=20&dtilt=0")
assert_has "$out" '"ok":true'
read -r exp_p exp_t < "$FAKE_EXPECT"
[ "$exp_p $exp_t" = "200 70" ] || { echo "FEHLER: Expect-Datei enthaelt '$exp_p $exp_t'"; exit 1; }
line=$(read_fifo)
[ "$line" = "t2p 200 70" ] || { echo "FEHLER: FIFO-Inhalt war '$line'"; exit 1; }

step "Einzelschritt: Richtung geht unveraendert in den FIFO, Expect-Datei wird verworfen"
echo "400.0 350.0" > "$FAKE_UPTIME"
out=$(call_cgi "POST" "action=left")
assert_has "$out" '"ok":true'
line=$(read_fifo)
[ "$line" = "left" ] || { echo "FEHLER: FIFO-Inhalt war '$line'"; exit 1; }
[ ! -f "$FAKE_EXPECT" ] || { echo "FEHLER: Expect-Datei sollte entfernt sein"; exit 1; }

step "Einzelschritt waehrend Busy wird abgewiesen"
out=$(call_cgi "POST" "action=right")
assert_has "$out" '"err":"busy"'

step "LED: Schalten per POST schreibt in sysfs"
out=$(call_cgi "POST" "action=light_on")
assert_has "$out" '"ok":true'
[ "$(cat "$FAKE_LED")" = "1" ] || { echo "FEHLER: LED-Datei enthaelt '$(cat "$FAKE_LED")'"; exit 1; }
out=$(call_cgi "GET" "action=status")
assert_has "$out" '"led_on":1'
out=$(call_cgi "POST" "action=light_off")
[ "$(cat "$FAKE_LED")" = "0" ] || { echo "FEHLER: LED-Datei enthaelt '$(cat "$FAKE_LED")'"; exit 1; }

step "Unbekannte Aktion wird abgewiesen"
out=$(call_cgi "POST" "action=reboot")
assert_has "$out" '"err":"invalid_action"'

echo "=== Alle $PASSED API-Tests erfolgreich bestanden ==="
