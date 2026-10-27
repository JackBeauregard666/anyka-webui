# HTTP REST API Dokumentation

Das CGI-Interface laeuft unter `/cgi-bin/api.cgi` ueber BusyBox `httpd` (Port 80).

---

## 1. Sicherheits- und Validierungsregeln

- **HTTP-Methoden:** Ausnahmslos alle mutierenden Aktionen (auch `dry=1`) erfordern `POST`. Nur `action=status` ist per `GET` zulaessig.
- **Referer-Pflicht:** Mutierende Anfragen muessen einen `Referer`-Header besitzen, der mit `http://<HOST>/` **beginnt** (Praefix-Vergleich; `<HOST>` ist der `Host`-Header der Anfrage). Fehlende, leere oder abweichende Referer (auch solche, die den Host nur irgendwo enthalten) werden mit `bad_referer` abgewiesen.
- **Origin-Pruefung:** Wird vom Webserver ein `Origin`-Header an das CGI durchgereicht (`HTTP_ORIGIN`), muss er exakt `http://<HOST>` lauten, sonst `bad_origin`. Der BusyBox-`httpd` reicht diesen Header moeglicherweise nicht durch; dann greifen Referer und Content-Type.
- **Grenzen:** Das ist ein CSRF-Schutz, keine Authentifizierung. Gegen DNS-Rebinding hilft er nicht (der Angreifer steuert dort den `Host`-Header selbst).
- **Content-Type-Pflicht:** Mutierende Anfragen muessen den Header `Content-Type: application/json` senden. Andere Typen werden mit `bad_content_type` abgewiesen.
- **Aktionen:** Nur `status`, `turn`, `up`, `down`, `left`, `right`, `light_on`, `light_off`. Alles andere ergibt `invalid_action`. Eine Home-/Kalibrierfahrt gibt es nicht.
- **Zahlenvalidierung:** Winkelwerte werden strikt geprueft (Vorzeichen `+` oder `-`, maximal 4 Zeichen, fuehrende Nullen werden ohne Oktal-Interpretation normalisiert).

---

## 2. Endpunkte

### 2.1 Systemstatus abfragen
`GET /cgi-bin/api.cgi?action=status`

**Beispielaufruf:**
```bash
curl -s "http://<KAMERA_IP>/cgi-bin/api.cgi?action=status"
```

**Erfolgsantwort (JSON):**
```json
{
  "ok": true,
  "uptime_s": 3413,
  "avail_kb": 24672,
  "lan_isolated": true,
  "wifi_link": "83",
  "wifi_dbm": "54",
  "ptz_ready": 1,
  "rtsp_ready": 1,
  "busy": false,
  "busy_remaining_s": 0,
  "ptz_valid": true,
  "led_on": 0,
  "debug_pan": 270,
  "debug_tilt": 25
}
```

`ptz_ready` ist `1`, wenn der FIFO `/tmp/ptz.daemon` existiert und ein Prozess `ptz_daemon` laeuft, sonst `0`.

*Hinweis zu `debug_pan` und `debug_tilt`: Diese Felder dienen ausschliesslich Diagnosezwecken. Sie stellen keine verlaesslichen absoluten Koordinaten dar.*

---

### 2.2 Relatives Fahren (`turn`)
`POST /cgi-bin/api.cgi?action=turn&dpan=<delta>&dtilt=<delta>[&dry=1]`

**Parameter:**
- `dpan`: Ganzzahl zwischen `-180` und `+180` (groesser = rechts, kleiner = links).
- `dtilt`: Ganzzahl zwischen `-60` und `+60` (groesser = runter, kleiner = hoch).
- `dry`: Optional `1`. Fuehrt die Berechnung ohne Motorenbewegung und ohne Sperre aus.

**Beispielaufruf (Drehung um 45 Grad nach rechts):**
```bash
curl -s -X POST \
  -H "Content-Type: application/json" \
  -e "http://<KAMERA_IP>/" \
  "http://<KAMERA_IP>/cgi-bin/api.cgi?action=turn&dpan=45&dtilt=0"
```

**Erfolgsantwort:**
```json
{
  "ok": true,
  "requested": { "dpan": 45, "dtilt": 0 },
  "executed": { "dpan": 45, "dtilt": 0 },
  "clamped": false,
  "busy_ms": 2800
}
```

**Antwort bei Klemmung an den Soft-Limits ($15^\circ..335^\circ$ Pan, $15^\circ..110^\circ$ Tilt):**
```json
{
  "ok": true,
  "requested": { "dpan": 90, "dtilt": 0 },
  "executed": { "dpan": 65, "dtilt": 0 },
  "clamped": true,
  "busy_ms": 3600
}
```

---

### 2.3 Einzelschritt-Fahrt (Pfeiltasten)
`POST /cgi-bin/api.cgi?action=up|down|left|right`

Fuehrt einen einzelnen relativen Schritt von $10$ Rohwerten in der angegebenen Richtung aus. Der Befehl geht unveraendert an den PTZ-Daemon und wird, anders als `turn`, nicht an den Soft-Limits geklemmt. Waehrend einer laufenden Fahrt wird er mit `busy` abgewiesen.

**Beispielaufruf:**
```bash
curl -s -X POST \
  -H "Content-Type: application/json" \
  -e "http://<KAMERA_IP>/" \
  "http://<KAMERA_IP>/cgi-bin/api.cgi?action=left"
```

---

### 2.4 Beleuchtung (LED)
- Einschalten: `POST /cgi-bin/api.cgi?action=light_on`
- Ausschalten: `POST /cgi-bin/api.cgi?action=light_off`

---

## 3. Fehlercodes

| Fehlercode (`err`) | Ursache |
| :--- | :--- |
| `post_required` | Die Anfrage wurde mit `GET` statt `POST` gesendet. |
| `bad_referer` | Der `Referer`-Header fehlt oder stimmt nicht mit dem Host ueberein. |
| `bad_origin` | Ein durchgereichter `Origin`-Header passt nicht zum Host. |
| `bad_content_type` | Der `Content-Type`-Header ist nicht `application/json`. |
| `invalid_action` | Unbekannte oder fehlende Aktion (auch die entfernte Aktion `calibrate`). |
| `missing_params` | Bei `turn` fehlen sowohl `dpan` als auch `dtilt`. |
| `busy` | Eine andere Fahrt laeuft noch. Das Feld `busy_remaining_s` nennt die Wartezeit. |
| `invalid_dpan` | Der Wert von `dpan` ist ungueltig (keine Zahl oder Laenge > 4). |
| `invalid_dtilt` | Der Wert von `dtilt` ist ungueltig (keine Zahl oder Laenge > 4). |
| `ptz_invalid` | Die Koordinatendatei `ptz.ini` fehlt oder ist beschaedigt. |
| `ptz_daemon_not_running` | Die FIFO-Datei `/tmp/ptz.daemon` fehlt oder der Prozess `ptz_daemon` laeuft nicht. |
| `ptz_fifo_open_failed` | Der FIFO konnte nicht zum Schreiben geoeffnet werden. |
