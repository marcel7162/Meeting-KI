"""Meeting-KI Server.

Nimmt den Audiostream des ESP32 per TCP entgegen. Die Aufnahme wird über die
Knöpfe am ESP32 gesteuert (START/STOP), die als kleine Steuer-Nachrichten
ankommen. Beim Stoppen entsteht WAV + Transkript + Zusammenfassung.

Protokoll (mit Framing, muss zur Firmware passen):
    Jeder Frame:  [1 Byte Typ][4 Byte Länge, little-endian][Nutzdaten]
      Typ 0x01 = AUDIO   -> Nutzdaten = 16-Bit-PCM (mono, little-endian)
      Typ 0x02 = CONTROL -> Nutzdaten = 1 Byte (0x10=START, 0x11=STOP)

Tastatur im Server-Fenster (optionale manuelle Steuerung / Beenden):
    s + Enter   Aufnahme starten
    e + Enter   Aufnahme beenden
    q + Enter   Server beenden
"""
from __future__ import annotations

import os
import socket
import struct
import threading
import wave
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from summarize import summarize
from transcribe import transcribe_segments, segments_to_text

load_dotenv()

def _env_flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in ("1", "true", "yes")


# Sprecher-Trennung ist optional und standardmäßig aus.
ENABLE_DIARIZATION = _env_flag("ENABLE_DIARIZATION", "false")

# Zusammenfassung via Claude. Standardmäßig an, aber ohne API-Key wird sie
# automatisch übersprungen (reines lokales Transkript).
ENABLE_SUMMARY = _env_flag("ENABLE_SUMMARY", "true")

LISTEN_HOST = os.getenv("LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.getenv("LISTEN_PORT", "8888"))
SAMPLE_RATE = int(os.getenv("SAMPLE_RATE", "16000"))

# Protokoll-Konstanten
MSG_AUDIO = 0x01
MSG_CONTROL = 0x02
CTRL_START = 0x10
CTRL_STOP = 0x11

BASE_DIR = Path(__file__).resolve().parent
REC_DIR = BASE_DIR / "recordings"
SUM_DIR = BASE_DIR / "summaries"
REC_DIR.mkdir(exist_ok=True)
SUM_DIR.mkdir(exist_ok=True)


class AudioReceiver:
    """Nimmt eine ESP32-Verbindung an, parst Frames und puffert Audio."""

    def __init__(self, on_stop) -> None:
        self._lock = threading.Lock()
        self._recording = False
        self._buffer = bytearray()
        self._client_connected = False
        self._stop = threading.Event()
        self._on_stop = on_stop  # Callback(pcm_bytes) beim Beenden einer Aufnahme

    # --- Aufnahmesteuerung ---------------------------------------------------
    def start_recording(self) -> bool:
        with self._lock:
            if self._recording:
                return False
            self._buffer = bytearray()
            self._recording = True
        print("[Server] ⏺  Aufnahme läuft ...")
        return True

    def stop_recording(self) -> bytes:
        with self._lock:
            if not self._recording:
                return b""
            self._recording = False
            data = bytes(self._buffer)
            self._buffer = bytearray()
        print(f"[Server] ⏹  Aufnahme beendet ({len(data) / (SAMPLE_RATE * 2):.1f}s)")
        return data

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._recording

    @property
    def client_connected(self) -> bool:
        return self._client_connected

    def shutdown(self) -> None:
        self._stop.set()

    # --- Netzwerk ------------------------------------------------------------
    def serve_forever(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((LISTEN_HOST, LISTEN_PORT))
        srv.listen(1)
        srv.settimeout(1.0)
        print(f"[Server] warte auf ESP32 an {LISTEN_HOST}:{LISTEN_PORT} ...")

        while not self._stop.is_set():
            try:
                conn, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            print(f"[Server] ESP32 verbunden: {addr[0]}:{addr[1]}")
            self._client_connected = True
            try:
                self._handle_client(conn)
            finally:
                self._client_connected = False
                # Falls die Verbindung mitten in einer Aufnahme abreißt:
                if self.is_recording:
                    print("[Server] Verbindung getrennt während der Aufnahme – "
                          "verarbeite bisher Empfangenes.")
                    self._on_stop(self.stop_recording())
            print("[Server] warte auf neue Verbindung ...")

        srv.close()

    def _recv_exact(self, conn: socket.socket, n: int) -> bytes | None:
        """Genau n Bytes lesen; None bei Verbindungsende."""
        buf = bytearray()
        while len(buf) < n and not self._stop.is_set():
            try:
                chunk = conn.recv(n - len(buf))
            except socket.timeout:
                continue
            except OSError:
                return None
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf) if len(buf) == n else None

    def _handle_client(self, conn: socket.socket) -> None:
        conn.settimeout(1.0)
        with conn:
            while not self._stop.is_set():
                header = self._recv_exact(conn, 5)
                if header is None:
                    break
                msg_type = header[0]
                (length,) = struct.unpack_from("<I", header, 1)

                payload = self._recv_exact(conn, length) if length else b""
                if payload is None:
                    break

                if msg_type == MSG_AUDIO:
                    with self._lock:
                        if self._recording:
                            self._buffer.extend(payload)
                elif msg_type == MSG_CONTROL and payload:
                    self._handle_control(payload[0])

    def _handle_control(self, command: int) -> None:
        if command == CTRL_START:
            print("[Server] Knopf: START")
            self.start_recording()
        elif command == CTRL_STOP:
            print("[Server] Knopf: STOP")
            pcm = self.stop_recording()
            self._on_stop(pcm)


def _save_wav(pcm: bytes, path: Path) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16 Bit
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)


def _build_transcript(wav_path: Path) -> str:
    """Transkript erzeugen – optional mit Sprecher-Labels."""
    segments = transcribe_segments(str(wav_path))

    if ENABLE_DIARIZATION:
        try:
            from diarize import diarize, label_segments
            turns = diarize(str(wav_path))
            return label_segments(segments, turns)
        except Exception as exc:  # noqa: BLE001
            print(f"[Server] Sprecher-Trennung fehlgeschlagen ({exc}) – "
                  "erstelle Transkript ohne Sprecher.")

    return segments_to_text(segments)


def _process_recording(pcm: bytes) -> None:
    """WAV speichern, transkribieren, zusammenfassen, Ergebnis ablegen."""
    if not pcm:
        print("[Server] Aufnahme war leer – nichts zu verarbeiten.")
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    seconds = len(pcm) / (SAMPLE_RATE * 2)
    wav_path = REC_DIR / f"meeting_{stamp}.wav"
    md_path = SUM_DIR / f"meeting_{stamp}.md"

    _save_wav(pcm, wav_path)
    print(f"[Server] Aufnahme gespeichert: {wav_path} ({seconds:.1f}s)")

    try:
        transcript = _build_transcript(wav_path)
    except Exception as exc:  # noqa: BLE001
        print(f"[Server] Transkription fehlgeschlagen: {exc}")
        return

    # Zusammenfassung nur, wenn aktiviert UND ein API-Key vorhanden ist.
    do_summary = ENABLE_SUMMARY and bool(os.getenv("ANTHROPIC_API_KEY"))
    if not ENABLE_SUMMARY:
        summary = "_(Zusammenfassung deaktiviert – ENABLE_SUMMARY=false.)_"
        print("[Server] Zusammenfassung übersprungen (ENABLE_SUMMARY=false).")
    elif not os.getenv("ANTHROPIC_API_KEY"):
        summary = "_(Zusammenfassung übersprungen – kein ANTHROPIC_API_KEY gesetzt.)_"
        print("[Server] Zusammenfassung übersprungen (kein ANTHROPIC_API_KEY).")
    else:
        try:
            summary = summarize(transcript)
        except Exception as exc:  # noqa: BLE001
            print(f"[Server] Zusammenfassung fehlgeschlagen: {exc}")
            summary = "_(Zusammenfassung fehlgeschlagen – siehe Transkript unten.)_"

    summary_block = f"{summary}\n\n---\n\n" if summary else ""
    md = (
        f"# Meeting {stamp}\n\n"
        f"- Aufnahme: `{wav_path.name}`\n"
        f"- Dauer: {seconds:.1f} Sekunden\n"
        f"- Sprecher-Trennung: {'ja' if ENABLE_DIARIZATION else 'nein'}\n"
        f"- Zusammenfassung: {'ja' if do_summary else 'nein'}\n\n"
        f"{summary_block}"
        f"## Vollständiges Transkript\n\n"
        f"{transcript or '_(kein Text erkannt)_'}\n"
    )
    md_path.write_text(md, encoding="utf-8")
    print(f"[Server] ✅ Zusammenfassung geschrieben: {md_path}")


def _process_in_background(pcm: bytes) -> None:
    """Verarbeitung in eigenem Thread, damit der Empfang nicht blockiert."""
    threading.Thread(target=_process_recording, args=(pcm,), daemon=True).start()


def main() -> None:
    if ENABLE_SUMMARY and not os.getenv("ANTHROPIC_API_KEY"):
        print("[Hinweis] Kein ANTHROPIC_API_KEY gesetzt – es wird nur lokal "
              "transkribiert (keine Claude-Zusammenfassung).")
    elif not ENABLE_SUMMARY:
        print("[Hinweis] ENABLE_SUMMARY=false – nur lokale Transkription, "
              "keine Zusammenfassung.")
    if ENABLE_DIARIZATION and not os.getenv("HUGGINGFACE_TOKEN"):
        print("[Warnung] ENABLE_DIARIZATION=true, aber HUGGINGFACE_TOKEN fehlt – "
              "Sprecher-Trennung wird fehlschlagen.")

    receiver = AudioReceiver(on_stop=_process_in_background)
    net_thread = threading.Thread(target=receiver.serve_forever, daemon=True)
    net_thread.start()

    print("\nSteuerung normalerweise über die Knöpfe am ESP32.")
    print("Tastatur:  s = starten | e = beenden | q = Server beenden\n")
    try:
        while True:
            cmd = input().strip().lower()
            if cmd == "s":
                receiver.start_recording()
            elif cmd == "e":
                _process_in_background(receiver.stop_recording())
            elif cmd == "q":
                break
            elif cmd:
                print("[Server] Unbekannter Befehl. s / e / q.")
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        receiver.shutdown()
        print("\n[Server] beendet.")


if __name__ == "__main__":
    main()
