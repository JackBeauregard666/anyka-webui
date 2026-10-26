#!/bin/sh
set -e

# Test-Suite fuer api.cgi auf dem Host (POSIX sh)
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

mkfifo "$FAKE_FIFO"
echo "180 70" > "$FAKE_INI"
echo "0" > "$FAKE_LED"
echo "100.5 50.2" > "$FAKE_UPTIME"
printf "MemFree: 15000 kB\nBuffers: 2000 kB\nCached: 5000 kB\nShmem: 1000 kB\n" > "$FAKE_MEMINFO"
printf "Iface Destination Gateway Flags RefCnt Use Metric Mask\nwlan0 00A8C0 00000000 0001 0 0 0 00FFFFFF\n" > "$FAKE_ROUTE"
printf "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n   0: 00000000:022A 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1234 1 0 0 0 10 -1\n" > "$FAKE_TCP"

# FIFO-Hintergrundleser starten
exec 3<>"$FAKE_FIFO"

call_cgi() {
    _method="$1"
    _query="$2"
    _referer="NONE"
    [ $# -ge 3 ] && _referer="$3"
    [ "$_referer" = "NONE" ] && _referer="http://testcamera/"
    _ctype="${4:-application/json}"
    _host="${5:-testcamera}"

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
    REQUEST_METHOD="$_method" \
    QUERY_STRING="$_query" \
    HTTP_REFERER="$_referer" \
    HTTP_HOST="$_host" \
    CONTENT_TYPE="$_ctype" \
    "$API_CGI" | sed -n '3,$p'
}

echo "=== Test 1: GET statt POST wird abgewiesen ==="
out=$(call_cgi "GET" "action=turn&dpan=10")
echo "$out" | grep '"err":"post_required"' >/dev/null

echo "=== Test 2: dry per GET wird ebenfalls abgewiesen ==="
out=$(call_cgi "GET" "action=turn&dpan=10&dry=1")
echo "$out" | grep '"err":"post_required"' >/dev/null

echo "=== Test 3: Fehlender oder ungueltiger Referer wird abgewiesen ==="
out=$(call_cgi "POST" "action=turn&dpan=10&dry=1" "" "application/json")
echo "$out" | grep '"err":"bad_referer"' >/dev/null
out=$(call_cgi "POST" "action=turn&dpan=10&dry=1" "http://evil.com/" "application/json")
echo "$out" | grep '"err":"bad_referer"' >/dev/null

echo "=== Test 4: Ungueltiger Content-Type wird abgewiesen ==="
out=$(call_cgi "POST" "action=turn&dpan=10&dry=1" "http://testcamera/" "text/plain")
echo "$out" | grep '"err":"bad_content_type"' >/dev/null

echo "=== Test 5: dpan=-015 wird normalisiert (-15, kein Oktalfehler) ==="
out=$(call_cgi "POST" "action=turn&dpan=-015&dtilt=0&dry=1")
echo "$out" | grep '"requested":{"dpan":-15,"dtilt":0}' >/dev/null
echo "$out" | grep '"executed":{"dpan":-15,"dtilt":0}' >/dev/null
echo "$out" | grep '"clamped":false' >/dev/null

echo "=== Test 6: dpan=abc wird abgewiesen ==="
out=$(call_cgi "POST" "action=turn&dpan=abc&dry=1")
echo "$out" | grep '"err":"invalid_dpan"' >/dev/null

echo "=== Test 7: dpan=99999 (Laenge > 4) wird abgewiesen ==="
out=$(call_cgi "POST" "action=turn&dpan=99999&dry=1")
echo "$out" | grep '"err":"invalid_dpan"' >/dev/null

echo "=== Test 8: Klemmung an den Grenzen (dpan=999 & dtilt=-100) ==="
out=$(call_cgi "POST" "action=turn&dpan=999&dtilt=-100&dry=1")
echo "$out" | grep '"clamped":true' >/dev/null
# 180 + 999 -> geklemmt auf 335 (executed = 155)
echo "$out" | grep '"executed":{"dpan":155,"dtilt":-55}' >/dev/null

echo "=== Test 9: ptz.ini defekt fuehrt zu ptz_invalid ==="
echo "GARBAGE_DATA" > "$FAKE_INI"
out=$(call_cgi "POST" "action=turn&dpan=10&dry=1")
echo "$out" | grep '"err":"ptz_invalid"' >/dev/null
echo "180 70" > "$FAKE_INI"

echo "=== Test 10: Status liefert valides JSON inkl. led_on und rtsp_ready ==="
out=$(call_cgi "GET" "action=status")
echo "$out" | grep '"ok":true' >/dev/null
echo "$out" | grep '"rtsp_ready":1' >/dev/null
echo "$out" | grep '"led_on":0' >/dev/null
echo "$out" | grep '"ptz_valid":true' >/dev/null

echo "=== Test 11: Echte Fahrt setzt Expect-Datei und Busy ==="
out=$(call_cgi "POST" "action=turn&dpan=10&dtilt=0")
echo "$out" | grep '"ok":true' >/dev/null
test -f "$FAKE_EXPECT"
read -r exp_p exp_t < "$FAKE_EXPECT"
[ "$exp_p" = "190" ] && [ "$exp_t" = "70" ]

echo "=== Test 12: Zweiter Aufruf waehrend Busy wird abgewiesen ==="
out=$(call_cgi "POST" "action=turn&dpan=10&dtilt=0")
echo "$out" | grep '"err":"busy"' >/dev/null

echo "=== Alle 12 API-Tests erfolgreich bestanden! ==="
