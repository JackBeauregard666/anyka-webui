#!/bin/sh
set -e

# tools/build_sd.sh -- Erstellt das anyka_webui SD-Karten-Layout
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET_DIR="${1:-$REPO_ROOT/dist/sd_card/anyka_webui}"

echo "Erstelle SD-Karten-Layout in: $TARGET_DIR"

rm -rf "$TARGET_DIR"
mkdir -p "$TARGET_DIR/bin" "$TARGET_DIR/www/cgi-bin"

copy_lf() {
    _src="$1"
    _dst="$2"
    mkdir -p "$(dirname "$_dst")"
    tr -d '\r' < "$_src" > "$_dst"
}

copy_lf "$REPO_ROOT/start_webui.sh" "$TARGET_DIR/start_webui.sh"
copy_lf "$REPO_ROOT/rtsp_supervisor.sh" "$TARGET_DIR/rtsp_supervisor.sh"
copy_lf "$REPO_ROOT/bin/udhcpc_lanonly.sh" "$TARGET_DIR/bin/udhcpc_lanonly.sh"
copy_lf "$REPO_ROOT/webui/www/index.html" "$TARGET_DIR/www/index.html"
copy_lf "$REPO_ROOT/webui/www/cgi-bin/api.cgi" "$TARGET_DIR/www/cgi-bin/api.cgi"

# Pruefsummen generieren
(
    cd "$TARGET_DIR"
    sha256sum \
        start_webui.sh \
        rtsp_supervisor.sh \
        bin/udhcpc_lanonly.sh \
        www/index.html \
        www/cgi-bin/api.cgi > SHA256SUMS
)

echo "SD-Karten-Layout erfolgreich erstellt. Pruefsummen:"
cat "$TARGET_DIR/SHA256SUMS"
