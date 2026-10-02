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

Es gibt zwei Varianten (in `config.h` über `USE_TOGGLE_BUTTON` wählbar):

**Variante A – ein Knopf als Start/Stop-Umschalter (Standard).** Nutzt den
**vorhandenen BOOT-Knopf** – du musst gar keinen Taster anlöten. 1× drücken
startet, nochmal drücken stoppt.

| Board               | BOOT-Knopf = `TOGGLE_BUTTON_PIN` |
|---------------------|----------------------------------|
| ESP32-S3 Zero       | GPIO 0                           |
| ESP32-C3 Super Mini | GPIO 9                           |

> BOOT nur **im Betrieb** drücken, **nicht** beim Einschalten/Reset (sonst
> startet der Chip im Flash-Modus).

**Variante B – zwei getrennte Taster** (`USE_TOGGLE_BUTTON 0`): je ein Taster
für Start und Stop, zwischen GPIO und **GND** (interner Pullup aktiv, kein
Widerstand nötig).

| Taster        | Funktion         | ESP32-S3 Zero | ESP32-C3 Super Mini |
|---------------|------------------|---------------|---------------------|
| START-Taster  | Aufnahme starten | GPIO 1        | GPIO 10             |
| STOP-Taster   | Aufnahme beenden | GPIO 2        | GPIO 7              |

Das Entprellen passiert in beiden Varianten in der Firmware.

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

### Alternatives Board: ESP32-C3 Super Mini

Funktioniert genauso (WLAN + 1× I2S). Die Audio-Aufgabe ist leicht – der C3
reicht dafür. Unterschiede: andere Pins und die **einfache Onboard-LED auf
GPIO8 (active-low)** statt WS2812 (zeigt nur an/aus bzw. Blinken).

| Signal         | ESP32-C3 Super Mini |
|----------------|---------------------|
| INMP441 SCK    | GPIO 4              |
| INMP441 WS     | GPIO 5              |
| INMP441 SD     | GPIO 6              |
| INMP441 L/R    | GPIO 3              |
| BOOT-Knopf (Start/Stop-Toggle) | GPIO 9 |
| START/STOP (falls zwei Taster) | GPIO 10 / GPIO 7 |
| Status-LED     | GPIO 8 (onboard, active-low) |

In `firmware/src/config.h` die C3-Werte eintragen (Vorlage steht im unteren Teil
von `config.h.example`), insbesondere:
`TOGGLE_BUTTON_PIN 9`, `STATUS_LED_IS_WS2812 0`, `STATUS_LED_ACTIVE_LOW 1`,
`STATUS_LED_PIN 8`.
Flashen mit dem passenden Board-Env:

```bash
pio run -e esp32-c3-supermini --target upload
```

> Strapping-Pins 2/8/9 nicht für Taster nehmen (GPIO9 ist der BOOT-Knopf). VDD
> des INMP441 weiterhin an **3,3 V**.

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
- `ENABLE_SUMMARY` – `true`/`false` (Zusammenfassung an/aus)
- `SUMMARY_BACKEND` – `claude` | `huggingface` | `none` (siehe unten)
- `ANTHROPIC_API_KEY` – Claude-Schlüssel (nur bei `SUMMARY_BACKEND=claude`)
- `WHISPER_MODEL` – z. B. `base`, `small`, `medium` (Standard: `small`)
- weitere Optionen siehe `.env.example`

### Zusammenfassungs-Backend wählen

| `SUMMARY_BACKEND` | Was passiert | Claude nötig? | Qualität | Zusätzliches Setup |
|-------------------|--------------|---------------|----------|--------------------|
| `claude`          | strukturierte Zusammenfassung via Anthropic-API | ja (API-Key) | ★★★★ | – |
| `ollama`          | starkes lokales LLM, **strukturiert** (Überblick, Entscheidungen, To-dos) | **nein** | ★★★☆ | Ollama + Modell |
| `huggingface`     | kleines lokales Modell, kompakt & **unstrukturiert** | **nein** | ★★ | `requirements-local-summary.txt` |
| `none`            | keine Zusammenfassung, nur Transkript | nein | – | – |

Für **starke, strukturierte Zusammenfassungen ohne Claude** ist `ollama`
die beste Wahl (siehe nächster Abschnitt).

> **Nur transkribieren:** `ENABLE_SUMMARY=false` (oder `SUMMARY_BACKEND=none`) –
> dann entsteht nur das Transkript, kein KI-Aufruf. Die Transkription läuft
> ohnehin komplett lokal (faster-whisper).

### Starke lokale Zusammenfassung ohne Claude (empfohlen: Ollama)

Das `ollama`-Backend nutzt ein echtes Instruct-LLM lokal und liefert dieselbe
strukturierte Gliederung wie Claude (Überblick, Entscheidungen, To-dos …) –
ohne Internet und ohne API-Key. Es braucht **keine** zusätzlichen Python-Pakete.

1. **Ollama installieren:** https://ollama.com/download
2. **Modell laden** (einmalig):
   ```bash
   ollama pull qwen2.5:14b-instruct
   ```
3. In `.env`:
   - `SUMMARY_BACKEND=ollama`
   - `OLLAMA_MODEL=qwen2.5:14b-instruct` (Standard)

Das war's – danach wie gewohnt `python process_file.py ...` bzw. den Server nutzen.

**Andere Modelle:** leichter/schneller `qwen2.5:7b-instruct` oder `llama3.1:8b`;
stärker (mehr RAM/VRAM, langsamer) `qwen2.5:32b-instruct` (jeweils vorher
`ollama pull`). Faustregel RAM/VRAM: 7B ≈ 6–8 GB, 14B ≈ 10–12 GB, 32B ≈ 20 GB+.
Auf CPU läuft es, dauert aber spürbar länger – für lange Meetings fasst das
Backend automatisch abschnittsweise zusammen (Map-Reduce).

### Komplett ohne Claude (kleines Modell via HuggingFace)

Alternativ ein kleines, schnelles Summarizer-Modell lokal (ohne Ollama):

```bash
pip install -r requirements-local-summary.txt   # transformers + torch (mehrere hundert MB)
```

In `.env`: `SUMMARY_BACKEND=huggingface` (optional `HF_SUMMARY_MODEL=...`).

> ⚠️ **Erwartung:** Dieses kleine Modell liefert nur eine kompakte,
> **unstrukturierte** Zusammenfassung – keine Abschnitte wie Entscheidungen/
> To-dos. Für Struktur ohne Claude nimm `ollama`.

Für **Sprecher-Trennung** zusätzlich `ENABLE_DIARIZATION=true` +
`HUGGINGFACE_TOKEN` setzen (siehe nächster Abschnitt) – sie lässt sich mit
jedem Zusammenfassungs-Backend kombinieren.

### Bedienung

Der Server nimmt die TCP-Verbindung des ESP32 automatisch an. Gesteuert wird
normalerweise über den **Knopf am ESP32**:

- **Standard (ein Knopf / BOOT):** 1× drücken → Aufnahme startet (LED **rot**);
  nochmal drücken → Aufnahme endet (LED wieder **grün**) → WAV + Transkript +
  Zusammenfassung.
- **Zwei-Taster-Variante:** START-Taster startet, STOP-Taster beendet.

Ersatzweise geht es auch über die Tastatur im Server-Fenster:

| Taste       | Aktion                                                 |
|-------------|--------------------------------------------------------|
| `s` + Enter | Aufnahme **starten**                                   |
| `e` + Enter | Aufnahme **beenden** → WAV + Transkript + Zusammenfassung |
| `q` + Enter | Server beenden                                         |

Nach dem Stoppen entstehen:
- `recordings/meeting_<zeitstempel>.wav` – der Mitschnitt
- `summaries/meeting_<zeitstempel>.md` – Transkript **und** Zusammenfassung

### Vorhandene Aufnahme nachträglich verarbeiten

Du kannst eine bereits aufgenommene WAV **ohne neue Aufnahme** erneut durch die
Pipeline schicken (z. B. nachdem die Transkription beim ersten Mal fehlschlug,
oder um nachträglich eine Zusammenfassung zu erzeugen). Die Ergebnisse landen
wie gewohnt in `summaries/`.

```powershell
# eine bestimmte Datei
python process_file.py recordings/meeting_20261001_152504.wav

# alle Aufnahmen, zu denen es noch kein summaries/*.md gibt
python process_file.py --all
```

Die Einstellungen aus `.env` gelten dabei genauso (z. B. `ENABLE_SUMMARY`,
`WHISPER_MODEL`, `ENABLE_DIARIZATION`). Der Server muss dafür **nicht** laufen.
Es funktioniert mit jeder 16-kHz-Mono-WAV – auch mit Aufnahmen aus anderer
Quelle.

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
5. **Knopf** drücken (LED rot) → sprechen → **Knopf erneut** drücken (bzw.
   STOP-Taster). Die Zusammenfassung landet in `summaries/`.

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

### Transkription: `open() got an unexpected keyword argument 'metadata_errors'`

**Ursache:** faster-whisper liest Audio normalerweise über **PyAV (`av`)** ein;
je nach `av`-Version passt der Aufruf `av.open(..., metadata_errors=...)` nicht
zur installierten faster-whisper-Version (in beide Richtungen möglich).

**Lösung:** Dieses Projekt liest WAV-Dateien inzwischen **ohne PyAV** direkt mit
NumPy ein – der Fehler kann damit nicht mehr auftreten. Einfach aktuellen Stand
holen:

```powershell
git pull
pip install -r requirements.txt   # stellt sicher, dass numpy vorhanden ist
```

### Warnung: „huggingface_hub … symlinks … not supported"

Nur eine **Warnung**, kein Fehler – das Whisper-Modell wird trotzdem geladen
(nur etwas mehr Speicherverbrauch im Cache). Wegklicken kannst du sie, indem du
entweder den **Entwicklermodus** von Windows aktivierst (Einstellungen → Für
Entwickler) oder die Warnung unterdrückst:

```powershell
setx HF_HUB_DISABLE_SYMLINKS_WARNING 1
```

(neues Terminal öffnen, damit die Variable greift).

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
    ├── pipeline.py           # gemeinsame Verarbeitung: WAV -> Transkript -> MD
    ├── process_file.py       # vorhandene WAV nachträglich verarbeiten
    ├── transcribe.py         # lokale Transkription (faster-whisper)
    ├── diarize.py            # optionale Sprecher-Trennung (pyannote/HuggingFace)
    ├── prompts.py            # gemeinsame Prompts (Claude + Ollama)
    ├── summarize.py          # Zusammenfassung via Claude
    ├── summarize_ollama.py   # starke lokale Zusammenfassung via Ollama (ohne Claude)
    ├── summarize_local.py    # kleine lokale Zusammenfassung via HuggingFace
    ├── requirements-local-summary.txt  # optionale Pakete für HF-Zusammenfassung
    ├── recordings/           # gespeicherte WAV-Dateien
    └── summaries/            # Transkripte + Zusammenfassungen
```
