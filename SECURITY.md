# Sicherheitshinweise

## 1. Einsatzbereich und Vertrauensnetz

Dieses Projekt wurde fuer den Betrieb in isolierten, vertrauenswuerdigen lokalen Netzwerken (z. B. separates IoT-VLAN) entwickelt.

- **Keine Authentifizierung:** Die integrierten Dienste (Telnet, FTP, RTSP und HTTP) laufen standardmaessig ohne Passwortschutz.
- **Keine Portfreigaben:** Das Geraet darf unter keinen Umstaenden per Port-Forwarding direkt aus dem Internet zugaenglich gemacht werden.
- **Zusaetzliche Absicherung:** Es wird empfohlen, im Router (z. B. AVM FRITZ!Box) das Zugangsprofil der Kamera auf "Gesperrt" (kein Internetzugang) zu setzen.

---

## 2. Meldung von Sicherheitsluecken

Sicherheitsrelevante Schwachstellen koennen direkt ueber GitHub Issues oder per E-Mail an den Repository-Maintainer gemeldet werden.
