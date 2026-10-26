# Installationsanleitung

## 1. Voraussetzungen

- Eine Anyka AK3918-basierte Dome-Kamera (getestet: AK3918EN080 V200 mit GC1054-Sensor).
- MicroSD-Karte (FAT32 formatiert, maximal 32 GB empfohlen).
- Ein eingerichteter Anyka-Bootloader-Hack (ausfuehrbare `time_zone.sh` oder `custom.sh` im Flash unter `/etc/jffs2`).
- Python 3 auf dem Host-Rechner (fuer das Management-Werkzeug `tools/cam_ctl.py`).

---

## 2. Herkunft und Pruefsummen der Upstream-Binaerdateien

Die Binaries im Verzeichnis `/mnt/custom/` stammen aus dem Projekt [MuhammedKalkan/Anyka-Camera-Firmware](https://github.com/MuhammedKalkan/Anyka-Camera-Firmware). Sie wurden gegen uClibc 0.9.33.2 fuer `armv5tejl` kompiliert.

### SHA-256 Pruefsummen der verifizierten Dateien:

```text
7cbce393cf2452a23f41e71c03c00ab7c98cb0ac8d6062e18a42a621a980e6d9  custom/rtsp
b418cd2b51681d6fb8b2bb57092017d039b960e4ad3fce1b32718e74c271e8d6  custom/ptz_daemon
f604f817bae39eb6f0ced45a870b1b5a5362ecd26ddd2eebfd0fb841a408f8f2  custom/busybox

68f78de8bf97fe22c86722a9eadbe1713e5d6120464fefe73e5ebeba1a59313f  custom/lib/libakae.so
b36db60d1f795446d3951f78ae9e5e1100abfd409e4b96e307cdc920151aadd2  custom/lib/libakstreamenc.so
ae8cec1df4b73cac4d9936355701b08dec02371f52160efa9676310d11bb4dda  custom/lib/libakuio.so
b88161772f0bc7edd3ca1f97407b9fc2548f53b4d3b23a9933952864847a4462  custom/lib/libapp_net.so
341eaee5ffd027a9d336c63f7f5f069c237dd4a69e1e4f7d2540ef9280d7126b  custom/lib/libapp_rtsp.so
ce2653708a133b92cf9042c4406b6870d6fccac2e237b44dc967fd7e63edf325  custom/lib/libmpi_aed.so
d512b96bbf872869b017f578198065a993e475962e04b8c644f3baafe59c29e3  custom/lib/libmpi_aenc.so
640c6a39dc8f6b5789a54b35df5cf1732c33e99c54e6b7f463c9490105b53844  custom/lib/libmpi_venc.so
0b5a36006494f1c9efbce53aa8e17f5dcf930e506fc5efa2493f261c976a4b09  custom/lib/libplat_ai.so
300a5ebb36f23bdeb7b504e5428fa25adc962895c58e6d8ba314ac0547c68ded  custom/lib/libplat_common.so
383d7d710f3c24aa18cd852a94bdfabe751cf6d7db4806f53ddf198fcb9e9e72  custom/lib/libplat_drv.so
76e57ac7393bb2bf0771e6288a1be54aebf9b8275806c9ae0a1515dedbb9607a  custom/lib/libplat_ipcsrv.so
370253ddff94ab5973ec2f296d0b901e955c44ca6b6670a8664bb9d7f15a30bd  custom/lib/libplat_thread.so
445a3f949d52387d13ce109c5ab4f8965171e90f7c2cdd722f36c071146c950a  custom/lib/libplat_vi.so
212e2c1e0ee4d64beafb2dd5fc8acc106b4e452092ae7e52602c2cbfa7b93378  custom/lib/libplat_vpss.so
```

---

## 3. SD-Karten Dateistruktur

Auf der FAT32-formatierten MicroSD-Karte liegt folgende Struktur:

```text
/mnt/
├── custom/                     # Upstream-Binaries & Bibliotheken
│   ├── busybox
│   ├── ptz_daemon
│   ├── rtsp
│   └── lib/
│       └── *.so
└── anyka_webui/                # Dieses Projekt
    ├── start_webui.sh
    ├── rtsp_supervisor.sh
    ├── bin/
    │   └── udhcpc_lanonly.sh
    └── www/
        ├── index.html
        └── cgi-bin/
            └── api.cgi
```

---

## 4. Boot-Hook im Flash (`/etc/jffs2/time_zone.sh`)

> **WICHTIGER SICHERHEITSHINWEIS:**
> Bestehende Skripte im Flash (`/etc/jffs2/time_zone.sh` oder `custom.sh`) duerfen **niemals blind ueberschrieben** werden. Vor jedem Eingriff muss ein vollstaendiges Backup angelegt werden. Die Ergaenzung erfolgt rein additiv.

Der reale Boot-Hook auf der Kamera lautet:

```sh
#!/bin/sh
# ---------- ANKER (immer zuerst) ----------
export TZ=GMT-1
pidof telnetd >/dev/null 2>&1 || telnetd >/dev/null 2>&1 &
pidof tcpsvd >/dev/null 2>&1 || pidof ftpd >/dev/null 2>&1 || /usr/bin/tcpsvd 0 21 ftpd -w / -t 600 >/dev/null 2>&1 &

# ---------- SD-LAUNCHER (entkoppelt im Hintergrund, max 1x pro Boot) ----------
if [ ! -f /tmp/webui_started ]; then
    touch /tmp/webui_started
    (
        i=0
        SD=""
        while [ "$i" -lt 20 ]; do
            while read -r dev mp fs _; do
                case "$dev" in
                    /dev/mmcblk*) SD="$mp"; break ;;
                esac
            done < /proc/mounts
            [ -n "$SD" ] && break
            sleep 1
            i=$((i + 1))
        done
        if [ -n "$SD" ] && [ -f "$SD/anyka_webui/start_webui.sh" ]; then
            sh "$SD/anyka_webui/start_webui.sh" "$SD"
        fi
    ) </dev/null >/dev/null 2>&1 &
fi
```

---

## 5. Rollback und Deinstallation

### 5.1 Notbremse (`DISABLE_WEBUI`)
Falls die WebUI oder die LAN-Isolation temporaer deaktiviert werden soll, erstelle eine leere Datei `DISABLE_WEBUI` im Wurzelverzeichnis der SD-Karte:

```bash
touch /mnt/DISABLE_WEBUI
```

**Wirkung:**
- `start_webui.sh` bricht beim Booten sofort ab.
- Die Kamera laeuft im vollstaendigen Werkszustand.
- **Achtung:** Der Werks-Daemon stellt in diesem Zustand die regulaere Internet- und Cloudverbindung her. Telnet und FTP bleiben erreichbar.

### 5.2 Dauerhafte Deinstallation
1. Entferne das Verzeichnis `/mnt/anyka_webui` von der SD-Karte.
2. Entferne den `SD-LAUNCHER`-Block aus `/etc/jffs2/time_zone.sh`.
3. Nach einem Neustart befindet sich das Geraet wieder im regulaeren Werkszustand.
