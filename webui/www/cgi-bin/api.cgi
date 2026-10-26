#!/bin/sh
printf "Content-Type: application/json\r\nCache-Control: no-store, no-cache, must-revalidate\r\n\r\n"

PTZ_FIFO="/tmp/ptz.daemon"
PTZ_INI="/etc/jffs2/ptz.ini"
PTZ_LOCK="/tmp/ptz_lock"
BUSY_FILE="/tmp/ptz_busy_until"

set -f

ACTION=""
STEP="1"
RAW_DPAN=""
RAW_DTILT=""
DRY=0

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
        action=up|action=down|action=left|action=right|action=stop|action=calibrate|action=status|action=light_on|action=light_off|action=turn)
            ACTION="${param#action=}"
            ;;
        step=[1-5])
            STEP="${param#step=}"
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
read -r UP _ < /proc/uptime
UP_S="${UP%.*}"

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
    case "$CONTENT" in
        *pan=*|*tilt=*|*PAN=*|*TILT=*)
            for token in $CONTENT; do
                case "$token" in
                    pan=*|PAN=*|x=*|X=*) P="${token#*=}" ;;
                    tilt=*|TILT=*|y=*|Y=*) T="${token#*=}" ;;
                esac
            done
            ;;
        *)
            set -- $CONTENT
            P="$1"
            T="$2"
            ;;
    esac
    case "$P" in *[!0-9]*|"") P="" ;; esac
    case "$T" in *[!0-9]*|"") T="" ;; esac
    if [ -n "$P" ] && [ -n "$T" ]; then
        CUR_PAN="$P"
        CUR_TILT="$T"
        PTZ_VALID=true
    fi
fi

# ----------------- AKTION: STATUS -----------------
if [ "$ACTION" = "status" ]; then
    MEM_FREE=0; MEM_BUF=0; MEM_CACHED=0; MEM_SHMEM=0
    while read -r k v _; do
        case "$k" in
            MemFree:) MEM_FREE="$v" ;;
            Buffers:) MEM_BUF="$v" ;;
            Cached:)  MEM_CACHED="$v" ;;
            Shmem:)   MEM_SHMEM="$v"; break ;;
        esac
    done < /proc/meminfo
    AVAIL_KB=$((MEM_FREE + MEM_BUF + MEM_CACHED - MEM_SHMEM))
    [ "$AVAIL_KB" -lt 0 ] && AVAIL_KB=0

    HAS_GW=0
    while read -r _ dest _ _ _ _ _ mask _; do
        if [ "$dest" = "00000000" ] && [ "$mask" = "00000000" ]; then
            HAS_GW=1
            break
        fi
    done < /proc/net/route
    if [ "$HAS_GW" -eq 0 ]; then ISO=true; else ISO=false; fi

    WIFI_LINK="n/a"; WIFI_DBM="n/a"
    if [ -r /proc/net/wireless ]; then
        while read -r line; do
            case "$line" in
                *wlan0:*)
                    set -- $line
                    WIFI_LINK="${3%.}"
                    WIFI_DBM="${4%.}"
                    ;;
            esac
        done < /proc/net/wireless
    fi

    PTZ_ALIVE=0; RTSP_ALIVE=0
    if [ -f /tmp/ptz.pid ] && kill -0 $(cat /tmp/ptz.pid 2>/dev/null) 2>/dev/null; then
        PTZ_ALIVE=1
    fi
    if [ -f /tmp/rtsp.pid ] && kill -0 $(cat /tmp/rtsp.pid 2>/dev/null) 2>/dev/null; then
        RTSP_ALIVE=1
    fi
    if [ "$PTZ_ALIVE" -eq 0 ] || [ "$RTSP_ALIVE" -eq 0 ]; then
        set +f
        for comm in /proc/[0-9]*/comm; do
            read -r c < "$comm" 2>/dev/null || continue
            [ "$c" = "ptz_daemon" ] && PTZ_ALIVE=1
            [ "$c" = "rtsp" ] && RTSP_ALIVE=1
            [ "$PTZ_ALIVE" -eq 1 ] && [ "$RTSP_ALIVE" -eq 1 ] && break
        done
        set -f
    fi

    printf '{"ok":true,"uptime_s":%s,"avail_kb":%d,"lan_isolated":%s,"wifi_link":"%s","wifi_dbm":"%s","ptz_ready":%d,"rtsp_ready":%d,"busy":%s,"busy_remaining_s":%d,"ptz_valid":%s,"debug_pan":%d,"debug_tilt":%d}\n' \
        "${UP_S}" "$AVAIL_KB" "$ISO" "$WIFI_LINK" "$WIFI_DBM" "$PTZ_ALIVE" "$RTSP_ALIVE" "$IS_BUSY" "$BUSY_REMAINING" "$PTZ_VALID" "$CUR_PAN" "$CUR_TILT"
    exit 0
fi

# ----------------- ZUSTANDSAENDERNDE AKTIONEN -----------------
# Nur POST + Referer-Schutz (ausser bei dry=1)
if [ "$REQUEST_METHOD" != "POST" ] && [ "$DRY" -eq 0 ]; then
    printf '{"ok":false,"err":"post_required"}\n'
    exit 0
fi
if [ -n "$HTTP_REFERER" ] && [ -n "$HTTP_HOST" ]; then
    case "$HTTP_REFERER" in
        *"//$HTTP_HOST/"*|*"//$HTTP_HOST") ;;
        *) printf '{"ok":false,"err":"bad_referer"}\n'; exit 0 ;;
    esac
fi

# Beleuchtung (Weißlicht-LED)
if [ "$ACTION" = "light_on" ]; then
    echo 1 > /sys/user-gpio/WHITE_LED 2>/dev/null
    printf '{"ok":true,"action":"light_on"}\n'
    exit 0
fi
if [ "$ACTION" = "light_off" ]; then
    echo 0 > /sys/user-gpio/WHITE_LED 2>/dev/null
    printf '{"ok":true,"action":"light_off"}\n'
    exit 0
fi

# Daemon-Check
if [ ! -p "$PTZ_FIFO" ]; then
    printf '{"ok":false,"err":"ptz_daemon_not_running"}\n'
    exit 0
fi

# ----------------- LOCK-FUNKTIONEN FUER BUSY -----------------
acquire_lock() {
    _tries=0
    while ! mkdir "$PTZ_LOCK" 2>/dev/null; do
        _tries=$((_tries + 1))
        if [ "$_tries" -gt 20 ]; then
            rmdir "$PTZ_LOCK" 2>/dev/null
            mkdir "$PTZ_LOCK" 2>/dev/null && return 0
            return 1
        fi
        usleep 50000 2>/dev/null || sleep 1
    done
    return 0
}
release_lock() {
    rmdir "$PTZ_LOCK" 2>/dev/null
}

# ----------------- AKTION: TURN (RELATIV) -----------------
if [ "$ACTION" = "turn" ]; then
    # 1. dpan & dtilt vorhanden pruefen
    if [ -z "$RAW_DPAN" ] && [ -z "$RAW_DTILT" ]; then
        printf '{"ok":false,"err":"missing_params"}\n'
        exit 0
    fi
    [ -z "$RAW_DPAN" ] && RAW_DPAN="0"
    [ -z "$RAW_DTILT" ] && RAW_DTILT="0"

    # Strikte Zahlenpruefung: max. 4 Zeichen
    [ "${#RAW_DPAN}" -gt 4 ] && { printf '{"ok":false,"err":"invalid_dpan"}\n'; exit 0; }
    [ "${#RAW_DTILT}" -gt 4 ] && { printf '{"ok":false,"err":"invalid_dtilt"}\n'; exit 0; }

    # dpan validieren & normalisieren
    SIGN_P=""
    CLEAN_P="$RAW_DPAN"
    case "$CLEAN_P" in
        -*) SIGN_P="-"; CLEAN_P="${CLEAN_P#-}" ;;
        +*) CLEAN_P="${CLEAN_P#+}" ;;
    esac
    case "$CLEAN_P" in *[!0-9]*|"") printf '{"ok":false,"err":"invalid_dpan"}\n'; exit 0 ;; esac

    # Fuehrende Nullen entfernen (kein Oktal-Fehler)
    while [ "${CLEAN_P#0}" != "$CLEAN_P" ] && [ "$CLEAN_P" != "0" ]; do
        CLEAN_P="${CLEAN_P#0}"
    done
    [ -z "$CLEAN_P" ] && CLEAN_P=0
    DPAN_VAL=$(( ${SIGN_P}${CLEAN_P} ))

    # dtilt validieren & normalisieren
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

    # 2. ptz.ini Gueltigkeit pruefen
    if [ "$PTZ_VALID" != "true" ]; then
        printf '{"ok":false,"err":"ptz_invalid"}\n'
        exit 0
    fi

    # 3. Zielposition & Soft-Limits berechnen
    # Vorzeichen: dpan > 0 = rechts (groesser), dtilt > 0 = nach unten (groesser)
    TARGET_PAN=$((CUR_PAN + DPAN_VAL))
    TARGET_TILT=$((CUR_TILT + DTILT_VAL))

    CLAMPED=false
    FINAL_PAN="$TARGET_PAN"
    FINAL_TILT="$TARGET_TILT"

    if [ "$TARGET_PAN" -lt 15 ]; then FINAL_PAN=15; CLAMPED=true; fi
    if [ "$TARGET_PAN" -gt 335 ]; then FINAL_PAN=335; CLAMPED=true; fi
    if [ "$TARGET_TILT" -lt 15 ]; then FINAL_TILT=15; CLAMPED=true; fi
    if [ "$TARGET_TILT" -gt 110 ]; then FINAL_TILT=110; CLAMPED=true; fi

    EXEC_DPAN=$((FINAL_PAN - CUR_PAN))
    EXEC_DTILT=$((FINAL_TILT - CUR_TILT))

    ABS_DPAN=$EXEC_DPAN
    [ "$ABS_DPAN" -lt 0 ] && ABS_DPAN=$(( -ABS_DPAN ))
    ABS_DTILT=$EXEC_DTILT
    [ "$ABS_DTILT" -lt 0 ] && ABS_DTILT=$(( -ABS_DTILT ))

    MAX_DELTA=$ABS_DPAN
    [ "$ABS_DTILT" -gt "$MAX_DELTA" ] && MAX_DELTA=$ABS_DTILT

    BUSY_MS=$((1000 + (MAX_DELTA * 1000 / 25)))
    BUSY_SEC=$(( (BUSY_MS + 999) / 1000 ))

    # 4. DRY-RUN Modus
    if [ "$DRY" -eq 1 ]; then
        printf '{"ok":true,"dry":true,"requested":{"dpan":%d,"dtilt":%d},"executed":{"dpan":%d,"dtilt":%d},"clamped":%s,"busy_ms":%d}\n' \
            "$DPAN_VAL" "$DTILT_VAL" "$EXEC_DPAN" "$EXEC_DTILT" "$CLAMPED" "$BUSY_MS"
        exit 0
    fi

    # 5. Busy-Check mit atomarem Lock
    if ! acquire_lock; then
        printf '{"ok":false,"err":"busy","busy_remaining_s":1}\n'
        exit 0
    fi

    # Nochmal pruefen unter Lock
    if [ -f "$BUSY_FILE" ]; then
        read -r B_UNTIL < "$BUSY_FILE" 2>/dev/null
        case "$B_UNTIL" in *[!0-9]*|"") B_UNTIL=0 ;; esac
        if [ "$UP_S" -lt "$B_UNTIL" ]; then
            release_lock
            printf '{"ok":false,"err":"busy","busy_remaining_s":%d}\n' "$((B_UNTIL - UP_S))"
            exit 0
        fi
    fi

    # Busy-Datei aktualisieren
    NEW_UNTIL=$((UP_S + BUSY_SEC))
    echo "$NEW_UNTIL" > "$BUSY_FILE"
    release_lock

    # An FIFO senden
    if { printf 't2p %d %d\n' "$FINAL_PAN" "$FINAL_TILT" >&3; } 3<>"$PTZ_FIFO" 2>/dev/null; then
        printf '{"ok":true,"requested":{"dpan":%d,"dtilt":%d},"executed":{"dpan":%d,"dtilt":%d},"clamped":%s,"busy_ms":%d}\n' \
            "$DPAN_VAL" "$DTILT_VAL" "$EXEC_DPAN" "$EXEC_DTILT" "$CLAMPED" "$BUSY_MS"
    else
        printf '{"ok":false,"err":"ptz_fifo_open_failed"}\n'
    fi
    exit 0
fi

# ----------------- ALTE AKTIONEN (Pfeiltasten / Calibrate) -----------------
# Auch hier gilt die Busy-Sperre!
if [ "$IS_BUSY" = "true" ] && [ "$DRY" -eq 0 ]; then
    printf '{"ok":false,"err":"busy","busy_remaining_s":%d}\n' "$BUSY_REMAINING"
    exit 0
fi

PTZ_CMD=""
REPEAT=1
BUSY_ADD=2

case "$ACTION" in
    calibrate)
        PTZ_CMD="init"
        BUSY_ADD=5
        ;;
    up|down|left|right)
        PTZ_CMD="$ACTION"
        [ "$PTZ_STEP_MODE" = "repeat" ] && REPEAT="$STEP"
        # 1 Step = 10°, Dauer ~1.4s
        BUSY_ADD=$(( 1 + (REPEAT * 10 / 25) ))
        [ "$BUSY_ADD" -lt 2 ] && BUSY_ADD=2
        ;;
    stop)
        PTZ_CMD="stop"
        BUSY_ADD=0
        ;;
esac

if [ "$DRY" -eq 1 ]; then
    printf '{"ok":true,"dry":true,"action":"%s","step":%s}\n' "$ACTION" "$REPEAT"
    exit 0
fi

# Busy pruefen & sperren unter Lock
if [ "$ACTION" != "stop" ]; then
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
    if [ "$BUSY_ADD" -gt 0 ]; then
        echo "$((UP_S + BUSY_ADD))" > "$BUSY_FILE"
    fi
    release_lock
fi

NL='
'
PAYLOAD=""
i=0
while [ "$i" -lt "$REPEAT" ]; do
    PAYLOAD="${PAYLOAD}${PTZ_CMD}${NL}"
    i=$((i + 1))
done

if { printf '%s' "$PAYLOAD" >&3; } 3<>"$PTZ_FIFO" 2>/dev/null; then
    printf '{"ok":true,"action":"%s","step":%s}\n' "$ACTION" "$REPEAT"
else
    printf '{"ok":false,"err":"ptz_fifo_open_failed"}\n'
fi
exit 0
