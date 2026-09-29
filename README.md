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

| INMP441 Pin | Funktion            | ESP32-S3 GPIO (Standard) |
|-------------|---------------------|--------------------------|
| VDD         | 3,3 V               | 3V3                      |
| GND         | Masse               | GND                      |
| SCK         | I2S Bit-Clock (BCLK)| GPIO 4                   |
| WS          | I2S Word-Select (LRCLK) | GPIO 5               |
| SD          | I2S Daten (DOUT)    | GPIO 6                   |
| L/R         | Kanalwahl           | GND (= linker Kanal)     |

### Knöpfe (Steuerung am ESP32)

| Taster        | Funktion              | ESP32-S3 GPIO (Standard) |
|---------------|-----------------------|--------------------------|
| START-Taster  | Aufnahme starten      | GPIO 15                  |
| STOP-Taster   | Aufnahme beenden      | GPIO 16                  |

Jeder Taster wird zwischen den GPIO-Pin und **GND** geschaltet. Ein interner
Pullup ist aktiviert – ein externer Widerstand ist nicht nötig. Ein zusätzliches
Entprellen in Hardware ist ebenfalls nicht erforderlich (passiert in der
Firmware).

> Alle GPIO-Nummern sind in `firmware/src/config.h` frei konfigurierbar. Nimm
> Pins, die auf deinem konkreten ESP32-S3-Board frei sind.

**Wichtig:** Das INMP441 wird mit **3,3 V** betrieben, nicht mit 5 V. `L/R` auf
GND legen, damit das Modul auf dem linken Kanal sendet (so ist die Firmware
konfiguriert).

---

## Teil 1 – Firmware (ESP32-S3)

Die Firmware ist ein [PlatformIO](https://platformio.org/)-Projekt.

```bash
cd firmware
cp src/config.h.example src/config.h   # dann config.h ausfüllen
# WLAN-Zugang und Server-IP in config.h eintragen
pio run --target upload
pio device monitor        # zum Mitlesen der seriellen Ausgabe
```

In `src/config.h` trägst du ein:
- `WIFI_SSID` / `WIFI_PASSWORD` – dein WLAN
- `SERVER_HOST` – IP-Adresse des Rechners, auf dem der Python-Server läuft
- `SERVER_PORT` – Port (Standard `8888`)

Die Firmware verbindet sich automatisch wieder, wenn WLAN oder Server-Verbindung
abbrechen. Die Onboard-LED zeigt den Status (siehe Kommentare in `main.cpp`).

---

## Teil 2 – Server (Python)

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

- **START-Taster** → Aufnahme beginnt (Status-LED leuchtet dauerhaft)
- **STOP-Taster** → Aufnahme endet → WAV + Transkript + Zusammenfassung

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

## Erste Inbetriebnahme (Checkliste)

1. INMP441 wie oben verdrahten.
2. `server/.env` mit deinem `ANTHROPIC_API_KEY` befüllen und `python server.py`
   starten. Die lokale IP des Rechners notieren (`ip addr` / `ipconfig`).
3. `firmware/src/config.h` mit WLAN und dieser Server-IP befüllen und flashen.
4. Seriellen Monitor öffnen – es sollte „WiFi verbunden" und „Server verbunden"
   erscheinen. Im Server-Fenster erscheint „ESP32 verbunden".
5. **START-Taster** drücken → sprechen → **STOP-Taster** drücken. Die
   Zusammenfassung landet in `summaries/`.

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
