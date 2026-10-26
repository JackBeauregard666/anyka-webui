# Sicherheitshinweise

## 1. Einsatzbereich und Vertrauensnetz

Dieses Projekt wurde fuer den Betrieb in isolierten, vertrauenswuerdigen lokalen Netzwerken (z. B. separates IoT-VLAN) entwickelt.

- **Keine Authentifizierung:** Die integrierten Dienste (Telnet mit Root-Shell, FTP, RTSP und HTTP) laufen standardmaessig ohne Passwortschutz. Wer im selben Netz ist, kann die Kamera steuern, den Stream ansehen und Dateien auf der Kamera aendern.
- **Keine Portfreigaben:** Das Geraet darf unter keinen Umstaenden per Port-Forwarding direkt aus dem Internet zugaenglich gemacht werden.
- **Zusaetzliche Absicherung:** Es wird empfohlen, im Router (z. B. AVM FRITZ!Box) das Zugangsprofil der Kamera auf "Gesperrt" (kein Internetzugang) zu setzen. Die Isolation auf der Kamera ist eine Softwaremassnahme und ersetzt diese Sperre nicht.

---

## 2. Grenzen der LAN-Isolation

- **Boot-Zeitfenster:** Waehrend der ersten ca. 35 Sekunden nach dem Einschalten besitzt die Kamera die vom Router vergebene Default-Route. Die Isolation greift erst, wenn `start_webui.sh` die Route entfernt. `boot.log` protokolliert mit `Default-Route vor der Isolation: JA/NEIN`, ob dieses Fenster bestand. Die optionale Datei `EARLY_ISOLATION` (siehe [docs/INSTALLATION.md](docs/INSTALLATION.md)) soll es schliessen, ist aber standardmaessig aus und noch nicht per Kaltstart bestaetigt.
- **Werkszustand bei Ausfall:** Fehlt die SD-Karte oder liegt `DISABLE_WEBUI` darauf, laeuft die Kamera im Werkszustand inklusive Cloud-Anbindung.
- **Nur IPv4:** Die Isolation prueft und entfernt IPv4-Default-Routen. Der getestete Kernel 3.4.35 hat keinen IPv6-Stack; bei anderer Firmware muss das neu bewertet werden.

---

## 3. Grenzen des Zugriffsschutzes der WebUI

Die API (`api.cgi`) verlangt fuer alle Aktionen ausser `status` die Methode POST, `Content-Type: application/json` und einen `Referer`, der mit `http://<Host>/` beginnt; ein durchgereichter `Origin`-Header muss `http://<Host>` sein. Das verhindert, dass eine fremde Webseite im Browser eines Nutzers unbemerkt Befehle ausloest (CSRF).

Das ist **keine Anmeldung**:

- **DNS-Rebinding:** Eine boesartige Webseite, die ihren Hostnamen auf die Kamera-IP umlenkt, steuert den `Host`-Header selbst und besteht die Pruefung. Moegliche Auswirkung: PTZ und LED der Kamera bedienen. Abhilfe waere eine Host-Allowlist oder eine Anmeldung; beides ist nicht umgesetzt.
- **`GET ?action=status`** ist ohne Pruefung lesbar (Uptime, freier RAM, WLAN-Signal, interne PTZ-Zaehlerwerte).
- Die API stellt keine Kommandoausfuehrung bereit: Parameter werden strikt als Zahlen validiert, Aktionen stehen auf einer festen Liste.

---

## 4. Meldung von Sicherheitsluecken

Sicherheitsrelevante Schwachstellen koennen direkt ueber GitHub Issues oder per E-Mail an den Repository-Maintainer gemeldet werden.
