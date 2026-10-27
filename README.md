# anyka-webui

[![CI](https://github.com/JackBeauregard666/anyka-webui/actions/workflows/ci.yml/badge.svg)](https://github.com/JackBeauregard666/anyka-webui/actions/workflows/ci.yml)

WebUI und Steuerung fuer Anyka AK3918 IP-Dome-Kameras mit relativer PTZ-Ausrichtung, nativer RTSP-Bereitstellung und lokaler Netzwerk-Isolation.

A lightweight web interface and control suite for Anyka AK3918 dome IP cameras.
It provides relative PTZ movement via browser, native RTSP streaming links, and network routing isolation without cloud dependencies.

---

## 1. Was das Projekt tut und was nicht

### Das Projekt bietet:
- **Relative PTZ-Steuerung:** Bedienung ueber einen visuellen Kreis in der Weboberflaeche und per HTTP-POST-API. Drehungen erfolgen relativ zur aktuellen Ausrichtung ("um X Grad nach links/rechts/oben/unten"). Die Drehrichtungen der Oberflaeche sind an der Kamera geprueft und stimmen mit der tatsaechlichen Bewegung ueberein.
- **RTSP-Streaming-Adressen:** Anzeige der RTSP-URLs fuer Haupt- und Substream zur Einbindung in externe Player (z. B. VLC) oder Smart-Home-Systeme (z. B. Home Assistant), inklusive M3U-Download.
- **LAN-Isolation:** Automatisches Entfernen des Standard-Gateways und Leeren der DNS-Konfiguration nach dem Systemstart, um ausgehende WAN- und Cloud-Verbindungen auf Netzwerkebene zu unterbinden.
- **Systemstatus:** Abfrage von Uptime, freiem Arbeitsspeicher, WLAN-Signalstaerke und Prozesszustaenden.

### Das Projekt bietet bewusst nicht:
- **Kein Livebild im Webbrowser:** Das Abgreifen von Einzelbildern (`snap.jpg`) ueber HTTP fuehrte zu Instabilitaeten und Speicherengpaessen und wurde vollstaendig entfernt. Die Videoanzeige erfolgt ausschliesslich ueber externe RTSP-Clients.
- **Keine absolute Positionierung:** Die Schrittmotoren der Kamera besitzen keine Rueckmeldekontakte. Nach einem Neustart ist die physische Blickrichtung zufaellig. Es gibt keine Kalibrierung auf absolute Raumkoordinaten.
- **Kein erweiterter Drehbereich:** Der Bewegungsbereich ist durch Software-Grenzen und mechanische Anschlaege begrenzt. Die Software-Grenzen beziehen sich auf die in `ptz.ini` gespeicherten Zaehlerwerte; nach einem Neustart stimmen diese nicht sicher mit der tatsaechlichen Blickrichtung ueberein. Sie sind deshalb ein Richtwert, kein exakter Anschlagschutz.
- **Keine Home- oder Referenzfahrt:** Eine Fahrt zu einer "gespeicherten Position" gibt es nicht, weil die Blickrichtung nach dem Start nicht reproduzierbar ist.

---

## 2. Funktionen

- Relativer Drehkreis (12 Uhr entspricht der aktuellen Ausrichtung) mit Touch- und Mausbedienung.
- Schnelltasten fuer Pan (15, 45, 90, 180 Grad links/rechts) und Tilt (15, 30 Grad hoch/runter).
- Feinjustierung ueber Einzelschritt-Tasten (jeweils 10 Einheiten).
- Opt-in Tastatursteuerung ueber Pfeiltasten (standardmaessig deaktiviert).
- Atomare Bewegungssperre waehrend laufender Motorfahrten (Abweisung paralleler Befehle mit Restzeitanzeige).
- Erkennung und Anzeige von Begrenzungen (Soft-Limits) bei Ueberschreitung des zulaessigen Fahrbereichs.
- Schalten der weissen LED ueber die Weboberflaeche und per API.
- HTTP-API mit Pflicht zur POST-Methode, Referer-Pruefung und Content-Type-Pruefung gegen unberechtigte Aufrufe.

---

## 3. Getestete Hardware und Umgebung

Die Tests und Messungen wurden auf folgendem Geraet durchgefuehrt:

| Parameter | Gemessener Wert / Identifikation |
| :--- | :--- |
| **Kamera-Modell** | Anyka-Dome-IP-Kamera mit PTZ (Hersteller und Modellbezeichnung unbekannt) |
| **SoC** | Anyka AK3918EN080 V200 (ARM926EJ-S @ 400 MHz, Soft-Float) |
| **Sensor-Treiber** | `sensor_gc1054.ko` (GalaxyCore GC1054), `akcamera.ko` |
| **WLAN-Treiber** | `rtl8188fu.ko` (Realtek RTL8188FU USB) |
| **Kernel / C-Library**| Linux 3.4.35 / uClibc 0.9.33.2 |
| **Upstream-Basis** | [MuhammedKalkan/Anyka-Camera-Firmware](https://github.com/MuhammedKalkan/Anyka-Camera-Firmware), Commit `823cb55` |
| **Testdatum** | 26. Oktober 2026 |

*Andere Hardware-Revisionen, Sensoren oder WLAN-Chipsaetze sind ungetestet.*

---

## 4. Messwerte

Die folgenden Werte wurden am 26. Oktober 2026 auf dem Testsystem erhoben:

### Video-Streams (gemessen per ffprobe ueber RTSP Port 554)
- **Hauptstream (`/vs0`):** Auflosung 1280x720 Pixel (720p), 25,0 FPS, Codec H.264.
- **Substream (`/vs1`):** Auflosung 640x480 Pixel (VGA), 25,0 FPS, Codec H.264.

### Arbeitsspeicher (gemessen per status-API / /proc/meminfo)
- **Verfuegbarer RAM:** 23,1 MB bis 24,5 MB (aus MemFree + Buffers + Cached - Shmem, von 64 MB physischem RAM abzg. ISP-Reservierung).

### API-Antwortzeiten (20 aufeinanderfolgende Abfragen ueber WLAN)
- `GET /cgi-bin/api.cgi?action=status`:
  - Minimum: 200,2 ms
  - Median: 232,2 ms
  - Durchschnitt: 257,0 ms
  - 95. Perzentil (p95): 425,8 ms
- `POST /cgi-bin/api.cgi?action=turn&dpan=10&dry=1`:
  - Minimum: 82,8 ms
  - Median: 101,2 ms
  - Durchschnitt: 106,3 ms
  - 95. Perzentil (p95): 149,3 ms

### Systemstart (gemessen an /mnt/anyka_webui/boot.log)
- `0 s`: Kernel-Initialisierung
- `7 s`: Start von `start_webui.sh`, Web-Verzeichnis nach `/tmp/www` gespiegelt
- `35 s`: WLAN-Verbindung steht (IP-Zuweisung abgeschlossen)
- `35 s`: Default-Gateway geloescht, DNS geleert, LAN-only aktiv
- `35 s`: `ptz_daemon` und `httpd` gestartet
- `37 s`: `rtsp_supervisor.sh` beendet `anyka_ipc` und startet RTSP-Daemon

### Drehgeschwindigkeit der Motoren
- **Pan / Tilt:** ca. 25 Grad pro Sekunde (1 Rohwert entspricht ca. 1,0 Grad physikalischer Drehung).

---

## 5. Voraussetzungen und Schnellstart

Ausfuehrliche Schritte, Pruefsummen und Vorlagen sind in [docs/INSTALLATION.md](docs/INSTALLATION.md) dokumentiert.

1. MicroSD-Karte mit FAT32 formatieren.
2. Das Verzeichnis `anyka_webui` auf die SD-Karte kopieren.
3. Die Binaries `busybox`, `ptz_daemon`, `rtsp` und `lib/` in den Ordner `custom/` auf der SD-Karte ablegen.
4. Den Boot-Hook in `/etc/jffs2/time_zone.sh` auf der Kamera ergaenzen (siehe Installationsanleitung).
5. Kamera mit gesteckter SD-Karte neu starten und Weboberflaeche unter `http://<KAMERA_IP>/` aufrufen.

---

## 6. Sicherheit und Netzwerk

Die Netzwerk-Isolation basiert auf technischem Routing und stellt keine absolute Sicherheitsgarantie dar:

1. **Zeitfenster beim Systemstart:** Waehrend der ersten ca. 35 Sekunden nach dem Einschalten laeuft der Werks-Daemon `anyka_ipc` mit aktiver Internetverbindung und gueltigem Standard-Gateway, um die WLAN-Verbindung herzustellen. Erst nach Zuweisung der IP-Adresse entfernt `start_webui.sh` die Standard-Route. Optional kann dieses Fenster verkleinert werden: Mit einer Datei `EARLY_ISOLATION` im Wurzelverzeichnis der SD-Karte wird das DHCP-Skript schon vor dem ersten Lease ersetzt. Das ist **standardmaessig aus** und noch nicht durch einen Kaltstart auf der Kamera bestaetigt (Pruefschritte in [docs/INSTALLATION.md](docs/INSTALLATION.md)). Ob es das Fenster in der Praxis schliesst, zeigt die Zeile `Default-Route vor der Isolation` in `boot.log`.
2. **Fehlende Authentifizierung:** Die auf der Kamera laufenden Dienste (Telnet mit Root-Shell, FTP, RTSP und der Webserver) besitzen standardmaessig keinen Kennwortschutz.
3. **Keine Portweiterleitung:** Die Kamera darf unter keinen Umstaenden per Port-Forwarding aus dem Internet erreichbar gemacht werden. Sie gehoert in ein dediziertes, isoliertes Netzwerksegment (z. B. IoT-VLAN).
4. **Empfohlene Routersperre:** Es wird dringend empfohlen, dem Geraet im heimischen Router (z. B. AVM FRITZ!Box ueber das Zugangsprofil "Gesperrt") saemtliche Internetverbindungen zusaetzlich auf Infrastrukturebene zu sperren.
5. **Zugriffsschutz der WebUI:** Die API verlangt POST, `Content-Type: application/json`, einen passenden `Referer` und (falls vom Webserver durchgereicht) einen passenden `Origin`. Das schuetzt vor einfachen Fremdseiten-Anfragen (CSRF), aber nicht vor DNS-Rebinding und ersetzt keine Anmeldung; wer im selben Netz ist, kann die Kamera steuern. Siehe [SECURITY.md](SECURITY.md).
6. **IPv6:** Auf dem getesteten Kernel 3.4.35 ist kein IPv6-Stack aktiv (`/proc/net/if_inet6` existiert nicht). Es koennen keine IPv6-Verbindungen aufgebaut werden.
7. **Notbremse:** Befindet sich auf der SD-Karte die Datei `DISABLE_WEBUI` oder fehlt die Karte beim Booten, startet die Kamera im regulaeren Werkszustand mit voller Cloud-Anbindung.

Weitere Hinweise sind in [SECURITY.md](SECURITY.md) hinterlegt.

---

## 7. Rollback und Notbremse

- **Temporaere Deaktivierung:** Datei `DISABLE_WEBUI` im Wurzelverzeichnis der SD-Karte anlegen und Kamera neu starten.
- **Nur `EARLY_ISOLATION` abschalten:** Datei `EARLY_ISOLATION` von der SD-Karte loeschen; alles andere bleibt unveraendert.
- **Rueckkehr zum Werkszustand:** SD-Karte entnehmen oder den Aufruf von `start_webui.sh` aus `/etc/jffs2/time_zone.sh` entfernen.
- Detaillierte Schritte zur vollstaendigen Deinstallation siehe [docs/INSTALLATION.md](docs/INSTALLATION.md).

---

## 8. Fehlersuche

- **WebUI reagiert nicht:** Pruefen, ob die Kamera anpingbar ist. Inhalt von `/mnt/anyka_webui/boot.log` pruefen.
- **RTSP-Stream nicht erreichbar:** Inhalt von `/mnt/anyka_webui/rtsp_supervisor.log` und `/tmp/rtsp.log` pruefen. Pruefen, ob Port 554 lauscht (`netstat -l` oder `/proc/net/tcp`).
- **Kamera dreht sich nicht:** Status abfragen (`curl -s http://<KAMERA_IP>/cgi-bin/api.cgi?action=status`). Das Feld `ptz_ready` ist nur `1`, wenn der Prozess `ptz_daemon` laeuft **und** der FIFO `/tmp/ptz.daemon` existiert. Bei `0` die Dateien `/tmp/ptz.log` und `boot.log` pruefen.
- **Boot-Zeitfenster pruefen:** In `boot.log` steht die Zeile `Default-Route vor der Isolation: JA/NEIN`. `JA` bedeutet, dass die Kamera vor der Isolation kurzzeitig eine Internetroute hatte (siehe Abschnitt 6).

---

## 9. Entwicklung und Tests

- **Steuerungs-CLI:** `tools/cam_ctl.py` ermoeglicht Befehlsausfuehrung und Dateiuebertragung per Telnet/FTP ohne externe Abhaengigkeiten.
- **SD-Build:** `tools/build_sd.sh` erstellt ein sauberes SD-Kartenverzeichnis mit LF-Zeilenenden und SHA-256-Pruefsummen.
- **Lokale Tests (Host, ohne Kamera):**
  - `tests/test_api.sh`: 23 Tests gegen `api.cgi` (POST-Pflicht, Validierung, Grenzwerte, Referer/Origin, Content-Type, Race-Schutz, PTZ-Prozesspruefung, LED).
  - `tests/test_start_webui.sh`: 7 Tests fuer `start_webui.sh` mit Attrappen fuer `ifconfig`, `route`, `mount` (Isolation, Notbremse, Singleton, `EARLY_ISOLATION`).
  - `tests/test_supervisor.sh`: 5 Tests fuer `rtsp_supervisor.sh` (Start, Einzelinstanz, sauberes Beenden, Health-Check mit Neustart, keine verwaisten Prozesse).
- **CI:** GitHub Actions prueft Syntax (`dash -n`), ShellCheck, JavaScript (`node --check`), Python (`py_compile`) und fuehrt alle drei Test-Suites aus.
- **Grenzen der Tests:** Die Tests laufen auf dem Entwicklungsrechner mit `dash`. Das Verhalten auf der Kamera (BusyBox `ash`, uClibc, echte Motoren, WLAN-Boot) pruefen sie nicht; dafuer gibt es die Checkliste in [docs/INSTALLATION.md](docs/INSTALLATION.md).

---

## 10. Lizenzen und Danksagung

### Danksagung an Upstream-Projekte
- **[MuhammedKalkan/Anyka-Camera-Firmware](https://github.com/MuhammedKalkan/Anyka-Camera-Firmware):** Basis fuer SD-Karten-Methode, `rtsp`-Daemon, `ptz_daemon` und Treiber-Bibliotheken (das Repository steht unter der MIT-Lizenz; fuer die enthaltenen Binaries und Herstellerbibliotheken gibt es keine eigene Lizenzangabe). Diese Binaries sind **nicht** Teil dieses Repositories.
- **[ricardojlrufino/anyka_v380ipcam_experiments](https://github.com/ricardojlrufino/anyka_v380ipcam_experiments):** Analyse und Skripte fuer Anyka V380 / AK3918 Kameras. Das Repository nennt keine Lizenz; es wird hier nur als Quelle genannt, Code daraus ist nicht uebernommen.
- **[VGerris/Anyka_ak3918_hacking_journey](https://github.com/VGerris/Anyka_ak3918_hacking_journey):** Dokumentation der Hardware-Register und Speicherstrukturen (lizenziert unter der GNU General Public License v3.0). Es wird nur als Quelle genannt, Code daraus ist nicht uebernommen.

### Eigene Lizenz
Der Code dieses Projekts ist unter der [MIT-Lizenz](LICENSE) veroeffentlicht.

### Haftungsausschluss
Die Modifikation von IP-Kameras erfolgt ausschliesslich auf eigene Gefahr. Das Ausfuehren von Drittanbieter-Skripten und Eingriffen in die Boot-Dateien kann zum Verlust von Herstellergarantien oder zur Beschaedigung des Geraets fuehren.
