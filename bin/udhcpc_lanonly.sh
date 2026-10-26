#!/bin/sh
# /tmp/udhcpc_lanonly.sh -- DHCP-Lease-Erneuerung ohne Gateway und DNS
[ -z "$1" ] && exit 1

CONF="/tmp/udhcpc_lanonly.conf"

write_if_diff() {
    _file="$1"
    _content="$2"
    if [ -w "$_file" ] || [ -L "$_file" ]; then
        _cur=$(cat "$_file" 2>/dev/null || true)
        if [ "$_cur" != "$_content" ]; then
            printf '%s\n' "$_content" > "$_file" 2>/dev/null || true
        fi
    fi
}

case "$1" in
    deconfig|leasefail|nak)
        # Bewusst No-Op: IP wird nicht genullt (verhindert Verbindungsabbrueche bei Lease-Renewal)
        ;;
    renew|bound)
        ifconfig "$interface" "$ip" ${subnet:+netmask "$subnet"} ${broadcast:+broadcast "$broadcast"}

        # Alle Default-Gateways entfernen
        n=0
        while [ "$n" -lt 10 ]; do
            route del default 2>/dev/null || break
            n=$((n + 1))
        done

        # Optionale statische Client-Routen
        if [ -r "$CONF" ] && [ -n "$router" ]; then
            CLIENT_ROUTES=""
            . "$CONF"
            set -- $router
            gw1="$1"
            for r in $CLIENT_ROUTES; do
                route add -net "${r%%:*}" netmask "${r#*:}" gw "$gw1" dev "$interface" 2>/dev/null
            done
        fi

        # DNS nur schreiben wenn abweichend (schont Flash /etc/jffs2)
        write_if_diff "/etc/resolv.conf" "# LAN-ONLY MODE"
        write_if_diff "/etc/jffs2/resolv.conf" "# LAN-ONLY MODE"
        ;;
esac
exit 0
