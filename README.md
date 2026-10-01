# Meeting-KI 🎙️🤖

Ein **ESP32-S3** mit **INMP441-Mikrofon**, das Meetings mithört, den Ton an einen
kleinen Python-Server streamt, dort automatisch transkribiert und am Ende mit
**Claude** eine Zusammenfassung schreibt.

> **Hinweis zur Hardware:** In der ursprünglichen Anfrage war von einem „INA441"
> die Rede. Der INA441 ist ein Verstärker-IC von Texas Instruments und **kein
> Mikrofon**. Für ESP32-Projekte ist das gängige I2S-MEMS-Mikrofon das
> **INMP441**. Dieses Projekt ist für das INMP441 ausgelegt. Wenn du wirklich ein
> anderes Mikrofon verwendest, sag Bescheid – die Firmware muss dann angepasst
> werden.

---

## Wie es funktioniert

```
┌──────────────┐   I2S    ┌───────────────┐   WLAN / TCP   ┌────────────────────────┐
│   INMP441    │ ───────► │   ESP32-S3    │ ─────────────► │      Python-Server      │
│  (Mikrofon)  │          │  (Firmware)   │   16 kHz PCM   │                        │
└──────────────┘          └───────────────┘                │  1. Audio → WAV        │
                                                            │  2. Whisper → Text     │
                                                            │  3. Claude → Zusammen- │
                                                            │     fassung (.md)      │
                                                            └────────────────────────┘
```

1. Das **INMP441** liefert digitales Audio über I2S an den **ESP32-S3**.
2. Die **Firmware** verbindet sich mit dem WLAN. Über zwei **Knöpfe am ESP32**
   startest/stoppst du die Aufnahme; während der Aufnahme wird
   16-kHz-Mono-PCM per TCP an den Server gestreamt.
3. Der **Server** puffert den Ton. Start/Stop kommen als kleine Steuer-Signale
   vom ESP32 (ersatzweise auch per Tastatur im Server-Fenster möglich).
4. Beim Stoppen wird das Audio als WAV gespeichert, mit **faster-whisper**
   lokal transkribiert und anschließend mit der **Anthropic-API (Claude)** zu
   einer strukturierten Zusammenfassung verarbeitet.

Transkription läuft **lokal** (Datenschutz – der Rohton verlässt dein Netz
nicht). Nur der fertige Transkript-Text geht zur Zusammenfassung an Claude.

---

## Hardware & Verkabelung

Board: **ESP32-S3 Zero** (Waveshare). Alle genutzten Signal-Pins liegen auf der
vorderen Stiftleiste (GPIO1–GPIO13); die WS2812-Status-LED ist fest onboard.

### Mikrofon (INMP441)

| INMP441 Pin | Funktion                | ESP32-S3 Zero |
|-------------|-------------------------|---------------|
| VDD         | 3,3 V                   | 3V3           |
| GND         | Masse                   | GND           |
| SCK         | I2S Bit-Clock (BCLK)    | GPIO 4        |
| WS          | I2S Word-Select (LRCLK) | GPIO 5        |
| SD          | I2S Daten (DOUT)        | GPIO 6        |
| L/R         | Kanalwahl               | GPIO 3        |

Der **L/R-Pin wird hier vom ESP32 über GPIO3 getrieben** (nicht fest an GND).
Die Firmware legt GPIO3 auf **LOW** = linker Kanal (passend zur I2S-Konfig). Wenn
du lieber fest verdrahten willst, kannst du `L/R` auch direkt an GND legen – dann
ist GPIO3 frei.

### Knöpfe (Steuerung am ESP32)

| Taster        | Funktion         | ESP32-S3 Zero |
|---------------|------------------|---------------|
| START-Taster  | Aufnahme starten | GPIO 1        |
| STOP-Taster   | Aufnahme beenden | GPIO 2        |

Jeder Taster wird zwischen den GPIO-Pin und **GND** geschaltet. Ein interner
Pullup ist aktiviert – ein externer Widerstand ist nicht nötig. Das Entprellen
passiert in der Firmware.

### Status-LED (WS2812, onboard auf GPIO21)

Die adressierbare RGB-LED des ESP32-S3 Zero zeigt den Zustand per Farbe:

| Farbe              | Bedeutung                              |
|--------------------|----------------------------------------|
| 🔴 rot blinkend    | kein WLAN                              |
| 🟠 orange blinkend | WLAN ok, aber kein Server              |
| 🟢 grün            | verbunden, wartet auf den START-Knopf  |
| 🔴 rot (dauerhaft) | Aufnahme läuft                         |

> Alle GPIO-Nummern (und Helligkeit/Farblogik) sind in `firmware/src/config.h`
> konfigurierbar. Nutzt du ein anderes Board ohne WS2812, setze
> `STATUS_LED_IS_WS2812 0` (einfache Ein/Aus-LED) oder `STATUS_LED_PIN -1` (aus).

**Wichtig:** Das INMP441 wird mit **3,3 V** betrieben, nicht mit 5 V.

---

## Teil 1 – Firmware (ESP32-S3 Zero)

Die Firmware ist ein [PlatformIO](https://platformio.org/)-Projekt (Board-Env
`esp32-s3-zero`).

```bash
cd firmware
cp src/config.h.example src/config.h   # dann config.h ausfüllen
# WLAN-Zugang und Server-IP in config.h eintragen
pio run --target upload
pio device monitor        # zum Mitlesen der seriellen Ausgabe
```

> **Flashen klappt nicht?** Der ESP32-S3 Zero lässt sich in den Download-Modus
> zwingen: **BOOT gedrückt halten**, kurz **RESET** tippen (oder USB einstecken),
> BOOT loslassen – dann erneut `pio run --target upload`.

In `src/config.h` trägst du ein:
- `WIFI_SSID` / `WIFI_PASSWORD` – dein WLAN
- `SERVER_HOST` – IP-Adresse des Rechners, auf dem der Python-Server läuft
- `SERVER_PORT` – Port (Standard `8888`)

Die Firmware verbindet sich automatisch wieder, wenn WLAN oder Server-Verbindung
abbrechen. Die Onboard-LED zeigt den Status (siehe Kommentare in `main.cpp`).

---

## Teil 2 – Server (Python)

> **Python-Version beachten:** `faster-whisper` braucht `ctranslate2`, das nur
> für **64-bit-Python 3.9–3.12** fertige Pakete hat. Mit **Python 3.13/3.14**
> oder 32-bit-Python schlägt `pip install` fehl (siehe
> [Problembehebung](#problembehebung)). Prüfen mit `python --version`.

**Windows** (PowerShell), Python von https://www.python.org/ vorausgesetzt:

```powershell
cd server
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

copy .env.example .env     # dann .env ausfüllen (ANTHROPIC_API_KEY!)
python server.py
```

> Falls PowerShell das Aktivieren blockiert („… kann nicht geladen werden …"),
> einmalig erlauben:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

**macOS / Linux:**

```bash
cd server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env       # dann .env ausfüllen (ANTHROPIC_API_KEY!)
python server.py
```

In `.env` trägst du ein:
- `ANTHROPIC_API_KEY` – dein Claude-API-Schlüssel (https://console.anthropic.com/)
- `WHISPER_MODEL` – z. B. `base`, `small`, `medium` (Standard: `small`)
- weitere Optionen siehe `.env.example`

### Bedienung

Der Server nimmt die TCP-Verbindung des ESP32 automatisch an. Gesteuert wird
normalerweise über die **Knöpfe am ESP32**:

- **START-Taster** → Aufnahme beginnt (LED wird **rot**)
- **STOP-Taster** → Aufnahme endet (LED wieder **grün**) → WAV + Transkript + Zusammenfassung

Ersatzweise geht es auch über die Tastatur im Server-Fenster:

| Taste       | Aktion                                                 |
|-------------|--------------------------------------------------------|
| `s` + Enter | Aufnahme **starten**                                   |
| `e` + Enter | Aufnahme **beenden** → WAV + Transkript + Zusammenfassung |
| `q` + Enter | Server beenden                                         |

Nach dem Stoppen entstehen:
- `recordings/meeting_<zeitstempel>.wav` – der Mitschnitt
- `summaries/meeting_<zeitstempel>.md` – Transkript **und** Zusammenfassung

### Wer spricht? (optionale Sprecher-Trennung)

Der Server kann das Transkript in **SPRECHER_1, SPRECHER_2, …** aufteilen
(sog. Diarization). Das erkennt *unterschiedliche Stimmen* – **keine Namen** –
und ist mit einem einzelnen, weiter entfernten MEMS-Mikrofon nur begrenzt
genau (Nachhall, Abstand, gleichzeitiges Sprechen).

So aktivierst du es:

```bash
pip install -r requirements-diarization.txt   # torch etc. – mehrere hundert MB
```

Dann in `.env`:
- `ENABLE_DIARIZATION=true`
- `HUGGINGFACE_TOKEN=...` – Token von https://huggingface.co/settings/tokens
- Auf huggingface.co die Nutzungsbedingungen des Modells
  **`pyannote/speaker-diarization-3.1`** akzeptieren (einmalig).

Ist alles vorhanden, erscheinen im Transkript und in der Zusammenfassung die
Sprecher-Labels. Schlägt die Trennung fehl, fällt der Server automatisch auf
ein Transkript ohne Sprecher zurück.

---

## Netzwerk: IP-Adresse & Firewall (Windows)

Der ESP32 muss die **lokale IP-Adresse** des Windows-Rechners kennen, auf dem
`server.py` läuft. Beide Geräte müssen im **selben 2,4-GHz-WLAN** sein.

### 1. Lokale IP herausfinden

Eingabeaufforderung (`cmd`) oder PowerShell öffnen und eingeben:

```powershell
ipconfig
```

Beim WLAN-Adapter („Drahtlos-LAN-Adapter WLAN") die Zeile **IPv4-Adresse**
suchen, z. B. `192.168.1.100`. Genau diese Adresse kommt in die Firmware:

```c
// firmware/src/config.h
#define SERVER_HOST  "192.168.1.100"   // deine IPv4-Adresse
#define SERVER_PORT  8888
```

> Es ist die lokale Adresse (`192.168.…` oder `10.…`) – **nicht** die
> Internet-IP von „wieistmeineip" und **nicht** `127.0.0.1`.

### 2. Firewall-Freigabe

Beim ersten `python server.py` fragt Windows meist:
„**Zugriff auf dieses Netzwerk zulassen?**" → für **private Netzwerke zulassen**.
Dann darf der ESP32 auf Port `8888` zugreifen.

Keine Abfrage erschienen oder versehentlich blockiert? Regel manuell anlegen
(PowerShell **als Administrator**):

```powershell
New-NetFirewallRule -DisplayName "Meeting-KI" -Direction Inbound `
  -Protocol TCP -LocalPort 8888 -Action Allow -Profile Private
```

### 3. IP bleibt nicht stabil? (feste IP)

Der Router vergibt IP-Adressen per DHCP – nach einem Neustart kann der Rechner
eine andere IP bekommen, und der ESP32 findet den Server nicht mehr. Abhilfe:
im Router unter **DHCP / Adressreservierung** dem Rechner (anhand seiner
MAC-Adresse, aus `ipconfig /all`) eine **feste IP** zuweisen. Danach bleibt
`SERVER_HOST` konstant.

### 4. Verbindung testen

- Server starten: Es erscheint „warte auf ESP32 an `0.0.0.0:8888`".
  (`0.0.0.0` ist Absicht – der Server lauscht auf allen Netzwerk-Schnittstellen.)
- ESP32 einschalten: LED wird **grün**, im Server-Fenster erscheint
  „ESP32 verbunden: 192.168.x.x".
- Kommt keine Verbindung: gleiches WLAN? Gast-WLAN/Client-Isolation aus?
  IP korrekt? Firewall offen?

---

## Erste Inbetriebnahme (Checkliste)

1. INMP441 wie oben verdrahten.
2. `server/.env` mit deinem `ANTHROPIC_API_KEY` befüllen und `python server.py`
   starten. Die lokale IP des Rechners notieren (`ip addr` / `ipconfig`).
3. `firmware/src/config.h` mit WLAN und dieser Server-IP befüllen und flashen.
4. Seriellen Monitor öffnen – es sollte „WiFi verbunden" und „Server verbunden"
   erscheinen. Im Server-Fenster erscheint „ESP32 verbunden", die LED wird grün.
5. **START-Taster** drücken (LED rot) → sprechen → **STOP-Taster** drücken. Die
   Zusammenfassung landet in `summaries/`.

---

## Problembehebung

### `pip install` scheitert an `ctranslate2` / `faster-whisper`

Fehlermeldung sinngemäß: *„Cannot install … faster-whisper … no matching
distributions available for your environment: ctranslate2"* bzw.
*„ResolutionImpossible"*.

**Ursache:** `faster-whisper` nutzt `ctranslate2`, und dafür gibt es nur fertige
Pakete für **64-bit-Python 3.9–3.12**. Mit **Python 3.13/3.14** oder einem
32-bit-Python findet pip kein passendes Paket.

**Prüfen:**

```powershell
python --version
python -c "import platform; print(platform.architecture()[0], platform.machine())"
```

Ist die Version `3.13`/`3.14` oder steht dort `32bit`, ist das die Ursache.

**Lösung (Windows): Python 3.12 (64-bit) nutzen**

1. Python 3.12 (64-bit) installieren von
   https://www.python.org/downloads/release/python-3129/
   (Datei „Windows installer (64-bit)"). Beim Installieren **„Add python.exe to
   PATH"** anhaken.
2. Alte venv löschen und mit 3.12 neu anlegen. Der [Python Launcher](https://docs.python.org/3/using/windows.html#python-launcher-for-windows)
   `py` wählt gezielt die Version:

   ```powershell
   cd server
   rmdir /s /q .venv            # in PowerShell: Remove-Item -Recurse -Force .venv
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python --version             # sollte 3.12.x zeigen
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

Danach installiert `faster-whisper` sauber durch.

> macOS/Linux: analog eine 3.12 anlegen, z. B. `python3.12 -m venv .venv`
> (ggf. vorher über den Paketmanager / pyenv installieren).

### ESP32 verbindet sich nicht mit dem Server

Siehe [Netzwerk: IP-Adresse & Firewall (Windows)](#netzwerk-ip-adresse--firewall-windows):
gleiches 2,4-GHz-WLAN, richtige lokale IP in `config.h`, Firewall-Port 8888 offen,
kein Gast-WLAN mit Client-Isolation.

---

## Datenschutz & rechtlicher Hinweis

Das Mitschneiden von Gesprächen und Meetings unterliegt rechtlichen Regeln
(in Deutschland u. a. § 201 StGB, DSGVO). **Informiere alle Teilnehmenden und
hole ihr Einverständnis ein, bevor du aufnimmst.** Dieses Projekt ist für den
eigenen, erlaubten Gebrauch gedacht.

---

## Projektstruktur

```
Meeting-KI/
├── firmware/                 # ESP32-S3 PlatformIO-Projekt
│   ├── platformio.ini
│   └── src/
│       ├── main.cpp          # I2S-Aufnahme + Knöpfe + WLAN + TCP-Streaming
│       └── config.h.example  # Vorlage für WLAN/Server/Pins-Konfiguration
└── server/                   # Python-Server
    ├── requirements.txt
    ├── requirements-diarization.txt  # optionale Pakete für Sprecher-Trennung
    ├── .env.example
    ├── server.py             # TCP-Empfang (Framing) + Aufnahmesteuerung
    ├── transcribe.py         # lokale Transkription (faster-whisper)
    ├── diarize.py            # optionale Sprecher-Trennung (pyannote)
    ├── summarize.py          # Zusammenfassung via Claude
    ├── recordings/           # gespeicherte WAV-Dateien
    └── summaries/            # Transkripte + Zusammenfassungen
```
