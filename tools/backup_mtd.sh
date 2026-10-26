#!/bin/sh
# Aufruf: sh backup_mtd.sh "$SD_MOUNT"   (Ziel ist IMMER die SD-Karte, NIE /tmp!)
SD_MOUNT="$1"
[ -n "$SD_MOUNT" ] || { echo "SD_MOUNT fehlt"; exit 1; }
D="$SD_MOUNT/backup_mtd"
mkdir -p "$D" || exit 1
: > "$D/MANIFEST.txt"
: > "$D/MD5SUMS"

# Partitionsliste kommt aus /proc/mtd (NICHT hartkodiert):  mtdN: <size hex> <erasesize hex> "<name>"
while read -r dev size erase name; do
    case "$dev" in
        mtd[0-9]*:) ;;
        *) continue ;;
    esac
    n="${dev%:}"
    n="${n#mtd}"
    src="/dev/mtdblock$n"
    if [ ! -e "$src" ]; then
        echo "mtd$n $name: kein $src, uebersprungen" >> "$D/MANIFEST.txt"
        continue
    fi
    out="$D/mtdblock$n.bin"
    dd if="$src" of="$out" bs=65536 2>/dev/null
    set -- $(wc -c < "$out")
    got="$1"
    want=$((0x$size))
    if [ "$got" -eq "$want" ]; then st="OK"; else st="GROESSE_FALSCH"; fi
    set -- $(md5sum "$out")
    echo "$1  mtdblock$n.bin" >> "$D/MD5SUMS"
    echo "mtd$n $name soll=$want ist=$got $st" >> "$D/MANIFEST.txt"
done < /proc/mtd
sync
cat "$D/MANIFEST.txt"
