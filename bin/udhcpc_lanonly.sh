#!/bin/sh
# /tmp/udhcpc_lanonly.sh -- Haelt das DHCP-Lease im LAN frisch,
# ignoriert aber Router/Gateway & DNS. Pflicht-Verifikation: Spec Abschnitt 6.
[ -z "$1" ] && exit 1

CONF="/tmp/udhcpc_lanonly.conf"

case "$1" in
    deconfig)
        # WICHTIG: Niemals 0.0.0.0 setzen, solange wlan0 aktiv ist (Telnet reisst sonst ab)!
        ;;
    renew|bound)
        ifconfig "$interface" "$ip" ${subnet:+netmask "$subnet"} ${broadcast:+broadcast "$broadcast"}

        # JEDES Default-Gateway entfernen (begrenzt, kein Endlosloop):
        n=0
        while [ "$n" -lt 10 ]; do
            route del default 2>/dev/null || break
            n=$((n + 1))
        done

        # Optional: gezielte Routen zu Client-Subnetzen
        if [ -r "$CONF" ] && [ -n "$router" ]; then
            CLIENT_ROUTES=""
            . "$CONF"
            set -- $router
            gw1="$1"
            for r in $CLIENT_ROUTES; do
                route add -net "${r%%:*}" netmask "${r#*:}" gw "$gw1" dev "$interface" 2>/dev/null
            done
        fi

        # DNS leeren
        if [ -L /etc/resolv.conf ] || [ -w /etc/resolv.conf ]; then
            { printf '# LAN-ONLY MODE\n' > /etc/resolv.conf; } 2>/dev/null
        fi
        if [ -w /etc/jffs2/resolv.conf ]; then
            { printf '# LAN-ONLY MODE\n' > /etc/jffs2/resolv.conf; } 2>/dev/null
        fi
        ;;
esac
exit 0
