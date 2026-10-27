# Architektur und technische Referenz

## 1. Systemuebersicht und Boot-Timeline

Die Kamera basiert auf dem Anyka AK3918EN080 V200 SoC (ARM926EJ-S, ARMv5TEJ-Architektur, Soft-Float) mit Linux Kernel 3.4.35 und uClibc 0.9.33.2.

### 1.1 Boot-Timeline (gemessen an boot.log)

| Zeit | Ereignis | Details |
| :--- | :--- | :--- |
| **0 s** | Kernel-Start | Bootloader laedt Kernel und mountet Rootfs (SquashFS, RO) sowie `/etc/jffs2` (JFFS2, RW). |
| **~7 s** | Boot-Hook | `/etc/jffs2/time_zone.sh` wird ausgefuehrt. Telnetd (Port 23) und ftpd (Port 21) starten. |
| **~7 s** | SD-Erkennung | SD-Launcher erkennt Mountpoint `/mnt` (`/dev/mmcblk0p1`) und startet `start_webui.sh`. |
| **~7 s** | Web-Mirroring | Web-Dateien werden von der SD-Karte nach `/tmp/www` (RAM/tmpfs) gespiegelt. |
| **~20–35 s** | WLAN-Verbindung | Werks-Daemon `anyka_ipc` initialisiert WLAN-Treiber, WPA und erhaelt DHCP-Lease. |
| **~35 s** | LAN-Isolation | `start_webui.sh` erkennt IPv4 an `wlan0`, bind-mountet `udhcpc_lanonly.sh`, loescht Default-Gateways und leert DNS. Vorher protokolliert es, ob bis dahin eine Default-Route bestand (`Default-Route vor der Isolation: JA/NEIN`). |
| **~35 s** | Dienste-Start | `ptz_daemon` (FIFO `/tmp/ptz.daemon`), `httpd` (Port 80) und `rtsp_supervisor.sh` starten. |
| **~37 s** | RTSP-Ablösung | `rtsp_supervisor.sh` beendet `anyka_ipc`, uebergibt Sensorschnittstelle an `/mnt/custom/rtsp` (Port 554). |

Mit der optionalen Datei `EARLY_ISOLATION` auf der SD-Karte wird der Bind-Mount des DHCP-Skripts bereits im Schritt "~7 s" ausgefuehrt, also vor dem ersten Lease. Diese Variante ist standardmaessig aus und auf der Kamera noch nicht per Kaltstart bestaetigt.

---

## 2. PTZ-Architektur und Steuerungssemantik

### 2.1 Hardware-Treiber und Motoren
- **Treiber:** `/dev/ak-motor0` (Pan / horizontal), `/dev/ak-motor1` (Tilt / vertikal).
- **Motoren:** Schrittmotoren, vermutlich vom Typ 28BYJ-48 (5V, 4 Phasen); der Typ ist nicht am Geraet verifiziert.
- **Feedback:** Nach dem Treiber-Code keine Hardware-Endschalter und keine Hall-Pins (`PTZ_FEEDBACK_PIN_NONE = 0`). Das passt zur Beobachtung, dass die Blickrichtung nach einem Kaltstart nicht reproduzierbar ist.

### 2.2 Problem der absoluten Koordinaten
1. Nach einem Kaltstart setzt `ptz_daemon` interne Software-Zaehler auf `0`, unabhaengig von der tatsaechlichen Ausrichtung der Kamera.
2. Beobachtung: Am Ende des Startvorgangs zeigt die Kamera in eine nicht reproduzierbare Richtung. Vermutete Ursache (nicht bewiesen): Der Werks-Start fuehrt eine unvollstaendige Referenzfahrt durch, bei der nur Tilt gegen einen Anschlag faehrt und Pan unreferenziert bleibt.
3. Folgerung: `ptz.ini` (Zaehlerstand, wird am Ende jeder Fahrt gespeichert) und die tatsaechliche Blickrichtung stimmen nach einem Neustart nicht sicher ueberein. Absolute Koordinaten waeren daher irrefuehrend, und die Soft-Limits sind ein Richtwert relativ zu einem unbekannten Startpunkt, kein exakter Anschlagschutz.
4. Aus demselben Grund gibt es keine Home-/`init`-Fahrt: Sie haette keinen definierten Zielzustand.

### 2.3 Loesung: Rein relative Steuerung
- Die Benutzeroberflaeche und die API operieren ausschliesslich relativ zur aktuellen Blickrichtung:
  - $\Delta\text{pan} \in [-180, +180]$ (groesser = rechts, kleiner = links).
  - $\Delta\text{tilt} \in [-60, +60]$ (groesser = runter, kleiner = hoch).
  - Die Drehrichtungen sind an der Kamera belegt (27.10.2026, Bedienung ueber die WebUI mit Kontrolle im Video): "rechts"/"links" und "hoch"/"runter" der Oberflaeche entsprechen der tatsaechlichen Bewegung. Die Angaben zu Einheit und Geschwindigkeit unten wurden dabei nicht erneut gemessen.
- `api.cgi` fuehrt die Berechnung aus:
  $$\text{Ziel-Pan} = \text{Ist-Pan} + \Delta\text{pan}, \quad \text{Ziel-Tilt} = \text{Ist-Tilt} + \Delta\text{tilt}$$
- Zielwerte werden an den Software-Grenzen geklemmt (bezogen auf den `ptz.ini`-Zaehlerstand, siehe 2.2):
  - Pan: $15 \dots 335$ (Mitte: 175).
  - Tilt: $15 \dots 110$ (Bereich: 95 Einheiten).
- **Einheit:** 1 Rohwert entspricht nach Bildmessung des Projektautors etwa $1{,}0^\circ$ physischer Drehung.
- **Drehgeschwindigkeit:** $\sim 25^\circ/\text{s}$.
- **Fahrtdauer-Formel:**
  $$T_{\text{busy}} = 1000\,\text{ms} + \frac{\max(|\Delta\text{pan}|, |\Delta\text{tilt}|) \times 1000}{25}$$

### 2.4 Einzelschritte (Pfeiltasten)
`up`, `down`, `left`, `right` werden unveraendert an den Daemon weitergegeben (1 Schritt = 10 Rohwerte). Sie laufen durch dieselbe Sperre (Busy-Datei), werden aber nicht an den Soft-Limits geklemmt; eine offene Zielvorgabe (`ptz_expect`) wird dabei verworfen.

### 2.5 Pruefung des PTZ-Daemons
`api.cgi` meldet den PTZ-Dienst nur als bereit, wenn der FIFO existiert **und** ein Prozess mit dem Namen `ptz_daemon` laeuft (Lesen von `/proc/<pid>/stat`, ohne Fork). Ein verwaister FIFO nach einem Absturz des Daemons wuerde sonst Befehle annehmen, die niemand ausfuehrt.

### 2.6 Baseline-Race-Schutz (`ptz_expect`)
Da der C++-Daemon `ptz_daemon` die Datei `/etc/jffs2/ptz.ini` asynchron nach Beginn des Fahrbefehls aktualisiert, speichert `api.cgi` die erwartete Zielposition in `/tmp/ptz_expect`:
- Beim naechsten Aufruf wird geprueft: Entspricht `ptz.ini` der Erwartung, gilt die Fahrt als beendet.
- Weicht `ptz.ini` ab und das Zeitfenster plus $3\,\text{s}$ Reserve ist noch nicht verstrichen, wird die Anfrage mit `err: "busy"` abgewiesen.
- Nach Ablauf der Reservezeit wird `ptz.ini` als neuer Ist-Zustand uebernommen.

---

## 3. Netzwerk- und Isolations-Architektur

### 3.1 Isolationsstufen pro Boot-Zustand

| Boot-Zustand | Default-Gateway | DNS-Server | Cloud-Kontakt |
| :--- | :--- | :--- | :--- |
| **0 s bis WLAN-IP (~35 s)** | Aktiv (vom Router vergeben) | Aktiv (vom Router vergeben) | Zeitfenster fuer Cloud-Verbindungen von `anyka_ipc`. |
| **Ab ~35 s (start_webui.sh)** | Geloescht (`route del default`) | Geleert (`# LAN-ONLY MODE`) | Unterbunden (`Network is unreachable`). |
| **Dauerbetrieb (Steady-State)** | Geloescht (ueberdecktes DHCP-Skript + 60s-Guard) | Geleert | Unterbunden. |
| **Notbremse (DISABLE_WEBUI)** | Aktiv (Werkszustand) | Aktiv (Werkszustand) | Cloud aktiv (Originalzustand). |

### 3.2 Vergleich DHCP-Skripte: Werksskript vs. `udhcpc_lanonly.sh`

| Eigenschaft | Original (`/usr/share/udhcpc/default.script`) | Dieses Projekt (`bin/udhcpc_lanonly.sh`) |
| :--- | :--- | :--- |
| **Default-Route** | Traegt Default-Gateway aus DHCP-Option 3 ein. | Entfernt Default-Gateway aktiv via `route del default`. |
| **DNS-Server** | Schreibt Router-DNS plus 8 feste chinesische DNS-Server (`47.89.253.148` etc.) nach `/etc/jffs2/resolv.conf`. | Schreibt nur `# LAN-ONLY MODE` nach `/etc/resolv.conf` und `/etc/jffs2/resolv.conf` (nur bei Aenderung). |
| **Flash-Schonung** | Schreibt bei jedem Renewal unkonditioniert in JFFS2. | Prueft vorherigen Inhalt; schreibt nur bei Abweichung. |
| **`deconfig`** | Setzt `ifconfig wlan0 0.0.0.0` (reisst Telnet und HTTP ab). | Bewusst No-Op; erhaelt bestehende IP-Konfiguration. |
| **`leasefail`/`nak`** | Setzt `0.0.0.0` oder beendet Interface. | Bewusst No-Op; verhindert Verbindungsabbrueche im LAN. |
| **Statische Routen** | Keine Unterstuetzung fuer lokale Subnetze ohne Gateway. | Unterstuetzt `/tmp/udhcpc_lanonly.conf` fuer getrennte IoT-Subnetze. |

---

## 4. Hardware- und Ressourcen-Einschraenkungen

- **CPU:** ARM926EJ-S @ ~400 MHz (`armv5tejl`), Single-Core, keine Hardware-FPU (Soft-Float).
- **C-Library:** `uClibc 0.9.33.2` (keine Kompatibilitaet zu glibc/musl-Binaries).
- **RAM:** 64 MB physisch, wovon ca. 25–28 MB fuer den Video-ISP reserviert sind. Im laufenden Betrieb verbleiben ca. 10–15 MB freier Arbeitsspeicher.
- **tmpfs:** `/tmp` liegt im RAM. Alle Logdateien muessen in Groesse und Frequenz strikt begrenzt sein, um Out-Of-Memory-Kernel-Panics zu vermeiden.
- **IPv6:** Kernel 3.4.35 enthaelt keine IPv6-Unterstuetzung (`/proc/net/if_inet6` existiert nicht).
