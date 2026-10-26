#!/bin/sh
SD_MOUNT="${SD_MOUNT:-/mnt}"
RTSP_BIN="$SD_MOUNT/custom/rtsp"
LOCK=/tmp/rtsp_supervisor.pid
RLOG=/tmp/rtsp.log
SLOG="$SD_MOUNT/anyka_webui/rtsp_supervisor.log"   # persistent, klein halten
LAST="$SD_MOUNT/anyka_webui/rtsp_last_exit.log"
export LD_LIBRARY_PATH="$SD_MOUNT/custom/lib:/usr/lib:/lib"

upt() { read -r u _ </proc/uptime; echo "${u%.*}"; }
log() { echo "[$(upt)s] $*" >> "$SLOG" 2>/dev/null; }

# Log-Rotation (SD schonen)
if [ -f "$SLOG" ] && [ "$(wc -c < "$SLOG" 2>/dev/null)" -gt 65536 ]; then
  tail -n 100 "$SLOG" > "$SLOG.tmp" && mv "$SLOG.tmp" "$SLOG"
fi

# Nur eine Instanz
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
  log "Supervisor läuft bereits (PID $(cat "$LOCK")), Abbruch"
  exit 0
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT INT TERM

# Läuft ein Prozess dieses Namens? (pidof, sonst ps-Fallback)
running() {
  if command -v pidof >/dev/null 2>&1; then
    pidof "$1" >/dev/null 2>&1
  else
    ps w 2>/dev/null | grep -v grep | grep -q "$1"
  fi
}

# anyka_ipc sauber beenden und warten, bis es wirklich weg ist
stop_anyka() {
  # Verhindern, dass factory-daemon anyka_ipc wiederbelebt
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
  sleep 2   # V4L2/Treiber Zeit zum Freigeben von /dev/video0 geben
}

log "=== Supervisor Start ==="
killall rtsp 2>/dev/null
fails=0
while true; do
  stop_anyka
  t0=$(upt)
  "$RTSP_BIN" </dev/null >"$RLOG" 2>&1 &
  pid=$!
  log "rtsp gestartet PID $pid"
  wait "$pid"
  rc=$?
  up=$(( $(upt) - t0 ))
  if [ "$up" -lt 15 ]; then
    fails=$((fails + 1))
  else
    fails=0
  fi
  log "rtsp beendet rc=$rc nach ${up}s (fails=$fails)"
  [ "$fails" -le 5 ] && cp "$RLOG" "$LAST" 2>/dev/null   # SD schonen bei Crash-Schleife
  d=$((fails * 3))
  [ "$d" -lt 3 ] && d=3
  [ "$d" -gt 30 ] && d=30
  sleep "$d"
done
