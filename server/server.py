"""Meeting-KI Server.

Nimmt den PCM-Audiostream des ESP32 per TCP entgegen, zeichnet auf Kommando
eine Meeting-Session auf und erzeugt beim Stoppen WAV + Transkript +
Zusammenfassung.

Bedienung (im Server-Fenster tippen):
    s + Enter   Aufnahme starten
    e + Enter   Aufnahme beenden -> WAV, Transkript, Zusammenfassung
    q + Enter   Server beenden
"""
from __future__ import annotations

import os
import socket
import threading
import wave
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from summarize import summarize
from transcribe import transcribe

load_dotenv()

LISTEN_HOST = os.getenv("LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.getenv("LISTEN_PORT", "8888"))
SAMPLE_RATE = int(os.getenv("SAMPLE_RATE", "16000"))

BASE_DIR = Path(__file__).resolve().parent
REC_DIR = BASE_DIR / "recordings"
SUM_DIR = BASE_DIR / "summaries"
REC_DIR.mkdir(exist_ok=True)
SUM_DIR.mkdir(exist_ok=True)


class AudioReceiver:
    """Nimmt eine einzelne ESP32-Verbindung an und puffert Audio bei Aufnahme."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._recording = False
        self._buffer = bytearray()
        self._client_connected = False
        self._stop = threading.Event()

    # --- Aufnahmesteuerung ---------------------------------------------------
    def start_recording(self) -> bool:
        with self._lock:
            if self._recording:
                return False
            self._buffer = bytearray()
            self._recording = True
        return True

    def stop_recording(self) -> bytes:
        with self._lock:
            self._recording = False
            data = bytes(self._buffer)
            self._buffer = bytearray()
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
            self._handle_client(conn)
            self._client_connected = False
            print("[Server] ESP32 getrennt – warte auf neue Verbindung ...")

        srv.close()

    def _handle_client(self, conn: socket.socket) -> None:
        conn.settimeout(1.0)
        with conn:
            while not self._stop.is_set():
                try:
                    chunk = conn.recv(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                with self._lock:
                    if self._recording:
                        self._buffer.extend(chunk)


def _save_wav(pcm: bytes, path: Path) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16 Bit
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)


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
        transcript = transcribe(str(wav_path))
    except Exception as exc:  # noqa: BLE001
        print(f"[Server] Transkription fehlgeschlagen: {exc}")
        return

    try:
        summary = summarize(transcript)
    except Exception as exc:  # noqa: BLE001
        print(f"[Server] Zusammenfassung fehlgeschlagen: {exc}")
        summary = "_(Zusammenfassung fehlgeschlagen – siehe Transkript unten.)_"

    md = (
        f"# Meeting {stamp}\n\n"
        f"- Aufnahme: `{wav_path.name}`\n"
        f"- Dauer: {seconds:.1f} Sekunden\n\n"
        f"{summary}\n\n"
        f"---\n\n"
        f"## Vollständiges Transkript\n\n"
        f"{transcript or '_(kein Text erkannt)_'}\n"
    )
    md_path.write_text(md, encoding="utf-8")
    print(f"[Server] ✅ Zusammenfassung geschrieben: {md_path}")


def main() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("[Warnung] ANTHROPIC_API_KEY ist nicht gesetzt – Zusammenfassung "
              "wird fehlschlagen. Trage ihn in .env ein.")

    receiver = AudioReceiver()
    net_thread = threading.Thread(target=receiver.serve_forever, daemon=True)
    net_thread.start()

    print("\nBefehle:  s = Aufnahme starten | e = beenden | q = Server beenden\n")
    try:
        while True:
            cmd = input().strip().lower()
            if cmd == "s":
                if not receiver.client_connected:
                    print("[Server] Kein ESP32 verbunden – trotzdem gestartet, "
                          "Aufnahme beginnt sobald Daten ankommen.")
                if receiver.start_recording():
                    print("[Server] ⏺  Aufnahme läuft ... (e + Enter zum Beenden)")
                else:
                    print("[Server] Aufnahme läuft bereits.")
            elif cmd == "e":
                if not receiver.is_recording:
                    print("[Server] Es läuft keine Aufnahme.")
                    continue
                print("[Server] ⏹  Aufnahme beendet – verarbeite ...")
                pcm = receiver.stop_recording()
                _process_recording(pcm)
                print("\nBefehle:  s = starten | e = beenden | q = beenden\n")
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
