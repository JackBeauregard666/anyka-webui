# ANYKA AK3918EN080 V200 — VERBINDLICHES ENGINEERING-HANDBUCH & CODE-REFERENZ (Rev. 2)

**WICHTIG FÜR DEN AUSFÜHRENDEN CLI-AGENTEN:**
Du arbeitest auf echter Embedded-Hardware mit extrem knappen Ressourcen und ohne serielle Rettungskonsole (kein UART angeschlossen). Rate NIEMALS Befehls-Flags, Dateipfade oder Daemon-Parameter. Nutze die Code-Bausteine in diesem Dokument als Ausgangspunkt, **aber verifiziere jeden Baustein in der jeweils genannten Phase auf der echten Kamera** und melde jede Abweichung.

**Status der Code-Bausteine (ehrlich):** Alle Bausteine sind **Entwürfe**. Sie wurden lokal auf einem Linux-Host mit `dash`/Python/Node syntaxgeprüft (`sh -n`, `py_compile`, `node --check`) und logisch getestet (FIFO-Verhalten ohne Leser, Whitelist/Injection, DHCP-Hook mit Stub-`route`/`ifconfig`, Boot-Hook mit simuliertem `/proc/mounts`, MTD-Backup mit Fake-Devices, `cam_ctl.py` gegen einen Fake-Telnetd). Sie wurden **nicht** auf BusyBox/uClibc/Kernel 3.4.35 der Kamera ausgeführt. "Funktioniert lokal" ist kein Beweis für die Kamera.

**Änderungen gegenüber Rev. 1 (Kurzüberblick):**
- `udhcpc`-Swap ohne `-q` (sonst läuft kein Renewal-Daemon mehr), plus erzwungener Renew-Test per `SIGUSR1`.
- CGI: kein 250-ms-`usleep` mehr (nicht-blockierender FIFO-Write per O_RDWR), `STEP` wird tatsächlich ausgewertet, POST-Pflicht für Aktionen, RAM-Anzeige ohne tmpfs.
- Boot-Hook: Launcher mit SD-Warteschleife im Hintergrund, Boot-Log, Watchdog-Regel, atomares Schreiben nach `/etc/jffs2`, zweistufiges Gate 2.
- Backup: Partitionsliste aus `/proc/mtd`, MD5-Prüfung (Kamera vs. Host), definierte Restore-Notizen.
- Ehrliche Isolations-Tabelle pro Boot-Zustand, Client-Subnetz-Hinweis, IPv6-Check, Sicherheits-Restrisiken.

---

## 1. Harte Hardware- & BusyBox-Restriktionen

| Komponente | Realität auf dem AK3918EN080 V200 | Zwingende Konsequenz für dich |
| :--- | :--- | :--- |
| **CPU** | ARM926EJ-S @ ~400 MHz (`armv5tejl`), Single-Core, **keine FPU** (Soft-Float) | Keine Shell-Subshells in Schleifen; jedes CGI muss in unter 30 ms enden (Zielwert; Messung siehe 5.4). |
| **C-Library** | `uClibc 0.9.33.2` (NICHT `glibc`, NICHT `musl`) | Keine fremden ARM-Binaries aus Debian/Alpine kopieren – sie crashen sofort. |
| **RAM** | 64 MB physisch, davon ~25–28 MB für Hardware-ISP reserviert (`mem=36M` oder `39M`). Nur **8–14 MB wirklich frei**! | **ABSOLUTES VERBOT**, Backups, Logs oder wachsende Dateien in `/tmp` oder `/var` (`tmpfs` = RAM!) abzulegen. OOM = sofortiger Kernel-Panic/Reboot. |
| **Flash (MTD)** | 8 MB SPI-NOR. **Typisches** Layout (Beispiel, NICHT als Wahrheit annehmen!): `mtd0` Boot, `mtd1/2` Env, `mtd3` Kernel, `mtd4` `/` SquashFS RO, `mtd5` `/usr` SquashFS RO, `mtd6` `/etc/jffs2` JFFS2 RW | Das echte Layout kommt aus `cat /proc/mtd` plus `mount`. **Beschreibe niemals eine MTD-Partition direkt** und rufe niemals `updater` auf. Einzige erlaubte Schreibziele im Flash sind Dateien im gemounteten `/etc/jffs2` (vorher `df -k /etc/jffs2`, mind. 20 % müssen für JFFS2 Garbage Collection frei bleiben; danach `sync`). |
| **WLAN** | Interface heißt `wlan0` (Treiber meist `8188fu.ko`, `rtl8189fs.ko`, `atbm603x_wifi_usb.ko` oder `ssv6x5x.ko`) | Niemals `rmmod` auf WLAN-Module ausführen, niemals `wpa_supplicant` beenden, niemals `ifconfig wlan0 down` aufrufen! |
| **Shell** | BusyBox `ash` (`/bin/sh`), **KEIN `bash`** | Keine Arrays `a=(1 2)`, kein `[[ ... ]]`, kein `pipefail`, kein `<(...)`, kein `$'\r'`, keine GNU-Optionen (z. B. `grep -U`). Nutze reines POSIX-`sh`. |
| **Fehlende Tools** | Im Werks-BusyBox fehlen oft `flock`, `stat`, `timeout`, `nohup`, `ip`, `curl`, `ps aux`, teils auch `pidof`, `usleep`, `killall`, `md5sum` | Nutze `ps` (ohne Flags) oder `/proc/<pid>/cmdline`, `route -n` / `/proc/net/route`, `mkdir` für Locks und `kill -0 $PID` zur Prozessprüfung. **Prüfe die Applet-Liste unten in Phase 1.** |

### 1.1 Pflicht-Applet-Abgleich (Phase 1, Teil von Gate 1)

Führe `busybox --list` aus (Flash-BusyBox **und** ggf. SD-BusyBox) und gleiche gegen diese Bedarfsliste ab. Fehlendes Applet = Fallback wählen oder SD-BusyBox mit dem Applet verwenden, **bevor** ein Baustein aus diesem Dokument benutzt wird:

| Applet | Gebraucht von | Fallback, falls es fehlt |
| :--- | :--- | :--- |
| `pidof` | CGI, Boot-Hook, Start-Skript | `pid_of`-Funktion (unten) |
| `killall` | DHCP-Swap, Supervisor-Stopp | `kill $(pid_of NAME)` |
| `tcpsvd`, `ftpd`, `telnetd` | Rettungsanker | bestehenden Werks-Aufruf übernehmen (Phase 1!) |
| `httpd` | WebUI (Port 80) | SD-BusyBox mit `httpd` |
| `udhcpc`, `route`, `ifconfig` | LAN-only | zwingend nötig, sonst STOPP und Nutzer informieren |
| `watchdog` | Watchdog-Übernahme | `while true; do echo 1 > /dev/watchdog; sleep 5; done &` nur als Notlösung, nach Rücksprache |
| `md5sum`, `wc`, `dd`, `sync`, `cp`, `mv` | Backup, Verifikation, atomares Schreiben | zwingend nötig |
| `grep`, `tr`, `sleep` | Hook, Diagnose | zwingend nötig |
| `mount` mit `--bind` | optionale DHCP-Methode B | Methode A verwenden |
| `ntpd` | optionaler LAN-NTP | Zeit bleibt unsynchronisiert (kein RTC) |
| `stty`, `od` | optional (Telnet-Echo, Diagnose) | weglassen |

`pidof`-Fallback (nur einsetzen, wenn das Applet fehlt):

```sh
# Fallback, falls das 'pidof'-Applet fehlt (liest /proc/<pid>/comm, Kernel >= 2.6.33)
pid_of() {
    for d in /proc/[0-9]*; do
        read -r n < "$d/comm" 2>/dev/null || continue
        if [ "$n" = "$1" ]; then
            echo "${d#/proc/}"
            return 0
        fi
    done
    return 1
}
```

---

## 2. Phase 0: Remote-Tool (`tools/cam_ctl.py`)

Interaktive `telnet`-Aufrufe in Subshells bleiben hängen, `telnetlib` existiert in modernem Python nicht mehr, und einfaches Socket-Lesen scheitert an Telnet-IAC-Sequenzen (`0xFF`) sowie am PTY-Befehlsecho von BusyBox `telnetd`.

**Vorbedingung:** Enthält der Prompt noch Platzhalter der Form `<...>` (Kamera-IP, Passwörter usw.), **STOPP** und den Nutzer fragen. Niemals mit Platzhalter-Strings gegen das Netzwerk arbeiten.

Lege in **Phase 0** exakt dieses Skript unter `./tools/cam_ctl.py` an (`chmod +x tools/cam_ctl.py`) und nutze es für **alle** Telnet- und FTP-Operationen:

```python
#!/usr/bin/env python3
"""
Deterministisches Telnet- & FTP-Steuerwerkzeug für Anyka BusyBox-Kameras.
- Zustandsbehafteter RFC-854-IAC-Parser (überlebt Paketgrenzen)
- Funktioniert mit 'telnetd -l /bin/sh' (ohne Login) UND '/bin/login' (mit User/Pass)
- Echo-sicheres Exit-Code-Framing (immun gegen PTY-Echo)
- Automatische CRLF->LF-Bereinigung bei Text-/Skript-Uploads per FTP
- get/put geben die MD5-Summe aus -> Vergleich mit 'md5sum' auf der Kamera (Backup-Verifikation!)
"""
import argparse
import ftplib
import hashlib
import io
import os
import re
import socket
import sys
import time

IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240
TEXT_EXTS = {".sh", ".cgi", ".html", ".htm", ".js", ".css", ".json", ".conf", ".ini", ".m3u", ".txt"}


class AnykaTelnet:
    def __init__(self, host: str, port: int = 23, timeout: float = 15.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(0.4)
        self._state = "DATA"
        self._iac_cmd = 0
        self.buf = bytearray()

    def _feed(self, chunk: bytes) -> None:
        reply = bytearray()
        for b in chunk:
            if self._state == "DATA":
                if b == IAC:
                    self._state = "IAC"
                else:
                    self.buf.append(b)
            elif self._state == "IAC":
                if b == IAC:
                    self.buf.append(255)
                    self._state = "DATA"
                elif b in (DO, DONT, WILL, WONT):
                    self._iac_cmd = b
                    self._state = "OPT"
                elif b == SB:
                    self._state = "SB"
                else:
                    self._state = "DATA"
            elif self._state == "OPT":
                # Lehne alle Optionen sauber ab -> zwingt telnetd in den einfachen NVT-Modus
                if self._iac_cmd in (DO, DONT):
                    reply.extend((IAC, WONT, b))
                elif self._iac_cmd in (WILL, WONT):
                    reply.extend((IAC, DONT, b))
                self._state = "DATA"
            elif self._state == "SB":
                if b == IAC:
                    self._state = "SB_IAC"
            elif self._state == "SB_IAC":
                self._state = "DATA" if b == SE else "SB"
        if reply:
            self.sock.sendall(bytes(reply))

    def pump(self, duration: float = 0.8) -> str:
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            try:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                self._feed(chunk)
            except socket.timeout:
                pass
        return self.buf.decode("utf-8", errors="replace")

    def login(self, user: str = "root", password: str = "") -> None:
        text = self.pump(0.9)
        if not text.strip():
            self.sock.sendall(b"\n")
            text = self.pump(0.9)

        low = text.lower()
        if "login:" in low:
            self.sock.sendall((user + "\n").encode("utf-8"))
            text = self.pump(1.0)
            low = text.lower()

        if "password:" in low:
            self.sock.sendall((password + "\n").encode("utf-8"))
            text = self.pump(1.0)

        # Schalte Echo ab und normiere PATH; funktioniert auch wenn telnetd direkt in /bin/sh startet
        self.sock.sendall(b"stty -echo 2>/dev/null; export PATH=/usr/sbin:/usr/bin:/sbin:/bin:$PATH\n")
        self.pump(0.5)
        self.buf.clear()

    def run(self, cmd: str, timeout: float = 30.0) -> tuple[int, str]:
        self.buf.clear()
        # Geteilter String im printf verhindert 100%ig falsche Matches durch lokales PTY-Echo!
        wrapped = f"{cmd}\nprintf '\\n__AGY'\"_RC_%d__\\n\" $?\n"
        self.sock.sendall(wrapped.encode("utf-8"))

        pattern = re.compile(r"\r?\n__AGY_RC_(\d+)__\r?\n")
        first_line = cmd.splitlines()[0].strip() if cmd.strip() else ""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.pump(0.25)
            decoded = self.buf.decode("utf-8", errors="replace")
            m = pattern.search(decoded)
            if m:
                rc = int(m.group(1))
                out = decoded[:m.start()]
                # Falls stty -echo ignoriert wurde: Echo des Befehls und des printf-Wrappers entfernen
                lines = out.splitlines()
                if lines and first_line and first_line in lines[0]:
                    lines = lines[1:]
                lines = [ln for ln in lines if "__AGY'" not in ln]
                return rc, "\n".join(lines).strip()
        raise TimeoutError(f"Telnet-Timeout nach {timeout}s bei Befehl: {cmd!r}\nBisherige Ausgabe:\n{self.buf.decode('utf-8', errors='replace')}")

    def close(self) -> None:
        try:
            self.sock.sendall(b"exit\n")
        except OSError:
            pass
        self.sock.close()


def ftp_connect(host: str, port: int, user: str, password: str) -> ftplib.FTP:
    ftp = ftplib.FTP()
    ftp.connect(host, port, timeout=15)
    ftp.login(user=user or "anonymous", passwd=password or "")
    ftp.voidcmd("TYPE I")  # Immer Binary-Modus erzwingen
    return ftp


def md5_file(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description="Anyka Camera Control CLI")
    ap.add_argument("--host", required=True)
    ap.add_argument("--telnet-port", type=int, default=23)
    ap.add_argument("--telnet-user", default="root")
    ap.add_argument("--telnet-pass", default="")
    ap.add_argument("--ftp-port", type=int, default=21)
    ap.add_argument("--ftp-user", default="root", help="Bei Login-Fehler 'anonymous' versuchen (BusyBox ftpd)")
    ap.add_argument("--ftp-pass", default="")

    sub = ap.add_subparsers(dest="mode", required=True)

    p_exec = sub.add_parser("exec")
    p_exec.add_argument("cmd")
    p_exec.add_argument("--timeout", type=float, default=30.0, help="Für dd/Backups auf SD höher setzen (z. B. 300)")

    p_get = sub.add_parser("get")
    p_get.add_argument("remote")
    p_get.add_argument("local")

    p_put = sub.add_parser("put")
    p_put.add_argument("local")
    p_put.add_argument("remote")
    p_put.add_argument("--raw", action="store_true", help="Keine LF-Normalisierung erzwingen")

    args = ap.parse_args()

    if args.mode == "exec":
        tn = AnykaTelnet(args.host, args.telnet_port)
        try:
            tn.login(args.telnet_user, args.telnet_pass)
            rc, out = tn.run(args.cmd, timeout=args.timeout)
            if out:
                print(out)
            return rc
        finally:
            tn.close()

    elif args.mode == "get":
        os.makedirs(os.path.dirname(os.path.abspath(args.local)), exist_ok=True)
        ftp = ftp_connect(args.host, args.ftp_port, args.ftp_user, args.ftp_pass)
        try:
            with open(args.local, "wb") as f:
                ftp.retrbinary(f"RETR {args.remote}", f.write)
            print(f"OK GET {args.remote} -> {args.local} ({os.path.getsize(args.local)} bytes) md5={md5_file(args.local)}")
            return 0
        finally:
            ftp.quit()

    elif args.mode == "put":
        with open(args.local, "rb") as f:
            data = f.read()
        ext = os.path.splitext(args.local)[1].lower()
        if not args.raw and ext in TEXT_EXTS:
            # Verhindert tödliche '\r\n' Shebang-Fehler auf BusyBox!
            data = data.replace(b"\r\n", b"\n")
        ftp = ftp_connect(args.host, args.ftp_port, args.ftp_user, args.ftp_pass)
        try:
            ftp.storbinary(f"STOR {args.remote}", io.BytesIO(data))
            print(f"OK PUT {args.local} -> {args.remote} ({len(data)} bytes) md5={hashlib.md5(data).hexdigest()}")
            return 0
        finally:
            ftp.quit()
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

Hinweise zur Nutzung:
- `exec` hat ein 30-s-Standard-Timeout. Für `dd`/Backups auf die SD `--timeout 300` (oder höher) setzen.
- `get` und `put` geben die MD5-Summe aus. Vergleiche sie mit `md5sum` auf der Kamera (Backup- und Upload-Verifikation, siehe 3.3 und 7.5).
- Schlägt der FTP-Login fehl, `--ftp-user anonymous` probieren (BusyBox `ftpd`).
- Der Test in Phase 0 (`uname -a && free`) ist harmlos. Fehlt `free` (rc 127), ist das kein Fehler des Tools, dann `cat /proc/meminfo` verwenden.

---

## 3. Phase 1: Reconnaissance (NICHTS ÄNDERN!) und Gate-1-Report

Kameras, die nach `MuhammedKalkan/Anyka-Camera-Firmware` entsperrt wurden, befinden sich in einem von **drei verschiedenen Boot-Zuständen**. Du MUSST in Phase 1 anhand von `ps`, `mount`, `/etc/init.d/rc.local` und `/etc/jffs2/` exakt feststellen, welcher Zustand vorliegt.

### 3.1 Dynamische SD-Mountpoint-Erkennung (NIEMALS `/mnt/sdcard` blind annehmen!)

Auf vielen AK3918-Firmwares mountet `/usr/sbin/udisk.sh` die MicroSD-Karte direkt unter **`/mnt`** (nicht `/mnt/sdcard`!), auf anderen unter `/mnt/sdcard` oder `/mnt/sd_card`. Manchmal ist sie als `/dev/mmcblk0p1`, manchmal ohne Partitionstabelle direkt als `/dev/mmcblk0` formatiert. Ermittle den echten Pfad **ohne `awk`** (Applet könnte fehlen):

```sh
SD_MOUNT=""; SD_OPTS=""
while read -r dev mp fs opts _; do
    case "$fs" in
        vfat|msdos) SD_MOUNT="$mp"; SD_OPTS="$opts"; break ;;
    esac
done < /proc/mounts
echo "SD_MOUNT=$SD_MOUNT OPTS=$SD_OPTS"
```

Speichere diesen Pfad als `SD_MOUNT`. **Abbruchbedingungen (STOPP und Nutzer informieren):**
1. `SD_MOUNT` ist leer, dann FAT32-formatierte MicroSD anfordern.
2. `SD_OPTS` enthält `ro` oder `touch "$SD_MOUNT/.rwtest" && rm "$SD_MOUNT/.rwtest"` schlägt fehl (nicht beschreibbar).
3. `df -k "$SD_MOUNT"` zeigt weniger als 32 MB frei (8 MB Flash-Backup plus Reserve).

### 3.2 Die 3 möglichen Boot-Zustände und wie du mit ihnen umgehst

| Merkmal in Phase 1 | Zustand 1: SD-Factory-Hack (`Factory/` oder `anyka_hack/` auf SD) | Zustand 2: Stock-ROM + Telnet-Hook (z. B. in `/etc/jffs2/time_zone.sh`) | Zustand 3: Geflashtes `MuhammedKalkan`-ROM (`update.tar` installiert) |
| :--- | :--- | :--- | :--- |
| **Woran erkennbar?** | `anyka_ipc` läuft NICHT oder wird vom SD-Skript gestoppt; auf `$SD_MOUNT/Factory/` liegt `config.sh` o. ä. | `anyka_ipc` läuft noch in `ps`! `/etc/init.d/rc.local` startet `/usr/sbin/service.sh`. | In `/etc/init.d/rc.local` oder `/usr/sbin/service.sh` steht eine Prüfung auf `/etc/jffs2/custom.sh`; lokale RTSP/PTZ-Binaries liegen schon in `/usr/bin` oder auf SD. |
| **Wo kommt unser Boot-Hook hin?** | Direkt in das bestehende SD-Startskript (`$SD_MOUNT/Factory/...`), **0 Bytes Änderung im Flash nötig!** | Entweder über `$SD_MOUNT/Factory/config.sh` (falls `service.sh` danach sucht – zuerst prüfen!) oder minimaler Hook **am Ende** des bereits genutzten `/etc/jffs2/`-Skripts. | Über `/etc/jffs2/custom.sh` (oder das aktive Startskript des Repos). |
| **LEBENSWICHTIGE FALLE!** | Ziehen der SD-Karte bootet wieder Werks-ROM. | `service.sh` / `anyka_ipc.sh` überwacht oft `anyka_ipc` in einer Schleife! Erst Supervisor stoppen, sonst Reboot/Respawn! Der bestehende Telnet-Hook im selben Skript ist dein aktueller Zugang: **nie** nicht-atomar überschreiben (siehe 7.5). | **EXTREM WICHTIG:** Existiert `/etc/jffs2/custom.sh` auf dem `MuhammedKalkan`-ROM, führt das System beim Booten **NUR** `custom.sh` aus und startet **KEINE** Standard-Dienste mehr (WLAN läuft bereits vorher, aber `telnetd`, `ftpd`, RTSP und PTZ MÜSSEN in `custom.sh` explizit gestartet werden, sonst sperrst du dich komplett aus!). Eine bestehende `custom.sh` **nie ersetzen**, nur additiv ergänzen. |

### 3.3 Reconnaissance-Befehle (rein lesend)

Ergänze zu den Befehlen aus dem Prompt diese Funde, **jeder davon ist Pflichtbestandteil des Gate-1-Reports**:

```sh
# Prozesse MIT vollständiger Kommandozeile (BusyBox 'ps' kürzt Zeilen):
for d in /proc/[0-9]*; do c="$(tr '\0' ' ' < "$d/cmdline" 2>/dev/null)"; [ -n "$c" ] && echo "${d#/proc/}: $c"; done

# Wer hält /dev/watchdog offen, und wie ist der Timeout? (Phase 5 hängt davon ab!)
ls -l /proc/[0-9]*/fd 2>/dev/null | grep watchdog
dmesg | grep -i -E 'watchdog|wdt'

# Exakte Aufrufe, die wir im Boot-Hook 1:1 übernehmen müssen:
#   udhcpc (Optionen, -s Skriptpfad), telnetd (mit/ohne -l), ftpd/tcpsvd (mit/ohne -w, Port, Verzeichnis), httpd (Port 80 belegt?)

# Freier Platz und Flash-Dateien:
df -k /etc/jffs2; ls -l /etc/jffs2/

# IPv6 vorhanden? (Isolation gilt nur für IPv4, falls ja)
[ -e /proc/net/if_inet6 ] && cat /proc/net/if_inet6 || echo "kein IPv6"
```

### 3.4 Gate-1-Pflichtfelder

Der Gate-1-Report MUSS diese Punkte einzeln und belegt (mit Befehlsausgabe) enthalten:
1. **Boot-Zustand (1/2/3)** samt Beleg und der daraus folgende Hook-Ort.
2. `SD_MOUNT`, rw-Status, freier Platz.
3. Laufender Streamer/Daemons, RTSP-/Snapshot-Ports, PTZ-Ansteuerung (Binary, FIFO/CLI, bekannte Befehle).
4. Watchdog: wer hält ihn, Timeout, wird er beim Boot scharf (relevant für 7, Gesetz 8).
5. Bestehende Aufrufe von `udhcpc`, `telnetd`, `ftpd`/`tcpsvd`, `httpd` (exakte Kommandozeilen).
6. Supervisor-/Respawn-Skripte (Pfad und PID).
7. `df -k /etc/jffs2` und Inhalt von `/etc/jffs2/`.
8. Applet-Abgleich gegen die Tabelle 1.1 (fehlende Applets und gewählte Fallbacks).
9. Backup-Ergebnis (MANIFEST, MD5-Vergleich Kamera vs. Host, siehe 3.5) und `RESTORE_NOTES.md`.
10. Ob ein Werks-`httpd` Port 80 belegt, ob IPv6 aktiv ist.

### 3.5 Sicheres MTD-Voll-Backup (ohne `/tmp` zu sprengen!)

Lege dieses Skript per `cam_ctl.py put` auf die SD-Karte (z. B. `$SD_MOUNT/backup_mtd/backup_mtd.sh`, **nicht** in `/tmp`) und führe es mit `exec --timeout 300` aus. Die Partitionsliste kommt aus `/proc/mtd`, nicht aus einer festen Zahl:

```sh
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
```

Danach (Pflicht):
1. Lade jede `mtdblock*.bin` und `MD5SUMS`/`MANIFEST.txt` per `cam_ctl.py get` nach `./backups/<timestamp>/`.
2. **Vergleiche die MD5-Summe der `get`-Ausgabe mit `MD5SUMS` von der Kamera** (fängt WLAN/FTP-Korruption). Zusätzlich muss jede Zeile im `MANIFEST.txt` auf `OK` enden (Größe gegen `/proc/mtd`).
3. Optional, aber empfohlen: ein zweiter Lesedurchlauf einer **nicht gemounteten** Partition muss die identische MD5 liefern (Flash-Lesefehler).
4. **Die JFFS2-Partition (`/etc/jffs2`) wird im laufenden Betrieb RW genutzt.** Ihr `mtdblock`-Image kann inkonsistent sein und ist nur "best effort". Das **echte** Backup von `/etc/jffs2` sind die Dateien selbst: sichere **alle** Dateien (insbesondere `isp_*.conf`, `anyka_cfg.ini`, `wpa_supplicant.conf`, `custom.sh`, `time_zone.sh`) per `get` auf den Host.
5. Sichere außerdem `/etc/init.d/*`, `/usr/sbin/*.sh` und alle Skripte/Binaries des Repo-Setups auf der SD.
6. **Restore-Weg:** Lege `./backups/<timestamp>/RESTORE_NOTES.md` an und halte darin fest, was du über den Rückweg *belegen* kannst (z. B. `update.tar`-Mechanismus des Repos, SPI-Programmer). Kennzeichne ausdrücklich, was **ungetestet** ist. Behaupte nie, das Backup sei "restorebar", solange der Rückweg nicht belegt ist. Ohne UART und mit dem Verbot von `updater` ist ein Backup nur so viel wert wie sein Restore-Pfad.
7. **Secrets:** Die Backups enthalten das WLAN-Passwort. Lege `./backups/` in eine `.gitignore` und behandle es als vertraulich.

---

## 4. Phase 2: Todesschleifen vermeiden (Watchdog, Supervisor, Libraries, BMP-Falle)

### 4.1 Die Single-Open `/dev/watchdog` & Supervisor-Regel

Falls `anyka_ipc` noch läuft (Zustand 2), beachte zwei Kernel-Gesetze:
1. **Eltern-Skript zuerst prüfen:** Lies `cat /usr/sbin/service.sh /usr/sbin/anyka_ipc.sh /usr/sbin/camera.sh 2>/dev/null`. Oft läuft dort eine `while true`-Schleife, die bei Tod von `anyka_ipc` das System neu startet! Ermittle per `ps` bzw. `/proc/<pid>/cmdline` die PID dieses Überwachungsskripts (NIEMALS Prozesse von `wpa_supplicant` oder `udhcpc` töten!).
2. **`/dev/watchdog` erlaubt nur EINEN offenen Dateideskriptor gleichzeitig (`EBUSY`):** Solange `anyka_ipc` läuft, schlägt ein vorher gestarteter `watchdog`-Daemon fehl! Du musst Supervisor-Kill, `anyka_ipc`-Kill und Watchdog-Übernahme **in einer einzigen atomaren Befehlszeile** ausführen:

```sh
# Beispiel (PID_SUPERVISOR vorher exakt bestimmen, falls vorhanden; BUSYBOX_BIN mit 'watchdog'-Applet prüfen!):
kill -9 <PID_SUPERVISOR> 2>/dev/null; killall -9 anyka_ipc 2>/dev/null; echo -n V > /dev/watchdog 2>/dev/null; sleep 1; $BUSYBOX_BIN watchdog -t 5 -T 30 /dev/watchdog
```

Prüfe sofort danach nach 10 Sekunden und nach 45 Sekunden per Telnet `uptime`, dass kein Hardware-Reset ausgelöst wurde! Dokumentiere den **tatsächlichen Watchdog-Timeout** (aus Phase 1) im Report. Er bestimmt die Zeitbudgets im Boot-Hook (Abschnitt 7, Gesetz 8).

### 4.2 Shared Libraries (`LD_LIBRARY_PATH`) & Sensor-Konfiguration (`isp_*.conf`)

- Custom-Binaries (`libre_anyka_app`, `ak_rtsp`, `ptz_daemon`, `ptz_daemon_cpp`, `ptz_daemon_dyn`) benötigen Anyka-Plattformbibliotheken (`libplat_*.so`, `libmpi_*.so`, `libak_*.so`, `libstdc++.so.6`). Liegen diese auf der SD-Karte (z. B. in `libs/`), MUSS in jedem Startskript vorab `export LD_LIBRARY_PATH="$SD_LIBS_DIR:/usr/lib:/lib"` gesetzt werden!
- Prüfe vor dem Start eines Binaries seine Parameter in vorhandenen Repo-Skripten oder per `strings <binary> | grep -E 'isp|snap|port|vs0|ptz|init'`.
- Stelle sicher, dass die zum geladenen Sensormodul (`lsmod` zeigt z. B. `sensor_gc1084`, `sensor_gc1054`, `sensor_gc1034`, `sensor_h62`, `sensor_h63`) passende `/etc/jffs2/isp_*.conf` vorhanden ist. Fehlt sie in `/etc/jffs2/`, suche im Backup oder in `/var/log/messages` (`dmesg`) nach dem erwarteten Dateinamen.

### 4.3 Snapshot-Prüfung: Die 2,7-MB-BMP-Falle auf Port 3000!

Viele Versionen von `libre_anyka_app` öffnen:
- **Port 554:** RTSP (`rtsp://<IP>:554/vs0` für HD-Mainstream, `rtsp://<IP>:554/vs1` für Substream – Achtung: ohne Passwortschutz, daher zwingend LAN-only!). Die Pfade sind **per RTSP-`DESCRIBE` zu bestätigen**, nicht anzunehmen.
- **Port 3000:** HTTP-Snapshot-Server (oder Dateiausgabe nach `/tmp/`).

**PFLICHTPRÜFUNG in Phase 2:** Rufe vom Host-Rechner einen Test-Snapshot ab und prüfe die ersten 3 Bytes (Magic Bytes) sowie die Dateigröße:
- Beginnt die Antwort mit **`FF D8 FF`** (echtes JPEG, typisch 15–90 KB): Perfekt! Das Frontend kann `http://${location.hostname}:3000/...` direkt im `<img>`-Tag mit 1–2 FPS laden (0 CGI-Aufrufe!).
- Beginnt die Antwort mit **`42 4D` (`BM`)** (unkomprimiertes BMP, 1,8 bis 2,7 MB pro Frame!): **STOPP!** Streamst du 2,7 MB zweimal pro Sekunde über das 2,4-GHz-WLAN (`wlan0`), bricht die Verbindung zusammen! Prüfe in diesem Fall in den CLI-Optionen / `strings` von `libre_anyka_app` (bzw. dem vorhandenen Kamera-Binary), welchen URL-Pfad oder Parameter der integrierte **JPEG**-Snapshot nutzt (oder ob er atomar ein kleines `.jpg` nach `/tmp/www/snap.jpg` schreibt).

**Zusatzprüfungen (Pflicht):**
1. **Parallelität:** Rufe den Snapshot-Port von zwei Clients gleichzeitig ab. Ein single-threaded Snapshot-Server kann dabei hängen oder RTSP stören. Mehrere offene Browser-Tabs vervielfachen die Last, dokumentiere das Verhalten.
2. **Requests pro Frame:** Das Double-Buffer-Muster (5.3) lädt jedes Bild über `new Image()` und setzt danach `viewEl.src` auf dieselbe URL. Je nach Cache-Header des Snapshot-Servers (`no-store`) kann der Browser das Bild ein **zweites Mal** anfordern, was Bandbreite verdoppelt und das Flackern zurückbringt. Prüfe in den Browser-DevTools (Network-Tab), dass pro Frame genau **ein** Request erfolgt. Falls nicht: Snapshot gleich-origin (Port 80, `/snap.jpg` atomar in `/tmp/www` schreiben) ausliefern und per `img.decode()` tauschen.

### 4.4 PTZ-Steuerung & die tödliche FIFO-Blockade (`/tmp/ptz.daemon`)

Im Ökosystem von `MuhammedKalkan` / `IOT-ANYKA-PTZdaemon` / `VGerris` liest `ptz_daemon` (bzw. `ptz_daemon_cpp` / `ptz_daemon_dyn`) Befehle aus einer Named Pipe (meist `/tmp/ptz.daemon`) oder über ein CLI-Tool.
- **Lies zwingend die echten Befehlsnamen aus!** Prüfe vorhandene WebUI-/Shell-Skripte auf der Kamera sowie `strings <ptz_binary>`. Häufige Kommandos sind `init` oder `init_ptz` zum Kalibrieren sowie `up`, `down`, `left`, `right` (teils auch `ir_on`/`ir_off` oder Koordinatenbefehle). Verifiziere jeden einzelnen Befehl live über Telnet!
- **Schrittweite:** Kläre, wie sich die Bewegungsweite steuern lässt, und trage das Ergebnis in `PTZ_STEP_MODE` im CGI ein. `repeat` (Standard im Entwurf) sendet den Richtungsbefehl `step`-mal als getrennte Zeilen. Unterstützt der Daemon einen Parameter (z. B. `left 3`) oder Koordinaten, ändere das CGI entsprechend. Ohne belegte Lösung hat die Anforderung "einstellbare Schrittweite" kein Backend.
- **DIE FIFO-KERNEL-FALLE:** Ist `/tmp/ptz.daemon` eine Named Pipe (`[ -p /tmp/ptz.daemon ]`) und der `ptz_daemon`-Prozess ist abgestürzt (kein Leser an der Pipe!), **blockiert `echo "left" > /tmp/ptz.daemon` im Linux-Kernel unendlich im `open(O_WRONLY)`-Syscall!** Nach 10 Klicks im Browser hängen 10 CGI-Prozesse fest und der Webserver stirbt.
- **Schutzmaßnahme im CGI (Rev. 2):** (1) Prüfe VOR jedem Schreiben per `pidof`, ob der Daemon lebt, und ob der Pfad eine FIFO ist. (2) Öffne die FIFO **lesend und schreibend** (`3<>`). Ein O_RDWR-Open blockiert unter Linux nie, auch ohne Leser. Dadurch entfallen Background-Subshell, Timeout-Kill und der bisherige 250-ms-`usleep`. Lokal getestet: ohne Leser keine Blockade (11 ms), unabgeholte Daten werden beim Schließen verworfen (keine Altlasten für den nächsten Daemon-Start). **Verifiziere dieses Verhalten auf der Kamera** (Phase 2), bevor du dich darauf verlässt.

---

## 5. Phase 3: Produktionsreife WebUI- & CGI-Architektur (`/tmp/www`)

### 5.1 Warum `/tmp/www` statt direktem Ausliefern von FAT32?

FAT32 (`$SD_MOUNT`) unterstützt keine sauberen Ausführrechte (`chmod 755`) pro Datei und erzeugt unnötige SD-Latenzen.
- **Lösung:** Speichere alles dauerhaft unter `$SD_MOUNT/anyka_webui/www/`. Beim Start kopiert das Boot-Skript diesen ~35 KB kleinen Ordner nach `/tmp/www/`, setzt `chmod 755 /tmp/www/cgi-bin/*.cgi` und startet BusyBox `httpd`:
  `$BUSYBOX_HTTPD -p 80 -h /tmp/www`
- **Port 80 belegt?** Läuft ein Werks-`httpd` auf Port 80 (Gate-1-Feld 10), beende gezielt dessen PID, bevor du deinen startest. Ein `pidof httpd`-Guard würde sonst deine WebUI nie starten.
- **Goldene BusyBox-`httpd`-Regel:** Wenn irgendein Prozess innerhalb eines CGI-Skripts im Hintergrund gestartet wird, **MUSS** er `</dev/null >/dev/null 2>&1 &` besitzen! Bleibt Dateideskriptor 1 (`stdout`) in einem Kindprozess offen, wartet `httpd` bis in alle Ewigkeit auf EOF und der Browser lädt endlos!

### 5.2 `/tmp/www/cgi-bin/api.cgi` (Zero-Eval, Non-Blocking, Entwurf)

Passe lediglich `PTZ_BIN_NAME`, `PTZ_FIFO`, `PTZ_STEP_MODE` und die in Phase 2 verifizierten `PTZ_CMD`-Strings an deine Hardware-Funde an. Änderungen gegenüber Rev. 1:
- Kein `usleep`/`sleep` mehr im Aktionspfad, damit ist der PTZ-Pfad nicht mehr durch künstliche Wartezeit gebremst.
- `STEP` wird ausgewertet (`PTZ_STEP_MODE=repeat`).
- Zustandsändernde Aktionen nur per **POST**, plus Referer-Mindestschutz gegen fremde Webseiten (CSRF). `status` bleibt GET. **Phase-3-Pflicht:** Teste, dass BusyBox `httpd` einen POST ohne Body (`Content-Length: 0`) akzeptiert. Falls nicht: auf GET plus Referer-Prüfung zurückfallen und das im Report vermerken.
- RAM-Anzeige zieht `Shmem` ab (`Cached` enthält tmpfs und wäre auf diesem System irreführend). `MemAvailable` gibt es auf Kernel 3.4 nicht.
- `status` liest nur `/proc` (ein Fork für `pidof`), die Default-Route-Erkennung prüft Destination **und** Genmask.
- Ob `ir_on`/`ir_off` existieren, ist in Phase 2 zu belegen. Nicht belegte Aktionen aus der Whitelist **entfernen**.

```sh
#!/bin/sh
# ENTWURF: schnelles, injektionssicheres POSIX-CGI fuer Anyka AK3918 (BusyBox ash).
# Vor Produktivnutzung in Phase 2/3 gegen echte Hardware verifizieren (siehe Spec 5.2).
printf "Content-Type: application/json\r\nCache-Control: no-store, no-cache, must-revalidate\r\n\r\n"

PTZ_BIN_NAME="ptz_daemon"       # in Phase 2 anpassen (ptz_daemon_cpp / ptz_daemon_dyn ...)
PTZ_FIFO="/tmp/ptz.daemon"      # in Phase 2 anpassen
PTZ_STEP_MODE="repeat"          # repeat = Befehl STEP-mal senden; in Phase 2 verifizieren

set -f                          # kein Globbing auf $QUERY_STRING

# 1. Strikte Whitelist-Auswertung von QUERY_STRING (NIEMALS eval!)
ACTION=""
STEP="1"
OLD_IFS="$IFS"
IFS="&"
for param in $QUERY_STRING; do
    case "$param" in
        action=up|action=down|action=left|action=right|action=stop|action=calibrate|action=status|action=ir_on|action=ir_off)
            ACTION="${param#action=}"
            ;;
        step=[1-5])
            STEP="${param#step=}"
            ;;
    esac
done
IFS="$OLD_IFS"

if [ -z "$ACTION" ]; then
    printf '{"ok":false,"err":"invalid_action"}\n'
    exit 0
fi

# 2. Systemstatus: liest direkt aus /proc (nur 1 Fork fuer pidof)
if [ "$ACTION" = "status" ]; then
    read -r UP _ < /proc/uptime
    MEM_FREE=0; MEM_BUF=0; MEM_CACHED=0; MEM_SHMEM=0
    while read -r k v _; do
        case "$k" in
            MemFree:) MEM_FREE="$v" ;;
            Buffers:) MEM_BUF="$v" ;;
            Cached:)  MEM_CACHED="$v" ;;
            Shmem:)   MEM_SHMEM="$v" ;;
        esac
    done < /proc/meminfo
    # Cached enthaelt tmpfs (Shmem) und ist NICHT reclaimbar -> abziehen!
    AVAIL_KB=$((MEM_FREE + MEM_BUF + MEM_CACHED - MEM_SHMEM))
    [ "$AVAIL_KB" -lt 0 ] && AVAIL_KB=0

    # Default-Route = Destination 00000000 UND Genmask 00000000
    HAS_GW=0
    while read -r iface dest gw flags refcnt use metric mask _; do
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

    PTZ_ALIVE=0
    pidof "$PTZ_BIN_NAME" >/dev/null 2>&1 && PTZ_ALIVE=1

    printf '{"ok":true,"uptime_s":%s,"avail_kb":%d,"lan_isolated":%s,"wifi_link":"%s","wifi_dbm":"%s","ptz_ready":%d}\n' \
        "${UP%.*}" "$AVAIL_KB" "$ISO" "$WIFI_LINK" "$WIFI_DBM" "$PTZ_ALIVE"
    exit 0
fi

# 3. Zustandsaendernde Aktionen: nur POST + Referer-Mindestschutz (CSRF)
if [ "$REQUEST_METHOD" != "POST" ]; then
    printf '{"ok":false,"err":"post_required"}\n'
    exit 0
fi
if [ -n "$HTTP_REFERER" ] && [ -n "$HTTP_HOST" ]; then
    case "$HTTP_REFERER" in
        *"//$HTTP_HOST/"*|*"//$HTTP_HOST") ;;
        *) printf '{"ok":false,"err":"bad_referer"}\n'; exit 0 ;;
    esac
fi

# 4. Daemon-Check (verhindert Schreiben ins Leere)
if ! pidof "$PTZ_BIN_NAME" >/dev/null 2>&1 || [ ! -p "$PTZ_FIFO" ]; then
    printf '{"ok":false,"err":"ptz_daemon_not_running"}\n'
    exit 0
fi

# 5. WebUI-Aktion -> in Phase 2 verifizierte Daemon-Befehle
PTZ_CMD=""
REPEAT=1
case "$ACTION" in
    calibrate) PTZ_CMD="init" ;;   # Phase 2: 'init' vs 'init_ptz' pruefen!
    up|down|left|right)
        PTZ_CMD="$ACTION"
        [ "$PTZ_STEP_MODE" = "repeat" ] && REPEAT="$STEP"
        ;;
    stop|ir_on|ir_off) PTZ_CMD="$ACTION" ;;
esac

NL='
'
PAYLOAD=""
i=0
while [ "$i" -lt "$REPEAT" ]; do
    PAYLOAD="${PAYLOAD}${PTZ_CMD}${NL}"
    i=$((i + 1))
done

# 6. Nicht-blockierender FIFO-Write: O_RDWR-Open blockiert unter Linux nie.
#    Kein Background-Fork, kein usleep, kein Timeout-Kill noetig.
#    (Redirect an der Gruppe: ein Fehler beendet die Shell NICHT, anders als bei 'exec'.)
if { printf '%s' "$PAYLOAD" >&3; } 3<>"$PTZ_FIFO" 2>/dev/null; then
    printf '{"ok":true,"action":"%s","step":%s}\n' "$ACTION" "$REPEAT"
else
    printf '{"ok":false,"err":"ptz_fifo_open_failed"}\n'
fi
exit 0
```

### 5.3 Pflicht-Patterns für das Single-File-Frontend (`/tmp/www/index.html`)

Baue **eine einzige `index.html`-Datei** (Inline-CSS, Inline-SVGs, Vanilla-JS, **Ziel unter 35 KB, harte Obergrenze 40 KB**, 0 externe URLs). Dadurch entfallen zusätzliche HTTP-Requests und MIME-Type-Bugs minimaler BusyBox-`httpd`-Versionen komplett.

Beachte im JavaScript zwingend diese kritischen Browser-Fallstricke:

1. **Self-Pacing Double-Buffer für flackerfreies 1–2-FPS-JPEG (NIEMALS `setInterval`!):**
   `setInterval` stapelt bei kurzem WLAN-Schluckauf parallele Bildanfragen und legt die Kamera lahm. Nutze ausschließlich eine Kette über `onload`/`onerror` + `visibilitychange`. Beachte die Zusatzprüfung "Requests pro Frame" in 4.3.

```javascript
let targetFps = 1;            // Umschaltbar: 2, 1, 0.5, 0 (Pause)
let timerId = null;
const viewEl = document.getElementById('live-view');
const preloader = new Image();
// Pfad/Port aus Phase 2 (Snapshot-Test) einsetzen; Host IMMER dynamisch:
const SNAPSHOT_BASE_URL = `http://${location.hostname}:3000/SNAPSHOT_PFAD_AUS_PHASE_2`;

function scheduleNext(delayMs) {
  clearTimeout(timerId);
  if (targetFps <= 0 || document.hidden) return;
  timerId = setTimeout(fetchFrame, Math.max(80, delayMs));
}

function fetchFrame() {
  if (targetFps <= 0 || document.hidden) return;
  const t0 = performance.now();
  preloader.onload = () => {
    viewEl.src = preloader.src;
    const elapsed = performance.now() - t0;
    scheduleNext((1000 / targetFps) - elapsed);
  };
  preloader.onerror = () => scheduleNext(1500);
  preloader.src = `${SNAPSHOT_BASE_URL}?t=${Date.now()}`;
}

function setFps(v) {            // von den 0.5 / 1 / 2 / Pause-Buttons aufrufen
  targetFps = v;
  clearTimeout(timerId);
  if (v > 0) fetchFrame();
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden) clearTimeout(timerId);
  else fetchFrame();
});
```

2. **`http://`-kompatible Zwischenablage (Kein Absturz ohne HTTPS!) und client-seitiger `.m3u`-Download:**
   Auf `http://192.168.x.x` ist `window.isSecureContext === false`, weshalb `navigator.clipboard` in Chrome, Firefox und Safari `undefined` ist! Nutze zwingend diesen Fallback für die RTSP-Kopier-Buttons. Die Playlist wird direkt im Browser aus `window.location.hostname` erzeugt (0 Server-Last, 0 MIME-Probleme) und enthält Haupt- und Substream, aber **nur Pfade, die in Phase 2 per `DESCRIBE` bestätigt wurden**:

```javascript
function copyTextLanSafe(text) {
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text);
  }
  return new Promise((resolve, reject) => {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    ok ? resolve() : reject(new Error('Copy failed'));
  });
}

// Pfade vs0/vs1 NUR verwenden, wenn in Phase 2 per RTSP-DESCRIBE bestaetigt
function downloadM3u(streamPaths = ['vs0', 'vs1']) {
  const host = window.location.hostname;
  let content = '#EXTM3U\n';
  for (const p of streamPaths) {
    content += `#EXTINF:-1,Anyka Domecam (${p})\nrtsp://${host}:554/${p}\n`;
  }
  const blob = new Blob([content], { type: 'audio/x-mpegurl' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `anyka-cam.m3u`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
```

3. **PTZ: Debounce, Tastatur, Achsen-Invertierung (`localStorage`), POST:**
   Domecams hängen oft kopfüber unter einem Dachvorsprung oder an der Zimmerdecke. Baue zwei Schalter („Horizontal spiegeln“, „Vertikal spiegeln“) in die Einstellungen, die `left`/`right` bzw. `up`/`down` vor dem Senden tauschen (und optional das Vorschaubild per CSS `transform: scale(-1, -1)` drehen, falls die Kamera-ISP-Config das Bild noch nicht gedreht hat). Der Kalibrierungs-Button sendet `action=calibrate`.

```javascript
// localStorage kann (z. B. Privatmodus) fehlschlagen -> immer kapseln
function lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* ignorieren */ } }

let flipX = lsGet('flipX') === '1';   // Deckenmontage: links/rechts tauschen
let flipY = lsGet('flipY') === '1';   // Deckenmontage: oben/unten tauschen
let ptzStep = 1;                      // 1..5, vom Schrittweiten-Regler gesetzt
const ptzState = { busy: false, last: 0 };

function setFlip(axis, on) {
  if (axis === 'x') { flipX = on; lsSet('flipX', on ? '1' : '0'); }
  else { flipY = on; lsSet('flipY', on ? '1' : '0'); }
}

// Zustandsaendernde Aktionen laufen per POST (CGI lehnt GET ab), mit Debounce und
// hoechstens einem Request im Flug -> keine Request-Stapel bei WLAN-Schluckauf.
function sendPtz(action, step) {
  const now = performance.now();
  if (ptzState.busy || now - ptzState.last < 120) return;
  ptzState.busy = true;
  ptzState.last = now;
  if (flipX && (action === 'left' || action === 'right')) action = action === 'left' ? 'right' : 'left';
  if (flipY && (action === 'up' || action === 'down')) action = action === 'up' ? 'down' : 'up';
  const ac = new AbortController();
  const to = setTimeout(() => ac.abort(), 3000);
  fetch(`/cgi-bin/api.cgi?action=${action}&step=${step}`, { method: 'POST', signal: ac.signal })
    .then(r => r.json())
    .catch(() => null)
    .then(() => { clearTimeout(to); ptzState.busy = false; });
}

const KEYMAP = { ArrowUp: 'up', w: 'up', ArrowDown: 'down', s: 'down',
                 ArrowLeft: 'left', a: 'left', ArrowRight: 'right', d: 'right' };
document.addEventListener('keydown', (e) => {
  if (/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName)) return;
  const dir = KEYMAP[e.key];
  if (dir) { e.preventDefault(); sendPtz(dir, ptzStep); }
});
```

4. **Status-Leiste (RAM, Uptime, WLAN, LAN-Isolation), selbst-taktend:**

```javascript
// Status-Polling: selbst-taktend (kein setInterval), pausiert bei versteckten Tabs
function pollStatus() {
  if (document.hidden) return;
  fetch('/cgi-bin/api.cgi?action=status')
    .then(r => r.json())
    .then(renderStatus)            // renderStatus(s): s.avail_kb, s.uptime_s, s.wifi_link, s.wifi_dbm, s.lan_isolated, s.ptz_ready
    .catch(() => {})
    .then(() => setTimeout(pollStatus, 5000));
}
document.addEventListener('visibilitychange', () => { if (!document.hidden) pollStatus(); });
```

### 5.4 Test-Matrix (vom Host aus, automatisiert)

Messe jeden Endpunkt **20-mal** und bewerte das 95. Perzentil (nicht den Einzelwert). Ein pauschales "<100 ms für alle Endpunkte" ist für den Snapshot unrealistisch (JPEG-Encoding auf 400 MHz plus WLAN):

| Endpunkt | Erwartung | Schwelle (p95) |
| :--- | :--- | :--- |
| `GET /` (index.html) | HTTP 200, `Content-Type: text/html`, Größe < 40 KB | < 150 ms |
| `GET /cgi-bin/api.cgi?action=status` | HTTP 200, valides JSON, `ok:true` | < 100 ms |
| `POST /cgi-bin/api.cgi?action=left&step=1` | HTTP 200, `ok:true`, Bewegung real beobachtet | < 100 ms |
| `GET /cgi-bin/api.cgi?action=left` | `err:post_required` (kein Zustandswechsel per GET) | < 100 ms |
| Snapshot (Port 3000 bzw. `/snap.jpg`) | HTTP 200, Magic `FF D8 FF`, 15–90 KB | < 400 ms |
| RTSP `DESCRIBE` Port 554 (`vs0`, `vs1`) | `RTSP/1.0 200 OK` und SDP | < 500 ms |

Zusätzlich: Injection-Versuche (`action=left;id`, `step=9`, `*`) müssen `invalid_action` bzw. harmlos enden, und der Status-Endpunkt muss unter paralleler Snapshot-Last (2 Clients) weiter antworten.

---

## 6. Phase 4: LAN-Only-Isolation ohne WLAN-Verlust (`udhcpc`-Falle!)

Auf dem AK3918 fehlt `iptables`. Die Sperre erfolgt im Linux-Kernel-Routing (kein Default-Gateway = Kernel verwirft jedes Nicht-Subnetz-Paket sofort mit `ENETUNREACH`). **Das ist eine technische Isolation per Routing, keine absolute Garantie** (siehe 6.5).

**DIE DHCP-FALLE:**
- Wenn du nur einmalig `route del default` ausführst, trägt der laufende `udhcpc`-Prozess beim nächsten DHCP-Lease-Renewal (oft alle 30–60 Minuten!) das Default-Gateway und die DNS-Server des Routers sofort wieder ein!
- Wenn du `udhcpc` hingegen einfach tötest **oder als One-Shot (`-q`) neu startest**, läuft kein Renewal-Daemon mehr, und die Kamera verliert bei Ablauf der Lease ihre IP. **`-q` ist deshalb verboten.**

### 6.1 Der DHCP-Hook (Entwurf)

Lege dieses Skript unter `$SD_MOUNT/anyka_webui/bin/udhcpc_lanonly.sh` ab (zur Laufzeit nach `/tmp/udhcpc_lanonly.sh`, `chmod 755`). Es entfernt Default-Gateways (begrenzt, kein Endlosloop), leert DNS und setzt optional gezielte Routen zu Client-Subnetzen (6.4):

```sh
#!/bin/sh
# /tmp/udhcpc_lanonly.sh -- ENTWURF. Haelt das DHCP-Lease im LAN frisch,
# ignoriert aber Router/Gateway & DNS. Pflicht-Verifikation: Spec Abschnitt 6.
[ -z "$1" ] && exit 1

# Optional: Routen zu Client-Subnetzen (VPN/VLAN) ueber den DHCP-Router statt Default-Gateway.
# Datei /tmp/udhcpc_lanonly.conf, Inhalt z. B.:  CLIENT_ROUTES="192.168.2.0:255.255.255.0"
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

        # DNS leeren (sofern resolv.conf beschreibbar bzw. Symlink nach /tmp oder /var)
        if [ -L /etc/resolv.conf ] || [ -w /etc/resolv.conf ]; then
            { printf '# LAN-ONLY MODE\n' > /etc/resolv.conf; } 2>/dev/null
        fi
        ;;
esac
exit 0
```

### 6.2 Zwei Wege, den Hook einzusetzen

**Methode A (Standard): `udhcpc` ersetzen.** Übernimm vorher die Optionen des Werks-Aufrufs aus Phase 1 (`-i`, `-x`, `-t`, `-T`, `-A`), ändere nur `-s` und füge `-b` sowie `-p` hinzu. **Niemals `-q`.**

```sh
cp "$SD_MOUNT/anyka_webui/bin/udhcpc_lanonly.sh" /tmp/udhcpc_lanonly.sh
chmod 755 /tmp/udhcpc_lanonly.sh
killall udhcpc 2>/dev/null
udhcpc -i wlan0 -s /tmp/udhcpc_lanonly.sh -b -p /tmp/udhcpc_lanonly.pid >/dev/null 2>&1
n=0; while [ "$n" -lt 10 ] && route del default 2>/dev/null; do n=$((n + 1)); done
```

Der Kill des alten `udhcpc` kann je nach BusyBox-Version den Werks-Skript-Event `deconfig` auslösen (`ifconfig wlan0 0.0.0.0` = Telnet-Abbruch). Prüfe das in Phase 4 **mit laufender Telnet-Session und einem zweiten, parallelen `ping` vom Host**. Bricht die Verbindung ab, nutze Methode B.

**Methode B (kein Prozess-Kill): Werks-Skript überbinden.** `udhcpc` ruft sein Skript bei jedem Event per Pfad auf. Liegt das Werks-Skript auf SquashFS (RO), geht das mit einem Bind-Mount, ganz ohne `udhcpc` zu beenden:

```sh
mount --bind /tmp/udhcpc_lanonly.sh <Pfad des Werks-udhcpc-Skripts aus Phase 1>
```

Voraussetzung: `mount --bind` funktioniert auf dieser Kamera (Phase-1-Applet-Check, Test in Phase 4). Das Werks-Skript wird dadurch **vollständig ersetzt**. Prüfe, ob es neben Gateway/DNS noch Weiteres tat (Hostname, Zeit), und ergänze es ggf.

### 6.3 Pflicht-Verifikation in Phase 4

1. `cat /proc/net/route`: Es darf **keine** Zeile mit `00000000` in Spalte 2 (Destination) **und** Spalte 8 (Genmask) existieren.
2. `ping -c 1 -W 2 8.8.8.8` und `1.1.1.1`: Muss **sofort** mit `ping: sendto: Network is unreachable` enden. Kennt das BusyBox-`ping` kein `-W`, lass es weg (`ping -c 1 8.8.8.8` endet ohne Route ebenfalls sofort).
3. **Erzwungenes Renew (der eigentliche Test der DHCP-Falle):** `kill -USR1 $(pidof udhcpc)` (bzw. die PID aus `/tmp/udhcpc_lanonly.pid`), 3 Sekunden warten, dann **Punkt 1 und die resolv.conf erneut prüfen**. Existiert kein `udhcpc`-Prozess mehr, ist der Swap fehlerhaft (Renewal-Daemon fehlt). So testest du in Sekunden, was sonst erst nach 30–60 Minuten auffiele. Wiederhole den Test zweimal.
4. Die Kamera-IP hat sich nicht geändert, die Telnet-Session lebt, die WebUI antwortet weiter.
5. `netstat -tupn` (bzw. `/proc/net/tcp`) zeigt ausschließlich lokale LAN-Verbindungen, und es laufen **keine** Cloud-/P2P-Prozesse mehr.
6. IPv6: `[ -e /proc/net/if_inet6 ] && cat /proc/net/if_inet6`. Ist IPv6 aktiv, gilt die Isolation nicht für IPv6. Dokumentiere das und schlage Deaktivierung vor (z. B. `sysctl`/`/proc/sys/net/ipv6/conf/all/disable_ipv6`, falls vorhanden).
7. Falls der Nutzer einen lokalen NTP-Server im selben Subnetz angegeben hat (z. B. `<ROUTER_IP>`), funktioniert `ntpd -q -p <NTP_IP>` weiterhin, weil die IP im direkten Subnetz liegt.

### 6.4 Folge ohne Default-Gateway: nur Clients im eigenen Subnetz

Ohne Default-Gateway kann die Kamera **keine Antworten an Clients außerhalb ihres Subnetzes** senden. WebUI, RTSP, Telnet und FTP sind dann nur aus demselben `/24` erreichbar. VPN-Clients, andere VLANs und Gastnetze scheitern technisch. Braucht der Nutzer solchen Zugriff, ersetze das Gateway durch **gezielte Routen nur zu den Client-Subnetzen** über den DHCP-Router. Der Hook unterstützt das über `$SD_MOUNT/anyka_webui/lan_routes.conf` (wird zur Laufzeit nach `/tmp/udhcpc_lanonly.conf` kopiert):

```sh
CLIENT_ROUTES="192.168.2.0:255.255.255.0 10.8.0.0:255.255.255.0"
```

### 6.5 Was die Isolation tatsächlich garantiert (pro Boot-Zustand)

| | SD vorhanden, Hook aktiv | SD gezogen oder `DISABLE_WEBUI` |
| :--- | :--- | :--- |
| **Zustand 1** | Isolation aktiv. **Boot-Fenster:** Das Werks-ROM startet `anyka_ipc` vor dem SD-Skript, Cloud-Kontakt ist in den ersten Sekunden möglich. | Werks-ROM startet unverändert: Cloud und Gateway aktiv, vermutlich ohne Telnet. **Keine Rettung per Telnet.** |
| **Zustand 2** | Isolation aktiv, sobald der Hook `anyka_ipc` beendet. **Boot-Fenster** bis dahin. | Anker (Telnet/FTP) läuft aus dem Flash, aber Werksdienste inkl. Cloud laufen weiter, Gateway vorhanden. |
| **Zustand 3** | `custom.sh` ersetzt die Standarddienste, `anyka_ipc` startet nie. Isolation aktiv. | Nur Anker läuft, Gateway vorhanden, **aber kein Cloud-Prozess läuft** (nichts startet ihn). Rettung per Telnet funktioniert. |

Konsequenzen:
- **`DISABLE_WEBUI` ist eine Rückkehr zum Ausgangszustand**, einschließlich Cloud in Zustand 1/2. Das ist gewollt, aber im Gate-2-Report ausdrücklich zu benennen.
- Standard-Policy (`SD_ABSENT_POLICY=open`): Erreichbarkeit und Rettung haben Vorrang. Die LAN-only-Logik liegt bewusst **auf der SD**, damit ein Fehler darin per SD-Ziehen reparierbar ist. Wer stattdessen "fail-closed" will (Isolation auch ohne SD), müsste Gateway-Entfernung in den Flash-Hook legen und erhöht damit das Aussperr-Risiko. Das ist eine Nutzer-Entscheidung, nicht deine.
- **Empfehlung (zweite Ebene):** Sperre die MAC der Kamera im Router für den WAN-Zugriff. Das schließt Boot-Fenster, SD-Fehler und vergessene Gateways unabhängig von der Kamera. Schreibe nie "garantiert", sondern "technisch isoliert per Routing, empfohlen: zusätzliche Router-Regel".

---

## 7. Phase 5: Brick-sichere Boot-Struktur & Checkliste vor Gate 2

### 7.1 Struktur auf der SD

```text
$SD_MOUNT/
├── backup_mtd/               # Voll-Backups aus Phase 1 (niemals löschen!)
└── anyka_webui/
    ├── start_webui.sh        # Haupt-Startskript (wird vom Boot-Hook im Hintergrund gestartet)
    ├── boot.log              # wird bei jedem Boot überschrieben (einzige Diagnose ohne UART)
    ├── lan_routes.conf       # optional: Client-Subnetze (6.4)
    ├── bin/
    │   └── udhcpc_lanonly.sh
    └── www/
        ├── index.html
        └── cgi-bin/
            └── api.cgi
```

### 7.2 Die 9 unumstößlichen Gesetze für den Boot-Hook und `start_webui.sh`

1. **Rettungsanker immer zuerst (vor ALLEM anderen!):**
   Besonders falls `/etc/jffs2/custom.sh` genutzt wird (Zustand 3), MUSS ganz oben (direkt nach dem Shebang) – noch vor jeder `if`-Bedingung und noch vor der Prüfung auf die SD-Karte – sichergestellt werden, dass `telnetd` und `ftpd` laufen. Prüfe in Phase 1 exakt, mit welchem Befehl die Kamera bisher `telnetd` und `ftpd` gestartet hat, und übernimm genau diese Aufrufe. Eine bestehende `custom.sh` wird **nie ersetzt**: Anker oben einfügen, Launcher unten anhängen, der Rest bleibt unverändert.

2. **Warte-Schleife für SD-Mount beim Kaltstart (im Hintergrund!):**
   Beim echten Strom-Kaltstart braucht der MMC-Treiber manchmal 2–5 Sekunden länger als `jffs2`. Die Warteschleife (bis zu 20 s) läuft im **Launcher als entkoppelte Subshell**, der Boot wird nie blockiert. Sie prüft `vfat`/`msdos` in `/proc/mounts` und übergibt den gefundenen Pfad als `$1` an `start_webui.sh`.

3. **Physischer Not-Aus (`DISABLE_WEBUI`):**
   Liegt die Datei `$SD_MOUNT/DISABLE_WEBUI` auf der SD-Karte, beendet sich `start_webui.sh` sofort sauber (`exit 0`), während Telnet und FTP weiterlaufen. Beachte die Semantik aus 6.5: Das ist die Rückkehr zum Ausgangszustand, inklusive deaktivierter LAN-Isolation.

4. **Niemals den Boot-Prozess blockieren:**
   Der Launcher startet `start_webui.sh` in einer Subshell mit `</dev/null >/dev/null 2>&1 &`. Kein Befehl im Hook darf ohne Zeitlimit auf etwas warten.

5. **Sauberer Zeilenumbruch, Rechte und Syntax:** Prüfe vor `reboot` auf der Kamera explizit:
   - `grep -c "$(printf '\r')" /etc/jffs2/custom.sh.new` muss `0` ausgeben (BusyBox-tauglich, ohne `$'\r'` und ohne `grep -U`).
   - `sh -n /etc/jffs2/custom.sh.new` meldet keinen Syntaxfehler.
   - `chmod +x` auf alle Skripte in `/etc/jffs2/`.
   - `df -k /etc/jffs2` hat mindestens 20 % freien Platz.
   - `sync` wurde zweimal ausgeführt.

6. **Atomares Schreiben und zweistufiges Gate 2:** Der Agent schreibt nie direkt in eine aktive Datei unter `/etc/jffs2/`. Ablauf siehe 7.5. Ein Abbruch oder Stromausfall während eines direkten FTP-`STOR` auf `custom.sh` hinterließe eine leere oder halbe Datei und, in Zustand 3, eine Kamera ohne Telnet.

7. **Boot-Log statt Blindflug:** `start_webui.sh` schreibt jeden Schritt (Zeitstempel aus `/proc/uptime`, ohne Fork) nach `$SD_MOUNT/anyka_webui/boot.log`, **überschrieben bei jedem Start** (wenige Zeilen, kein SD-Verschleiß), und ruft am Ende `sync` auf. Ohne UART ist das die einzige Diagnose nach einem fehlgeschlagenen Kaltstart. `>/dev/null` ist nur für die entkoppelten Hintergrunddienste erlaubt, nicht für das Skript selbst.

8. **Watchdog beim Kaltstart:** Auf Basis von Phase 1 (wer hält `/dev/watchdog`, welcher Timeout, wird er beim Boot scharf):
   - Ist der Watchdog beim Boot scharf und feuert **kein** anderer Prozess ihn mehr (typisch Zustand 3 ohne `anyka_ipc`), startet der Anker den BusyBox-`watchdog` **als zweite Zeile**, noch vor der SD-Wartezeit.
   - Die Summe aller Wartezeiten bis zum Watchdog-Feeder bleibt unter dem dokumentierten Timeout. Andernfalls droht ein Boot-Loop. Telnet kommt dann evtl. nicht lange genug hoch, um einzugreifen.
   - Ist der Watchdog beim Boot nicht scharf, wird **kein** neuer gestartet (sonst führst du Reboots ein, die es vorher nicht gab).

9. **Idempotenz und Rollback:** Jeder Dienststart ist mit `pidof`-Guard (bzw. `pid_of`) abgesichert, weil `custom.sh`/Werksskripte Dienste schon gestartet haben können. Der DHCP-Swap wartet vorher auf eine IPv4-Adresse an `wlan0` (max. 20 s) und fällt bei fehlender IP nach dem Swap automatisch auf das Werks-`udhcpc` zurück (siehe `start_webui.sh`).

### 7.3 Boot-Hook (Anker + Launcher, Entwurf)

Dieser Block gehört in die aktive Boot-Datei (Anker direkt nach dem Shebang, Launcher am Ende, bestehender Inhalt bleibt dazwischen unverändert). FTP-Aufruf und Watchdog-Zeile an die Phase-1-Funde anpassen. Bei `FTP_MODE=readonly` das `-w` weglassen (dann funktionieren `cam_ctl.py put`-Uploads nach dem Boot nicht mehr):

```sh
#!/bin/sh
# ===== ENTWURF: Boot-Hook (Inhalt fuer /etc/jffs2/custom.sh bzw. das aktive Startskript) =====
# Bestehenden Inhalt NIE ersetzen: Anker direkt nach dem Shebang einfuegen,
# Launcher ans Ende anhaengen. Alles Dazwischen bleibt unveraendert.

# ---------- ANKER (immer zuerst, vor jeder Bedingung, vor jeder SD-Pruefung) ----------
pidof telnetd >/dev/null 2>&1 || telnetd >/dev/null 2>&1 &
# FTP: EXAKT den in Phase 1 gefundenen Aufruf uebernehmen. Bei FTP_MODE=readonly das '-w' weglassen.
pidof tcpsvd >/dev/null 2>&1 || pidof ftpd >/dev/null 2>&1 || tcpsvd -vE 0.0.0.0 21 ftpd -w / >/dev/null 2>&1 &
# Nur falls Phase 1 belegt, dass der HW-Watchdog beim Boot bereits scharf ist und
# kein anderer Prozess ihn fuettert (Spec 7, Gesetz 8):
# pidof watchdog >/dev/null 2>&1 || watchdog -t 5 -T 30 /dev/watchdog >/dev/null 2>&1

# ---------- SD-LAUNCHER (entkoppelt, blockiert den Boot nie) ----------
(
    i=0
    SD=""
    while [ "$i" -lt 20 ]; do
        while read -r _ mp fs _; do
            case "$fs" in
                vfat|msdos) SD="$mp"; break ;;
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
```

### 7.4 `start_webui.sh` (Entwurf)

Alle `<PARAMS>`/Pfade stammen aus den Phase-2-Funden, nichts davon raten. Jeder Schritt ist unabhängig, ein Fehler gefährdet nie den Rest:

```sh
#!/bin/sh
# ===== ENTWURF: $SD_MOUNT/anyka_webui/start_webui.sh =====
# Aufruf durch den Boot-Hook:  sh start_webui.sh "$SD_MOUNT"
# Jeder Schritt ist unabhaengig; ein Fehler darf nie den Rest (und nie Telnet/FTP) gefaehrden.

SD_MOUNT="$1"
[ -n "$SD_MOUNT" ] || exit 0
BASE="$SD_MOUNT/anyka_webui"
LOG="$BASE/boot.log"

# Boot-Log: pro Boot ueberschrieben, wenige Zeilen -> kein SD-Verschleiss, einzige Diagnose ohne UART
log() { read -r _up _ < /proc/uptime; echo "[${_up%.*}s] $*" >> "$LOG" 2>/dev/null; }
: > "$LOG" 2>/dev/null
log "start_webui.sh gestartet (SD_MOUNT=$SD_MOUNT)"

# ---------- Notbremse ----------
# DISABLE_WEBUI = Rueckkehr zum Ausgangszustand: KEINE Isolation, KEIN Cloud-Kill.
# (Zustand 1/2: Werksdienste inkl. Cloud laufen dann weiter. Das ist gewollt und Teil von Gate 2.)
if [ -e "$SD_MOUNT/DISABLE_WEBUI" ]; then
    log "DISABLE_WEBUI gefunden -> Abbruch (Telnet/FTP laufen weiter)"
    sync
    exit 0
fi

export LD_LIBRARY_PATH="$BASE/libs:/usr/lib:/lib"      # an Phase-1-Fund anpassen
BUSYBOX_HTTPD="${BUSYBOX_HTTPD:-httpd}"                # Phase 1: Applet-Pfad pruefen

# ---------- Web-Root nach tmpfs spiegeln (FAT32: keine Exec-Rechte; SD schonen) ----------
rm -rf /tmp/www 2>/dev/null
mkdir -p /tmp/www/cgi-bin 2>/dev/null
cp "$BASE/www/index.html" /tmp/www/ 2>/dev/null || log "FEHLER: index.html kopieren"
cp "$BASE"/www/cgi-bin/* /tmp/www/cgi-bin/ 2>/dev/null || log "FEHLER: cgi-bin kopieren"
chmod 755 /tmp/www/cgi-bin/* 2>/dev/null
log "www gespiegelt"

# ---------- Dienste (nur starten, wenn nicht schon durch custom.sh/Werksskripte gestartet) ----------
# Phase-2-Funde einsetzen (exakte Binaries/Parameter, NICHT raten):
# pidof libre_anyka_app >/dev/null 2>&1 || "$BASE/bin/libre_anyka_app" <PARAMS> </dev/null >/dev/null 2>&1 &
# pidof ptz_daemon      >/dev/null 2>&1 || "$BASE/bin/ptz_daemon"      <PARAMS> </dev/null >/dev/null 2>&1 &
# Zustand 2/1: Cloud-/Supervisor-Prozesse hier NACH Spec 4.1 beenden (Supervisor zuerst!).

# Falls ein Werks-httpd Port 80 belegt (Phase 1!), gezielt dessen PID beenden statt pidof-Guard.
pidof httpd >/dev/null 2>&1 || $BUSYBOX_HTTPD -p 80 -h /tmp/www </dev/null >/dev/null 2>&1 &
log "httpd angefordert"

# ---------- LAN-only: erst auf IPv4 an wlan0 warten (max. 20 s) ----------
i=0
while [ "$i" -lt 20 ]; do
    ifconfig wlan0 2>/dev/null | grep -q 'inet addr:' && break
    sleep 1
    i=$((i + 1))
done

cp "$BASE/bin/udhcpc_lanonly.sh" /tmp/udhcpc_lanonly.sh 2>/dev/null
chmod 755 /tmp/udhcpc_lanonly.sh 2>/dev/null
[ -r "$BASE/lan_routes.conf" ] && cp "$BASE/lan_routes.conf" /tmp/udhcpc_lanonly.conf 2>/dev/null

# METHODE A (Standard): udhcpc ersetzen -- MUSS als Daemon weiterlaufen (-b, KEIN -q!)
killall udhcpc 2>/dev/null
udhcpc -i wlan0 -s /tmp/udhcpc_lanonly.sh -b -p /tmp/udhcpc_lanonly.pid </dev/null >/dev/null 2>&1 &
# METHODE B (falls in Phase 4 verifiziert, kein Kill noetig):
#   mount --bind /tmp/udhcpc_lanonly.sh <Pfad des Werks-udhcpc-Skripts aus Phase 1>

# Rollback, falls danach keine IP anliegt
i=0
while [ "$i" -lt 15 ]; do
    ifconfig wlan0 2>/dev/null | grep -q 'inet addr:' && break
    sleep 1
    i=$((i + 1))
done
if ! ifconfig wlan0 2>/dev/null | grep -q 'inet addr:'; then
    log "FEHLER: keine IP nach DHCP-Swap -> Rollback auf Werks-udhcpc"
    killall udhcpc 2>/dev/null
    udhcpc -i wlan0 -b </dev/null >/dev/null 2>&1 &     # Werks-Optionen aus Phase 1 einsetzen
fi
n=0
while [ "$n" -lt 10 ]; do route del default 2>/dev/null || break; n=$((n + 1)); done
log "LAN-only angewendet"

# Optional: lokale Zeit aus dem LAN-NTP (nur wenn ntpd-Applet vorhanden, Router-IP aus dem Prompt)
# ntpd -q -p <NTP_IP> >/dev/null 2>&1 &

log "fertig"
sync
exit 0
```

### 7.5 Atomarer Schreibablauf nach `/etc/jffs2` und zweistufiges Gate 2

**Gate 2a (vor jedem Schreiben):** Zeige dem Nutzer
- den **exakten Diff** zwischen bisherigem und neuem Boot-Hook (lokal mit `diff -u` aus dem Backup),
- den kompletten Inhalt von `start_webui.sh` und `udhcpc_lanonly.sh`,
- die Tabelle aus 6.5 mit dem konkreten Verhalten **für den festgestellten Zustand**, `SD_ABSENT_POLICY`, `FTP_MODE` und die `DISABLE_WEBUI`-Semantik,
- die Watchdog-Analyse aus Phase 1 (Gesetz 8).

Warte auf das ausdrückliche **„GO-STAGE“** des Nutzers. Bis dahin: **kein weiterer Tool-Aufruf.**

**Staging (nach GO-STAGE):** Schreibe **nur** `custom.sh.new` (eine neue, inaktive Datei), niemals die aktive Datei:

```sh
# Lokal gebaute Datei hochladen (cam_ctl.py normalisiert CRLF zu LF und gibt die md5 aus):
python3 tools/cam_ctl.py --host <IP> put build/custom.sh /etc/jffs2/custom.sh.new

# Auf der Kamera verifizieren (alles muss grün sein):
df -k /etc/jffs2                                        # mindestens 20 % frei
sh -n /etc/jffs2/custom.sh.new && echo SYNTAX_OK
grep -c "$(printf '\r')" /etc/jffs2/custom.sh.new       # muss 0 ausgeben
md5sum /etc/jffs2/custom.sh.new                         # identisch mit md5 aus der put-Ausgabe
head -n 6 /etc/jffs2/custom.sh.new                      # Anker steht ganz oben
```

**Gate 2b (vor Aktivierung):** Berichte das Staging-Ergebnis und warte auf das ausdrückliche **„GO-ACTIVATE“**. Erst danach:

```sh
[ -e /etc/jffs2/custom.sh ] && [ ! -e /etc/jffs2/custom.sh.orig ] && cp /etc/jffs2/custom.sh /etc/jffs2/custom.sh.orig
chmod +x /etc/jffs2/custom.sh.new
mv /etc/jffs2/custom.sh.new /etc/jffs2/custom.sh        # rename ist auf JFFS2 atomar
sync; sync
```

`custom.sh.orig` bleibt als Schnellrückweg per Telnet erhalten (`mv custom.sh.orig custom.sh`). Anschließend `reboot` **nur** nach separater Freigabe. Empfehlung an den Nutzer: Starte den CLI-Agenten so, dass Aufrufe, die `/etc/jffs2` oder `reboot` berühren, manuell bestätigt werden müssen. Textuelle Gates allein sind kein mechanischer Schutz.

### 7.6 Checkliste nach dem Kaltstart

1. Kamera per Telnet erreichbar, `cat $SD_MOUNT/anyka_webui/boot.log` zeigt alle Schritte ohne `FEHLER`.
2. `uptime` plausibel (kein Boot-Loop), Watchdog-Feeder läuft (falls Gesetz 8 zutrifft).
3. Phase-4-Verifikation (6.3) komplett wiederholen, inklusive erzwungenem Renew.
4. WebUI-Test-Matrix (5.4) wiederholen.
5. **Notbremsen-Test:** `DISABLE_WEBUI` auf die SD legen, rebooten, prüfen, dass Telnet/FTP laufen und der Custom-Start nicht ausgeführt wurde. Datei wieder entfernen. Dann **SD ziehen**, rebooten, prüfen, dass Telnet erreichbar ist (Zustand 3/2). In Zustand 1 ist das Ergebnis "Werks-ROM" erwartetes Verhalten, dokumentiere es.
