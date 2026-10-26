#!/bin/sh
printf "Content-Type: application/json\r\nCache-Control: no-store, no-cache, must-revalidate\r\n\r\n"

# Konfigurierbare Pfade fuer Host-Tests und Embedded-Betrieb
PTZ_FIFO="${PTZ_FIFO:-/tmp/ptz.daemon}"
PTZ_INI="${PTZ_INI:-/etc/jffs2/ptz.ini}"
PTZ_LOCK="${PTZ_LOCK:-/tmp/ptz_lock}"
BUSY_FILE="${BUSY_FILE:-/tmp/ptz_busy_until}"
EXPECT_FILE="${EXPECT_FILE:-/tmp/ptz_expect}"
LED_SYSFS="${LED_SYSFS:-/sys/user-gpio/WHITE_LED}"
PROC_TCP="${PROC_TCP:-/proc/net/tcp}"
PROC_ROUTE="${PROC_ROUTE:-/proc/net/route}"
PROC_MEMINFO="${PROC_MEMINFO:-/proc/meminfo}"
PROC_UPTIME="${PROC_UPTIME:-/proc/uptime}"
PROC_WIRELESS="${PROC_WIRELESS:-/proc/net/wireless}"

# Feste physikalische und rechnerische Konstanten
PAN_MIN=15
PAN_MAX=335
TILT_MIN=15
TILT_MAX=110
SPEED_DEG_PER_S=25
BASE_RESERVE_MS=1000
RACE_RESERVE_S=3

set -f

ACTION=""
RAW_DPAN=""
RAW_DTILT=""
DRY=0

# Parameter aus QUERY_STRING oder POST-Body lesen
BODY=""
if [ "$REQUEST_METHOD" = "POST" ] && [ -n "$CONTENT_LENGTH" ] && [ "$CONTENT_LENGTH" -gt 0 ]; then
    read -r BODY 2>/dev/null
fi
COMBINED_PARAMS="$QUERY_STRING"
[ -n "$BODY" ] && COMBINED_PARAMS="${COMBINED_PARAMS}&${BODY}"

OLD_IFS="$IFS"
IFS="&"
for param in $COMBINED_PARAMS; do
    case "$param" in
        action=up|action=down|action=left|action=right|action=calibrate|action=status|action=light_on|action=light_off|action=turn)
            ACTION="${param#action=}"
            ;;
        dpan=*)
            RAW_DPAN="${param#dpan=}"
            ;;
        dtilt=*)
            RAW_DTILT="${param#dtilt=}"
            ;;
        dry=1)
            DRY=1
            ;;
    esac
done
IFS="$OLD_IFS"

if [ -z "$ACTION" ]; then
    printf '{"ok":false,"err":"invalid_action"}\n'
    exit 0
fi

# Uptime erfassen
read -r UP _ < "$PROC_UPTIME" 2>/dev/null || UP="0 0"
UP_S="${UP%.*}"
case "$UP_S" in *[!0-9]*|"") UP_S=0 ;; esac

# Busy-Status pruefen
IS_BUSY=false
BUSY_REMAINING=0
if [ -f "$BUSY_FILE" ]; then
    read -r B_UNTIL < "$BUSY_FILE" 2>/dev/null
    case "$B_UNTIL" in *[!0-9]*|"") B_UNTIL=0 ;; esac
    if [ "$UP_S" -lt "$B_UNTIL" ]; then
        IS_BUSY=true
        BUSY_REMAINING=$((B_UNTIL - UP_S))
    fi
fi

# ptz.ini lesen & validieren
PTZ_VALID=false
CUR_PAN=0
CUR_TILT=0
if [ -f "$PTZ_INI" ] && [ -r "$PTZ_INI" ]; then
    CONTENT=$(cat "$PTZ_INI" 2>/dev/null)
    set -- $CONTENT
    P="$1"
    T="$2"
    case "$P" in *[!0-9]*|"") P="" ;; esac
    case "$T" in *[!0-9]*|"") T="" ;; esac
    if [ -n "$P" ] && [ -n "$T" ]; then
        CUR_PAN="$P"
        CUR_TILT="$T"
        PTZ_VALID=true
    fi
fi

# ----------------- AKTION: STATUS (GET erlaubt) -----------------
if [ "$ACTION" = "status" ]; then
    MEM_FREE=0; MEM_BUF=0; MEM_CACHED=0; MEM_SHMEM=0
    if [ -r "$PROC_MEMINFO" ]; then
        while read -r k v _; do
            case "$k" in
                MemFree:) MEM_FREE="$v" ;;
                Buffers:) MEM_BUF="$v" ;;
                Cached:)  MEM_CACHED="$v" ;;
                Shmem:)   MEM_SHMEM="$v"; break ;;
            esac
        done < "$PROC_MEMINFO"
    fi
    AVAIL_KB=$((MEM_FREE + MEM_BUF + MEM_CACHED - MEM_SHMEM))
    [ "$AVAIL_KB" -lt 0 ] && AVAIL_KB=0

    # Pruefung Default-Route (IPv4)
    HAS_GW=0
    if [ -r "$PROC_ROUTE" ]; then
        while read -r _ dest _ _ _ _ _ mask _; do
            if [ "$dest" = "00000000" ] && [ "$mask" = "00000000" ]; then
                HAS_GW=1
                break
            fi
        done < "$PROC_ROUTE"
    fi

    # Pruefung Default-Route (IPv6, falls Kernel IPv6 unterstuetzt)
    if [ -r /proc/net/ipv6_route ]; then
        while read -r dest _ _ _ _ _ _ _ _ _; do
            if [ "$dest" = "00000000000000000000000000000000" ]; then
                HAS_GW=1
                break
            fi
        done < /proc/net/ipv6_route
    fi

    if [ "$HAS_GW" -eq 0 ]; then ISO=true; else ISO=false; fi

    WIFI_LINK="n/a"; WIFI_DBM="n/a"
    if [ -r "$PROC_WIRELESS" ]; then
        while read -r line; do
            case "$line" in
                *wlan0:*)
                    set -- $line
                    WIFI_LINK="${3%.}"
                    WIFI_DBM="${4%.}"
                    ;;
            esac
        done < "$PROC_WIRELESS"
    fi

    # Port 554 im LISTEN-Zustand (0A) ohne Fork aus /proc/net/tcp lesen
    RTSP_READY=0
    if [ -r "$PROC_TCP" ]; then
        while read -r _ local _ st _; do
            case "$local" in
                *:022A)
                    if [ "$st" = "0A" ]; then
                        RTSP_READY=1
                        break
                    fi
                    ;;
            esac
        done < "$PROC_TCP"
    fi

    # PTZ Daemon FIFO pruefen
    PTZ_READY=0
    [ -p "$PTZ_FIFO" ] && PTZ_READY=1

    # LED-Status aus Sysfs lesen
    LED_STATUS=0
    if [ -r "$LED_SYSFS" ]; then
        read -r LED_VAL < "$LED_SYSFS" 2>/dev/null
        case "$LED_VAL" in
            1) LED_STATUS=1 ;;
            *) LED_STATUS=0 ;;
        esac
    fi

    printf '{"ok":true,"uptime_s":%s,"avail_kb":%d,"lan_isolated":%s,"wifi_link":"%s","wifi_dbm":"%s","ptz_ready":%d,"rtsp_ready":%d,"busy":%s,"busy_remaining_s":%d,"ptz_valid":%s,"led_on":%d,"debug_pan":%d,"debug_tilt":%d}\n' \
        "${UP_S}" "$AVAIL_KB" "$ISO" "$WIFI_LINK" "$WIFI_DBM" "$PTZ_READY" "$RTSP_READY" "$IS_BUSY" "$BUSY_REMAINING" "$PTZ_VALID" "$LED_STATUS" "$CUR_PAN" "$CUR_TILT"
    exit 0
fi

# ----------------- ZUSTANDSAENDERNDE AKTIONEN (NUR POST) -----------------
# POST-Zwang fuer ausnahmslos alle mutierenden Aktionen (inkl. dry=1)
if [ "$REQUEST_METHOD" != "POST" ]; then
    printf '{"ok":false,"err":"post_required"}\n'
    exit 0
fi

# Referer-Pruefung: Fehlender oder leere Referer wird abgewiesen
if [ -z "$HTTP_REFERER" ] || [ -z "$HTTP_HOST" ]; then
    printf '{"ok":false,"err":"bad_referer"}\n'
    exit 0
fi
case "$HTTP_REFERER" in
    *"//$HTTP_HOST/"*|*"//$HTTP_HOST") ;;
    *)
        printf '{"ok":false,"err":"bad_referer"}\n'
        exit 0
        ;;
esac

# Content-Type-Pruefung: application/json fordern
case "$CONTENT_TYPE" in
    application/json*|*/json*) ;;
    *)
        printf '{"ok":false,"err":"bad_content_type"}\n'
        exit 0
        ;;
esac

# Beleuchtung (Weißlicht-LED)
if [ "$ACTION" = "light_on" ]; then
    if [ "$DRY" -eq 1 ]; then
        printf '{"ok":true,"dry":true,"action":"light_on"}\n'
        exit 0
    fi
    echo 1 > "$LED_SYSFS" 2>/dev/null
    printf '{"ok":true,"action":"light_on"}\n'
    exit 0
fi
if [ "$ACTION" = "light_off" ]; then
    if [ "$DRY" -eq 1 ]; then
        printf '{"ok":true,"dry":true,"action":"light_off"}\n'
        exit 0
    fi
    echo 0 > "$LED_SYSFS" 2>/dev/null
    printf '{"ok":true,"action":"light_off"}\n'
    exit 0
fi

# Daemon-Check (FIFO muss existieren)
if [ ! -p "$PTZ_FIFO" ]; then
    printf '{"ok":false,"err":"ptz_daemon_not_running"}\n'
    exit 0
fi

# ----------------- ATOMARE LOCK-FUNKTIONEN MIT TRAP -----------------
acquire_lock() {
    _tries=0
    _has_usleep=0
    type usleep >/dev/null 2>&1 && _has_usleep=1
    while ! mkdir "$PTZ_LOCK" 2>/dev/null; do
        _tries=$((_tries + 1))
        # Stale-Lock-Erkennung: Aelter als 5s aufbrechen
        if [ "$_tries" -ge 20 ]; then
            rmdir "$PTZ_LOCK" 2>/dev/null
            if mkdir "$PTZ_LOCK" 2>/dev/null; then
                trap 'rmdir "$PTZ_LOCK" 2>/dev/null' EXIT INT TERM
                return 0
            fi
            return 1
        fi
        if [ "$_has_usleep" -eq 1 ]; then
            usleep 100000 2>/dev/null || sleep 1
        else
            sleep 1
            [ "$_tries" -ge 2 ] && return 1 # Max 2s Wartezeit
        fi
    done
    trap 'rmdir "$PTZ_LOCK" 2>/dev/null' EXIT INT TERM
    return 0
}

release_lock() {
    rmdir "$PTZ_LOCK" 2>/dev/null
    trap - EXIT INT TERM
}

# ----------------- AKTION: TURN (RELATIV) -----------------
if [ "$ACTION" = "turn" ]; then
    if [ -z "$RAW_DPAN" ] && [ -z "$RAW_DTILT" ]; then
        printf '{"ok":false,"err":"missing_params"}\n'
        exit 0
    fi
    [ -z "$RAW_DPAN" ] && RAW_DPAN="0"
    [ -z "$RAW_DTILT" ] && RAW_DTILT="0"

    # Strikte Zahlenpruefung: max. 4 Zeichen
    [ "${#RAW_DPAN}" -gt 4 ] && { printf '{"ok":false,"err":"invalid_dpan"}\n'; exit 0; }
    [ "${#RAW_DTILT}" -gt 4 ] && { printf '{"ok":false,"err":"invalid_dtilt"}\n'; exit 0; }

    # dpan normalisieren & Fuehrende Nullen entfernen (kein Oktal-Fehler)
    SIGN_P=""
    CLEAN_P="$RAW_DPAN"
    case "$CLEAN_P" in
        -*) SIGN_P="-"; CLEAN_P="${CLEAN_P#-}" ;;
        +*) CLEAN_P="${CLEAN_P#+}" ;;
    esac
    case "$CLEAN_P" in *[!0-9]*|"") printf '{"ok":false,"err":"invalid_dpan"}\n'; exit 0 ;; esac
    while [ "${CLEAN_P#0}" != "$CLEAN_P" ] && [ "$CLEAN_P" != "0" ]; do
        CLEAN_P="${CLEAN_P#0}"
    done
    [ -z "$CLEAN_P" ] && CLEAN_P=0
    DPAN_VAL=$(( ${SIGN_P}${CLEAN_P} ))

    # dtilt normalisieren
    SIGN_T=""
    CLEAN_T="$RAW_DTILT"
    case "$CLEAN_T" in
        -*) SIGN_T="-"; CLEAN_T="${CLEAN_T#-}" ;;
        +*) CLEAN_T="${CLEAN_T#+}" ;;
    esac
    case "$CLEAN_T" in *[!0-9]*|"") printf '{"ok":false,"err":"invalid_dtilt"}\n'; exit 0 ;; esac
    while [ "${CLEAN_T#0}" != "$CLEAN_T" ] && [ "$CLEAN_T" != "0" ]; do
        CLEAN_T="${CLEAN_T#0}"
    done
    [ -z "$CLEAN_T" ] && CLEAN_T=0
    DTILT_VAL=$(( ${SIGN_T}${CLEAN_T} ))

    # ptz.ini Gueltigkeit pruefen
    if [ "$PTZ_VALID" != "true" ]; then
        printf '{"ok":false,"err":"ptz_invalid"}\n'
        exit 0
    fi

    # Baseline-Race-Pruefung gegen ptz_expect
    if [ -f "$EXPECT_FILE" ]; then
        read -r EXP_P EXP_T < "$EXPECT_FILE" 2>/dev/null
        if [ "$CUR_PAN" -eq "$EXP_P" ] && [ "$CUR_TILT" -eq "$EXP_T" ]; then
            rm -f "$EXPECT_FILE"
        else
            if [ -f "$BUSY_FILE" ]; then
                read -r B_UNTIL < "$BUSY_FILE" 2>/dev/null
                case "$B_UNTIL" in *[!0-9]*|"") B_UNTIL=0 ;; esac
                if [ "$UP_S" -lt $((B_UNTIL + RACE_RESERVE_S)) ]; then
                    printf '{"ok":false,"err":"busy","busy_remaining_s":%d}\n' "$((B_UNTIL + RACE_RESERVE_S - UP_S))"
                    exit 0
                fi
            fi
            # Zeitfenster plus Reserve abgelaufen -> ptz.ini als Wahrheit akzeptieren
            rm -f "$EXPECT_FILE"
        fi
    fi

    # Zielposition berechnen & Klemmen an Soft-Limits
    TARGET_PAN=$((CUR_PAN + DPAN_VAL))
    TARGET_TILT=$((CUR_TILT + DTILT_VAL))

    CLAMPED=false
    FINAL_PAN="$TARGET_PAN"
    FINAL_TILT="$TARGET_TILT"

    if [ "$TARGET_PAN" -lt "$PAN_MIN" ]; then FINAL_PAN="$PAN_MIN"; CLAMPED=true; fi
    if [ "$TARGET_PAN" -gt "$PAN_MAX" ]; then FINAL_PAN="$PAN_MAX"; CLAMPED=true; fi
    if [ "$TARGET_TILT" -lt "$TILT_MIN" ]; then FINAL_TILT="$TILT_MIN"; CLAMPED=true; fi
    if [ "$TARGET_TILT" -gt "$TILT_MAX" ]; then FINAL_TILT="$TILT_MAX"; CLAMPED=true; fi

    EXEC_DPAN=$((FINAL_PAN - CUR_PAN))
    EXEC_DTILT=$((FINAL_TILT - CUR_TILT))

    ABS_DPAN=$EXEC_DPAN
    [ "$ABS_DPAN" -lt 0 ] && ABS_DPAN=$(( -ABS_DPAN ))
    ABS_DTILT=$EXEC_DTILT
    [ "$ABS_DTILT" -lt 0 ] && ABS_DTILT=$(( -ABS_DTILT ))

    MAX_DELTA=$ABS_DPAN
    [ "$ABS_DTILT" -gt "$MAX_DELTA" ] && MAX_DELTA=$ABS_DTILT

    BUSY_MS=$((BASE_RESERVE_MS + (MAX_DELTA * 1000 / SPEED_DEG_PER_S)))
    BUSY_SEC=$(( (BUSY_MS + 999) / 1000 ))

    # DRY-RUN Modus: Rechnen ohne FIFO und ohne Sperren
    if [ "$DRY" -eq 1 ]; then
        printf '{"ok":true,"dry":true,"requested":{"dpan":%d,"dtilt":%d},"executed":{"dpan":%d,"dtilt":%d},"clamped":%s,"busy_ms":%d}\n' \
            "$DPAN_VAL" "$DTILT_VAL" "$EXEC_DPAN" "$EXEC_DTILT" "$CLAMPED" "$BUSY_MS"
        exit 0
    fi

    # Atomare Busy-Pruefung
    if ! acquire_lock; then
        printf '{"ok":false,"err":"busy","busy_remaining_s":1}\n'
        exit 0
    fi

    if [ -f "$BUSY_FILE" ]; then
        read -r B_UNTIL < "$BUSY_FILE" 2>/dev/null
        case "$B_UNTIL" in *[!0-9]*|"") B_UNTIL=0 ;; esac
        if [ "$UP_S" -lt "$B_UNTIL" ]; then
            release_lock
            printf '{"ok":false,"err":"busy","busy_remaining_s":%d}\n' "$((B_UNTIL - UP_S))"
            exit 0
        fi
    fi

    NEW_UNTIL=$((UP_S + BUSY_SEC))
    echo "$NEW_UNTIL" > "$BUSY_FILE"
    echo "$FINAL_PAN $FINAL_TILT" > "$EXPECT_FILE"
    release_lock

    if { printf 't2p %d %d\n' "$FINAL_PAN" "$FINAL_TILT" >&3; } 3<>"$PTZ_FIFO" 2>/dev/null; then
        printf '{"ok":true,"requested":{"dpan":%d,"dtilt":%d},"executed":{"dpan":%d,"dtilt":%d},"clamped":%s,"busy_ms":%d}\n' \
            "$DPAN_VAL" "$DTILT_VAL" "$EXEC_DPAN" "$EXEC_DTILT" "$CLAMPED" "$BUSY_MS"
    else
        printf '{"ok":false,"err":"ptz_fifo_open_failed"}\n'
    fi
    exit 0
fi

# ----------------- AKTIONEN: RICHTUNGSTASTEN & CALIBRATE -----------------
# Busy-Pruefung unter Lock
if ! acquire_lock; then
    printf '{"ok":false,"err":"busy","busy_remaining_s":1}\n'
    exit 0
fi

if [ -f "$BUSY_FILE" ]; then
    read -r B_UNTIL < "$BUSY_FILE" 2>/dev/null
    case "$B_UNTIL" in *[!0-9]*|"") B_UNTIL=0 ;; esac
    if [ "$UP_S" -lt "$B_UNTIL" ]; then
        release_lock
        printf '{"ok":false,"err":"busy","busy_remaining_s":%d}\n' "$((B_UNTIL - UP_S))"
        exit 0
    fi
fi

PTZ_CMD=""
BUSY_ADD=2

case "$ACTION" in
    calibrate)
        PTZ_CMD="init"
        BUSY_ADD=5
        ;;
    up|down|left|right)
        PTZ_CMD="$ACTION"
        # 1 relativer Schritt = 10 Rohwerte im C++ Daemon (Dauer ~1.4s)
        BUSY_ADD=$((BASE_RESERVE_MS / 1000 + (10 / SPEED_DEG_PER_S) + 1))
        [ "$BUSY_ADD" -lt 2 ] && BUSY_ADD=2
        ;;
esac

if [ "$DRY" -eq 1 ]; then
    release_lock
    printf '{"ok":true,"dry":true,"action":"%s"}\n' "$ACTION"
    exit 0
fi

echo "$((UP_S + BUSY_ADD))" > "$BUSY_FILE"
release_lock

if { printf '%s\n' "$PTZ_CMD" >&3; } 3<>"$PTZ_FIFO" 2>/dev/null; then
    printf '{"ok":true,"action":"%s"}\n' "$ACTION"
else
    printf '{"ok":false,"err":"ptz_fifo_open_failed"}\n'
fi
exit 0
