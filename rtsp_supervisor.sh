#!/bin/sh
SD_MOUNT="${SD_MOUNT:-/mnt}"
RTSP_BIN="$SD_MOUNT/custom/rtsp"
LOCK=/tmp/rtsp_supervisor.pid
RLOG=/tmp/rtsp.log
SLOG="$SD_MOUNT/anyka_webui/rtsp_supervisor.log"
LAST="$SD_MOUNT/anyka_webui/rtsp_last_exit.log"
export LD_LIBRARY_PATH="$SD_MOUNT/custom/lib:/usr/lib:/lib"

upt() { read -r u _ </proc/uptime; echo "${u%.*}"; }
log() { echo "[$(upt)s] $*" >> "$SLOG" 2>/dev/null; }

# Log-Rotation auf SD-Karte
if [ -f "$SLOG" ] && [ "$(wc -c < "$SLOG" 2>/dev/null)" -gt 65536 ]; then
  tail -n 100 "$SLOG" > "$SLOG.tmp" && mv "$SLOG.tmp" "$SLOG"
fi

# Nur eine Instanz zulassen
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
  log "Supervisor laeuft bereits (PID $(cat "$LOCK")), Abbruch"
  exit 0
fi
echo $$ > "$LOCK"

pid=""
clean_exit() {
  rm -f "$LOCK"
  [ -n "$pid" ] && kill "$pid" 2>/dev/null
  exit 0
}
trap clean_exit INT TERM
trap 'rm -f "$LOCK"' EXIT

running() {
  if command -v pidof >/dev/null 2>&1; then
    pidof "$1" >/dev/null 2>&1
  else
    ps w 2>/dev/null | grep -v grep | grep -q "$1"
  fi
}

check_port_554() {
  if [ -r /proc/net/tcp ]; then
    while read -r _ local _ st _; do
      case "$local" in
        *:022A)
          if [ "$st" = "0A" ]; then
            return 0
          fi
          ;;
      esac
    done < /proc/net/tcp
  fi
  return 1
}

stop_anyka() {
  killall -12 daemon 2>/dev/null
  killall daemon cmd_serverd 2>/dev/null

  running anyka_ipc || return 0
  log "Beende anyka_ipc..."
  t_stop0=$(upt)
  killall anyka_ipc 2>/dev/null
  i=0
  while running anyka_ipc && [ "$i" -lt 10 ]; do
    [ "$i" -ge 3 ] && killall -9 anyka_ipc 2>/dev/null
    sleep 1
    i=$((i + 1))
  done
  t_stop_duration=$(( $(upt) - t_stop0 ))
  if running anyka_ipc; then
    log "WARNUNG: anyka_ipc nach 10s noch aktiv"
  else
    log "anyka_ipc beendet nach ${t_stop_duration}s"
  fi
  sleep 2
}

log "=== Supervisor Start ==="
killall rtsp 2>/dev/null
fails=0
while true; do
  stop_anyka

  # Log-Begrenzung im RAM (/tmp) vor jedem Start: Max 64 KB
  if [ -f "$RLOG" ] && [ "$(wc -c < "$RLOG" 2>/dev/null)" -gt 65536 ]; then
    tail -n 100 "$RLOG" > "$RLOG.tmp" && mv -f "$RLOG.tmp" "$RLOG"
  fi

  t0=$(upt)
  "$RTSP_BIN" </dev/null >"$RLOG" 2>&1 &
  pid=$!
  log "rtsp gestartet PID $pid"

  # Health-Check: Lauscht Port 554 nach 45s?
  (
    sleep 45
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      if ! check_port_554; then
        echo "[$(upt)s] Health-Check fehlgeschlagen: Port 554 lauscht nach 45s nicht -> Neustart" >> "$SLOG"
        kill "$pid" 2>/dev/null
      fi
    fi
  ) </dev/null >/dev/null 2>&1 &
  watchdog_pid=$!

  wait "$pid"
  rc=$?
  kill "$watchdog_pid" 2>/dev/null || true
  up=$(( $(upt) - t0 ))
  if [ "$up" -lt 15 ]; then
    fails=$((fails + 1))
  else
    fails=0
  fi
  log "rtsp beendet rc=$rc nach ${up}s (fails=$fails)"
  [ "$fails" -le 5 ] && cp "$RLOG" "$LAST" 2>/dev/null

  d=$((fails * 3))
  [ "$d" -lt 3 ] && d=3
  [ "$d" -gt 30 ] && d=30
  sleep "$d"
done
